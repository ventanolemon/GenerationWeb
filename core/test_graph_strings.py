"""
Случайные слова, буквенная нумерация и начальное значение регистра.

Второй и третий куски разбора старых генераторов
(docs/architecture/informatics_on_july.md).

Узлы `random_word`, `text_length` и `letter_keys` к информатике отношения
не имеют, хотя нашлись на ней: случайное слово нужно и заданию на вес
текста, и на URL, а нумерация «а) б) в)» — и английскому с его вариантами
ответа, и русскому.

Третий кусок — про цикл. Начальное значение регистра сдвига задавалось
литералом в объявлении (`акк:number:0`), проводом его подать было нельзя,
и случайный старт приходилось обходить импортом плюс `loop_index == 0`
плюс мультиплексором. Четыре лишних узла в теле там, где просилось ребро.
"""

from __future__ import annotations

import unittest

from core.graph.errors import GraphValidationError
from core.graph.executor import GraphExecutor
from core.graph.nodes import DEFAULT_REGISTRY
from core.graph.nodes.strings import LATIN
from core.graph.port_types import PortType
from core.graph.spec import GraphSpec


def _run(graph):
    return GraphExecutor(GraphSpec.parse(graph)).run()


class RandomWordTests(unittest.TestCase):

    def _words(self, **params):
        node = DEFAULT_REGISTRY.create("random_word", "w", params)
        import random
        from core.graph.node import ExecContext
        return node.compute({}, ExecContext(rng=random.Random(7)))["out"]

    def test_one_word_is_a_string_several_are_a_list(self):
        """
        Тип выхода следует количеству: список из одного элемента
        заставлял бы автора его разбирать в самом частом случае.
        """
        self.assertEqual(
            DEFAULT_REGISTRY.create("random_word", "w", {"count": 1})
            .output_ports()[0].type, PortType.STRING)
        self.assertEqual(
            DEFAULT_REGISTRY.create("random_word", "w", {"count": 4})
            .output_ports()[0].type, PortType.LIST)

    def test_length_is_within_the_range(self):
        for word in self._words(count=8, min_length=3, max_length=6):
            with self.subTest(word=word):
                self.assertTrue(3 <= len(word) <= 6, word)

    def test_letters_come_from_the_alphabet(self):
        word = self._words(alphabet="абв", min_length=5, max_length=5)
        self.assertTrue(set(word) <= set("абв"), word)

    def test_unique_letters(self):
        word = self._words(min_length=8, max_length=8, unique_letters="yes")
        self.assertEqual(len(set(word)), len(word), word)

    def test_distinct_lengths(self):
        words = self._words(count=6, min_length=4, max_length=15,
                            distinct_lengths="yes")
        self.assertEqual(len({len(w) for w in words}), 6, words)

    def test_repeated_alphabet_letters_do_not_skew(self):
        """
        Повторённая буква иначе выпадала бы чаще прочих, а автор об этом
        не догадается — он просто написал алфавит с опечаткой.
        """
        node = DEFAULT_REGISTRY.create("random_word", "w",
                                       {"alphabet": "ааабв"})
        self.assertEqual(node._alphabet(), "абв")

    def test_impossible_requests_are_refused_when_saving(self):
        # Слово длиннее алфавита без повторов не составить.
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("random_word", "w", {
                "alphabet": "абв", "min_length": 5, "max_length": 5,
                "unique_letters": "yes"})
        # Восьми разных длин из диапазона 3..6 не набрать.
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("random_word", "w", {
                "count": 8, "min_length": 3, "max_length": 6,
                "distinct_lengths": "yes"})
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("random_word", "w", {"alphabet": ""})
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("random_word", "w",
                                    {"min_length": 5, "max_length": 3})

    def test_default_alphabet_is_latin(self):
        self.assertTrue(set(self._words()) <= set(LATIN))


