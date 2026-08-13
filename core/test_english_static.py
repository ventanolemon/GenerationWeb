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


# ======================================================================
#  Та же болезнь у соседей
# ======================================================================

SENTENCES = [{"template": "She ___ to school and ___ home at five.",
              "answers": ["goes", "comes"],
              "translation": "Она ходит в школу и приходит домой в пять."},
             {"template": "I ___ tea.", "answers": ["like"],
              "translation": "Я люблю чай."}]


def _sentences_file() -> str:
    import json
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(SENTENCES, fh, ensure_ascii=False)
    return path


class SentenceFillIsGoneTests(unittest.TestCase):
    """
    Узла «предложение с пропусками» больше нет.

    Он собирал условие и ответ блоками и отдавал их наружу. Стоял
    посреди графа и потому выглядел составным, но составить с ним было
    нечего: блок не проверишь, не превратишь в тест и не подставишь в
    чужой текст. Замерялось это так: задание получалось с
    `is_checkable == False` — то есть не проверялось вовсе и не попадало
    в статистику, — а правильные ответы уезжали в браузер прямо в
    условии, потому что сверять их было больше негде.

    Ввод ПО МЕСТУ, единственное, ради чего узел стоило бы держать, — это
    не отдельный узел, а способ показа: `sentence_pick` + слот `много` +
    виджет `slot_inline`.
    """

    def test_the_node_is_not_registered(self):
        from core.graph.nodes import DEFAULT_REGISTRY
        self.assertNotIn("sentence_fill", DEFAULT_REGISTRY.type_ids())

    def test_nothing_converts_sentences_to_blocks_any_more(self):
        """
        Автоподстановка конвертера вела в тот же тупик, только молча:
        соединив предложения с блоками, редактор вставлял бы узел,
        делающий задание непроверяемым.
        """
        from core.graph.conversions import find_converter
        from core.graph.port_types import PortType
        self.assertIsNone(
            find_converter(PortType.SENTENCES, PortType.BLOCK_LIST))


