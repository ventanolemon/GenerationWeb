"""
Дополнительные блоки контента: динамические и интерактивные.

Эти блоки расширяют систему стандарта без её изменения. Каждый из них —
это обычный Block с четырьмя методами рендера. Используются модулями,
которым нужны специфические виды контента (например, английский тренажёр
с пропусками в предложении).

Все Qt-зависимости импортируются лениво (внутри render_qt / FlowLayout-
конструктора). Без этого ядро не получится импортировать в headless-окружении
вроде FastAPI-микросервиса.
"""

from __future__ import annotations
import difflib
from typing import Callable, List, TYPE_CHECKING

from core.content import Block

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


# ============================================================
# FillInTheBlankBlock
# ============================================================

class FillInTheBlankBlock(Block):
    """
    Динамический блок: предложение с пропусками, в которые пользователь
    вписывает слова. Каждый пропуск в Qt — отдельное QLineEdit с подсветкой
    по мере набора. В вебе — фронт сам строит инпуты по списку answers.

    Параметры:
      template — строка с маркерами '___' (три подчёркивания) на местах пропусков
      answers  — список правильных ответов в порядке появления маркеров
      on_change(values, correctness) — опциональный коллбек только для Qt-режима
      case_sensitive — учитывать ли регистр при проверке (по умолчанию нет)

    В режиме plain/docx экспорта каждый пропуск замещается своим ответом
    (с подчёркиванием в plain), чтобы документ был осмысленным.
    """

    PLACEHOLDER = "___"

    def __init__(
        self,
        template: str,
        answers: List[str],
        on_change: Callable[[List[str], List[bool]], None] | None = None,
        case_sensitive: bool = False,
    ):
        self.template = template
        self.answers = list(answers)
        self.on_change = on_change
        self.case_sensitive = case_sensitive

        n_blanks = template.count(self.PLACEHOLDER)
        if n_blanks != len(answers):
            raise ValueError(
                f"FillInTheBlankBlock: маркеров {n_blanks}, ответов {len(answers)}"
            )

    # --- Qt ---

    def render_qt(self, parent: "QWidget") -> "QWidget":
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget, QLabel, QLineEdit

        wrap = QWidget(parent)
        flow = _FlowLayout(wrap)

        line_edits: list = []
        parts = self.template.split(self.PLACEHOLDER)
        for i, segment in enumerate(parts):
            if segment:
                lbl = QLabel(segment, wrap)
                lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                flow.addWidget(lbl)
            if i < len(self.answers):
                edit = QLineEdit(wrap)
                edit.setMaximumWidth(120)
                edit.setPlaceholderText("...")
                line_edits.append(edit)
                flow.addWidget(edit)

        def emit_change():
            if self.on_change is None:
                return
            values = [e.text() for e in line_edits]
            correctness = [self._check(v, a)
                           for v, a in zip(values, self.answers)]
            self.on_change(values, correctness)

        def on_text_changed(idx: int):
            text = line_edits[idx].text()
            ok = self._check(text, self.answers[idx]) if text else None
            if ok is None:
                line_edits[idx].setStyleSheet("")
            elif ok:
                line_edits[idx].setStyleSheet(
                    "background: #d8f0d8; color: #1a4d1a;"
                )
            else:
                line_edits[idx].setStyleSheet(
                    "background: #f4d8d8; color: #5a1a1a;"
                )
            emit_change()

        for i, edit in enumerate(line_edits):
            edit.textChanged.connect(lambda _, idx=i: on_text_changed(idx))

        return wrap

    def _check(self, value: str, expected: str) -> bool:
        if self.case_sensitive:
            return value.strip() == expected.strip()
        return value.strip().lower() == expected.strip().lower()

    # --- Plain / Docx ---

    def render_plain(self) -> str:
        text = self.template
        for ans in self.answers:
            text = text.replace(self.PLACEHOLDER, f"_{ans}_", 1)
        return text

    def render_docx(self, doc) -> None:
        p = doc.add_paragraph()
        parts = self.template.split(self.PLACEHOLDER)
        for i, segment in enumerate(parts):
            if segment:
                p.add_run(segment)
            if i < len(self.answers):
                run = p.add_run(self.answers[i])
                run.italic = True

    # --- Web ---

    def to_dict(self) -> dict:
        return {
            "type": "fill_in_blank",
            "template": self.template,
            "answers": self.answers,
            "case_sensitive": self.case_sensitive,
            "placeholder": self.PLACEHOLDER,
        }


# ============================================================
# Lazy FlowLayout — нужен только для Qt-рендера FillInTheBlankBlock
# ============================================================

