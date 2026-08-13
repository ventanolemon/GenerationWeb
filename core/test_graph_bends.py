"""
Ручные точки перегиба провода (§7.2 плана, meta["bends"]).

Перегибы живут в meta, а не в самом DocEdge — иначе синк ловит LWW-конфликты
из-за того, что двое просто подвигали провод (безобидный конфликт по
расположению превращается в конфликт по логике соединений). Проверяем ровно
это устройство: ключ по (узел, порт) на обоих концах — а не по индексу в
списке рёбер, — уборку осиротевших перегибов при удалении ребра/узла,
устойчивость к мусору из чужого файла и round-trip сериализации.
"""

from __future__ import annotations

import unittest

from core.graph.document import GraphDocument, _edge_key


def _doc_with_edge(from_node: str = "a", to_node: str = "b") -> GraphDocument:
    doc = GraphDocument()
    doc.add_node("random_natural", {}, 0, 0, node_id=from_node)
    doc.add_node("random_natural", {}, 100, 0, node_id=to_node)
    doc.add_edge(from_node, "out", to_node, "in")
    return doc


class EdgeKeyTests(unittest.TestCase):
    """Формат ключа прибит нарочно: его читают синк-дифф и другие клиенты."""

    def test_key_format(self):
        self.assertEqual(_edge_key("n1", "out", "n2", "in"), "n1:out->n2:in")

    def test_key_distinguishes_ports_not_just_nodes(self):
        # Два провода между теми же узлами, но в разные входы — разные ключи,
        # иначе перегиб одного провода перепрыгнул бы на другой.
        k1 = _edge_key("n1", "out", "n2", "a")
        k2 = _edge_key("n1", "out", "n2", "b")
        self.assertNotEqual(k1, k2)


class BendsStorageTests(unittest.TestCase):

    def test_empty_by_default(self):
        doc = GraphDocument()
        self.assertEqual(doc.bends(), {})
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [])

    def test_set_and_read_back(self):
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[10, 20], [30, 40]])
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"),
                         [[10.0, 20.0], [30.0, 40.0]])

    def test_stored_under_edge_key(self):
        # Хранилище — по образцу comments: meta напрямую, никакой обёртки.
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[1, 2]])
        self.assertEqual(doc.meta["bends"], {"a:out->b:in": [[1.0, 2.0]]})

    def test_empty_points_erases_key_not_leaves_empty_list(self):
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[1, 2]])
        doc.set_edge_bends("a", "out", "b", "in", [])
        # Ключа не должно остаться вовсе — иначе meta пухнет мусором и
        # диффы синка шумят на пустом месте.
        self.assertNotIn("a:out->b:in", doc.bends())
        self.assertNotIn("bends", doc.meta)

    def test_different_edges_independent(self):
        doc = GraphDocument()
        doc.add_node("random_natural", {}, 0, 0, node_id="a")
        doc.add_node("random_natural", {}, 100, 0, node_id="b")
        doc.add_node("random_natural", {}, 100, 100, node_id="c")
        doc.add_edge("a", "out", "b", "in")
        doc.add_edge("a", "out", "c", "in")
        doc.set_edge_bends("a", "out", "b", "in", [[1, 1]])
        doc.set_edge_bends("a", "out", "c", "in", [[2, 2]])
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [[1.0, 1.0]])
        self.assertEqual(doc.edge_bends("a", "out", "c", "in"), [[2.0, 2.0]])

    def test_clear_bends(self):
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[1, 2]])
        doc.clear_bends()
        self.assertEqual(doc.bends(), {})
        self.assertNotIn("bends", doc.meta)


