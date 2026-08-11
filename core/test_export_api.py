"""
Экспорт: варианты и четыре размещения ответов.

Проверяется ПОРЯДОК на бумаге, а не «функция не упала»: смысл настройки в
том, где именно окажется ответ, и увидеть это можно только по
последовательности заголовков.

Документ подделан списком событий — python-docx здесь не нужен, а тест от
этого становится читаемым: видно ровно то, что увидит преподаватель.

Запуск:
    python -m unittest core.test_export_api
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import export_api  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.task import StaticTask  # noqa: E402


class FakeDoc:
    """Документ как список событий: ('h', уровень, текст) и ('b', текст)."""

    def __init__(self):
        self.events: list[tuple] = []

    def add_heading(self, text, level=1):
        self.events.append(("h", level, text))

    def add_page_break(self):
        self.events.append(("break",))

    def add_paragraph(self, text="", style=None):
        # TextBlock создаёт пустой абзац и добавляет run — так задаётся
        # начертание. Подделка повторяет эту форму, иначе тест проверял бы
        # вызов, которого в бою уже нет.
        para = FakeParagraph(self)
        if text:
            para.add_run(text)
        return para


    def headings(self):
        return [e[2] for e in self.events if e[0] == "h"]

    def texts(self):
        return [e[1] for e in self.events if e[0] == "b"]


class FakeParagraph:
    def __init__(self, doc):
        self._doc = doc

    def add_run(self, text=""):
        self._doc.events.append(("b", text))
        return FakeRun()


class FakeRun:
    """Начертание записывается в run — подделка его принимает и хранит."""

    def __init__(self):
        self.bold = False
        self.italic = False
        self.font = type("F", (), {"size": None})()


def _task(n: int) -> StaticTask:
    return StaticTask(statement=[TextBlock(f"условие {n}")],
                      answer=[TextBlock(f"ответ {n}")])


def _build(variants, answers, title="Работа"):
    doc = FakeDoc()
    export_api.build_document(doc, variants, title=title, answers=answers)
    return doc


class UnderTaskTests(unittest.TestCase):
    """Прежнее поведение: ответ сразу под заданием."""

    def test_answer_follows_its_task(self):
        doc = _build([[_task(1), _task(2)]], "under")
        self.assertEqual(doc.headings(),
                         ["Работа", "Задание 1", "Ответ 1",
                          "Задание 2", "Ответ 2"])

    def test_single_variant_gets_no_variant_heading(self):
        # Заголовок «Вариант 1» сообщал бы о структуре, которой нет.
        self.assertNotIn("Вариант 1", _build([[_task(1)]], "under").headings())


class HiddenTests(unittest.TestCase):
    def test_answers_are_absent_entirely(self):
        doc = _build([[_task(1), _task(2)]], "hidden")
        self.assertEqual(doc.headings(),
                         ["Работа", "Задание 1", "Задание 2"])
        self.assertEqual(doc.texts(), ["условие 1", "условие 2"])
        self.assertNotIn("ответ 1", doc.texts(),
                         "ответ утёк в лист, который раздают студентам")


class VariantEndTests(unittest.TestCase):
    def test_answers_go_after_all_tasks_of_the_variant(self):
        doc = _build([[_task(1), _task(2)]], "variant_end")
        self.assertEqual(doc.headings(),
                         ["Работа", "Задание 1", "Задание 2",
                          "Ответы", "Задание 1", "Задание 2"])
        # Условия идут раньше любых ответов — ключ отрывается.
        texts = doc.texts()
        self.assertLess(texts.index("условие 2"), texts.index("ответ 1"))

    def test_each_variant_keeps_its_own_key(self):
        doc = _build([[_task(1)], [_task(2)]], "variant_end")
        self.assertEqual(
            doc.headings(),
            ["Работа", "Вариант 1", "Задание 1", "Ответы", "Задание 1",
             "Вариант 2", "Задание 1", "Ответы", "Задание 1"])


class FileEndTests(unittest.TestCase):
    def test_all_answers_are_collected_at_the_very_end(self):
        doc = _build([[_task(1), _task(2)]], "file_end")
        self.assertEqual(doc.headings(),
                         ["Работа", "Задание 1", "Задание 2",
                          "Ответы", "Задание 1", "Задание 2"])

    def test_captions_name_the_variant_when_there_are_several(self):
        # Иначе в общей пачке ключей не понять, к какому варианту ответ.
        doc = _build([[_task(1)], [_task(2)]], "file_end")
        self.assertEqual(
            doc.headings(),
            ["Работа", "Вариант 1", "Задание 1", "Вариант 2", "Задание 1",
             "Ответы", "Вариант 1, задание 1", "Вариант 2, задание 1"])

    def test_no_answer_appears_before_the_last_statement(self):
        doc = _build([[_task(1)], [_task(2)]], "file_end")
        texts = doc.texts()
        self.assertLess(texts.index("условие 2"), texts.index("ответ 1"))


class VariantStructureTests(unittest.TestCase):
    def test_variants_are_separated_by_a_page_break(self):
        doc = _build([[_task(1)], [_task(2)]], "hidden")
        kinds = [e[0] for e in doc.events]
        self.assertIn("break", kinds)

    def test_tasks_of_one_variant_are_not_split_across_pages(self):
        """
        Разрыв на каждое задание осмыслен, когда вариант один: лист на
        задание. Внутри варианта задания идут подряд — иначе вариант из
        пяти заданий превращается в пять листов.
        """
        doc = _build([[_task(1), _task(2)], [_task(3), _task(4)]], "hidden")
        # Ровно один разрыв — между вариантами.
        self.assertEqual(sum(1 for e in doc.events if e[0] == "break"), 1)


class ValidationTests(unittest.TestCase):
    def test_unknown_placement_is_refused(self):
        with self.assertRaises(export_api.ExportError):
            _build([[_task(1)]], "куда-нибудь")

    def test_empty_export_is_refused(self):
        with self.assertRaises(export_api.ExportError):
            _build([], "under")
        with self.assertRaises(export_api.ExportError):
            _build([[]], "under")


class CompatibilityTests(unittest.TestCase):
    """Старый контракт `with_answers` шлют три экрана фронта и десктоп."""

    def test_true_means_under_the_task(self):
        self.assertEqual(export_api.normalise_placement(None, True), "under")

    def test_false_means_hidden(self):
        self.assertEqual(export_api.normalise_placement(None, False), "hidden")

    def test_explicit_placement_wins(self):
        self.assertEqual(
            export_api.normalise_placement("file_end", True), "file_end")

    def test_missing_both_defaults_to_the_old_behaviour(self):
        self.assertEqual(export_api.normalise_placement(None, None), "under")

    def test_garbage_placement_is_refused(self):
        with self.assertRaises(export_api.ExportError):
            export_api.normalise_placement("подальше", True)


if __name__ == "__main__":
    unittest.main()
