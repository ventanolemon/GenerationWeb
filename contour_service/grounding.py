"""
S0 — заземление (closed_loop_contract.md): компактный каталог узлов из
NodeRegistry (ИМПОРТ core.graph_api, не HTTP — system_topology.md §3) +
few-shot retrieval по описанию.

Каталог версионируется: catalog_version из core.graph_api пишется в каждый
лог и каждую запись корпуса (инвариант №4 контракта). Решение о каталоге
из training_plan.md §1: каталог живёт В ПРОМПТЕ всегда — модель учится
ЧИТАТЬ каталог, рост языка её не ломает; компакт-форма ~1 строка на узел.

Few-shot: 2–4 графа, подобранных лексическим retrieval'ом по описанию —
стартовый пул exercises/graph_examples, по мере накопления корпуса
добавляются принятые записи corpus_records (kind=generate, approved).
Эмбеддингов здесь сознательно нет: лексическая близость детерминирована,
дёшева и достаточна для десятков-сотен кандидатов; замена скорера локальна.
"""

from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass, field

from core import graph_api

_WORD_RE = re.compile(r"[a-zа-яё0-9]{3,}", re.IGNORECASE)


def _stem(word: str) -> str:
    """Грубый стемминг: отрезать 2 последних символа (падежные окончания RU —
    «сила/силу/силе» → «сил»). Для лексического retrieval'а этого достаточно;
    английские термины страдают мало (constraint → constrai)."""
    return word[: max(3, len(word) - 2)]


def _tokens(text: str) -> set[str]:
    return {_stem(w.lower()) for w in _WORD_RE.findall(text or "")}


def _similarity(a: set[str], b: set[str]) -> float:
    """Косинусоподобная лексическая близость (0..1), детерминированная."""
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


@dataclass
class FewShotExample:
    """Один пример заземления: человекочитаемое описание → граф."""
    example_id: str
    description: str
    graph: dict


@dataclass
class FewShotPool:
    """Пул кандидатов few-shot: стартовые примеры + принятый корпус."""

    examples: list[FewShotExample] = field(default_factory=list)

    @classmethod
    def from_graph_examples(cls) -> "FewShotPool":
        """Стартовый пул из exercises/graph_examples (title+note как описание)."""
        from exercises.graph_examples import EXAMPLES
        pool = cls()
        for name, entry in EXAMPLES.items():
            pool.examples.append(FewShotExample(
                example_id=f"graph_examples:{name}",
                description=f"{entry.get('title', name)}. {entry.get('note', '')}".strip(),
                graph=entry["graph"],
            ))
        return pool

    def extend_from_corpus(self, records: list[dict]) -> None:
        """Добавить принятые generate-записи корпуса (дают лучший стиль:
        реальные описания пользователей, а не витринные title)."""
        for rec in records:
            payload = rec.get("record") or {}
            desc = ((payload.get("input") or {}).get("description") or "").strip()
            graph = payload.get("target_graph")
            if desc and isinstance(graph, dict):
                self.examples.append(FewShotExample(
                    example_id=str(rec.get("id", payload.get("id", "corpus"))),
                    description=desc,
                    graph=graph,
                ))

    def select(self, description: str, k: int = 3) -> list[FewShotExample]:
        """Top-k по лексической близости; тай-брейк по id (детерминизм)."""
        query = _tokens(description)
        scored = sorted(
            self.examples,
            key=lambda ex: (-_similarity(query, _tokens(ex.description)),
                            ex.example_id),
        )
        return scored[:max(0, k)]


# ---------- Компактный каталог (1 строка на узел) ----------

def compact_catalog() -> tuple[str, str]:
    """(catalog_version, текст каталога для системного промпта).

    Формат строки: type_id [категория] in(имя:тип…) out(имя:тип…)
    params{имя=дефолт…} — описание. Динамические порты (var_dict, маркеры
    text/template, туннели repeat) модель доопределяет по правилам формата.
    """
    cat = graph_api.build_catalog()
    lines = []
    for node in cat["nodes"]:
        ins = ",".join(f"{p['name']}:{p['type']}" + ("" if p["required"] else "?")
                       for p in node["inputs"])
        outs = ",".join(f"{p['name']}:{p['type']}" for p in node["outputs"])
        params = ",".join(
            f"{k}={json.dumps(v.get('default'), ensure_ascii=False)}"
            + ("?" if v.get("optional") else "")
            for k, v in (node.get("params_schema") or {}).items()
            if isinstance(v, dict) and v.get("type") not in ("hidden",)
        )
        desc = (node.get("description") or "").strip()
        line = f"{node['type_id']} [{node['category']}]"
        if ins:
            line += f" in({ins})"
        if outs:
            line += f" out({outs})"
        if params:
            line += f" params{{{params}}}"
        if desc:
            line += f" — {desc}"
        lines.append(line)

    conversions = "; ".join(
        f"{c['from']}→{c['to']} via {c['via']}" for c in cat["conversions"])
    types = ", ".join(t["id"] for t in cat["port_types"])
    text = (
        "УЗЛЫ (type_id [категория] входы выходы параметры — назначение):\n"
        + "\n".join(lines)
        + f"\n\nТИПЫ ПОРТОВ: {types}"
        + f"\nКОНВЕРТЕРЫ (несовместимые типы соединяй через узел): {conversions}"
    )
    return cat["catalog_version"], text
