"""
Узлы английского языка (категория english).

Слова переносятся типом PortType.WORDS — это dict[str, str] вида
{термин: перевод}. Узлы:
  words_file    — прочитать JSON-файл со словами (любой из поддерживаемых
                  форматов) и выдать WORDS; необязательный параметр inline
                  позволяет переопределить/дополнить словарь из редактора.
  words_trainer — обернуть словарь в интерактивный тренажёр (перевод RU→EN
                  с межсессионной статистикой) и выдать TASK.

Логику чтения/нормализации форматов и саму сессию переиспользуем из
exercises.english.generators — здесь только обёртки под графовый движок.
Импорт ленивый: модуль english тянет PyQt6 (динамические блоки), а движок
графа в остальном headless.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


def _load_words_file(path: str) -> dict[str, str]:
    """Прочитать файл и привести к dict[str, str] (через english.generators)."""
    from pathlib import Path
    from exercises.english.generators import (
        _read_json_lenient, WordsTrainerGenerator,
    )
    p = Path(path)
    if not p.exists():
        raise GraphValidationError(f"Файл со словами не найден: {path!r}")
    data = _read_json_lenient(p)
    return WordsTrainerGenerator._flatten_words(data)


def _load_sentences_file(path: str) -> list[dict]:
    """Прочитать JSON с предложениями-пропусками (список объектов template/answers)."""
    from pathlib import Path
    from exercises.english.generators import _read_json_lenient
    p = Path(path)
    if not p.exists():
        raise GraphValidationError(f"Файл предложений не найден: {path!r}")
    data = _read_json_lenient(p)
    if not isinstance(data, list):
        raise GraphValidationError(
            f"Файл предложений {path!r}: ожидался список объектов "
            f"{{template, answers, translation}}."
        )
    return data


class WordsFileNode(Node):
    """
    Словарь слов из JSON-файла. Источник WORDS.

    Параметр file — путь к JSON (выбирается в инспекторе, там же предпросмотр и
    правка). Поддерживаются форматы vocabulary/units и старые. Параметр inline
    (dict term→translation) при наличии используется вместо файла — так
    отредактированные слова сохраняются прямо в графе.
    """
    type_id = "words_file"
    category = "english"
    display_name = "Слова из файла"
    description = ("Словарь слов из JSON-файла (term→translation). "
                   "Источник. Выход: WORDS.")
    OUTPUTS = [Port("out", PortType.WORDS)]
    PARAMS_SCHEMA = {
        "file": {"type": "file", "default": "",
                 "filter": "JSON (*.json)", "preview": "words"},
        # Встроенный словарь (правки из предпросмотра). Не редактируется как
        # обычное поле — хранится графом; пусто → читаем file.
        "inline": {"type": "hidden", "default": None},
    }

    def validate_params(self) -> None:
        inline = self.params.get("inline")
        file = str(self.params.get("file", "")).strip()
        if not inline and not file:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: укажите файл со словами или встроенный список."
            )

    def compute(self, inputs, ctx: ExecContext):
        inline = self.params.get("inline")
        if isinstance(inline, dict) and inline:
            words = {str(k): str(v) for k, v in inline.items()}
        else:
            words = _load_words_file(str(self.params.get("file", "")).strip())
        if not words:
            raise RetryGeneration(
                f"words_file {self.node_id!r}: словарь пуст."
            )
        return {"out": words}


class WordsTrainerNode(Node):
    """
    Интерактивный тренажёр слов из словаря WORDS → TASK.

    Оборачивает словарь в WordsSession (перевод RU→EN, антиповтор, мягкая
    проверка по расстоянию Левенштейна). Финальный узел графа (как static_task).
    """
    type_id = "words_trainer"
    category = "english"
    display_name = "Тренажёр слов"
    description = ("Интерактивный тренажёр перевода RU→EN из словаря. "
                   "Вход: WORDS. Выход: TASK.")
    INPUTS = [Port("words", PortType.WORDS)]
    OUTPUTS = [Port("out", PortType.TASK)]
    PARAMS_SCHEMA = {
        "tolerant": {"type": "enum", "values": ["no", "yes"], "default": "no",
                     "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from exercises.english.generators import WordsSession
        words = inputs.get("words") or {}
        if not isinstance(words, dict) or not words:
            raise RetryGeneration(
                f"words_trainer {self.node_id!r}: на вход не пришёл непустой словарь."
            )
        tolerant = str(self.params.get("tolerant", "no")) == "yes"
        return {"out": WordsSession(dict(words), tolerant=tolerant)}


class SentencesFileNode(Node):
    """
    Предложения с пропусками из JSON-файла. Источник SENTENCES.

    Формат файла — список объектов {template, answers, translation?}, где в
    template пропуски обозначены '___'. Параметр file выбирается в инспекторе.
    """
    type_id = "sentences_file"
    category = "english"
    display_name = "Предложения из файла"
    description = ("Предложения с пропусками (___) из JSON. "
                   "Источник. Выход: SENTENCES.")
    OUTPUTS = [Port("out", PortType.SENTENCES)]
    PARAMS_SCHEMA = {
        "file": {"type": "file", "default": "", "filter": "JSON (*.json)"},
    }

    def validate_params(self) -> None:
        if not str(self.params.get("file", "")).strip():
            raise GraphValidationError(
                f"Узел {self.node_id!r}: укажите файл с предложениями."
            )

    def compute(self, inputs, ctx: ExecContext):
        items = _load_sentences_file(str(self.params.get("file", "")).strip())
        if not items:
            raise RetryGeneration(f"sentences_file {self.node_id!r}: файл пуст.")
        return {"out": items}


class SentenceFillNode(Node):
    """
    Задание «вставьте пропущенные слова»: выбирает случайное предложение из
    набора SENTENCES и строит интерактивный блок с пропусками.

    Выходы — два BLOCK_LIST (как у static_task): statement (условие с полями
    ввода + перевод) и answer (правильное предложение + список слов). Выбор
    предложения воспроизводим через ctx.rng.
    """
    type_id = "sentence_fill"
    category = "english"
    display_name = "Предложение с пропусками"
    description = ("Случайное предложение с пропусками → блоки условия и ответа. "
                   "Вход: SENTENCES. Выходы: statement, answer (BLOCK_LIST).")
    INPUTS = [Port("in", PortType.SENTENCES)]
    OUTPUTS = [Port("statement", PortType.BLOCK_LIST),
               Port("answer", PortType.BLOCK_LIST)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock
        from core.dynamic_blocks import FillInTheBlankBlock
        items = inputs.get("in") or []
        if not isinstance(items, (list, tuple)) or not items:
            raise RetryGeneration(
                f"sentence_fill {self.node_id!r}: на вход не пришёл непустой список."
            )
        item = ctx.rng.choice(list(items))
        try:
            template = str(item["template"])
            answers = [str(a) for a in item["answers"]]
        except (KeyError, TypeError):
            raise RetryGeneration(
                f"sentence_fill {self.node_id!r}: у предложения нет template/answers."
            )
        translation = str(item.get("translation", "")) if isinstance(item, dict) else ""

        statement = [
            TextBlock("Вставьте пропущенные слова в предложение:"),
            FillInTheBlankBlock(template=template, answers=answers),
        ]
        if translation:
            statement.append(TextBlock(f"Перевод: {translation}"))

        full = template
        for ans in answers:
            full = full.replace(FillInTheBlankBlock.PLACEHOLDER, ans, 1)
        answer = [
            TextBlock("Правильное предложение:"),
            TextBlock(full),
            TextBlock(f"Пропущенные слова: {', '.join(answers)}"),
        ]
        return {"statement": statement, "answer": answer}
