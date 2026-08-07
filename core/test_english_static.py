"""
Статическое задание по английскому целиком на языке Июль.

Задание собиралось не ради самого задания: тесты здесь — протокол
проверки того, насколько язык годится для заданий такого рода, и каждый
класс отвечает на вопрос, найденный этой сборкой.

Что она нашла:

  * **тип WORDS был тупиковым.** Словарь умел принять один узел —
    `words_trainer`, — и тот сразу отдавал готовую сессию. Достать из
    словаря одну пару было нечем, то есть словарь годился ровно для
    одного заранее заложенного сценария. Отсюда `words_pick`;
  * **неверные варианты приходят из данных, а не из текста задания.**
    Для «переведите слово» дистракторы — другие переводы из того же
    словаря, и написать их в объявлении слота нельзя: они меняются
    вместе с выбранным словом. Отсюда провод `<слот>_wrong`;
  * **тест жил только на экране.** `choices=4` давал выбор в браузере и
    открытый вопрос в .docx — одно задание в двух разных смыслах;
  * **намерение не равно возможности.** Автор пишет `choices=4` на
    строковом слоте и забывает неверные варианты; переключатель, в
    котором нечего переключать, — это уже не «мягкая деградация».
"""

from __future__ import annotations

import unittest

from core.answers import TextSpec
from core.blocks import TextBlock
from core.graph.executor import GraphExecutor
from core.graph.spec import GraphSpec
from core.interactive import Question, option_blocks, session_from_task


WORDS = {"vacuum tube": "электронная лампа",
         "semiconductor": "полупроводник",
         "silicon": "кремний",
         "chip": "микросхема"}


def _graph(*, direction="term_to_translation", choices=4, wire_wrong=True,
           others=3) -> dict:
    slot = "перевод:text:label=Перевод"
    if choices:
        slot += f":choices={choices}"
    edges = [{"from": "d:out", "to": "p:words"},
             {"from": "p:question", "to": "t:слово"},
             {"from": "p:answer", "to": "t:перевод"}]
    # Без теста порта `_wrong` нет вовсе, и провод в него — ошибка графа,
    # а не молчаливо неиспользуемое значение.
    if wire_wrong and choices:
        edges.append({"from": "p:others", "to": "t:перевод_wrong"})
    return {
        "nodes": [
            {"id": "d", "type": "words_file", "params": {"inline": dict(WORDS)}},
            {"id": "p", "type": "words_pick",
             "params": {"direction": direction, "others": others}},
            {"id": "t", "type": "task", "params": {
                "statement": "Как переводится «#слово#»?", "slots": [slot]}},
        ],
        "edges": edges,
    }


def _run(**kwargs):
    return GraphExecutor(GraphSpec.parse(_graph(**kwargs))).run()


# ======================================================================
#  Достать слово из словаря
# ======================================================================

class WordsPickTests(unittest.TestCase):

    def _pick(self, direction="term_to_translation", others=3):
        graph = {
            "nodes": [
                {"id": "d", "type": "words_file",
                 "params": {"inline": dict(WORDS)}},
                {"id": "p", "type": "words_pick",
                 "params": {"direction": direction, "others": others}},
                {"id": "t", "type": "task", "params": {
                    "statement": "#вопрос#", "slots": ["ответ:text"]}},
            ],
            "edges": [{"from": "d:out", "to": "p:words"},
                      {"from": "p:question", "to": "t:вопрос"},
                      {"from": "p:answer", "to": "t:ответ"},
                      {"from": "p:others", "to": "t:прочие"}],
        }
        # Прочие переводы забирать некуда, кроме как в шаблон — здесь
        # интересны сами значения, а не их место в задании.
        graph["edges"] = graph["edges"][:-1]
        node = GraphExecutor(GraphSpec.parse(graph)).run()
        return node

    def test_question_and_answer_are_a_real_pair(self):
        for _ in range(20):
            task = self._pick()
            question = task.statement[0].render_plain()
            self.assertEqual(WORDS[question],
                             task.answer_spec.accepted_examples()[0])

    def test_direction_swaps_the_sides(self):
        back = {v: k for k, v in WORDS.items()}
        for _ in range(20):
            task = self._pick(direction="translation_to_term")
            question = task.statement[0].render_plain()
            self.assertEqual(back[question],
                             task.answer_spec.accepted_examples()[0])

    def test_others_come_from_the_answer_side(self):
        """
        Русский ответ среди английских вариантов виден не глядя — это не
        тест, а подарок. Дистракторы обязаны быть с той же стороны.
        """
        for _ in range(20):
            task = _run()
            options = session_from_task(task).questions[0].options()
            self.assertTrue(set(options) <= set(WORDS.values()),
                            f"чужая сторона среди вариантов: {options}")

    def test_the_answer_is_never_among_the_others(self):
        for _ in range(20):
            task = _run()
            options = session_from_task(task).questions[0].options()
            correct = [o for o in options if task.answer_spec.check(o).accepted]
            self.assertEqual(len(correct), 1, f"верных не один: {options}")

    def test_a_short_dictionary_gives_fewer_options(self):
        """
        Просить четыре варианта из словаря на две пары нечестно, и
        падать тут не за что: тест из трёх вариантов лучше выдуманного
        четвёртого.
        """
        graph = _graph()
        graph["nodes"][0]["params"]["inline"] = {"chip": "микросхема",
                                                 "silicon": "кремний"}
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual(len(session_from_task(task).questions[0].options()), 2)

    def test_negative_count_is_refused(self):
        from core.graph.errors import GraphValidationError
        with self.assertRaises(GraphValidationError):
            _run(others=-1)


