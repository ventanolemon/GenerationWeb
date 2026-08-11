"""
Ветки «условие»/«ответ» и подписи проводов (july_language_wishlist §7, §8).

Главное свойство, ради которого всё и сделано так: ветка НЕ хранится, а
вычисляется по графу от финального узла. Поэтому тесты строят граф и
спрашивают, кто куда попал, — будь ветка авторской пометкой, проверять
было бы нечего. Пометка на второй правке разошлась бы с проводами и врала
бы ровно там, где на неё смотрят.

Подписи, наоборот, авторские — и живут по правилам bends: meta, ключ по
паре портов, уборка вслед за своим проводом.

Запуск:
    python -m unittest core.test_graph_branches
"""

from __future__ import annotations

import json
import pathlib
import unittest

from core.graph.branches import EdgeRef
from core.graph.document import GraphDocument

CASES = json.loads(
    (pathlib.Path(__file__).parent / "graph" / "branch_cases.json")
    .read_text(encoding="utf-8"))["cases"]


def _sample() -> GraphDocument:
    """
    a → #a# (условие), c → слот x (ответ), shared → и туда, и туда,
    dead → никуда.
    """
    doc = GraphDocument()
    for nid in ("a", "c", "shared", "dead"):
        doc.add_node("constant_number", {"value": 1}, node_id=nid)
    doc.add_node("task", {"statement": "Дано #a# и #s#",
                          "slots": ["x:number", "y:number"]}, node_id="fin")
    doc.add_edge("a", "out", "fin", "a")
    doc.add_edge("c", "out", "fin", "x")
    doc.add_edge("shared", "out", "fin", "s")
    doc.add_edge("shared", "out", "fin", "y")
    return doc


class BranchTests(unittest.TestCase):

    def test_branches_are_computed_from_the_graph(self):
        # Ничего не размечали — а деление есть.
        b = _sample().branches()
        self.assertEqual(b.sink, "fin")
        self.assertEqual(b.nodes["a"], "statement")
        self.assertEqual(b.nodes["c"], "answer")

    def test_node_feeding_both_sides_is_marked_shared(self):
        # Самый частый случай: величина показана в условии и она же —
        # часть ответа. Отнести её к одной стороне значило бы соврать.
        self.assertEqual(_sample().branches().nodes["shared"], "both")

    def test_node_not_reaching_the_sink_has_no_branch(self):
        # Отсутствие ветки — и есть сообщение «ни на что не влияет»;
        # холст красит такие узлы отдельно.
        self.assertNotIn("dead", _sample().branches().nodes)

    def test_branch_belongs_to_the_wire_not_only_to_the_node(self):
        # У общей величины два провода, и они уходят в РАЗНЫЕ стороны.
        # Красить по узлу-источнику значило бы показать оба одинаковыми.
        b = _sample().branches()
        self.assertEqual(b.edges["shared:out->fin:s"], "statement")
        self.assertEqual(b.edges["shared:out->fin:y"], "answer")

    def test_branch_reaches_deep_up_the_chain(self):
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 2}, node_id="n1")
        doc.add_node("number_base", {}, node_id="mid")
        doc.add_node("task", {"slots": ["x:number"]}, node_id="fin")
        ins = [p.name for p in doc.ports("mid")[0]]
        outs = [p.name for p in doc.ports("mid")[1]]
        doc.add_edge("n1", "out", "mid", ins[0])
        doc.add_edge("mid", outs[0], "fin", "x")
        b = doc.branches()
        self.assertEqual(b.nodes["mid"], "answer")
        self.assertEqual(b.nodes["n1"], "answer")

    def test_shared_branch_propagates_up_a_diamond(self):
        # Ромб: величина через промежуточный узел уходит и в условие, и в
        # ответ. Предок обязан стать общим, иначе подсветка скажет «это
        # только для ответа» там, где оно и в условии тоже.
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 2}, node_id="root")
        doc.add_node("number_base", {}, node_id="mid")
        doc.add_node("task", {"statement": "Дано #s#",
                              "slots": ["x:number"]}, node_id="fin")
        ins = [p.name for p in doc.ports("mid")[0]]
        outs = [p.name for p in doc.ports("mid")[1]]
        doc.add_edge("root", "out", "mid", ins[0])
        doc.add_edge("mid", outs[0], "fin", "s")
        doc.add_edge("mid", outs[0], "fin", "x")
        b = doc.branches()
        self.assertEqual(b.nodes["mid"], "both")
        self.assertEqual(b.nodes["root"], "both")

    def test_answer_template_marker_belongs_to_the_answer(self):
        # Тонкость `task`: вход появляется от #имя# и в условии, и в
        # шаблоне ответа. По имени порта их не различить — только по
        # тому, в каком из двух текстов маркер стоит.
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 1}, node_id="v")
        doc.add_node("task", {"statement": "Посчитайте",
                              "slots": ["x:number"],
                              "layout": "template",
                              "answer_template": "x = #v#"}, node_id="fin")
        doc.add_edge("v", "out", "fin", "v")
        self.assertEqual(doc.branches().nodes["v"], "answer")

    def test_static_task_splits_by_its_two_ports(self):
        doc = GraphDocument()
        doc.add_node("text", {"text": "условие"}, node_id="s")
        doc.add_node("text", {"text": "ответ"}, node_id="a")
        doc.add_node("static_task", {}, node_id="fin")
        doc.add_edge("s", "out", "fin", "statement")
        doc.add_edge("a", "out", "fin", "answer")
        b = doc.branches()
        self.assertEqual(b.nodes["s"], "statement")
        self.assertEqual(b.nodes["a"], "answer")

    def test_no_sink_means_no_branches(self):
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 1}, node_id="a")
        b = doc.branches()
        self.assertIsNone(b.sink)
        self.assertEqual(b.nodes, {})

    def test_two_sinks_mean_no_branches(self):
        # Граф уже ошибочен; подсветка от произвольно выбранного финала
        # накрыла бы настоящую проблему правдоподобной картинкой.
        doc = GraphDocument()
        doc.add_node("static_task", {}, node_id="f1")
        doc.add_node("static_task", {}, node_id="f2")
        self.assertIsNone(doc.branches().sink)

    def test_broken_slot_declaration_does_not_crash(self):
        # Недописанное объявление слота — обычное состояние во время
        # правки. Подсветка не повод ронять холст.
        doc = GraphDocument()
        doc.add_node("task", {"slots": ["x:", "::"]}, node_id="fin")
        doc.branches()

    def test_edge_ref_key_matches_the_document_key(self):
        # Ключи одни и те же: холст ищет ветку провода по тому же ключу,
        # по которому документ хранит его подпись и перегибы.
        from core.graph.document import _edge_key
        self.assertEqual(EdgeRef("n1", "out", "n2", "in").key(),
                         _edge_key("n1", "out", "n2", "in"))