class CleanupOnRemovalTests(unittest.TestCase):
    """
    Осиротевший перегиб — мусор, который переживёт удалённый узел/ребро и
    молча всплывёт, если id когда-нибудь переиспользуют.
    """

    def test_remove_edge_drops_its_bends(self):
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[1, 2]])
        edge = doc.edges[0]
        doc.remove_edge(edge)
        self.assertEqual(doc.bends(), {})

    def test_remove_edge_keeps_other_edges_bends(self):
        doc = GraphDocument()
        doc.add_node("random_natural", {}, 0, 0, node_id="a")
        doc.add_node("random_natural", {}, 100, 0, node_id="b")
        doc.add_node("random_natural", {}, 100, 100, node_id="c")
        doc.add_edge("a", "out", "b", "in")
        doc.add_edge("a", "out", "c", "in")
        doc.set_edge_bends("a", "out", "b", "in", [[1, 1]])
        doc.set_edge_bends("a", "out", "c", "in", [[2, 2]])
        gone = next(e for e in doc.edges if e.to_node == "b")
        doc.remove_edge(gone)
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [])
        self.assertEqual(doc.edge_bends("a", "out", "c", "in"), [[2.0, 2.0]])

    def test_remove_node_drops_bends_of_all_its_edges(self):
        # Узел b — и приёмник (от a), и источник (к c): оба его провода
        # должны потерять перегибы при удалении b.
        doc = GraphDocument()
        doc.add_node("random_natural", {}, 0, 0, node_id="a")
        doc.add_node("random_natural", {}, 100, 0, node_id="b")
        doc.add_node("random_natural", {}, 200, 0, node_id="c")
        doc.add_edge("a", "out", "b", "in")
        doc.add_edge("b", "out", "c", "in")
        doc.set_edge_bends("a", "out", "b", "in", [[1, 1]])
        doc.set_edge_bends("b", "out", "c", "in", [[2, 2]])
        doc.remove_node("b")
        self.assertEqual(doc.bends(), {})

    def test_remove_node_keeps_unrelated_bends(self):
        doc = GraphDocument()
        doc.add_node("random_natural", {}, 0, 0, node_id="a")
        doc.add_node("random_natural", {}, 100, 0, node_id="b")
        doc.add_node("random_natural", {}, 100, 100, node_id="c")
        doc.add_edge("a", "out", "b", "in")
        doc.add_edge("a", "out", "c", "in")
        doc.set_edge_bends("a", "out", "b", "in", [[1, 1]])
        doc.set_edge_bends("a", "out", "c", "in", [[2, 2]])
        doc.remove_node("b")
        self.assertEqual(doc.edge_bends("a", "out", "c", "in"), [[2.0, 2.0]])

    def test_id_reuse_after_removal_starts_clean(self):
        # Ровно сценарий из задачи: узел с тем же id появился снова — его
        # провод не должен унаследовать перегиб чужого прошлого провода.
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[9, 9]])
        doc.remove_node("b")
        doc.add_node("random_natural", {}, 100, 0, node_id="b")
        doc.add_edge("a", "out", "b", "in")
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [])


class SerializationRoundTripTests(unittest.TestCase):

    def test_round_trip_preserves_bends_verbatim(self):
        doc = _doc_with_edge()
        doc.set_edge_bends("a", "out", "b", "in", [[10, 20], [30, 40]])
        data = doc.to_spec_dict()
        restored = GraphDocument.from_spec_dict(data)
        self.assertEqual(restored.bends(), doc.bends())
        self.assertEqual(restored.edge_bends("a", "out", "b", "in"),
                         [[10.0, 20.0], [30.0, 40.0]])

    def test_round_trip_with_no_bends_adds_no_key(self):
        doc = _doc_with_edge()
        data = doc.to_spec_dict()
        self.assertNotIn("bends", data["meta"])
        restored = GraphDocument.from_spec_dict(data)
        self.assertEqual(restored.bends(), {})


class GarbageMetaTests(unittest.TestCase):
    """
    meta["bends"] может прийти от чужого клиента синком или из файла старой
    версии — форматом каким угодно. Ни один метод не должен упасть.
    """

    def test_bends_not_a_dict(self):
        doc = GraphDocument()
        doc.meta["bends"] = "не словарь"
        self.assertEqual(doc.bends(), {})
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [])

    def test_bends_is_a_list(self):
        doc = GraphDocument()
        doc.meta["bends"] = ["мусор"]
        self.assertEqual(doc.bends(), {})

    def test_value_for_key_not_a_list(self):
        doc = GraphDocument()
        doc.meta["bends"] = {"a:out->b:in": "не список точек"}
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [])

    def test_points_with_wrong_arity_are_skipped(self):
        doc = GraphDocument()
        doc.meta["bends"] = {"a:out->b:in": [[1, 2], [1], [1, 2, 3], [1, 2]]}
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"),
                         [[1.0, 2.0], [1.0, 2.0]])

    def test_non_numeric_points_are_skipped(self):
        doc = GraphDocument()
        doc.meta["bends"] = {"a:out->b:in": [["x", "y"], [3, 4]]}
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [[3.0, 4.0]])

    def test_point_not_list_or_tuple_is_skipped(self):
        doc = GraphDocument()
        doc.meta["bends"] = {"a:out->b:in": [42, "строка", None, [5, 6]]}
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [[5.0, 6.0]])

    def test_tuple_points_accepted(self):
        doc = GraphDocument()
        doc.meta["bends"] = {"a:out->b:in": [(7, 8)]}
        self.assertEqual(doc.edge_bends("a", "out", "b", "in"), [[7.0, 8.0]])

    def test_remove_node_survives_garbage_bends(self):
        # Мусор в meta не должен мешать уборке при удалении узла/ребра.
        doc = _doc_with_edge()
        doc.meta["bends"] = "мусор"
        doc.remove_node("b")  # не должно бросить исключение


if __name__ == "__main__":
    unittest.main()
