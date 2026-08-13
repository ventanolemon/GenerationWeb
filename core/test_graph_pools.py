"""
Пул значений: таблица, из которой берут случайную строку.

Пятый кусок разбора (docs/architecture/informatics_on_july.md). Английский
читал словарь своим способом, русскому нужны пары «слово с пропуском →
верное слово», информатике — списки расширений и доменов: три формата под
одну нужду, и каждый новый предмет добавлял бы четвёртый.

Общая форма — таблица со столбцами. Словарь это таблица из двух столбцов,
список — из одного, поэтому она покрывает все три случая сразу.

Ради чего затевалось: завести генератор должно быть заполнением таблицы,
а не программированием. Генератор по русскому (при-/пре-) собирается
теперь в ТРИ узла и три провода.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from core.graph.errors import GraphError, GraphValidationError
from core.graph.executor import GraphExecutor
from core.graph.nodes import DEFAULT_REGISTRY
from core.graph.nodes.pools import parse_columns, parse_rows
from core.graph.spec import GraphSpec
from core.interactive import session_from_task


РУССКИЙ = ["Пр_баутка|Прибаутка", "Беспр_кословный|Беспрекословный",
           "Пр_беречь|Приберечь", "Не пр_минуть|Не преминуть",
           "Пр_ватизация|Приватизация", "Непр_станный|Непрестанный",
           "Пр_амбула|Преамбула", "Пр_верженец|Приверженец"]


class ParsingTests(unittest.TestCase):

    def test_columns_default_to_one(self):
        self.assertEqual(parse_columns([]), ["значение"])
        self.assertEqual(parse_columns(["а", "б"]), ["а", "б"])

    def test_column_names_become_port_names(self):
        """Имя столбца становится именем порта, а по именам ходят провода."""
        for bad in (["с пробелом"], ["1цифра"], ["а-б"]):
            with self.subTest(bad=bad):
                with self.assertRaises(GraphValidationError):
                    parse_columns(bad)

    def test_duplicate_column_is_refused(self):
        with self.assertRaises(GraphValidationError):
            parse_columns(["а", "а"])

    def test_short_row_is_padded(self):
        self.assertEqual(parse_rows(["раз"], ["а", "б"]), [["раз", ""]])

    def test_long_row_is_refused(self):
        """
        Лишнее значение почти наверняка означает лишнюю черту в тексте.
        Промолчать — оставить автора со сдвинутыми столбцами.
        """
        with self.assertRaises(GraphValidationError) as caught:
            parse_rows(["а|б|в"], ["один", "два"])
        self.assertIn("разделитель", str(caught.exception))

    def test_blank_rows_are_skipped(self):
        self.assertEqual(parse_rows(["а|б", "", "  ", "в|г"], ["x", "y"]),
                         [["а", "б"], ["в", "г"]])


class PoolSourceTests(unittest.TestCase):

    def _run(self, params, columns=("слово",)):
        graph = {"nodes": [
            {"id": "п", "type": "pool", "params": params},
            {"id": "с", "type": "pool_pick",
             "params": {"columns": list(columns)}},
            {"id": "t", "type": "task", "params": {
                "statement": "#w#", "slots": ["x:text"]}},
        ], "edges": [{"from": "п:out", "to": "с:in"},
                     {"from": f"с:{columns[0]}", "to": "t:w"},
                     {"from": f"с:{columns[0]}", "to": "t:x"}]}
        return GraphExecutor(GraphSpec.parse(graph)).run()

    def test_inline_table(self):
        task = self._run({"columns": ["слово"], "rows": [".bmp", ".txt"]})
        self.assertIn(task.statement[0].render_plain(), (".bmp", ".txt"))

    def test_empty_pool_is_refused_when_saving(self):
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("pool", "п", {"columns": ["a"]})

    def test_file_with_lines(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("а|раз\nб|два\n")
        self.addCleanup(lambda: os.unlink(path))
        task = self._run({"columns": ["к", "з"], "file": path}, ("к", "з"))
        self.assertIn(task.statement[0].render_plain(), ("а", "б"))

    def test_file_with_json_dict(self):
        """
        Словари английского уже лежат объектом, и переделывать их ради
        пула незачем — словарь это таблица из двух столбцов.
        """
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"chip": "микросхема", "silicon": "кремний"}, fh,
                      ensure_ascii=False)
        self.addCleanup(lambda: os.unlink(path))
        task = self._run({"columns": ["слово", "перевод"], "file": path},
                         ("слово", "перевод"))
        self.assertIn(task.statement[0].render_plain(), ("chip", "silicon"))

    def test_missing_file_says_so(self):
        with self.assertRaises((GraphValidationError, GraphError)) as caught:
            self._run({"columns": ["a"], "file": "/нет/такого.txt"})
        self.assertIn("не найден", str(caught.exception))


class PoolPickTests(unittest.TestCase):

    def _pick(self, **params):
        return DEFAULT_REGISTRY.create("pool_pick", "с", params)

    def test_a_port_per_column(self):
        node = self._pick(columns=["вопрос", "ответ"])
        self.assertEqual([p.name for p in node.output_ports()],
                         ["вопрос", "ответ"])

    def test_others_port_appears_only_when_asked(self):
        self.assertNotIn("прочие",
                         [p.name for p in self._pick(columns=["a"]).output_ports()])
        self.assertIn("прочие",
                      [p.name for p in
                       self._pick(columns=["a"], others=3).output_ports()])

    def test_unknown_others_column_is_refused(self):
        with self.assertRaises(GraphValidationError):
            self._pick(columns=["a", "b"], others=2, others_from="нет")

    def test_negative_others_is_refused(self):
        with self.assertRaises(GraphValidationError):
            self._pick(columns=["a"], others=-1)


class RussianGeneratorTests(unittest.TestCase):
    """
    Старая игра по русскому (при-/пре-) целиком: ТРИ узла, три провода.

    В оригинале это было окно на PyQt со списками слов в исходнике,
    подсчётом очков и проверкой в обработчике клавиши. Здесь — таблица.
    """

    GRAPH = {
        "nodes": [
            {"id": "пул", "type": "pool",
             "params": {"columns": ["пропуск", "верно"], "rows": РУССКИЙ}},
            {"id": "стр", "type": "pool_pick",
             "params": {"columns": ["пропуск", "верно"]}},
            {"id": "t", "type": "task", "params": {
                "statement": "Вставьте пропущенную букву:\n#слово#",
                "slots": ["целиком:text:label=Слово"]}},
        ],
        "edges": [{"from": "пул:out", "to": "стр:in"},
                  {"from": "стр:пропуск", "to": "t:слово"},
                  {"from": "стр:верно", "to": "t:целиком"}],
    }

    def test_question_and_answer_are_the_same_row(self):
        pairs = {row.split("|")[0]: row.split("|")[1] for row in РУССКИЙ}
        for _ in range(30):
            task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
            shown = task.statement[0].render_plain().split("\n")[1]
            self.assertEqual(task.answer_spec.accepted_examples()[0],
                             pairs[shown])

    def test_the_task_is_checkable(self):
        task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
        self.assertTrue(task.is_checkable)
        session = session_from_task(task)
        self.assertTrue(
            session.submit(task.answer_spec.accepted_examples()[0]).correct)

    def test_the_letter_variant_is_a_two_option_test(self):
        """
        Как в оригинальной игре: жмут «и» или «е», а не набирают слово.
        """
        graph = {
            "nodes": [
                {"id": "пул", "type": "pool", "params": {
                    "columns": ["слово", "буква"],
                    "rows": ["Пр_баутка|и", "Беспр_кословный|е",
                             "Пр_амбула|е", "Пр_верженец|и"]}},
                {"id": "стр", "type": "pool_pick",
                 "params": {"columns": ["слово", "буква"]}},
                {"id": "t", "type": "task", "params": {
                    "statement": "Какая буква пропущена?\n#w#",
                    "slots": ["буква:text:wrong=и|е:choices=2"]}},
            ],
            "edges": [{"from": "пул:out", "to": "стр:in"},
                      {"from": "стр:слово", "to": "t:w"},
                      {"from": "стр:буква", "to": "t:буква"}],
        }
        for _ in range(10):
            task = GraphExecutor(GraphSpec.parse(graph)).run()
            question = session_from_task(task).questions[0]
            self.assertEqual(question.widget_name(), "choice_one")
            self.assertEqual(sorted(question.options()), ["е", "и"])


class EnglishFromAPoolTests(unittest.TestCase):
    """Тот же пул кормит английский — неверные варианты берутся из него же."""

    GRAPH = {
        "nodes": [
            {"id": "пул", "type": "pool", "params": {
                "columns": ["слово", "перевод"],
                "rows": ["chip|микросхема", "silicon|кремний",
                         "resistor|резистор", "diode|диод"]}},
            {"id": "стр", "type": "pool_pick", "params": {
                "columns": ["слово", "перевод"], "others": 3}},
            {"id": "t", "type": "task", "params": {
                "statement": "Как переводится «#w#»?",
                "slots": ["перевод:text:label=Перевод:choices=4"]}},
        ],
        "edges": [{"from": "пул:out", "to": "стр:in"},
                  {"from": "стр:слово", "to": "t:w"},
                  {"from": "стр:перевод", "to": "t:перевод"},
                  {"from": "стр:прочие", "to": "t:перевод_wrong"}],
    }

    def test_exactly_one_option_is_correct(self):
        for _ in range(20):
            task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
            options = session_from_task(task).questions[0].options()
            correct = [o for o in options if task.answer_spec.check(o).accepted]
            self.assertEqual(len(correct), 1, options)

    def test_others_come_from_the_pool(self):
        translations = {row.split("|")[1] for row in
                        self.GRAPH["nodes"][0]["params"]["rows"]}
        for _ in range(20):
            task = GraphExecutor(GraphSpec.parse(self.GRAPH)).run()
            options = session_from_task(task).questions[0].options()
            self.assertTrue(set(options) <= translations, options)


class TypoBudgetFollowsLengthTests(unittest.TestCase):
    """
    Допуск на опечатку не может быть больше, чем позволяет длина ответа.

    Поймано на генераторе по русскому: ответ — одна буква, а расстояние
    от «е» до «и», «ы» и вообще любой буквы равно единице. Задание
    «вставьте пропущенную букву» засчитывало ЛЮБОЙ ввод — не тест
    сломался, а проверка была неверной.

    Правило: одна правка на каждые четыре символа. Объявленный
    `max_edits` остаётся верхней границей — он ослабляет проверку, но
    отменить её не может.
    """

    def test_one_letter_answer_accepts_only_itself(self):
        from core.answers import TextSpec
        spec = TextSpec(value="е")
        self.assertTrue(spec.check("е").accepted)
        for wrong in ("и", "ы", "щ", "q", "ем"):
            with self.subTest(wrong=wrong):
                self.assertFalse(spec.check(wrong).accepted)

    def test_short_words_too(self):
        from core.answers import TextSpec
        for value, wrong in (("да", "ба"), ("go", "no"), ("кот", "код")):
            with self.subTest(value=value):
                self.assertFalse(TextSpec(value=value).check(wrong).accepted)
                self.assertTrue(TextSpec(value=value).check(value).accepted)

    def test_long_words_still_forgive_a_typo(self):
        """Ради чего допуск и заводился — его отменять нельзя."""
        from core.answers import TextSpec
        self.assertTrue(TextSpec(value="Москва").check("Масква").accepted)
        self.assertTrue(
            TextSpec(value="Приватизация").check("Приватезация").accepted)

    def test_a_different_word_is_still_wrong(self):
        from core.answers import TextSpec
        self.assertFalse(TextSpec(value="Москва").check("Казань").accepted)

    def test_max_edits_zero_still_means_zero(self):
        from core.answers import TextSpec
        spec = TextSpec(value="Приватизация", max_edits=0)
        self.assertFalse(spec.check("Приватезация").accepted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