class SharedCaseTests(unittest.TestCase):
    """
    Общие ожидания с веб-редактором (core/graph/branch_cases.json).

    Правило живёт дважды: здесь и в TS-зеркале `branchMap`. Две реализации
    одного правила — ровно тот дрейф, ради которого заведён core_drift, а
    он про TypeScript ничего не знает. Один файл ожиданий на обе стороны:
    разойдясь, они уронят тест той стороны, которая отстала.
    """

    def test_every_case(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                doc = GraphDocument()
                for nid, spec in case["nodes"].items():
                    doc.add_node(spec["type"], spec.get("params") or {},
                                 node_id=nid)
                for src, dst in case["edges"]:
                    doc.add_edge(*src.split(":"), *dst.split(":"))
                result = doc.branches()
                self.assertEqual(result.sink, case["expect_sink"])
                self.assertEqual(dict(result.nodes), case["expect_nodes"])
                self.assertEqual(dict(result.edges), case["expect_edges"])

    def test_cases_file_is_not_empty(self):
        # Пустой файл прошёл бы предыдущий тест, ничего не проверив.
        self.assertGreaterEqual(len(CASES), 5)


class EdgeNoteTests(unittest.TestCase):

    def _doc(self) -> GraphDocument:
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 1}, node_id="a")
        doc.add_node("task", {"slots": ["x:number"]}, node_id="fin")
        doc.add_edge("a", "out", "fin", "x")
        return doc

    def test_empty_by_default(self):
        self.assertEqual(GraphDocument().edge_notes(), {})

    def test_stored_in_meta_and_trimmed(self):
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "  уже отсортировано  ")
        self.assertEqual(doc.edge_note("a", "out", "fin", "x"),
                         "уже отсортировано")
        self.assertIn("edge_notes", doc.meta)

    def test_empty_note_erases_the_key(self):
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        doc.set_edge_note("a", "out", "fin", "x", "   ")
        self.assertEqual(doc.edge_notes(), {})
        self.assertNotIn("edge_notes", doc.meta)

    def test_note_leaves_with_its_wire(self):
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        doc.remove_edge(doc.edges[0])
        self.assertEqual(doc.edge_notes(), {})

    def test_note_leaves_with_a_removed_node(self):
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        doc.remove_node("a")
        self.assertEqual(doc.edge_notes(), {})

    def test_displaced_wire_takes_its_note_away(self):
        # На вход провод один: новый вытесняет старый. Подпись была
        # написана про старый — и должна уйти с ним, иначе всплывёт на
        # новом проводе между теми же портами.
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        doc.add_node("constant_number", {"value": 2}, node_id="b")
        doc.add_edge("b", "out", "fin", "x")
        self.assertEqual(doc.edge_notes(), {})

    def test_note_survives_an_unrelated_edit(self):
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        doc.add_node("constant_number", {"value": 2}, node_id="b")
        doc.remove_node("b")
        self.assertEqual(doc.edge_note("a", "out", "fin", "x"), "текст")

    def test_pruning_invalid_edges_takes_notes_and_bends(self):
        # Ребро исчезает не через remove_edge: слот убрали, вход пропал.
        # Раньше здесь оставался осиротевший перегиб — тем же путём
        # осиротела бы и подпись.
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        doc.set_edge_bends("a", "out", "fin", "x", [[10.0, 20.0]])
        doc.set_params("fin", {"slots": []})
        doc.prune_invalid_edges()
        self.assertEqual(doc.edges, [])
        self.assertEqual(doc.edge_notes(), {})
        self.assertEqual(doc.bends(), {})

    def test_garbage_from_another_client_reads_as_no_note(self):
        # meta приезжает по синку и из файлов, сохранённых старой
        # версией: мусор читается как «подписи нет», а не роняет вызов.
        doc = self._doc()
        doc.meta["edge_notes"] = ["не словарь"]
        self.assertEqual(doc.edge_note("a", "out", "fin", "x"), "")
        doc.meta["edge_notes"] = {"a:out->fin:x": 17}
        self.assertEqual(doc.edge_note("a", "out", "fin", "x"), "")

    def test_round_trip_through_serialization(self):
        doc = self._doc()
        doc.set_edge_note("a", "out", "fin", "x", "текст")
        back = GraphDocument.from_spec_dict(doc.to_spec_dict())
        self.assertEqual(back.edge_note("a", "out", "fin", "x"), "текст")


if __name__ == "__main__":
    unittest.main()
