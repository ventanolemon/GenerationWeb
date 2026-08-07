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
                f"{self.node_ref()}: укажите файл со словами или встроенный список."
            )

    def compute(self, inputs, ctx: ExecContext):
        inline = self.params.get("inline")
        if isinstance(inline, dict) and inline:
            words = {str(k): str(v) for k, v in inline.items()}
        else:
            words = _load_words_file(str(self.params.get("file", "")).strip())
        if not words:
            raise RetryGeneration(
                f"{self.node_ref()}: словарь пуст."
            )
        return {"out": words}


class WordsPickNode(Node):
    """
    Взять из словаря одно слово: вопрос, ответ и чужие переводы.

    Появился, когда понадобилось собрать в Июле СТАТИЧЕСКОЕ задание по
    английскому, и выяснилось, что тип WORDS тупиковый: его умел принять
    только `words_trainer`, который сразу отдаёт готовую сессию. Достать
    из словаря одну пару было нечем — то есть словарь годился ровно для
    одного сценария, заложенного заранее.

    Три выхода вместо одного «пары» — потому что дальше они идут в разные
    места: вопрос в текст условия, ответ в слот проверки, чужие переводы
    в неверные варианты теста. Собирать их в структуру, чтобы тут же
    разобрать, значило бы завести тип ради одного узла.

    `direction` меняет вопрос и ответ местами: «переведите на русский» и
    «переведите на английский» — это одно задание с двух сторон, а не два
    разных, и разводить их по узлам было бы удвоением.
    """
    type_id = "words_pick"
    category = "english"
    display_name = "Слово из словаря"
    description = ("Случайное слово: вопрос, ответ и чужие переводы для "
                   "теста. Вход: WORDS. Выход: STRING, STRING, LIST.")
    INPUTS = [Port("words", PortType.WORDS)]
    OUTPUTS = [Port("question", PortType.STRING),
               Port("answer", PortType.STRING),
               Port("others", PortType.LIST)]
    PARAMS_SCHEMA = {
        "direction": {"type": "enum",
                      "values": ["term_to_translation", "translation_to_term"],
                      "default": "term_to_translation"},
        "others": {"type": "int", "default": 3, "optional": True},
    }

    def _others_count(self) -> int:
        try:
            count = int(self.params.get("others", 3))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: 'others' должно быть целым ≥ 0.")
        if count < 0:
            raise GraphValidationError(
                f"{self.node_ref()}: 'others' не может быть отрицательным.")
        return count

    def validate_params(self) -> None:
        self._others_count()

    def summary(self) -> str:
        return ("англ→рус" if self.params.get(
            "direction", "term_to_translation") == "term_to_translation"
            else "рус→англ")

    def compute(self, inputs, ctx: ExecContext):
        words = inputs.get("words") or {}
        if not words:
            raise RetryGeneration(f"{self.node_ref()}: словарь пуст.")

        pairs = list(words.items())
        term, translation = ctx.rng.choice(pairs)
        forward = self.params.get(
            "direction", "term_to_translation") == "term_to_translation"
        question, answer = (term, translation) if forward else (translation, term)

        # Чужие переводы С ТОЙ ЖЕ стороны, что и ответ: иначе среди
        # русских вариантов оказалось бы английское слово, и верный ответ
        # был бы виден не глядя.
        pool = [(t if forward else k) for k, t in pairs
                if (t if forward else k) != answer]
        count = min(self._others_count(), len(pool))
        others = ctx.rng.sample(pool, count) if count else []

        return {"question": question, "answer": answer, "others": others}


class WordsTrainerNode(Node):
    """
    Интерактивный тренажёр слов из словаря WORDS → TASK.

    Оборачивает словарь в WordsSession (антиповтор, межсессионная
    статистика по каждому слову, мягкая проверка по расстоянию
    Левенштейна). Финальный узел графа (как static_task).

    Терминальность здесь законная, в отличие от `sentence_fill`: сессия
    делает то, чего из частей не собрать — помнит, какие слова этому
    ученику давались тяжело, между запусками. Ради одного задания
    берите `words_pick` и `task`.

    Направление перевода раньше было зашито внутрь (RU→EN), и автор
    графа до него не дотягивался — то же самое, из-за чего словарь
    оказался типом на один сценарий. Теперь оно параметр, и называется
    так же, как у `words_pick`.
    """
    type_id = "words_trainer"
    category = "english"
    display_name = "Тренажёр слов"
    description = ("Интерактивный тренажёр перевода из словаря, с "
                   "межсессионной статистикой. Вход: WORDS. Выход: TASK.")
    INPUTS = [Port("words", PortType.WORDS)]
    OUTPUTS = [Port("out", PortType.TASK)]
    PARAMS_SCHEMA = {
        "tolerant": {"type": "enum", "values": ["no", "yes"], "default": "no",
                     "optional": True},
        "direction": {"type": "enum",
                      "values": ["translation_to_term", "term_to_translation"],
                      "default": "translation_to_term", "optional": True},
    }

    def summary(self) -> str:
        return ("рус→англ" if self.params.get(
            "direction", "translation_to_term") == "translation_to_term"
            else "англ→рус")

    def compute(self, inputs, ctx: ExecContext):
        from exercises.english.generators import WordsSession
        words = inputs.get("words") or {}
        if not isinstance(words, dict) or not words:
            raise RetryGeneration(
                f"{self.node_ref()}: на вход не пришёл непустой словарь."
            )
        tolerant = str(self.params.get("tolerant", "no")) == "yes"
        # Обратное направление — тот же словарь, перевёрнутый. Заводить
        # ради него второй класс сессии незачем: она спрашивает ключ и
        # ждёт значение, а что считать ключом — дело вызывающего.
        if str(self.params.get("direction", "translation_to_term")) \
                == "term_to_translation":
            words = {v: k for k, v in words.items()}
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
                f"{self.node_ref()}: укажите файл с предложениями."
            )

    def compute(self, inputs, ctx: ExecContext):
        items = _load_sentences_file(str(self.params.get("file", "")).strip())
        if not items:
            raise RetryGeneration(f"{self.node_ref()}: файл пуст.")
        return {"out": items}


