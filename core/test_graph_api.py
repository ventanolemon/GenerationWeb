"""
Проверка graph-API и probe (Фаза 2), headless и без fastapi.

Роутер generator_service — тонкая обёртка над core.graph_api; вся логика
(каталог, валидация, предпросмотр, probe, поставочные ресурсы)
проверяется здесь напрямую.

Файл был написан со своим раннером: голые `assert`, список функций и
`if __name__ == "__main__"`. Выглядел он тестом, но `unittest discover`
не находил в нём НИ ОДНОГО теста — классов не было, — и общий прогон
показывал «OK», пока семь проверок просто не выполнялись. Обнаружилось
это так, как и должно: одна из них к тому моменту падала (в каталог
прибавились узлы моделей, а прибитые здесь число и хэш остались
прежними), и ни один прогон набора об этом не сообщал.

Запуск:
    python -m unittest core.test_graph_api
"""

from __future__ import annotations
import os
import sys
import unittest

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


class CatalogTests(unittest.TestCase):

    def test_catalog(self):
        # 145 = 140 узлов, объявленных классами в core/graph/nodes (столько
        # же сверяет scripts/core_drift.py), плюс пять узлов моделей: они
        # создаются на лету по реестру моделей, поэтому в исходниках их не
        # видно, а в каталоге они есть.
        #
        # Версия каталога и число узлов прибиты нарочно: клиенты кэшируют
        # каталог по версии, и её незамеченный сдвиг означает, что редактор у
        # кого-то остался со старой палитрой. Меняются они ВМЕСТЕ с составом
        # узлов — это не «падающий тест», а напоминание сверить список.
        cat = graph_api.build_catalog()
        self.assertEqual(cat["catalog_version"], "61377cf5e5311f68")
        self.assertEqual(len(cat["nodes"]), 145)
        self.assertTrue(cat["port_types"] and cat["conversions"])
        rn = next(n for n in cat["nodes"] if n["type_id"] == "random_natural")
        self.assertEqual(rn["category"], "source")
        self.assertEqual(rn["outputs"],
                         [{"name": "out", "type": "number", "required": True}])
        self.assertIn("min", rn["params_schema"])
        # у text-узла порты динамические (по маркерам) — INPUTS пуст в шаблоне
        conv = {(c["from"], c["to"]): c["via"] for c in cat["conversions"]}
        self.assertEqual(conv.get(("expr", "number")), "expr_eval")

    def test_model_nodes_are_in_the_catalog(self):
        """
        Узлы моделей — те самые, из-за которых разошлись прибитые выше
        число и хэш, пока никто этого не видел. Пусть теперь они названы:
        выпадет модель из палитры — упадёт эта проверка, а не арифметика
        в соседней.
        """
        types = {n["type_id"] for n in graph_api.build_catalog()["nodes"]}
        self.assertLessEqual(
            {"model_linal_eigen", "model_linal_triangle", "model_linal_pyramid",
             "model_opvs_circuit", "model_opvs_ccode"}, types)


class ResourcesTests(unittest.TestCase):
    """Поставочные файлы — отдельная ручка (см. core/graph/resources.py)."""

    def test_lists_shipped_files(self):
        payload = graph_api.build_resources()
        self.assertTrue(payload["resources"])
        first = payload["resources"][0]
        self.assertEqual(set(first), {"id", "kind", "name", "title"})

    def test_every_id_is_an_identifier_not_a_path(self):
        # Ровно то, ради чего ручка и появилась: клиент кладёт в граф
        # переносимый идентификатор, а не путь этой машины.
        for res in graph_api.build_resources()["resources"]:
            with self.subTest(id=res["id"]):
                self.assertTrue(res["id"].startswith("res:"))


class ValidateTests(unittest.TestCase):

    def test_validate_ok(self):
        r = graph_api.validate_graph(EXAMPLES["physics_force"]["graph"])
        self.assertIs(r["ok"], True)
        self.assertEqual(r["result_node"], "task")
        self.assertEqual(r["errors"], [])

    def test_validate_error_verbatim(self):
        r = graph_api.validate_graph(_BROKEN)
        self.assertIs(r["ok"], False)
        self.assertIsNone(r["result_node"])
        self.assertEqual(
            r["errors"], ["Провод ссылается на несуществующий выход s:res."])


class PreviewTests(unittest.TestCase):

    def test_preview_blocks(self):
        r = graph_api.preview_graph(EXAMPLES["physics_force"]["graph"],
                                    seeds=[0, 1, 2, 3])
        self.assertIs(r["ok"], True)
        self.assertEqual(len(r["runs"]), 4)
        for run in r["runs"]:
            self.assertIsNone(run["error"])
            self.assertTrue(run["statement"] and run["answer"])
            self.assertEqual(run["statement"][0]["type"], "text")  # BlockJSON
            self.assertGreaterEqual(run["attempts"], 1)
        # варианты действительно разные (есть случайность)
        stmts = {tuple(b["content"] for b in run["statement"])
                 for run in r["runs"]}
        self.assertGreater(len(stmts), 1, "предпросмотр не даёт разнообразия")


class ProbeTests(unittest.TestCase):

    def test_probe_clean_and_deterministic(self):
        rep = graph_probe.probe_graph(EXAMPLES["physics_force"]["graph"])
        agg = rep["aggregates"]
        self.assertEqual(agg["runs_ok"], 8)
        self.assertGreaterEqual(agg["distinct_statements"], 5)  # разнообразие
        self.assertIs(agg["double_run_mismatch"], False, "недетерминизм при seed")
        codes = {f["code"] for f in rep["flags"]}
        self.assertNotIn("F2", codes)
        self.assertNotIn("D2", codes)

    def test_probe_b4_gate_on_deterministic_graph(self):
        # limit_rational детерминирован (expr_const, без random) — distinct=1, но
        # B4 НЕ ставится (гейт по наличию random-источника).
        graph = EXAMPLES["limit_rational"]["graph"]
        self.assertIs(graph_probe._has_random_source(graph), False)
        rep = graph_probe.probe_graph(graph, seeds=[0, 1, 2, 3])
        self.assertEqual(rep["aggregates"]["distinct_statements"], 1)
        self.assertNotIn("B4", {f["code"] for f in rep["flags"]})
        # а у физики random-источник есть
        self.assertIs(
            graph_probe._has_random_source(EXAMPLES["physics_force"]["graph"]),
            True)

    def test_probe_helpers(self):
        self.assertEqual(
            graph_probe._MARKER_RE.findall("дано #v# и #t2#"), ["#v#", "#t2#"])
        self.assertEqual(
            graph_probe._template("масса 12.5 кг, ускорение 9 м/с"),
            "масса • кг, ускорение • м/с")


if __name__ == "__main__":
    unittest.main()
