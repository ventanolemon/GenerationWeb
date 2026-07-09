"""
Пробный прогон графа (probe) — общий вход для SYM-проверок и агента-критика.

Реализует docs/critic_taxonomy.md §3 поверх движка `core/graph`, НЕ меняя его.
Один и тот же модуль импортируют два потребителя (см.
docs/architecture/system_topology.md §3): generator_service (для /graph/preview,
через core.graph_api) и будущий contour_service (стадия S3 петли). Поэтому probe
лёгкий — plain-текст + метрики + флаги, без base64-блоков (их отдаёт preview для
UI отдельно).

Покрытие таксономии — ПОЛНАЯ SYM-колонка critic_taxonomy.md §2
(B4 B5 D2 E4 F1 F2 F3 F4): D2 (остаточные маркеры), F2 (недетерминизм при
seed), F3 (медленный прогон), F1 (близость к лимиту попыток), B4 (низкое
разнообразие при random-источниках), B5 (кучкование ответов при активной
отбраковке), E4 (число шаблонов условия против числа ветвей case), F4
(мёртвые подграфы вне конуса финального TASK). Остальные коды (HYBRID/LLM:
A*, C*, …) — зона агента-критика в contour_service, не probe.

Связанность с исполнителем: probe воспроизводит retry-цикл `GraphExecutor.
run_full`, чтобы посчитать число попыток (движок его наружу не отдаёт), и
использует `executor._execute_once`/`executor.result`. Это осознанная тесная
связь probe↔executor — они спроектированы вместе; движок остаётся байт-в-байт
копией десктопного (единый источник истины по формату графа).
"""

from __future__ import annotations
import json
import random
import re
import statistics
import time
from typing import Any, NamedTuple, Optional

from .graph.errors import GraphError, RetryGeneration
from .graph.executor import GraphExecutor
from .graph.node import ExecContext
from .graph.spec import GraphSpec

# Seed-наборы: обычный (быстрый предпросмотр/критик) и релизный (проверка
# партиции перед сохранением). Фиксированы ради воспроизводимости.
DEFAULT_SEEDS = list(range(8))
RELEASE_SEEDS = list(range(32))

# Пороги по умолчанию (docs/critic_taxonomy.md §5) — калибруемые.
SLOW_MS = 3000.0                 # F3
ATTEMPTS_WARN_FRACTION = 0.3     # F1: p50 > 0.3·max_attempts
B4_MIN_STATEMENT_RATIO = 0.6     # B4
B4_MIN_ANSWER_RATIO = 0.4
B5_MIN_ATTEMPTS_P50 = 2          # B5: отбраковка реально активна…
B5_MAX_RELATIVE_SPREAD = 0.05    # …а выжившие ответы в полосе < 5% величины

# Типы узлов, вносящих случайность (гейт для B4: у детерминированного графа
# distinct=1 — это норма, а не провал).
RANDOM_TYPES = {
    "random_natural", "random_real", "random_choice", "random_matrix",
    "random_polynomial", "logic_circuit", "sentence_fill", "words_trainer",
    "number_range",
}

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_MARKER_RE = re.compile(r"#[A-Za-zА-Яа-я0-9_]+#")


class RunResult(NamedTuple):
    task: Any                 # объект задания или None (если прогон упал)
    attempts: int
    error: Optional[str]
    wall_ms: float


def run_once(executor: GraphExecutor, seed: Optional[int]) -> RunResult:
    """
    Один прогон графа с retry, с подсчётом попыток. Повторяет семантику
    GraphExecutor.run_full, но возвращает число попыток и время.
    """
    try:
        max_attempts = int(executor.spec.meta.get("max_attempts", 100))
    except (TypeError, ValueError):
        max_attempts = 100
    if executor.result is None:
        return RunResult(None, 0, "в графе нет финального узла (выход TASK)", 0.0)

    if seed is not None:
        random.seed(seed)
    ctx = ExecContext(rng=random.Random(seed) if seed is not None else random.Random())

    node_id, port = executor.result
    start = time.perf_counter()
    last: Exception | None = None
    for attempt in range(max_attempts):
        ctx.attempt = attempt
        try:
            outputs = executor._execute_once(ctx)
            wall = (time.perf_counter() - start) * 1000.0
            return RunResult(outputs[node_id][port], attempt + 1, None, wall)
        except RetryGeneration as e:
            last = e
            continue
        except GraphError as e:
            wall = (time.perf_counter() - start) * 1000.0
            return RunResult(None, attempt + 1, str(e), wall)
    wall = (time.perf_counter() - start) * 1000.0
    return RunResult(None, max_attempts, f"исчерпано {max_attempts} попыток: {last}", wall)