class SentencePickNode(Node):
    """
    Взять из набора одно предложение: шаблон, пропущенные слова, перевод.

    Тот же разбор, что и у `words_pick`, и по той же причине. Готовый
    `sentence_fill` отдаёт наружу только СОБРАННЫЕ БЛОКИ, а значения —
    шаблон, ответы, перевод — остаются внутри. Выглядит это как узел
    посреди графа, то есть как нечто составное, но составить с ним
    ничего нельзя: блок не проверишь, не превратишь в тест и не
    подставишь в чужой текст.

    Цена этого замера: задание, собранное через `sentence_fill`, имеет
    `is_checkable == False` — то есть не проверяется вовсе, не идёт в
    задание с оценкой и не попадает в статистику. А правильные ответы
    при этом уезжают в браузер прямо в условии, потому что сверять их
    больше негде.

    Отсюда четыре выхода. `answers` идёт списком в слот `много`, и это
    единственный способ проверять пропуски: сколько их — знает
    предложение, а не автор графа.
    """
    type_id = "sentence_pick"
    category = "english"
    display_name = "Предложение из набора"
    description = ("Случайное предложение: шаблон с пропусками, ответы, "
                   "перевод, готовый текст. Вход: SENTENCES. "
                   "Выходы: STRING, LIST, STRING, STRING.")
    INPUTS = [Port("in", PortType.SENTENCES)]
    OUTPUTS = [Port("template", PortType.STRING),
               Port("answers", PortType.LIST),
               Port("translation", PortType.STRING),
               Port("filled", PortType.STRING)]
    PARAMS_SCHEMA = {
        # Чем рисовать пропуск в условии. '___' — то, что стоит в файлах;
        # но в печатном задании длинное подчёркивание читается лучше, а
        # менять из-за этого сами файлы неправильно.
        "blank": {"type": "str", "default": "___", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.dynamic_blocks import FillInTheBlankBlock
        items = inputs.get("in") or []
        if not isinstance(items, (list, tuple)) or not items:
            raise RetryGeneration(
                f"{self.node_ref()}: на вход не пришёл непустой список.")

        item = ctx.rng.choice(list(items))
        try:
            template = str(item["template"])
            answers = [str(a) for a in item["answers"]]
        except (KeyError, TypeError):
            raise RetryGeneration(
                f"{self.node_ref()}: у предложения нет template/answers.")
        if template.count(FillInTheBlankBlock.PLACEHOLDER) != len(answers):
            raise RetryGeneration(
                f"{self.node_ref()}: пропусков в шаблоне не столько, "
                f"сколько ответов.")

        filled = template
        for answer in answers:
            filled = filled.replace(FillInTheBlankBlock.PLACEHOLDER, answer, 1)

        blank = str(self.params.get("blank", "___")) or "___"
        shown = template.replace(FillInTheBlankBlock.PLACEHOLDER, blank)

        return {"template": shown, "answers": answers, "filled": filled,
                "translation": str(item.get("translation", ""))
                if isinstance(item, dict) else ""}


class SentenceFillNode(Node):
    """
    Задание «вставьте пропущенные слова»: выбирает случайное предложение из
    набора SENTENCES и строит интерактивный блок с пропусками.

    Проверки у этого узла нет и быть не может: наружу уходят готовые
    блоки, а `FillInTheBlankBlock` сверяет ввод сам, у себя — в Qt по
    подсветке поля, в браузере по списку `answers`, который для этого
    едет в условии. Ни попытка, ни результат никуда не записываются.

    Узел остаётся ради заданий, где нужен именно ввод ПО МЕСТУ, внутри
    предложения. Если задание должно проверяться и оцениваться, берите
    `sentence_pick` и слот `много` у `task`: там сверка на сервере, а
    ответы клиенту не показываются.

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
                f"{self.node_ref()}: на вход не пришёл непустой список."
            )
        item = ctx.rng.choice(list(items))
        try:
            template = str(item["template"])
            answers = [str(a) for a in item["answers"]]
        except (KeyError, TypeError):
            raise RetryGeneration(
                f"{self.node_ref()}: у предложения нет template/answers."
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
