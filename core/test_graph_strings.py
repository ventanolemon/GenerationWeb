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


class ComparisonOperatorAsDataTests(unittest.TestCase):
    """
    Знак сравнения — данные, а не настройка узла.

    Поймано на задании «сколько раз программа выведет YES»: знак там
    выбирается случайно. Обойти это было нечем — четыре узла с
    фиксированными знаками надо было бы выбирать мультиплексором, а
    `pick` булевы каналы не берёт вовсе.
    """

    def _cmp(self, a, b, *, param="==", wired=None):
        graph = {"nodes": [
            {"id": "a", "type": "constant_number", "params": {"value": a}},
            {"id": "b", "type": "constant_number", "params": {"value": b}},
            {"id": "c", "type": "compare", "params": {"op": param}},
            {"id": "n", "type": "bool_number", "params": {}},
            {"id": "t", "type": "task", "params": {
                "statement": "?", "slots": ["x:number"]}},
        ], "edges": [
            {"from": "a:out", "to": "c:a"}, {"from": "b:out", "to": "c:b"},
            {"from": "c:out", "to": "n:in"}, {"from": "n:out", "to": "t:x"},
        ]}
        if wired is not None:
            graph["nodes"].append({"id": "op", "type": "constant_string",
                                   "params": {"value": wired}})
            graph["edges"].append({"from": "op:out", "to": "c:op"})
        return _run(graph).answer_spec.value == 1.0

    def test_every_operator_works_through_the_wire(self):
        cases = {"<": (1, 2), "<=": (2, 2), ">": (3, 2), ">=": (2, 2),
                 "==": (2, 2), "!=": (1, 2)}
        for op, (a, b) in cases.items():
            with self.subTest(op=op):
                self.assertTrue(self._cmp(a, b, wired=op))

    def test_the_wire_beats_the_parameter(self):
        # Параметр говорит «равно», провод — «меньше».
        self.assertTrue(self._cmp(1, 2, param="==", wired="<"))

    def test_the_parameter_still_works_alone(self):
        self.assertTrue(self._cmp(2, 2, param="=="))
        self.assertFalse(self._cmp(1, 2, param="=="))

    def test_garbage_on_the_wire_does_not_pass_silently(self):
        """
        Подставить «==» молча значило бы сравнивать не тем знаком, и
        никто бы не заметил.
        """
        from core.graph.errors import GraphError
        with self.assertRaises(GraphError):
            self._cmp(1, 2, wired="≈")


class BoolReachesArithmeticTests(unittest.TestCase):
    """
    «Сколько случаев подходит» — форма, которой полна информатика.
    Без превращения логического в число она собиралась мультиплексором с
    двумя константами на каждое сравнение.
    """

    def _value(self, flag):
        graph = {"nodes": [
            {"id": "b", "type": "constant_bool", "params": {"value": flag}},
            {"id": "n", "type": "bool_number", "params": {}},
            {"id": "t", "type": "task", "params": {
                "statement": "?", "slots": ["x:number"]}},
        ], "edges": [{"from": "b:out", "to": "n:in"},
                     {"from": "n:out", "to": "t:x"}]}
        return _run(graph).answer_spec.value

    def test_yes_is_one_no_is_zero(self):
        self.assertEqual(self._value(True), 1.0)
        self.assertEqual(self._value(False), 0.0)

    def test_the_editor_can_insert_it_automatically(self):
        """
        Провод BOOL → NUMBER теперь предлагает конвертер, а не отказ.
        """
        from core.graph.conversions import find_converter
        from core.graph.port_types import PortType
        self.assertEqual(find_converter(PortType.BOOL, PortType.NUMBER),
                         "bool_number")


