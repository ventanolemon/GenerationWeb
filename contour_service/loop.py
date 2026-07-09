"""
Оркестратор петли S0–S5 (closed_loop_contract.md). Одна джоба = один вызов
run_pipeline(); S6 (человек) живёт в API (routers/jobs.py — approve/reject).

Инварианты контракта (§6), зашитые в код:
  1. Критик не вызывается до успешного прохождения S2–S4 — по построению
     (вызов S5 стоит ПОСЛЕ всех структурных проверок в теле цикла).
  2. Repair всегда содержит ПОЛНЫЙ предыдущий граф + ДОСЛОВНЫЕ ошибки —
     build_repair_message() контракта §2, тексты исключений не пересказываются.
  3. Запись корпуса без probe невозможна — сигнатуры CorpusStore.
  4. catalog_version/engine_commit — в каждой записи (передаются из deps).
  6. Бюджет V тратится до первого прохода S4, R — только после: v_used
     инкрементируют ТОЛЬКО стадии build/execute/probe, r_used — только critic.

Отказ провайдера (сеть/ключ/квота) НЕ жжёт V (contour_integration §5) —
после ретраев джоба падает в failed через ProviderError, который
пробрасывается наружу (ловит worker).
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core import graph_api, graph_probe
from core.graph.errors import GraphError, GraphValidationError
from core.graph.executor import GraphExecutor
from core.graph.spec import GraphSpec

from .config import ContourConfig
from .corpus import CorpusStore
from .grounding import FewShotPool, compact_catalog
from .prompts import (
    CRITIC_SYSTEM, build_critic_input, build_generator_system,
    build_repair_message,
)
from .providers import TASK_CRITIC, TASK_GENERATE, ProviderError, ProviderRegistry


@dataclass
class LoopDeps:
    """Зависимости петли — всё внешнее по отношению к алгоритму."""
    providers: ProviderRegistry
    corpus: CorpusStore
    config: ContourConfig
    fewshot_pool: Optional[FewShotPool] = None


@dataclass
class PipelineOutcome:
    """Итог петли для персиста воркером."""
    status: str                      # awaiting_human | escalated | failed
    rounds: list[dict] = field(default_factory=list)
    result_graph: Optional[dict] = None
    result_probe: Optional[dict] = None
    critic: Optional[dict] = None
    error: Optional[str] = None
    fewshot_ids: list[str] = field(default_factory=list)


def _invoke_with_retries(providers: ProviderRegistry, task: str,
                         payload: dict, retries: int) -> dict:
    """Вызов провайдера с ретраями; исчерпание — ProviderError наружу."""
    last: Optional[ProviderError] = None
    for _ in range(max(1, retries + 1)):
        try:
            return providers.get(task).invoke(payload)
        except ProviderError as e:
            last = e
    raise last if last else ProviderError("провайдер недоступен")


def _parse_graph(response: dict) -> tuple[Optional[dict], Optional[str]]:
    """(graph, error): достать GraphSpec-словарь из ответа провайдера.
    Невалидный JSON — ошибка ГРАФА (жжёт V), не транспорта."""
    graph = response.get("graph")
    if isinstance(graph, dict):
        return graph, None
    text = str(response.get("text", "")).strip()
    if not text:
        return None, "Ответ LLM пуст — ожидался JSON-объект графа."
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"Ответ LLM не является валидным JSON: {e}"
    if not isinstance(parsed, dict):
        return None, "Ответ LLM — не JSON-объект графа."
    return parsed, None


def normalize_critic(raw: dict) -> dict:
    """Привести вердикт критика к контракту critic_taxonomy.md §4.

    Модель стохастична — правила применяются КОДОМ, не доверяются тексту:
      - провал без evidence отбрасывается (гасит галлюцинации критика);
      - свёртка: любой block → не accept; revise, если у всех block есть
        fix_hint, иначе reject; только warn → accept.
    """
    failures = []
    for f in raw.get("failures") or []:
        if not isinstance(f, dict):
            continue
        if not str(f.get("evidence", "")).strip():
            continue                       # без цитаты провал не засчитывается
        failures.append({
            "code": str(f.get("code", "")).strip(),
            "severity": ("block" if str(f.get("severity", "warn")).lower()
                         == "block" else "warn"),
            "evidence": str(f.get("evidence", "")).strip(),
            "fix_hint": str(f.get("fix_hint", "")).strip(),
        })

    blocks = [f for f in failures if f["severity"] == "block"]
    if not blocks:
        verdict = "accept"
    elif all(f["fix_hint"] for f in blocks):
        verdict = "revise"
    else:
        verdict = "reject"

    try:
        confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "verdict": verdict,
        "failures": failures,
        "confidence": confidence,
        "summary": str(raw.get("summary", "")).strip(),
        "model": str(raw.get("model", "")),
    }


def _usage_tokens(response: dict) -> int:
    usage = response.get("usage") or {}
    try:
        return int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    except (TypeError, ValueError):
        return 0


def run_pipeline(job: dict, deps: LoopDeps,
                 on_status: Optional[Callable[[str], None]] = None,
                 on_round: Optional[Callable[[dict], None]] = None,
                 ) -> PipelineOutcome:
    """Прогнать петлю S0–S5 для одной джобы. Статусы — через on_status
    (generating → validating → critic → …), каждый раунд — через on_round
    (персист истории до終ного статуса)."""
    cfg = deps.config
    description = str(job.get("description", ""))
    constraints = job.get("constraints") or {}
    job_id = str(job.get("id"))
    started = time.monotonic()

    def status(s: str) -> None:
        if on_status:
            on_status(s)

    # ---------- S0: заземление ----------
    catalog_version, catalog_text = compact_catalog()
    pool = deps.fewshot_pool or FewShotPool.from_graph_examples()
    pool.extend_from_corpus(deps.corpus.approved_generate_records())
    shots = pool.select(description, cfg.fewshot_count)
    fewshot_ids = [s.example_id for s in shots]
    system_prompt = build_generator_system(catalog_version, catalog_text, shots)

    outcome = PipelineOutcome(status="failed", fewshot_ids=fewshot_ids)
    rounds = outcome.rounds

    v_used = 0                 # бюджет структурных раундов (S2+S3+S4)
    r_used = 0                 # бюджет revise-раундов критика
    tokens_used = 0
    round_no = 0
    # user-сообщение текущего раунда: описание (generate) или repair-JSON.
    user_message = description
    repair_context: Optional[dict] = None   # {prior_graph, errors} для корпуса

    def escalate(reason: str) -> PipelineOutcome:
        outcome.status = "escalated"
        outcome.error = reason
        deps.corpus.write_escalation(
            job_id, description, reason, rounds,
            catalog_version=catalog_version, engine_commit=cfg.engine_commit)
        return outcome

    while True:
        round_no += 1
        if time.monotonic() - started > cfg.job_timeout_s:
            outcome.status = "failed"
            outcome.error = f"таймаут джобы ({cfg.job_timeout_s:.0f} с) исчерпан"
            return outcome

        # ---------- S1: генерация ----------
        status("generating")
        response = _invoke_with_retries(
            deps.providers, TASK_GENERATE,
            {"system": system_prompt, "user": user_message},
            cfg.provider_retries,
        )
        tokens_used += _usage_tokens(response)
        if cfg.token_budget and tokens_used > cfg.token_budget:
            return escalate(
                f"токен-бюджет исчерпан ({tokens_used} > {cfg.token_budget})")

        graph, parse_error = _parse_graph(response)
        this_round = {
            "n": round_no,
            "kind": "repair" if repair_context else "generate",
            "graph": graph,
            "stage_failed": None,
            "errors": [],
            "probe_flags": [],
            "critic": None,
        }
        rounds.append(this_round)

        def fail_structural(stage: str, errors: list[dict]) -> Optional[PipelineOutcome]:
            """Ошибка S2/S3/S4: жжёт V; готовит repair-сообщение или эскалирует."""
            nonlocal v_used, user_message, repair_context
            this_round["stage_failed"] = stage
            this_round["errors"] = errors
            if on_round:
                on_round(this_round)
            v_used += 1
            if v_used > cfg.v_budget:
                return escalate(
                    f"структурно не сходится: бюджет V={cfg.v_budget} исчерпан; "
                    f"последняя стадия {stage}: "
                    + "; ".join(e["text"] for e in errors))
            prev = graph if graph is not None else {}
            user_message = json.dumps(
                build_repair_message(round_no, stage, errors, prev),
                ensure_ascii=False)
            repair_context = {"prior_graph": prev,
                              "errors": [e["text"] for e in errors]}
            return None

        # ---------- S2: сборка ----------
        status("validating")
        if parse_error is not None:
            esc = fail_structural(
                "build", [{"text": parse_error, "seed": None, "code": None}])
            if esc:
                return esc
            continue
        try:
            executor = GraphExecutor(GraphSpec.parse(graph))
        except GraphValidationError as e:
            esc = fail_structural(
                "build", [{"text": str(e), "seed": None, "code": None}])
            if esc:
                return esc
            continue
        if executor.result is None:
            esc = fail_structural("build", [{
                "text": ("В графе нет финального узла: ни у одного узла нет "
                         "свободного выхода TASK — генерация не вернёт задание."),
                "seed": None, "code": None}])
            if esc:
                return esc
            continue

        # ---------- S3: probe (исполнение на K seed, каждый дважды) ----------
        try:
            probe = graph_probe.probe_graph(graph, seeds=cfg.probe_seeds)
        except GraphError as e:      # структурная ошибка, всплывшая на прогоне
            esc = fail_structural(
                "execute", [{"text": str(e), "seed": None, "code": None}])
            if esc:
                return esc
            continue
        exec_errors = [
            {"text": r["error"], "seed": r["seed"], "code": None}
            for r in probe["runs"] if r["error"] is not None
        ]
        if exec_errors:
            esc = fail_structural("execute", exec_errors)
            if esc:
                return esc
            continue

        # ---------- S4: SYM-флаги ----------
        this_round["probe_flags"] = probe["flags"]
        blocking = [f for f in probe["flags"] if f.get("severity") == "block"]
        if blocking:
            esc = fail_structural("probe", [
                {"text": f"[{f['code']}] {f['detail']}", "seed": None,
                 "code": f["code"]}
                for f in blocking
            ])
            if esc:
                return esc
            continue

        # S2–S4 пройдены. Если этот раунд был repair — успешный repair-раунд
        # пишется в корпус СРАЗУ (closed_loop_contract §5), не ждёт человека.
        if repair_context is not None:
            deps.corpus.write_repair(
                job_id, description,
                prior_graph=repair_context["prior_graph"],
                errors=repair_context["errors"],
                target_graph=graph, probe=probe,
                catalog_version=catalog_version,
                engine_commit=cfg.engine_commit,
                model=deps.providers.get(TASK_GENERATE).name,
                fewshot_ids=fewshot_ids,
            )
            repair_context = None

        # ---------- S5: критик (только для прошедших S2–S4 кандидатов) ----------
        status("critic")
        critic_raw = _invoke_with_retries(
            deps.providers, TASK_CRITIC,
            {"system": CRITIC_SYSTEM,
             "input": build_critic_input(description, constraints, graph,
                                         probe, catalog_version)},
            cfg.provider_retries,
        )
        tokens_used += _usage_tokens(critic_raw)
        critic = normalize_critic(critic_raw)
        critic.setdefault("model", deps.providers.get(TASK_CRITIC).name)
        this_round["critic"] = critic
        if on_round:
            on_round(this_round)

        if critic["verdict"] == "accept":
            outcome.status = "awaiting_human"
            outcome.result_graph = graph
            outcome.result_probe = probe
            outcome.critic = critic
            return outcome

        if critic["verdict"] == "revise":
            r_used += 1
            if r_used > cfg.r_budget:
                return escalate(
                    f"качество не сходится: бюджет R={cfg.r_budget} исчерпан; "
                    f"{critic['summary']}")
            errors = [
                {"text": f["fix_hint"] or f["evidence"], "seed": None,
                 "code": f["code"]}
                for f in critic["failures"] if f["severity"] == "block"
            ]
            user_message = json.dumps(
                build_repair_message(round_no, "critic", errors, graph),
                ensure_ascii=False)
            repair_context = {"prior_graph": graph,
                              "errors": [e["text"] for e in errors]}
            continue

        # reject — исправление одной правкой невозможно.
        return escalate(f"критик отклонил кандидата: {critic['summary']}")