class TextLengthTests(unittest.TestCase):

    def test_counts_characters(self):
        graph = {"nodes": [
            {"id": "s", "type": "constant_string",
             "params": {"value": "привет"}},
            {"id": "n", "type": "text_length", "params": {}},
            {"id": "t", "type": "task", "params": {
                "statement": "?", "slots": ["x:number"]}},
        ], "edges": [{"from": "s:out", "to": "n:in"},
                     {"from": "n:out", "to": "t:x"}]}
        self.assertEqual(_run(graph).answer_spec.value, 6.0)

    def test_empty_string_is_zero(self):
        from core.graph.node import ExecContext
        import random
        node = DEFAULT_REGISTRY.create("text_length", "n", {})
        self.assertEqual(
            node.compute({"in": ""}, ExecContext(rng=random.Random(0)))["out"],
            0.0)


class LetterKeysTests(unittest.TestCase):

    def _keys(self, items, **params):
        import random
        from core.graph.node import ExecContext
        node = DEFAULT_REGISTRY.create("letter_keys", "k", params)
        return node.compute({"in": items}, ExecContext(rng=random.Random(1)))

    def test_labels_in_order(self):
        out = self._keys(["раз", "два", "три"])
        self.assertEqual(out["keys"], ["а", "б", "в"])
        self.assertEqual(out["labelled"], ["а) раз", "б) два", "в) три"])

    def test_keys_are_a_separate_output(self):
        """
        Ответом в таких заданиях бывает сама последовательность ключей
        («расшифруйте слово» — это «абв»), и склеенный вид для этого не
        годится.
        """
        self.assertEqual("".join(self._keys(["a", "b"])["keys"]), "аб")

    def test_separator_is_a_parameter(self):
        out = self._keys(["раз"], separator=". ")
        self.assertEqual(out["labelled"], ["а. раз"])

    def test_running_out_of_letters_is_an_error(self):
        with self.assertRaises(GraphValidationError):
            self._keys([str(i) for i in range(40)])

    def test_empty_list_gives_empty(self):
        self.assertEqual(self._keys([])["labelled"], [])


class RegisterInitialFromAWireTests(unittest.TestCase):
    """
    Начальное значение регистра — проводом.

    Раньше оно писалось литералом в объявлении, и случайный старт
    обходился так: импорт старта в тело + `loop_index == 0` + `select`.
    Четыре узла и неочевидная конструкция на месте одного ребра.
    """

    BODY = {"nodes": [
        {"id": "акк", "type": "shift_get",
         "params": {"name": "акк", "type": "number"}},
        {"id": "f", "type": "formula", "params": {"expr": "x + 1"}},
        {"id": "зап", "type": "shift_set",
         "params": {"name": "акк", "type": "number"}},
        {"id": "о", "type": "output_var",
         "params": {"name": "итог", "type": "number"}},
        {"id": "tb", "type": "to_block", "params": {}},
    ], "edges": [
        {"from": "акк:out", "to": "f:x"},
        {"from": "f:out", "to": "зап:value"},
        {"from": "зап:out", "to": "о:value"},
        {"from": "зап:out", "to": "tb:in"},
    ], "meta": {}}

    def _graph(self, *, wired: bool, literal=None):
        register = "акк:number" + (f":{literal}" if literal is not None else "")
        nodes = [
            {"id": "ц", "type": "repeat", "params": {
                "count": 3, "registers": [register],
                "outputs": ["итог:number:last"], "body": self.BODY}},
            {"id": "t", "type": "task", "params": {
                "statement": "?", "slots": ["x:number"]}},
        ]
        edges = [{"from": "ц:итог", "to": "t:x"}]
        if wired:
            nodes.append({"id": "старт", "type": "constant_number",
                          "params": {"value": 100}})
            edges.append({"from": "старт:out", "to": "ц:reg_акк"})
        return {"nodes": nodes, "edges": edges}

    def test_the_port_exists(self):
        node = DEFAULT_REGISTRY.create("repeat", "ц", {
            "count": 2, "registers": ["акк:number"]})
        names = [p.name for p in node.input_ports()]
        self.assertIn("reg_акк", names)

    def test_the_wire_sets_the_start(self):
        # 100, потом три раза +1.
        self.assertEqual(_run(self._graph(wired=True)).answer_spec.value, 103.0)

    def test_the_literal_still_works(self):
        self.assertEqual(
            _run(self._graph(wired=False, literal=5)).answer_spec.value, 8.0)

    def test_the_wire_beats_the_literal(self):
        """
        Иначе автору пришлось бы стирать литерал, чтобы провод заработал,
        — молчаливая ловушка ровно того сорта, которого быть не должно.
        """
        self.assertEqual(
            _run(self._graph(wired=True, literal=5)).answer_spec.value, 103.0)

    def test_default_is_unchanged(self):
        self.assertEqual(_run(self._graph(wired=False)).answer_spec.value, 3.0)

    def test_an_import_may_not_shadow_the_register_port(self):
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("repeat", "ц", {
                "count": 2, "registers": ["акк:number"],
                "imports": ["reg_акк:number"]})