class Generator6Tests(unittest.TestCase):
    """
    Старое задание «сколько раз выведет YES»: одиннадцать узлов снаружи и
    девятнадцать в теле цикла.

    Проверяется независимым пересчётом: ответ обязан совпасть с тем, что
    даёт прямое вычисление предиката по показанным наборам.
    """

    OPS = ["<", "<=", ">", ">="]
    BODY = {"nodes": [
        {"id": "i", "type": "loop_index", "params": {}},
        {"id": "N_", "type": "input_var", "params": {"name": "N", "type": "list"}},
        {"id": "T_", "type": "input_var", "params": {"name": "T", "type": "list"}},
        {"id": "n", "type": "list_get", "params": {"elem_type": "number"}},
        {"id": "t", "type": "list_get", "params": {"elem_type": "number"}},
        {"id": "пN", "type": "input_var",
         "params": {"name": "порогN", "type": "number"}},
        {"id": "пT", "type": "input_var",
         "params": {"name": "порогT", "type": "number"}},
        {"id": "оN", "type": "input_var",
         "params": {"name": "опN", "type": "string"}},
        {"id": "оT", "type": "input_var",
         "params": {"name": "опT", "type": "string"}},
        {"id": "срN", "type": "compare", "params": {}},
        {"id": "срT", "type": "compare", "params": {}},
        {"id": "чN", "type": "bool_number", "params": {}},
        {"id": "чT", "type": "bool_number", "params": {}},
        {"id": "и", "type": "formula",
         "params": {"expr": "p*q", "constants": "off"}},
        {"id": "акк", "type": "shift_get",
         "params": {"name": "счёт", "type": "number"}},
        {"id": "плюс", "type": "formula",
         "params": {"expr": "a + b", "constants": "off"}},
        {"id": "зап", "type": "shift_set",
         "params": {"name": "счёт", "type": "number"}},
        {"id": "о", "type": "output_var",
         "params": {"name": "итог", "type": "number"}},
        {"id": "tb", "type": "to_block", "params": {}}],
        "edges": [
            {"from": "i:out", "to": "n:index"},
            {"from": "N_:out", "to": "n:list"},
            {"from": "i:out", "to": "t:index"},
            {"from": "T_:out", "to": "t:list"},
            {"from": "n:out", "to": "срN:a"},
            {"from": "пN:out", "to": "срN:b"},
            {"from": "оN:out", "to": "срN:op"},
            {"from": "t:out", "to": "срT:a"},
            {"from": "пT:out", "to": "срT:b"},
            {"from": "оT:out", "to": "срT:op"},
            {"from": "срN:out", "to": "чN:in"},
            {"from": "срT:out", "to": "чT:in"},
            {"from": "чN:out", "to": "и:p"},
            {"from": "чT:out", "to": "и:q"},
            {"from": "акк:out", "to": "плюс:a"},
            {"from": "и:out", "to": "плюс:b"},
            {"from": "плюс:out", "to": "зап:value"},
            {"from": "зап:out", "to": "о:value"},
            {"from": "зап:out", "to": "tb:in"}], "meta": {}}

    @property
    def GRAPH(self):
        return {"nodes": [
            {"id": "диап", "type": "number_range",
             "params": {"start": -25, "stop": 100, "step": 1}},
            {"id": "N", "type": "random_choice", "params": {
                "elem_type": "number", "count": 9, "allow_duplicates": True}},
            {"id": "T", "type": "random_choice", "params": {
                "elem_type": "number", "count": 9, "allow_duplicates": True}},
            {"id": "пN", "type": "random_natural", "params": {"min": 1, "max": 100}},
            {"id": "пT", "type": "random_natural", "params": {"min": 1, "max": 100}},
            {"id": "оN", "type": "random_choice", "params": {
                "elem_type": "string", "items": self.OPS, "count": 1}},
            {"id": "оT", "type": "random_choice", "params": {
                "elem_type": "string", "items": self.OPS, "count": 1}},
            {"id": "ц", "type": "repeat", "params": {
                "count": 9,
                "imports": ["N:list", "T:list", "порогN:number",
                            "порогT:number", "опN:string", "опT:string"],
                "registers": ["счёт:number:0"],
                "outputs": ["итог:number:last"], "body": self.BODY}},
            {"id": "jN", "type": "list_join", "params": {"sep": ", "}},
            {"id": "jT", "type": "list_join", "params": {"sep": ", "}},
            {"id": "t", "type": "task", "params": {
                "statement": "Печатает YES, если N #опN# #пN# И T #опT# #пT#.\n"
                             "N: #сN#\nT: #сT#\nСколько раз?",
                "slots": ["сколько:number"]}}],
            "edges": [
                {"from": "диап:out", "to": "N:list"},
                {"from": "диап:out", "to": "T:list"},
                {"from": "N:out", "to": "ц:N"}, {"from": "T:out", "to": "ц:T"},
                {"from": "пN:out", "to": "ц:порогN"},
                {"from": "пT:out", "to": "ц:порогT"},
                {"from": "оN:out", "to": "ц:опN"},
                {"from": "оT:out", "to": "ц:опT"},
                {"from": "N:out", "to": "jN:in"},
                {"from": "T:out", "to": "jT:in"},
                {"from": "jN:out", "to": "t:сN"},
                {"from": "jT:out", "to": "t:сT"},
                {"from": "оN:out", "to": "t:опN"},
                {"from": "оT:out", "to": "t:опT"},
                {"from": "пN:out", "to": "t:пN"},
                {"from": "пT:out", "to": "t:пT"},
                {"from": "ц:итог", "to": "t:сколько"}]}

    def test_the_count_matches_a_direct_recount(self):
        import operator
        import re
        ops = {"<": operator.lt, "<=": operator.le,
               ">": operator.gt, ">=": operator.ge}
        for _ in range(25):
            task = _run(self.GRAPH)
            shown = task.statement[0].render_plain()
            found = re.search(r"N (\S+) (\d+) И T (\S+) (\d+)", shown)
            ns = [int(x) for x in
                  shown.split("N: ")[1].split("\n")[0].split(", ")]
            ts = [int(x) for x in
                  shown.split("T: ")[1].split("\n")[0].split(", ")]
            want = sum(1 for n, t in zip(ns, ts)
                       if ops[found.group(1)](n, int(found.group(2)))
                       and ops[found.group(3)](t, int(found.group(4))))
            self.assertEqual(
                int(float(task.answer_spec.accepted_examples()[0])), want,
                shown)

    def test_the_task_is_checkable(self):
        task = _run(self.GRAPH)
        self.assertTrue(task.is_checkable)


