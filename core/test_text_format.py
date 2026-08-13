"""
Формат условия: абзацы и оформление.

Проверяется две вещи, и вторая важнее первой: что оформление доезжает до
всех трёх выходов (JSON, .docx, Qt), и что БЕЗ оформления не меняется
ничего — форму обычного блока читают десктоп, фронт и замороженные
контрактные тесты.

Запуск:
    python -m unittest core.test_text_format
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.blocks import TextBlock  # noqa: E402
from core.graph.nodes.assembly import _statement_blocks, parse_style  # noqa: E402


class ParseStyleTests(unittest.TestCase):
    def test_order_does_not_matter(self):
        self.assertEqual(parse_style("крупный жирный"),
                         parse_style("жирный крупный"))

    def test_russian_and_english_are_the_same(self):
        self.assertEqual(parse_style("мелкий курсив"),
                         parse_style("small italic"))

    def test_empty_means_plain(self):
        self.assertEqual(parse_style(""),
                         {"size": "normal", "bold": False, "italic": False})

    def test_unknown_word_is_ignored_not_fatal(self):
        # Оформление — не смысл задания; терять сгенерированное задание
        # из-за опечатки в стиле несоразмерно.
        self.assertEqual(parse_style("жирный подчёркнутый"),
                         {"size": "normal", "bold": True, "italic": False})


class ParagraphSplitTests(unittest.TestCase):
    def test_blank_line_starts_a_new_paragraph(self):
        blocks = _statement_blocks("Первый\n\nВторой", [])
        self.assertEqual([b.text for b in blocks], ["Первый", "Второй"])

    def test_single_newline_stays_inside_one_paragraph(self):
        """
        Перенос внутри абзаца — обычное дело: формула с новой строки,
        перечисление. Разрывать по нему значило бы плодить блоки там, где
        автор просто отформатировал текст.
        """
        blocks = _statement_blocks("Условие\nвторая строка", [])
        self.assertEqual(len(blocks), 1)
        self.assertIn("\n", blocks[0].text)

    def test_styles_apply_positionally(self):
        blocks = _statement_blocks("Заголовок\n\nТекст\n\nСноска",
                                   ["крупный жирный", "", "мелкий курсив"])
        self.assertEqual([(b.size, b.bold, b.italic) for b in blocks],
                         [("large", True, False),
                          ("normal", False, False),
                          ("small", False, True)])

    def test_fewer_styles_than_paragraphs_is_normal(self):
        blocks = _statement_blocks("А\n\nБ\n\nВ", ["жирный"])
        self.assertEqual([b.bold for b in blocks], [True, False, False])

    def test_empty_text_gives_no_blocks(self):
        self.assertEqual(_statement_blocks("   \n\n  ", ["жирный"]), [])


class SerialisationTests(unittest.TestCase):
    def test_plain_block_is_unchanged(self):
        """
        Ключевое: форму обычного блока читают десктоп, фронт и
        контрактные тесты. Появление полей оформления у КАЖДОГО блока
        было бы молчаливой сменой контракта.
        """
        self.assertEqual(TextBlock("текст").to_dict(),
                         {"type": "text", "content": "текст"})

    def test_styled_block_carries_its_style(self):
        self.assertEqual(
            TextBlock("текст", size="large", bold=True).to_dict(),
            {"type": "text", "content": "текст", "size": "large",
             "bold": True, "italic": False})

    def test_unknown_size_falls_back_to_normal(self):
        self.assertEqual(TextBlock("т", size="огромный").size, "normal")


class DocxTests(unittest.TestCase):
    def test_style_reaches_the_document(self):
        from docx import Document

        doc = Document()
        TextBlock("жирно", size="large", bold=True, italic=True).render_docx(doc)
        run = doc.paragraphs[-1].runs[0]
        self.assertEqual(run.text, "жирно")
        self.assertTrue(run.bold)
        self.assertTrue(run.italic)
        self.assertIsNotNone(run.font.size)

    def test_plain_block_sets_no_size(self):
        from docx import Document

        doc = Document()
        TextBlock("обычно").render_docx(doc)
        run = doc.paragraphs[-1].runs[0]
        self.assertFalse(run.bold)
        self.assertIsNone(run.font.size,
                          "обычному абзацу навязан размер в пунктах")


if __name__ == "__main__":
    unittest.main()