# ======================================================================
#  Неверные варианты по проводу
# ======================================================================

class WiredWrongOptionsTests(unittest.TestCase):
    """
    Литералов `wrong=` здесь мало: неверные варианты меняются вместе с
    выбранным словом, а объявление слота одно на все выпуски задания.
    """

    def test_the_port_appears_only_for_a_text_test(self):
        from core.graph.nodes import DEFAULT_REGISTRY

        def ports(slots):
            node = DEFAULT_REGISTRY.create(
                "task", "t", {"statement": "?", "slots": slots})
            return [p.name for p in node.input_ports()]

        self.assertIn("x_wrong", ports(["x:text:choices=4"]))
        # Без теста неверные варианты некуда девать.
        self.assertNotIn("x_wrong", ports(["x:text"]))
        # Число и выражение порождают дистракторы сами, из типа.
        self.assertNotIn("x_wrong", ports(["x:number:choices=4"]))
        self.assertNotIn("x_wrong", ports(["x:expr:choices=4"]))

    def test_the_wire_feeds_the_options(self):
        task = _run()
        options = session_from_task(task).questions[0].options()
        self.assertEqual(len(options), 4)

    def test_without_the_wire_there_is_no_test(self):
        """
        Намерение автора не выполнилось — и вопрос честно становится
        полем ввода, а не пустым переключателем.
        """
        question = session_from_task(_run(wire_wrong=False)).questions[0]
        self.assertEqual(question.options(), [])
        self.assertEqual(question.widget_name(), "text_input")

    def test_the_wire_overrides_the_literals(self):
        graph = _graph()
        graph["nodes"][2]["params"]["slots"] = [
            "перевод:text:label=Перевод:wrong=ерунда|чепуха:choices=4"]
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        options = session_from_task(task).questions[0].options()
        self.assertNotIn("ерунда", options)
        self.assertTrue(set(options) <= set(WORDS.values()))


# ======================================================================
#  Печатная форма теста
# ======================================================================

class PrintedOptionsTests(unittest.TestCase):
    """
    Варианты кладутся в условие, потому что условие читают все — экспорт
    в .docx, предпросмотр, десктоп. Сессия единственная, кто рисует
    варианты сам, и она же их оттуда убирает.
    """

    def test_options_are_printed_in_the_statement(self):
        task = _run()
        printed = [b.render_plain() for b in task.statement]
        self.assertIn("Варианты ответа:", printed)
        for option in session_from_task(task).questions[0].options():
            self.assertTrue(any(line.endswith(option) for line in printed),
                            f"вариант {option!r} не напечатан")

    def test_printed_order_matches_the_widget(self):
        """
        Разойтись эти два списка не могут: источник один. Если бы
        порядок был случайным, «второй сверху» на бумаге и на экране
        означали бы разное.
        """
        task = _run()
        widget = session_from_task(task).questions[0].options()
        printed = [b.render_plain().split(") ", 1)[1]
                   for b in task.statement
                   if b.render_plain()[:1].isdigit()]
        self.assertEqual(printed, widget)

    def test_the_session_does_not_show_them_twice(self):
        task = _run()
        statement = session_from_task(task).questions[0].statement
        self.assertEqual(len(statement), 1)
        self.assertNotIn("Варианты ответа:",
                         [b.render_plain() for b in statement])

    def test_a_plain_task_keeps_its_statement(self):
        task = _run(choices=0)
        self.assertEqual(len(task.statement), 1)
        self.assertEqual(
            len(session_from_task(task).questions[0].statement), 1)

    def test_nothing_is_printed_when_no_test_can_be_built(self):
        task = _run(wire_wrong=False)
        self.assertEqual(len(task.statement), 1)

    def test_a_lookalike_tail_survives(self):
        """
        Убирается ровно то, что было положено: сравнение идёт по
        содержимому, а не по «последние N блоков».
        """
        spec = TextSpec(value="Москва", wrong_options=("Тверь", "Казань"))
        statement = [TextBlock("?"), TextBlock("Варианты ответа:")]
        question = Question(statement=list(statement), spec=spec,
                            options_count=4)
        self.assertEqual(len(question.statement), 2)

    def test_option_blocks_are_empty_without_a_fair_test(self):
        self.assertEqual(option_blocks(TextSpec(value="Москва"), 4), [])


# ======================================================================
#  Ответ
# ======================================================================

class AnsweringTests(unittest.TestCase):

    def test_the_right_option_is_accepted(self):
        task = _run()
        session = session_from_task(task)
        correct = next(o for o in session.questions[0].options()
                       if task.answer_spec.check(o).accepted)
        self.assertTrue(session.submit(correct).correct)

    def test_a_wrong_option_is_refused(self):
        task = _run()
        session = session_from_task(task)
        wrong = next(o for o in session.questions[0].options()
                     if not task.answer_spec.check(o).accepted)
        self.assertFalse(session.submit(wrong).correct)

    def test_the_displayed_answer_is_the_translation(self):
        task = _run()
        shown = " ".join(b.render_plain() for b in task.answer)
        self.assertIn(task.answer_spec.accepted_examples()[0], shown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
