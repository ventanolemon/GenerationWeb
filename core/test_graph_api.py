"""
Проверка graph-API и probe (Фаза 2), headless и без fastapi.

Роутер generator_service — тонкая обёртка над core.graph_api; вся логика
(каталог, валидация, предпросмотр, probe) проверяется здесь напрямую.

Запуск:  python core/test_graph_api.py
"""

from __future__ import annotations
import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import graph_api, graph_probe  # noqa: E402
from exercises.graph_examples import EXAMPLES  # noqa: E402

# Битый граф (висячий провод s:res) — тот же, что seed-rep-001 в корпусе.
_BROKEN = {
    "version": 1,
    "nodes": [
        {"id": "v", "type": "random_natural", "params": {"min": 2, "max": 15}},
        {"id": "t", "type": "random_natural", "params": {"min": 3, "max": 20}},
        {"id": "s", "type": "formula", "params": {"expr": "v * t"}},
        {"id": "cond", "type": "text", "params": {"text": "скорость #v#, время #t#"}},
        {"id": "ans", "type": "text", "params": {"text": "S = #S# м"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "v:out", "to": "s:v"}, {"from": "t:out", "to": "s:t"},
        {"from": "v:out", "to": "cond:v"}, {"from": "t:out", "to": "cond:t"},
        {"from": "s:res", "to": "ans:S"},
        {"from": "cond:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {},
}


def test_catalog():
    cat = graph_api.build_catalog()
    assert cat["catalog_version"] == "165616006ce6e373", cat["catalog_version"]
    assert len(cat["nodes"]) == 117, len(cat["nodes"])
    assert cat["port_types"] and cat["conversions"]
    rn = next(n for n in cat["nodes"] if n["type_id"] == "random_natural")
    assert rn["category"] == "source"
    assert rn["outputs"] == [{"name": "out", "type": "number", "required": True}], rn["outputs"]
    assert "min" in rn["params_schema"]
    # у text-узла порты динамические (по маркерам) — INPUTS пуст в шаблоне
    conv = {(c["from"], c["to"]): c["via"] for c in cat["conversions"]}
    assert conv.get(("expr", "number")) == "expr_eval", conv


def test_validate_ok():
    r = graph_api.validate_graph(EXAMPLES["physics_force"]["graph"])
    assert r["ok"] is True, r
    assert r["result_node"] == "task", r["result_node"]
    assert r["errors"] == []


def test_validate_error_verbatim():
    r = graph_api.validate_graph(_BROKEN)
    assert r["ok"] is False
    assert r["result_node"] is None
    assert r["errors"] == ["Провод ссылается на несуществующий выход s:res."], r["errors"]


def test_preview_blocks():
    r = graph_api.preview_graph(EXAMPLES["physics_force"]["graph"], seeds=[0, 1, 2, 3])
    assert r["ok"] is True, r
    assert len(r["runs"]) == 4
    for run in r["runs"]:
        assert run["error"] is None, run
        assert run["statement"] and run["answer"], run
        assert run["statement"][0]["type"] == "text"  # BlockJSON
        assert run["attempts"] >= 1
    # варианты действительно разные (есть случайность)
    stmts = {tuple(b["content"] for b in run["statement"]) for run in r["runs"]}
    assert len(stmts) > 1, "предпросмотр не даёт разнообразия"


def test_probe_clean_and_deterministic():
    rep = graph_probe.probe_graph(EXAMPLES["physics_force"]["graph"])
    agg = rep["aggregates"]
    assert agg["runs_ok"] == 8, agg
    assert agg["distinct_statements"] >= 5, agg          # хорошее разнообразие
    assert agg["double_run_mismatch"] is False, "недетерминизм при seed"
    codes = {f["code"] for f in rep["flags"]}
    assert "F2" not in codes and "D2" not in codes, rep["flags"]


def test_probe_b4_gate_on_deterministic_graph():
    # limit_rational детерминирован (expr_const, без random) — distinct=1, но
    # B4 НЕ ставится (гейт по наличию random-источника).
    graph = EXAMPLES["limit_rational"]["graph"]
    assert graph_probe._has_random_source(graph) is False
    rep = graph_probe.probe_graph(graph, seeds=[0, 1, 2, 3])
    assert rep["aggregates"]["distinct_statements"] == 1, rep["aggregates"]
    assert "B4" not in {f["code"] for f in rep["flags"]}, rep["flags"]
    # а у физики random-источник есть
    assert graph_probe._has_random_source(EXAMPLES["physics_force"]["graph"]) is True


def test_probe_helpers():
    import re
    assert graph_probe._MARKER_RE.findall("дано #v# и #t2#") == ["#v#", "#t2#"]
    assert graph_probe._template("масса 12.5 кг, ускорение 9 м/с") == \
        "масса • кг, ускорение • м/с"


_TESTS = [
    test_catalog,
    test_validate_ok,
    test_validate_error_verbatim,
    test_preview_blocks,
    test_probe_clean_and_deterministic,
    test_probe_b4_gate_on_deterministic_graph,
    test_probe_helpers,
]


def main() -> int:
    failed = 0
    for t in _TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(_TESTS) - failed}/{len(_TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