class Generator1Tests(unittest.TestCase):
    """
    Старое задание «вес текста»: восемь узлов, десять проводов.

    Проверяется арифметика — вес уменьшился ровно на (длина + 2) × цена,
    и ответ это то самое слово.
    """

    GRAPH = {
        "nodes": [
            {"id": "сл", "type": "random_word", "params": {
                "count": 7, "min_length": 4, "max_length": 15,
                "distinct_lengths": "yes", "unique_letters": "yes"}},
            {"id": "цена", "type": "random_choice", "params": {
                "elem_type": "number", "items": [1, 2, 4, 6, 8], "count": 1}},
            {"id": "вычерк", "type": "random_choice",
             "params": {"elem_type": "string", "count": 1}},
            {"id": "текст", "type": "list_join", "params": {"sep": ", "}},
            {"id": "дл", "type": "text_length", "params": {}},
            {"id": "бит", "type": "formula",
             "params": {"expr": "8*k", "constants": "off"}},
            {"id": "вес", "type": "formula",
             "params": {"expr": "(n + 2) * k", "constants": "off"}},
            {"id": "t", "type": "task", "params": {
                "statement": "Символ кодируется #бит# битами. Текст:\n"
                             "#текст#\nВес упал на #вес# байт. Какое слово?",
                "slots": ["слово:text"]}},
        ],
        "edges": [
            {"from": "сл:out", "to": "вычерк:list"},
            {"from": "сл:out", "to": "текст:in"},
            {"from": "вычерк:out", "to": "дл:in"},
            {"from": "дл:out", "to": "вес:n"},
            {"from": "цена:out", "to": "бит:k"},
            {"from": "цена:out", "to": "вес:k"},
            {"from": "текст:out", "to": "t:текст"},
            {"from": "бит:out", "to": "t:бит"},
            {"from": "вес:out", "to": "t:вес"},
            {"from": "вычерк:out", "to": "t:слово"},
        ],
    }

    def test_the_arithmetic_holds(self):
        import re
        for _ in range(20):
            task = _run(self.GRAPH)
            shown = task.statement[0].render_plain()
            bits = int(re.search(r"кодируется (\d+) битами", shown).group(1))
            weight = int(re.search(r"упал на (\d+) байт", shown).group(1))
            answer = task.answer_spec.accepted_examples()[0]
            self.assertEqual(weight, (len(answer) + 2) * (bits // 8), shown)

    def test_the_answer_is_one_of_the_words(self):
        for _ in range(20):
            task = _run(self.GRAPH)
            words = task.statement[0].render_plain().split("\n")[1].split(", ")
            self.assertIn(task.answer_spec.accepted_examples()[0], words)

    def test_words_have_distinct_lengths(self):
        """
        Иначе «какое слово вычеркнули» имеет несколько ответов, и
        задание становится нечестным.
        """
        for _ in range(20):
            words = _run(self.GRAPH).statement[0].render_plain() \
                .split("\n")[1].split(", ")
            self.assertEqual(len({len(w) for w in words}), len(words), words)


class Generator7Tests(unittest.TestCase):
    """Старое задание «соберите адрес»: фрагменты вперемешку с ключами."""

    GRAPH = {
        "nodes": [
            {"id": "прот", "type": "pool", "params": {
                "columns": ["v"], "rows": ["http", "ftp", "https"]}},
            {"id": "pп", "type": "pool_pick", "params": {"columns": ["v"]}},
            {"id": "дом", "type": "pool", "params": {
                "columns": ["v"], "rows": [".org", ".com", ".ru", ".net"]}},
            {"id": "pд", "type": "pool_pick", "params": {"columns": ["v"]}},
            {"id": "расш", "type": "pool", "params": {
                "columns": ["v"], "rows": [".bmp", ".txt", ".gif", ".htm"]}},
            {"id": "pр", "type": "pool_pick", "params": {"columns": ["v"]}},
            {"id": "имя", "type": "random_word", "params": {
                "min_length": 3, "max_length": 6, "unique_letters": "yes"}},
            {"id": "файл", "type": "random_word", "params": {
                "min_length": 3, "max_length": 6, "unique_letters": "yes"}},
            {"id": "сайт", "type": "template", "params": {"text": "#имя##дом#"}},
            {"id": "док", "type": "template", "params": {"text": "#файл##расш#"}},
            {"id": "сл1", "type": "constant_string", "params": {"value": "://"}},
            {"id": "сл2", "type": "constant_string", "params": {"value": "/"}},
            {"id": "куски", "type": "list_new",
             "params": {"count": 5, "elem_type": "string"}},
            {"id": "пер", "type": "random_choice", "params": {
                "elem_type": "string", "count": 5, "allow_duplicates": False}},
            {"id": "кл", "type": "letter_keys", "params": {}},
            {"id": "спис", "type": "list_join", "params": {"sep": "\n"}},
            {"id": "url", "type": "list_join", "params": {"sep": ""}},
            {"id": "t", "type": "task", "params": {
                "statement": "Соберите адрес:\n#варианты#",
                "slots": ["адрес:text"]}},
        ],
        "edges": [
            {"from": "прот:out", "to": "pп:in"},
            {"from": "дом:out", "to": "pд:in"},
            {"from": "расш:out", "to": "pр:in"},
            {"from": "имя:out", "to": "сайт:имя"},
            {"from": "pд:v", "to": "сайт:дом"},
            {"from": "файл:out", "to": "док:файл"},
            {"from": "pр:v", "to": "док:расш"},
            {"from": "pп:v", "to": "куски:in0"},
            {"from": "сл1:out", "to": "куски:in1"},
            {"from": "сайт:out", "to": "куски:in2"},
            {"from": "сл2:out", "to": "куски:in3"},
            {"from": "док:out", "to": "куски:in4"},
            {"from": "куски:out", "to": "пер:list"},
            {"from": "пер:out", "to": "кл:in"},
            {"from": "кл:labelled", "to": "спис:in"},
            {"from": "куски:out", "to": "url:in"},
            {"from": "спис:out", "to": "t:варианты"},
            {"from": "url:out", "to": "t:адрес"},
        ],
    }

    def test_the_answer_is_a_well_formed_address(self):
        for _ in range(20):
            answer = _run(self.GRAPH).answer_spec.accepted_examples()[0]
            self.assertRegex(
                answer, r"^(http|https|ftp)://[a-z]+\.[a-z]+/[a-z]+\.[a-z]+$")

    def test_every_fragment_is_shown_exactly_once(self):
        """
        Перемешивание — это перестановка, а не выборка: потерять кусок
        значит сделать задание нерешаемым.
        """
        for _ in range(20):
            task = _run(self.GRAPH)
            lines = task.statement[0].render_plain().split("\n")[1:]
            pieces = sorted(line.split(") ", 1)[1] for line in lines)
            answer = task.answer_spec.accepted_examples()[0]
            self.assertEqual(len(pieces), 5)
            self.assertEqual("".join(sorted("".join(pieces))),
                             "".join(sorted(answer)))

    def test_fragments_are_lettered(self):
        lines = _run(self.GRAPH).statement[0].render_plain().split("\n")[1:]
        self.assertEqual([line[0] for line in lines], list("абвгд"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