def task_plain(task: Any) -> tuple[str, str]:
    """(условие, ответ) как plain-текст. Для интерактивных заданий условие —
    начальный промпт, ответ пуст."""
    if task is None:
        return ("", "")
    statement = getattr(task, "statement", None)
    answer = getattr(task, "answer", None)
    if statement is not None:
        s = " ".join(b.render_plain() for b in statement)
        a = " ".join(b.render_plain() for b in answer) if answer else ""
        return (s.strip(), a.strip())
    # Интерактивная сессия (words_trainer): нет статических statement/answer.
    prompt = getattr(task, "initial_prompt", None)
    if callable(prompt):
        try:
            return (str(prompt()).strip(), "")
        except Exception:
            pass
    return (type(task).__name__, "")


def _template(text: str) -> str:
    """Сигнатура шаблона: числа заменены на •, пробелы схлопнуты."""
    return _NUM_RE.sub("•", " ".join(text.split()))


def _has_random_source(spec_dict: dict) -> bool:
    """Есть ли в графе (включая вложенные тела) узел, вносящий случайность."""
    blob = json.dumps(spec_dict, ensure_ascii=False)
    return any(f'"{t}"' in blob for t in RANDOM_TYPES)


def probe_graph(
    spec: "dict | GraphSpec", seeds: Optional[list[int]] = None
) -> dict:
    """
    Прогнать граф на seeds (дважды на seed — для детектора F2) и собрать отчёт:
    runs, aggregates, flags. Structural-невалидный граф бросает
    GraphValidationError из GraphExecutor — ловит вызывающий (это зона
    валидатора, не probe).
    """
    seeds = seeds if seeds is not None else DEFAULT_SEEDS
    spec_dict = spec if isinstance(spec, dict) else spec.to_dict()
    executor = GraphExecutor(GraphSpec.parse(spec))

    runs: list[dict] = []
    for seed in seeds:
        r1 = run_once(executor, seed)
        r2 = run_once(executor, seed)           # тот же seed → должно совпасть
        s1, a1 = task_plain(r1.task)
        s2, a2 = task_plain(r2.task)
        runs.append({
            "seed": seed,
            "statement": s1,
            "answer": a1,
            "attempts": r1.attempts,
            "wall_ms": round(r1.wall_ms, 2),
            "error": r1.error,
            "double_run_mismatch": (s1, a1) != (s2, a2),
        })

    aggregates = _aggregate(runs)
    flags = _flags(spec_dict, runs, aggregates, executor)
    return {"seeds": seeds, "runs": runs, "aggregates": aggregates, "flags": flags}


def _aggregate(runs: list[dict]) -> dict:
    ok = [r for r in runs if r["error"] is None]
    statements = [r["statement"] for r in ok]
    answers = [r["answer"] for r in ok]
    attempts = [r["attempts"] for r in ok] or [0]
    templates = sorted({_template(s) for s in statements})
    return {
        "runs_ok": len(ok),
        "runs_total": len(runs),
        "distinct_statements": len(set(statements)),
        "distinct_answers": len(set(answers)),
        "templates": templates,
        "template_count": len(templates),
        "attempts_p50": int(statistics.median(attempts)),
        "attempts_max": max(attempts),
        "double_run_mismatch": any(r["double_run_mismatch"] for r in runs),
        "wall_ms_max": max((r["wall_ms"] for r in runs), default=0.0),
    }