class _FlowLayout:
    """
    Прокси, который ленится. Реальный QLayout создаётся только при
    обращении — это позволяет импортировать модуль без PyQt6. Все
    методы делегируются настоящему _FlowLayoutImpl.
    """

    def __new__(cls, parent=None, margin=0, spacing=6):
        from PyQt6.QtWidgets import QLayout, QSizePolicy
        from PyQt6.QtCore import QRect, QSize, QPoint, Qt

        class _FlowLayoutImpl(QLayout):
            """Простой flow-layout: располагает виджеты слева направо с переносом."""

            def __init__(self, parent=None, margin=0, spacing=6):
                super().__init__(parent)
                if parent is not None:
                    self.setContentsMargins(margin, margin, margin, margin)
                self.setSpacing(spacing)
                self._items = []

            def addItem(self, item):
                self._items.append(item)

            def count(self):
                return len(self._items)

            def itemAt(self, index):
                return self._items[index] if 0 <= index < len(self._items) else None

            def takeAt(self, index):
                if 0 <= index < len(self._items):
                    return self._items.pop(index)
                return None

            def expandingDirections(self):
                return Qt.Orientation(0)

            def hasHeightForWidth(self):
                return True

            def heightForWidth(self, width: int) -> int:
                return self._do_layout(QRect(0, 0, width, 0), test_only=True)

            def setGeometry(self, rect):
                super().setGeometry(rect)
                self._do_layout(rect, test_only=False)

            def sizeHint(self):
                return self.minimumSize()

            def minimumSize(self):
                size = QSize()
                for item in self._items:
                    size = size.expandedTo(item.minimumSize())
                m = self.contentsMargins()
                size += QSize(m.left() + m.right(), m.top() + m.bottom())
                return size

            def _do_layout(self, rect, test_only: bool) -> int:
                x = rect.x()
                y = rect.y()
                line_height = 0
                spacing = self.spacing()
                for item in self._items:
                    wid = item.sizeHint().width()
                    hgt = item.sizeHint().height()
                    if x + wid > rect.right() and line_height > 0:
                        x = rect.x()
                        y += line_height + spacing
                        line_height = 0
                    if not test_only:
                        item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
                    x += wid + spacing
                    line_height = max(line_height, hgt)
                return y + line_height - rect.y()

        return _FlowLayoutImpl(parent, margin, spacing)


# ============================================================
# WordCorrectionBlock
# ============================================================
#
# Используется тренажёром английского при ответе пользователя.
# Показывает три строки:
#   1) Перевод (русский) — что было задано.
#   2) Ответ пользователя с подсветкой неправильных букв (через diff).
#   3) Правильное английское слово.
#
# В Qt-режиме рендерится одним QLabel с rich HTML.
# В plain/docx — обычное текстовое представление с пометками.
# В web — to_dict() отдаёт структурированный diff, чтобы фронт сам
# стилизовал ошибки (без сырого HTML — это безопаснее и предсказуемее).


