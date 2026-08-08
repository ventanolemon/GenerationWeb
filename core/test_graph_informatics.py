"""
Узлы информатики: системы счисления.

Первый кусок разбора восьми старых генераторов
(docs/architecture/informatics_on_july.md). Разбор показал, что половина
из них собирается на языке как есть, а упирается всё в несколько
узкопредметных вещей. Перевод систем счисления — первая из них: узла не
было ни одного, и задание «найдите наибольшее» упиралось в него сразу.

Проверяется здесь то, что легко сделать почти правильно:

  * **направление — параметр, а не второй узел.** «Перевести в двоичную»
    и «прочитать двоичную» — одно действие с двух сторон;
  * **тип выхода следует направлению.** `1011` в двоичной и `1011` в
    десятичной — разные величины, поэтому запись уезжает строкой; в
    обратную сторону, наоборот, числом;
  * **несовместимый провод ловится при СБОРКЕ графа**, а не при выдаче
    задания студенту — для этого порты и объявляются по направлению;
  * **чужой ввод не роняет генерацию**: основание вне 2..36, мусор
    вместо записи числа.
"""

from __future__ import annotations

import unittest

from core.graph.errors import GraphValidationError
from core.graph.executor import GraphExecutor
from core.graph.nodes import DEFAULT_REGISTRY
from core.graph.nodes.informatics import from_base, to_base
from core.graph.port_types import PortType
from core.graph.spec import GraphSpec