def _flags(spec_dict: dict, runs: list[dict], agg: dict, executor) -> list[dict]:
    flags: list[dict] = []

    def add(code: str, severity: str, detail: str) -> None:
        flags.append({"code": code, "severity": severity, "detail": detail})

    # D2 — остаточные маркеры #var# в готовом тексте (опечатка имени маркера).
    for r in runs:
        leftover = _MARKER_RE.findall(r["statement"]) + _MARKER_RE.findall(r["answer"])
        if leftover:
            add("D2", "block", f"seed {r['seed']}: незамещённые маркеры {leftover}")
            break

    # F2 — недетерминизм при фиксированном seed (блокирующий).
    if agg["double_run_mismatch"]:
        bad = [r["seed"] for r in runs if r["double_run_mismatch"]]
        add("F2", "block", f"один seed даёт разные задания: seeds {bad}")

    # F3 — слишком долгий прогон.
    if agg["wall_ms_max"] > SLOW_MS:
        add("F3", "warn", f"макс. время прогона {agg['wall_ms_max']:.0f} мс > {SLOW_MS:.0f}")

    # F1 — близость к лимиту попыток (хрупкость отбраковки).
    max_attempts = int(executor.spec.meta.get("max_attempts", 100))
    if agg["attempts_p50"] > ATTEMPTS_WARN_FRACTION * max_attempts:
        add("F1", "warn",
            f"медиана попыток {agg['attempts_p50']} > {ATTEMPTS_WARN_FRACTION:.0%} от {max_attempts}")

    # B4 — низкое разнообразие (только если в графе есть random-источник).
    k = agg["runs_ok"] or 1
    if _has_random_source(spec_dict) and agg["runs_ok"] > 1:
        if agg["distinct_statements"] < B4_MIN_STATEMENT_RATIO * k:
            add("B4", "warn",
                f"различимых условий {agg['distinct_statements']} из {k} "
                f"(< {B4_MIN_STATEMENT_RATIO:.0%})")
        elif agg["distinct_answers"] < B4_MIN_ANSWER_RATIO * k:
            add("B4", "warn",
                f"различимых ответов {agg['distinct_answers']} из {k} "
                f"(< {B4_MIN_ANSWER_RATIO:.0%})")

    # B5 — деформация распределения отбраковкой: guard/constraint реально
    # работают (медиана попыток ≥ порога), а выжившие числовые ответы
    # кучкуются в узкой полосе. Гейт по попыткам гасит ложные срабатывания
    # на графах без отбраковки.
    numeric = _numeric_answers(runs)
    if (agg["attempts_p50"] >= B5_MIN_ATTEMPTS_P50 and len(numeric) >= 4):
        spread = max(numeric) - min(numeric)
        scale = max(abs(v) for v in numeric)
        if scale > 0 and spread / scale < B5_MAX_RELATIVE_SPREAD:
            add("B5", "warn",
                f"ответы кучкуются: разброс {spread:g} при величине {scale:g} "
                f"(< {B5_MAX_RELATIVE_SPREAD:.0%}), медиана попыток "
                f"{agg['attempts_p50']}")

    # E4 — нестабильный тип задания между seed. Считаем ТОЛЬКО при наличии
    # узлов case: их ветви — легитимный источник разных шаблонов, и допустимое
    # число шаблонов известно из spec (произведение числа ветвей). Без case
    # разные шаблоны дают и строковые пулы random_choice (один тип задания,
    # разные функции в тексте) — это зона критика, не SYM-флага.
    branches = _case_branch_count(spec_dict)
    if branches is not None and agg["template_count"] > branches:
        add("E4", "warn",
            f"шаблонов условий {agg['template_count']} при {branches} "
            f"ветвях case — тип задания скачет между seed")

    # F4 — мёртвые подграфы: узлы вне конуса предков финального TASK-узла.
    dead = _dead_nodes(spec_dict, executor)
    if dead:
        add("F4", "warn", f"узлы вне конуса финального задания: {sorted(dead)}")

    return flags


def _numeric_answers(runs: list[dict]) -> list[float]:
    """Числовые значения ответов (где парсятся): первое число plain-текста."""
    out = []
    for r in runs:
        if r["error"] is not None:
            continue
        m = _NUM_RE.search(r["answer"] or "")
        if m:
            try:
                out.append(float(m.group().replace(",", ".")))
            except ValueError:
                pass
    return out


def _case_branch_count(spec_dict: dict) -> Optional[int]:
    """Произведение числа ветвей узлов case (ветви + default); None — нет case."""
    total = None
    for node in spec_dict.get("nodes") or []:
        if node.get("type") == "case":
            try:
                n = max(1, int((node.get("params") or {}).get("cases", 2)))
            except (TypeError, ValueError):
                n = 2
            total = (total or 1) * (n + 1)          # + ветвь default
    return total


def _dead_nodes(spec_dict: dict, executor: GraphExecutor) -> set[str]:
    """Узлы вне конуса предков финального TASK (жадный исполнитель их считает,
    на результат они не влияют — сигнал ошибки замысла, F4)."""
    if executor.result is None:
        return set()
    final_node = executor.result[0]
    preds: dict[str, set[str]] = {}
    for e in spec_dict.get("edges") or []:
        src = str(e.get("from", "")).split(":", 1)[0]
        dst = str(e.get("to", "")).split(":", 1)[0]
        preds.setdefault(dst, set()).add(src)
    cone = {final_node}
    stack = [final_node]
    while stack:
        for p in preds.get(stack.pop(), ()):
            if p not in cone:
                cone.add(p)
                stack.append(p)
    all_ids = {str(n.get("id")) for n in spec_dict.get("nodes") or []}
    return all_ids - cone