class WordCorrectionBlock(Block):
    """
    Показ результата ответа в тренажёре слов с подсветкой ошибок.

    Параметры:
      translation     — задание (русский перевод)
      user_answer     — что ввёл пользователь
      expected        — правильное английское слово
      correct         — True/False общая оценка
      tolerant_accept — ответ принят мягким режимом (Левенштейн), но
                        не совпадает посимвольно с expected.
    """

    def __init__(
        self,
        translation: str,
        user_answer: str,
        expected: str,
        correct: bool,
        tolerant_accept: bool = False,
    ):
        self.translation = translation
        self.user_answer = user_answer
        self.expected = expected
        self.correct = correct
        self.tolerant_accept = tolerant_accept

    # --- Qt ---

    def render_qt(self, parent: "QWidget") -> "QWidget":
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

        wrap = QWidget(parent)
        v = QVBoxLayout(wrap)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)

        if self.correct and self.tolerant_accept:
            marker, color = "≈", "#a07a1a"
        elif self.correct:
            marker, color = "✓", "#2a7a2a"
        else:
            marker, color = "✗", "#aa2a2a"
        head = QLabel(
            f"<span style='color:{color}; font-weight:bold;'>{marker}</span> "
            f"<span style='color:#555;'>{_html_escape(self.translation)}</span>",
            wrap,
        )
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        v.addWidget(head)

        if self.correct and not self.tolerant_accept:
            user_html = (
                f"<span style='font-family: Consolas, monospace; color:#2a7a2a;'>"
                f"{_html_escape(self.user_answer)}</span>"
            )
        else:
            user_html = _diff_highlight_html(self.user_answer, self.expected)

        user_lbl = QLabel(f"&nbsp;&nbsp;ввод: {user_html}", wrap)
        user_lbl.setTextFormat(Qt.TextFormat.RichText)
        user_lbl.setWordWrap(True)
        v.addWidget(user_lbl)

        if not self.correct or self.tolerant_accept:
            right = QLabel(
                f"&nbsp;&nbsp;ответ: "
                f"<span style='font-family: Consolas, monospace; color:#2a5a8a;'>"
                f"{_html_escape(self.expected)}</span>",
                wrap,
            )
            right.setTextFormat(Qt.TextFormat.RichText)
            right.setWordWrap(True)
            v.addWidget(right)

        return wrap

    # --- Plain / Docx ---

    def render_plain(self) -> str:
        if self.correct and self.tolerant_accept:
            marker = "≈"
        elif self.correct:
            marker = "✓"
        else:
            marker = "✗"
        lines = [
            f"{marker} {self.translation}",
            f"   ввод: {self.user_answer}",
        ]
        if not self.correct or self.tolerant_accept:
            lines.append(f"   ответ: {self.expected}")
        return "\n".join(lines)

    def render_docx(self, doc) -> None:
        if self.correct and self.tolerant_accept:
            marker = "≈"
        elif self.correct:
            marker = "✓"
        else:
            marker = "✗"
        p = doc.add_paragraph()
        p.add_run(f"{marker} {self.translation}").bold = True
        p2 = doc.add_paragraph()
        p2.add_run(f"  ввод: {self.user_answer}")
        if not self.correct or self.tolerant_accept:
            p3 = doc.add_paragraph()
            run = p3.add_run(f"  ответ: {self.expected}")
            run.italic = True

    # --- Web ---

    def to_dict(self) -> dict:
        """
        Структурированное представление для веба. diff отдаётся как
        список операций — фронт сам решит, как стилизовать каждую.

        Каждая операция: {"op": "equal"|"replace"|"delete"|"insert",
                          "user": "<подстрока из ответа пользователя>",
                          "expected": "<подстрока из правильного ответа>"}

        Это безопаснее и предсказуемее, чем отдавать HTML — фронт не
        обязан использовать dangerouslySetInnerHTML, может рендерить
        diff как нативные React-элементы.
        """
        return {
            "type": "word_correction",
            "translation": self.translation,
            "user_answer": self.user_answer,
            "expected": self.expected,
            "correct": self.correct,
            "tolerant_accept": self.tolerant_accept,
            "diff": _diff_ops(self.user_answer, self.expected),
        }


# ============================================================
# Вспомогательные функции для diff
# ============================================================

def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace(" ", "&nbsp;")
    )


def _diff_ops(user: str, expected: str) -> list[dict]:
    """
    Сравнить введённое и ожидаемое посимвольно через SequenceMatcher.
    Возвращает список операций для веб-сериализации.
    """
    matcher = difflib.SequenceMatcher(a=user, b=expected, autojunk=False)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        out.append({
            "op": op,
            "user": user[i1:i2],
            "expected": expected[j1:j2],
        })
    return out


def _diff_highlight_html(user: str, expected: str) -> str:
    """
    Сравнить введённое и ожидаемое посимвольно через SequenceMatcher.
    Возвращает HTML, где:
      * совпавшие буквы — обычные (зелёные)
      * лишние/неверные буквы пользователя — красные с подчёркиванием
      * пропущенные буквы (из expected) — серые в скобках

    Для Qt-режима десктопа.
    """
    matcher = difflib.SequenceMatcher(a=user, b=expected, autojunk=False)
    out: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            out.append(
                f"<span style='color:#2a7a2a;'>{_html_escape(user[i1:i2])}</span>"
            )
        elif op == "replace":
            out.append(
                f"<span style='color:#aa2a2a; text-decoration: underline;'>"
                f"{_html_escape(user[i1:i2])}</span>"
                f"<span style='color:#999;'>"
                f"[{_html_escape(expected[j1:j2])}]</span>"
            )
        elif op == "delete":
            out.append(
                f"<span style='color:#aa2a2a; text-decoration: underline;'>"
                f"{_html_escape(user[i1:i2])}</span>"
            )
        elif op == "insert":
            out.append(
                f"<span style='color:#999;'>[{_html_escape(expected[j1:j2])}]</span>"
            )
    return (
        "<span style='font-family: Consolas, monospace;'>"
        + "".join(out)
        + "</span>"
    )