class ConversionTests(unittest.TestCase):

    def test_known_values(self):
        self.assertEqual(to_base(28, 2), "11100")
        self.assertEqual(to_base(46, 8), "56")
        self.assertEqual(to_base(92, 16), "5c")
        self.assertEqual(to_base(255, 16, upper=True), "FF")

    def test_zero_and_negative(self):
        self.assertEqual(to_base(0, 2), "0")
        self.assertEqual(to_base(-5, 2), "-101")

    def test_round_trip(self):
        for value in (0, 1, 7, 28, 255, 4095, 100000):
            for base in (2, 8, 16, 36):
                with self.subTest(value=value, base=base):
                    self.assertEqual(from_base(to_base(value, base), base),
                                     value)

    def test_base_out_of_range(self):
        for base in (1, 0, 37, -2):
            with self.subTest(base=base):
                with self.assertRaises(ValueError):
                    to_base(10, base)

    def test_garbage_is_refused(self):
        for text in ("", "   ", "хрю", "2", "1z"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    from_base(text, 2)


class NodePortsFollowTheDirectionTests(unittest.TestCase):
    """
    Порты объявляются по направлению, чтобы несовместимый провод ловился
    при сборке графа. Принимать ANY было бы проще и хуже: ошибка дожила
    бы до выдачи задания.
    """

    def _node(self, **params):
        return DEFAULT_REGISTRY.create("number_base", "n", params)

    def test_to_base_takes_a_number_and_gives_text(self):
        node = self._node(base=2, direction="to_base")
        self.assertEqual(node.input_ports()[0].type, PortType.NUMBER)
        self.assertEqual(node.output_ports()[0].type, PortType.STRING)

    def test_to_decimal_takes_text_and_gives_a_number(self):
        node = self._node(base=2, direction="to_decimal")
        self.assertEqual(node.input_ports()[0].type, PortType.STRING)
        self.assertEqual(node.output_ports()[0].type, PortType.NUMBER)

    def test_a_bad_base_is_refused_when_saving(self):
        for base in (1, 40, "два"):
            with self.subTest(base=base):
                with self.assertRaises(GraphValidationError):
                    DEFAULT_REGISTRY.create("number_base", "n", {"base": base})

    def test_summary_shows_the_direction(self):
        self.assertEqual(self._node(base=16).summary(), "→ 16")
        self.assertEqual(
            self._node(base=16, direction="to_decimal").summary(), "16 → 10")


class BaseNameTests(unittest.TestCase):

    def _run(self, base):
        graph = {"nodes": [
            {"id": "c", "type": "constant_number", "params": {"value": base}},
            {"id": "n", "type": "base_name", "params": {}},
            {"id": "t", "type": "task", "params": {
                "statement": "В #имя# системе.", "slots": ["x:number"]}},
        ], "edges": [{"from": "c:out", "to": "n:in"},
                     {"from": "n:out", "to": "t:имя"},
                     {"from": "c:out", "to": "t:x"}]}
        return GraphExecutor(GraphSpec.parse(graph)).run()

    def test_known_bases_are_named(self):
        self.assertIn("двоичной", self._run(2).statement[0].render_plain())
        self.assertIn("шестнадцатеричной",
                      self._run(16).statement[0].render_plain())

    def test_unknown_base_falls_back_to_digits(self):
        self.assertIn("7-ичной", self._run(7).statement[0].render_plain())


class Generator10Tests(unittest.TestCase):
    """
    Старое задание целиком: «найдите наибольшее из трёх, записанных в
    2/8/16-ричной». Десять узлов и четырнадцать проводов.

    Тест сторожит не текст, а то, ради чего задание собиралось: ответ
    сходится с записями, и задание ПРОВЕРЯЕМО — старый генератор
    печатал ответ в чат и на этом заканчивался.
    """

    GRAPH = {
        "nodes": [
            {"id": "rng", "type": "number_range",
             "params": {"start": 10, "stop": 99, "step": 1}},
            {"id": "p", "type": "random_choice",
             "params": {"elem_type": "number", "count": 3,
                        "allow_duplicates": False}},
            {"id": "a", "type": "list_get",
             "params": {"elem_type": "number", "index": 0}},
            {"id": "b", "type": "list_get",
             "params": {"elem_type": "number", "index": 1}},
            {"id": "c", "type": "list_get",
             "params": {"elem_type": "number", "index": 2}},
            {"id": "b2", "type": "number_base", "params": {"base": 2}},
            {"id": "b8", "type": "number_base", "params": {"base": 8}},
            {"id": "b16", "type": "number_base", "params": {"base": 16}},
            # `constants: off` обязателен: иначе `c` — скорость света, а не
            # переменная, и провод в неё не втыкается. Ловушка настоящая,
            # поймана при сборке этого самого задания.
            {"id": "мх", "type": "formula",
             "params": {"expr": "max(x, y, z)", "constants": "off"}},
            {"id": "t", "type": "task", "params": {
                "statement": "Наибольшее из: #д2#, #д8#, #д16#",
                "slots": ["ответ:number"]}},
        ],
        "edges": [
            {"from": "rng:out", "to": "p:list"},
            {"from": "p:out", "to": "a:list"},
            {"from": "p:out", "to": "b:list"},
            {"from": "p:out", "to": "c:list"},
            {"from": "a:out", "to": "b2:in"},
            {"from": "b:out", "to": "b8:in"},
            {"from": "c:out", "to": "b16:in"},
            {"from": "b2:out", "to": "t:д2"},
            {"from": "b8:out", "to": "t:д8"},
            {"from": "b16:out", "to": "t:д16"},
            {"from": "a:out", "to": "мх:x"},
            {"from": "b:out", "to": "мх:y"},
            {"from": "c:out", "to": "мх:z"},
            {"from": "мх:out", "to": "t:ответ"},
        ],
    }

    def _run(self):
        return GraphExecutor(GraphSpec.parse(self.GRAPH)).run()

    def test_the_answer_is_the_maximum_of_the_three(self):
        import re
        for _ in range(25):
            task = self._run()
            shown = task.statement[0].render_plain()
            found = re.findall(r"[0-9a-f]+", shown.split(":", 1)[1])
            self.assertEqual(len(found), 3, shown)
            values = [from_base(found[0], 2), from_base(found[1], 8),
                      from_base(found[2], 16)]
            answer = int(float(task.answer_spec.accepted_examples()[0]))
            self.assertEqual(answer, max(values), f"{shown} → {answer}")

    def test_the_task_is_checkable(self):
        """
        Главное отличие от старого генератора: тот печатал ответ в чат.
        """
        from core.interactive import session_from_task
        task = self._run()
        self.assertTrue(task.is_checkable)
        session = session_from_task(task)
        self.assertTrue(
            session.submit(task.answer_spec.accepted_examples()[0]).correct)

    def test_the_three_numbers_are_distinct(self):
        """
        Иначе «наибольшее» бывает не одно, и задание становится
        двусмысленным.
        """
        import re
        for _ in range(25):
            shown = self._run().statement[0].render_plain()
            found = re.findall(r"[0-9a-f]+", shown.split(":", 1)[1])
            values = [from_base(found[0], 2), from_base(found[1], 8),
                      from_base(found[2], 16)]
            self.assertEqual(len(set(values)), 3, shown)


class MaxIsAllowedInFormulasTests(unittest.TestCase):
    """
    Белый список функций собирался под физику и матанализ. Максимум из
    нескольких чисел там не значился, а в информатике это первое, обо что
    спотыкаешься.
    """

    def test_max_and_min_parse(self):
        from exercises.fisic.expression import evaluate_formula
        self.assertEqual(evaluate_formula("max(x, y, z)",
                                          {"x": 1, "y": 9, "z": 5}), 9)
        self.assertEqual(evaluate_formula("min(x, y)", {"x": 1, "y": 9}), 1)

    def test_old_functions_still_work(self):
        from exercises.fisic.expression import evaluate_formula
        self.assertAlmostEqual(evaluate_formula("sqrt(x)", {"x": 9}), 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PrefixCodeTests(unittest.TestCase):
    """
    Условие Фано: ни одно кодовое слово не является началом другого.

    Строится дерево, а не перебор с отбраковкой. Старый генератор брал
    все слова длины 1..4, вычёркивал несовместимые с уже выбранными и
    подбирал длину эвристикой со счётчиком «потерь» — работало, но на
    случай несхождения там стоял сторож `if stroky > 4: stroky = 1`. У
    отбраковочных схем всегда есть вход, на котором они буксуют; у
    построения дерева такого входа нет по устройству.
    """

    def _codes(self, count, seed=0, **kwargs):
        import random
        from core.graph.nodes.informatics import prefix_code
        return prefix_code(count, random.Random(seed), **kwargs)

    @staticmethod
    def _prefix_free(codes) -> bool:
        return all(not (a.startswith(b) or b.startswith(a))
                   for i, a in enumerate(codes) for b in codes[i + 1:])

    def test_the_fano_condition_holds_always(self):
        """
        Инвариант проверяется прогоном, а не доверием к построению:
        тысяча наборов разного размера.
        """
        import random
        rng = random.Random(11)
        for _ in range(1000):
            count = rng.randint(2, 16)
            with self.subTest(count=count):
                codes = self._codes(count, seed=rng.randint(0, 10 ** 6),
                                    max_length=5)
                self.assertEqual(len(codes), count)
                self.assertEqual(len(set(codes)), count, codes)
                self.assertTrue(self._prefix_free(codes), codes)

    def test_lengths_vary(self):
        """
        Ради этого задание и существует: равномерные коды делают его
        тривиальным. Разные длины выходят сами — какой лист выпал, тот и
        удлинился.
        """
        seen = set()
        for seed in range(20):
            seen.update(len(c) for c in self._codes(7, seed, max_length=4))
        self.assertGreater(len(seen), 1, seen)

    def test_capacity_is_respected(self):
        self.assertEqual(len(self._codes(32, max_length=5)), 32)
        with self.assertRaises(ValueError):
            self._codes(33, max_length=5)

    def test_max_length_is_honoured(self):
        for code in self._codes(8, max_length=4):
            self.assertLessEqual(len(code), 4, code)

    def test_a_larger_alphabet_works(self):
        codes = self._codes(9, alphabet="012", max_length=3)
        self.assertTrue(self._prefix_free(codes), codes)
        self.assertTrue(set("".join(codes)) <= set("012"))

    def test_impossible_setup_is_refused_when_saving(self):
        for params in ({"count": 0}, {"count": 40, "max_length": 5},
                       {"count": 4, "alphabet": "0"},
                       {"count": 4, "max_length": 0}):
            with self.subTest(params=params):
                with self.assertRaises(GraphValidationError):
                    DEFAULT_REGISTRY.create("prefix_code", "p", params)


class Generator2Tests(unittest.TestCase):
    """
    Старое задание «расшифруйте слово» целиком: девять узлов.

    Главный инвариант не в том, что коды префиксные, а в том, что
    зашифрованная строка расшифровывается ОДНОЗНАЧНО — иначе у задания
    несколько верных ответов, и студент прав в любом случае.
    """

    GRAPH = {
        "nodes": [
            {"id": "коды", "type": "prefix_code",
             "params": {"count": 6, "max_length": 4}},
            {"id": "кл", "type": "letter_keys", "params": {}},
            {"id": "диап", "type": "number_range",
             "params": {"start": 0, "stop": 5, "step": 1}},
            {"id": "инд", "type": "random_choice", "params": {
                "elem_type": "number", "count": 4, "allow_duplicates": True}},
            {"id": "м", "type": "map", "params": {
                "imports": ["коды:list", "ключи:list"],
                "outputs": ["код:string:list", "ключ:string:list"],
                "body": {"nodes": [
                    {"id": "i", "type": "map_item", "params": {"type": "number"}},
                    {"id": "c_", "type": "input_var",
                     "params": {"name": "коды", "type": "list"}},
                    {"id": "k_", "type": "input_var",
                     "params": {"name": "ключи", "type": "list"}},
                    {"id": "c", "type": "list_get",
                     "params": {"elem_type": "string"}},
                    {"id": "k", "type": "list_get",
                     "params": {"elem_type": "string"}},
                    {"id": "oc", "type": "output_var",
                     "params": {"name": "код", "type": "string"}},
                    {"id": "ok", "type": "output_var",
                     "params": {"name": "ключ", "type": "string"}},
                    {"id": "tb", "type": "to_block", "params": {}}],
                    "edges": [
                        {"from": "i:out", "to": "c:index"},
                        {"from": "c_:out", "to": "c:list"},
                        {"from": "i:out", "to": "k:index"},
                        {"from": "k_:out", "to": "k:list"},
                        {"from": "c:out", "to": "oc:value"},
                        {"from": "k:out", "to": "ok:value"},
                        {"from": "c:out", "to": "tb:in"}], "meta": {}}}},
            {"id": "шифр", "type": "list_join", "params": {"sep": ""}},
            {"id": "отв", "type": "list_join", "params": {"sep": ""}},
            {"id": "табл", "type": "list_join", "params": {"sep": "\n"}},
            {"id": "t", "type": "task", "params": {
                "statement": "Расшифруйте слово #шифр#, если:\n#табл#",
                "slots": ["слово:text"]}},
        ],
        "edges": [
            {"from": "коды:out", "to": "кл:in"},
            {"from": "диап:out", "to": "инд:list"},
            {"from": "инд:out", "to": "м:items"},
            {"from": "коды:out", "to": "м:коды"},
            {"from": "кл:keys", "to": "м:ключи"},
            {"from": "м:код", "to": "шифр:in"},
            {"from": "м:ключ", "to": "отв:in"},
            {"from": "кл:labelled", "to": "табл:in"},
            {"from": "шифр:out", "to": "t:шифр"},
            {"from": "табл:out", "to": "t:табл"},
            {"from": "отв:out", "to": "t:слово"},
        ],
    }

    def _parts(self, task):
        """Шифровка и таблица «ключ → код» из текста условия."""
        lines = task.statement[0].render_plain().split("\n")
        encoded = lines[0].split("слово ")[1].split(",")[0]
        table = {}
        for line in lines[1:]:
            key, code = line.split(") ", 1)
            table[key] = code
        return encoded, table

    @staticmethod
    def _decode_all(encoded, table):
        """Все возможные расшифровки — их должно быть ровно одна."""
        results = []

        def walk(rest, acc):
            if not rest:
                results.append("".join(acc))
                return
            for key, code in table.items():
                if rest.startswith(code):
                    walk(rest[len(code):], acc + [key])
        walk(encoded, [])
        return results

    def test_decoding_is_unique(self):
        for _ in range(30):
            task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
            encoded, table = self._parts(task)
            answers = self._decode_all(encoded, table)
            self.assertEqual(len(answers), 1,
                             f"{encoded} → {answers} при {table}")

    def test_the_answer_is_that_decoding(self):
        for _ in range(30):
            task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
            encoded, table = self._parts(task)
            self.assertEqual(task.answer_spec.accepted_examples()[0],
                             self._decode_all(encoded, table)[0])

    def test_the_table_is_prefix_free(self):
        for _ in range(20):
            _, table = self._parts(
                GraphExecutor(GraphSpec.parse(self.GRAPH)).run())
            codes = list(table.values())
            self.assertTrue(PrefixCodeTests._prefix_free(codes), codes)

    def test_the_task_is_checkable(self):
        from core.interactive import session_from_task
        task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
        self.assertTrue(task.is_checkable)
        session = session_from_task(task)
        self.assertTrue(
            session.submit(task.answer_spec.accepted_examples()[0]).correct)