class Generator8Tests(unittest.TestCase):
    """
    Старое задание про поисковые запросы: включение-исключение.
    Тринадцать узлов, семнадцать проводов, ни одного нового узла.
    """

    GRAPH = {
        "nodes": [
            {"id": "x", "type": "random_word", "params": {
                "min_length": 3, "max_length": 7, "unique_letters": "yes"}},
            {"id": "y", "type": "random_word", "params": {
                "min_length": 3, "max_length": 7, "unique_letters": "yes"}},
            {"id": "nx", "type": "random_natural",
             "params": {"min": 5, "max": 50, "step": 1}},
            {"id": "ny", "type": "random_natural",
             "params": {"min": 5, "max": 50, "step": 1}},
            {"id": "пер", "type": "random_natural", "params": {"min": 1, "max": 4}},
            {"id": "мин", "type": "formula",
             "params": {"expr": "min(a,b)", "constants": "off"}},
            {"id": "inter", "type": "formula",
             "params": {"expr": "floor(m/k)", "constants": "off"}},
            {"id": "union", "type": "formula",
             "params": {"expr": "a + b - i", "constants": "off"}},
            {"id": "сотX", "type": "formula",
             "params": {"expr": "100*a", "constants": "off"}},
            {"id": "сотU", "type": "formula",
             "params": {"expr": "100*u", "constants": "off"}},
            {"id": "сотI", "type": "formula",
             "params": {"expr": "100*i", "constants": "off"}},
            {"id": "сотY", "type": "formula",
             "params": {"expr": "100*b", "constants": "off"}},
            {"id": "t", "type": "task", "params": {
                "statement": "Найдено страниц:\n#X# — #nX#\n#X# | #Y# — #nU#\n"
                             "#X# & #Y# — #nI#\nСколько найдёт #Y#?",
                "slots": ["сколько:number"]}}],
        "edges": [
            {"from": "nx:out", "to": "мин:a"}, {"from": "ny:out", "to": "мин:b"},
            {"from": "мин:out", "to": "inter:m"},
            {"from": "пер:out", "to": "inter:k"},
            {"from": "nx:out", "to": "union:a"},
            {"from": "ny:out", "to": "union:b"},
            {"from": "inter:out", "to": "union:i"},
            {"from": "nx:out", "to": "сотX:a"},
            {"from": "union:out", "to": "сотU:u"},
            {"from": "inter:out", "to": "сотI:i"},
            {"from": "ny:out", "to": "сотY:b"},
            {"from": "x:out", "to": "t:X"}, {"from": "y:out", "to": "t:Y"},
            {"from": "сотX:out", "to": "t:nX"},
            {"from": "сотU:out", "to": "t:nU"},
            {"from": "сотI:out", "to": "t:nI"},
            {"from": "сотY:out", "to": "t:сколько"}],
    }

    def test_inclusion_exclusion_holds(self):
        """|Y| = |X ∪ Y| − |X| + |X ∩ Y| — иначе задание нерешаемо."""
        import re
        for _ in range(25):
            task = _run(self.GRAPH)
            shown = task.statement[0].render_plain()
            nx, nu, ni = [int(v) for v in re.findall(r"— (\d+)", shown)]
            self.assertEqual(
                int(float(task.answer_spec.accepted_examples()[0])),
                nu - nx + ni, shown)

    def test_the_intersection_is_not_bigger_than_the_parts(self):
        import re
        for _ in range(25):
            shown = _run(self.GRAPH).statement[0].render_plain()
            nx, nu, ni = [int(v) for v in re.findall(r"— (\d+)", shown)]
            self.assertLessEqual(ni, nx, shown)
            self.assertLessEqual(nx, nu, shown)