class SentencePickTests(unittest.TestCase):
    """Лечение то же, что у словаря: узел отдаёт ЧАСТИ, а не блоки."""

    def setUp(self):
        import os
        self.path = _sentences_file()
        self.addCleanup(lambda: os.unlink(self.path))

    def _task(self, slot="пропуск:text:много:typos=0"):
        return GraphExecutor(GraphSpec.parse({
            "nodes": [
                {"id": "s", "type": "sentences_file",
                 "params": {"file": self.path}},
                {"id": "p", "type": "sentence_pick", "params": {}},
                {"id": "t", "type": "task", "params": {
                    "statement": "Вставьте пропущенные слова:\n"
                                 "#предложение#\nПеревод: #перевод#",
                    "slots": [slot],
                    "layout": "template",
                    "answer_template": "#целиком#"}},
            ],
            "edges": [{"from": "s:out", "to": "p:in"},
                      {"from": "p:template", "to": "t:предложение"},
                      {"from": "p:answers", "to": "t:пропуск"},
                      {"from": "p:translation", "to": "t:перевод"},
                      {"from": "p:filled", "to": "t:целиком"}],
        })).run()

    def test_the_task_is_checkable(self):
        self.assertTrue(self._task().is_checkable)

    def test_the_statement_keeps_no_answers(self):
        """Главное отличие от блока: сверка на сервере, ответов у клиента нет."""
        for _ in range(10):
            task = self._task()
            shown = " ".join(b.render_plain() for b in task.statement)
            answers = [a for s in SENTENCES for a in s["answers"]]
            leaked = [a for a in answers if a in shown]
            self.assertEqual(leaked, [], f"ответ виден в условии: {shown!r}")

    def test_fields_follow_the_sentence(self):
        """
        У одного предложения один пропуск, у другого два, а объявление
        слотов одно на все выпуски. Ради этого `много` и заведено.
        """
        seen = set()
        for _ in range(30):
            task = self._task()
            seen.add(len(task.answer_spec.input_fields()))
        self.assertEqual(seen, {1, 2})

    def test_every_blank_is_checked(self):
        for _ in range(20):
            task = self._task()
            session = session_from_task(task)
            right = {f.name: a for f, a in
                     zip(task.answer_spec.input_fields(),
                         self._expected(task))}
            self.assertTrue(session.submit_values(right).correct)

    def test_a_wrong_blank_is_refused(self):
        for _ in range(20):
            task = self._task()
            values = {f.name: "нет" for f in task.answer_spec.input_fields()}
            self.assertFalse(session_from_task(task).submit_values(values).correct)

    def _expected(self, task):
        shown = " ".join(b.render_plain() for b in task.answer)
        for item in SENTENCES:
            filled = item["template"]
            for a in item["answers"]:
                filled = filled.replace("___", a, 1)
            if filled in shown:
                return item["answers"]
        self.fail(f"ответ не совпал ни с одним предложением: {shown!r}")

    def test_the_answer_shows_the_whole_sentence(self):
        task = self._task()
        shown = " ".join(b.render_plain() for b in task.answer)
        self.assertNotIn("___", shown)

    def test_the_blank_marker_is_a_parameter(self):
        """
        В печатном задании длинное подчёркивание читается лучше, но
        менять из-за этого сами файлы неправильно.
        """
        graph = {
            "nodes": [
                {"id": "s", "type": "sentences_file",
                 "params": {"file": self.path}},
                {"id": "p", "type": "sentence_pick",
                 "params": {"blank": "………"}},
                {"id": "t", "type": "task", "params": {
                    "statement": "#предложение#",
                    "slots": ["пропуск:text:много"]}},
            ],
            "edges": [{"from": "s:out", "to": "p:in"},
                      {"from": "p:template", "to": "t:предложение"},
                      {"from": "p:answers", "to": "t:пропуск"}],
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertIn("………", task.statement[0].render_plain())


class WordsTrainerReachesItsDecisionsTests(unittest.TestCase):
    """
    Терминальность тренажёра законная: сессия помнит, какие слова этому
    ученику давались тяжело, между запусками, — из частей такого не
    собрать. Болезнь была мягче:
    направление перевода лежало внутри, и автор графа до него не
    дотягивался.
    """

    def _session(self, **params):
        return GraphExecutor(GraphSpec.parse({
            "nodes": [{"id": "d", "type": "words_file",
                       "params": {"inline": dict(WORDS)}},
                      {"id": "w", "type": "words_trainer", "params": params}],
            "edges": [{"from": "d:out", "to": "w:words"}],
        })).run()

    def test_default_direction_is_unchanged(self):
        asked = self._session().initial_prompt()[1].render_plain()
        self.assertIn(asked, WORDS.values())

    def test_direction_can_be_reversed(self):
        session = self._session(direction="term_to_translation")
        asked = session.initial_prompt()[1].render_plain()
        self.assertIn(asked, WORDS)
        self.assertTrue(session.submit(WORDS[asked]).correct)

    def test_the_reversed_trainer_still_checks(self):
        session = self._session(direction="term_to_translation")
        self.assertFalse(session.submit("ерунда").correct)


class InlineInputIsADisplayModeTests(unittest.TestCase):
    """
    Ввод ПО МЕСТУ — режим показа, а не вид задания.

    То же решение, что и с тестом (§2): проверка та же, ответ тот же,
    отличается только рисование. Поэтому здесь нет ни узла, ни вида
    спецификации — только имя виджета в `meta`, а рисует его платформа.
    """

    def setUp(self):
        import os
        self.path = _sentences_file()
        self.addCleanup(lambda: os.unlink(self.path))

    def _task(self, widget="slot_inline", slots=None):
        return GraphExecutor(GraphSpec.parse({
            "nodes": [
                {"id": "s", "type": "sentences_file",
                 "params": {"file": self.path}},
                {"id": "p", "type": "sentence_pick", "params": {}},
                {"id": "t", "type": "task", "params": {
                    "statement": "Вставьте пропущенные слова:\n#предложение#",
                    "slots": slots or ["пропуск:text:много:typos=0"],
                    "widget": widget}},
            ],
            "edges": [{"from": "s:out", "to": "p:in"},
                      {"from": "p:template", "to": "t:предложение"},
                      {"from": "p:answers", "to": "t:пропуск"}],
        })).run()

    def test_the_widget_reaches_the_session(self):
        task = self._task()
        self.assertEqual(task.meta["widget"], "slot_inline")
        self.assertEqual(
            session_from_task(task).questions[0].widget_name(), "slot_inline")

    def test_without_the_parameter_nothing_changes(self):
        task = self._task(widget="")
        self.assertNotIn("widget", task.meta)
        self.assertEqual(
            session_from_task(task).questions[0].widget_name(), "slot_fields")

    def test_blanks_match_the_fields(self):
        """
        Клиент ставит поля на места `___`, и счёт обязан сойтись —
        иначе поле окажется не в том пропуске и предложение сменит
        смысл.
        """
        for _ in range(20):
            task = self._task()
            text = " ".join(b.render_plain() for b in task.statement)
            self.assertEqual(text.count("___"),
                             len(task.answer_spec.input_fields()))

    def test_checking_is_the_same_as_without_it(self):
        """Режим показа не трогает проверку — в этом весь смысл слова."""
        for _ in range(10):
            inline = self._task()
            values = {f.name: "нет" for f in inline.answer_spec.input_fields()}
            self.assertFalse(
                session_from_task(inline).submit_values(values).correct)

    def test_an_unknown_widget_is_refused_when_saving(self):
        from core.graph.errors import GraphValidationError
        with self.assertRaises(GraphValidationError) as caught:
            self._task(widget="нет_такого")
        self.assertIn("не зарегистрирован", str(caught.exception))

    def test_an_incompatible_widget_is_refused_when_saving(self):
        """
        Ловить это надо при сохранении графа: подменив виджет молча, мы
        показали бы студенту не тот способ ввода, а причину спрятали.
        """
        from core.graph.errors import GraphValidationError
        with self.assertRaises(GraphValidationError) as caught:
            self._task(widget="choice_one")
        self.assertIn("не обслуживает", str(caught.exception))

    def test_a_formula_slot_can_ask_for_the_palette(self):
        """Тот же параметр обслуживает этап 7 — палитру формул."""
        task = GraphExecutor(GraphSpec.parse({
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": 4}},
                {"id": "t", "type": "task", "params": {
                    "statement": "?", "slots": ["y:expr"],
                    "widget": "formula_input"}},
            ],
            "edges": [{"from": "c:out", "to": "t:y"}],
        })).run()
        self.assertEqual(
            session_from_task(task).questions[0].widget_name(), "formula_input")
