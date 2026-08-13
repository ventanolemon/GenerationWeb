"""
Строки и перечисления — узлы, общие для всех предметов.

Появились при разборе старых генераторов по информатике
(docs/architecture/informatics_on_july.md), но к информатике отношения не
имеют: случайное слово нужно и заданиям на вес текста, и на URL, а
буквенная нумерация «а) б) в)» — и английскому с его вариантами ответа, и
русскому. Поэтому лежат в общих категориях, а не в предметном модуле.

Своих типов портов не заводят: слово это STRING, набор — LIST.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


LATIN = "abcdefghijklmnopqrstuvwxyz"

#: Буквы для нумерации вариантов. Без «ё», «й», «ъ», «ы», «ь» — их не
#: используют для перечислений, а «з» и «о» рядом с цифрами читаются
#: плохо, но их оставляем: выкидывать больше значит быстрее упереться в
#: конец алфавита.
RUSSIAN_KEYS = "абвгдежиклмнпрстуфхцчшщэюя"


class RandomWordNode(Node):
    """
    Слово из случайных букв — источник.

    Собрать его существующими узлами можно: алфавит списком, `map` по
    длине, `list_join`. Пять узлов на то, что в задании звучит как
    «случайное слово из 3–6 букв», и в графе эти пять читаются как шум.

    `unique_letters` — буквы в слове не повторяются. Нужно там, где
    слово потом ищут глазами среди других: повторы делают строки
    похожими, а задание — раздражающим.

    Количество параметром, и от него зависит ТИП выхода: одно слово это
    строка, несколько — список. Отдавать список из одного элемента и
    заставлять автора его разбирать значило бы усложнить частый случай
    ради редкого.
    """
    type_id = "random_word"
    category = "source"
    display_name = "Случайное слово"
    description = ("Слово (или несколько) из случайных букв алфавита. "
                   "Источник. Выход: STRING или LIST.")
    PARAMS_SCHEMA = {
        "alphabet": {"type": "string", "default": LATIN},
        "min_length": {"type": "int", "default": 3},
        "max_length": {"type": "int", "default": 6},
        "count": {"type": "int", "default": 1, "optional": True},
        "unique_letters": {"type": "enum", "values": ["no", "yes"],
                           "default": "no", "optional": True},
        "distinct_lengths": {"type": "enum", "values": ["no", "yes"],
                             "default": "no", "optional": True},
    }

    def _int(self, key: str, default: int) -> int:
        try:
            return int(self.params.get(key, default))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: {key} должно быть целым.")

    def _alphabet(self) -> str:
        text = str(self.params.get("alphabet", LATIN) or "")
        # Дубли схлопываем, сохраняя порядок: повторённая буква иначе
        # выпадала бы чаще прочих, и автор об этом не догадается.
        seen: list[str] = []
        for ch in text:
            if ch not in seen:
                seen.append(ch)
        return "".join(seen)

    def _count(self) -> int:
        return max(1, self._int("count", 1))

    def _lengths(self) -> tuple[int, int]:
        lo, hi = self._int("min_length", 3), self._int("max_length", 6)
        if lo < 1:
            raise GraphValidationError(
                f"{self.node_ref()}: длина слова не может быть меньше единицы.")
        if hi < lo:
            raise GraphValidationError(
                f"{self.node_ref()}: max_length меньше min_length.")
        return lo, hi

    def validate_params(self) -> None:
        lo, hi = self._lengths()
        alphabet = self._alphabet()
        if not alphabet:
            raise GraphValidationError(f"{self.node_ref()}: пустой алфавит.")
        if str(self.params.get("unique_letters", "no")) == "yes" \
                and hi > len(alphabet):
            raise GraphValidationError(
                f"{self.node_ref()}: слово до {hi} букв без повторов из "
                f"алфавита в {len(alphabet)} букв не составить.")
        if str(self.params.get("distinct_lengths", "no")) == "yes" \
                and self._count() > hi - lo + 1:
            raise GraphValidationError(
                f"{self.node_ref()}: {self._count()} слов разной длины из "
                f"диапазона {lo}..{hi} не набрать — длин всего "
                f"{hi - lo + 1}.")

    def summary(self) -> str:
        lo, hi = self._lengths()
        count = self._count()
        return f"{lo}–{hi} букв" + (f" × {count}" if count > 1 else "")

    def output_ports(self):
        return [Port("out", PortType.STRING if self._count() == 1
                     else PortType.LIST)]

    def compute(self, inputs, ctx: ExecContext):
        alphabet = self._alphabet()
        lo, hi = self._lengths()
        count = self._count()
        unique = str(self.params.get("unique_letters", "no")) == "yes"
        distinct = str(self.params.get("distinct_lengths", "no")) == "yes"

        lengths = (ctx.rng.sample(range(lo, hi + 1), count) if distinct
                   else [ctx.rng.randint(lo, hi) for _ in range(count)])

        words = []
        for length in lengths:
            if unique:
                words.append("".join(ctx.rng.sample(alphabet, length)))
            else:
                words.append("".join(ctx.rng.choice(alphabet)
                                     for _ in range(length)))
        if len(set(words)) < len(words):
            # Совпавшие слова ломают задание, где их потом различают.
            # Перегенерация дешевле, чем доборка по одному: слов мало, а
            # алфавит велик.
            raise RetryGeneration(
                f"{self.node_ref()}: слова совпали, пробуем заново.")
        return {"out": words[0] if count == 1 else words}


class TextLengthNode(Node):
    """
    Длина строки в символах.

    `list_length` считает элементы списка, и для строки его не
    приспособить: строка не список. Понадобилось сразу же — задание «вес
    текста» считает байты по длине вычеркнутого слова, и без этого узла
    цепочка обрывается на арифметике.

    Больше строковых операций здесь намеренно нет: подстрока, замена,
    регистр — всё это придумывалось бы «на будущее», а универсальность,
    придуманная на одном примере, всегда оказывается неправильной.
    """
    type_id = "text_length"
    category = "list"
    display_name = "Длина строки"
    description = "Число символов в строке. Вход: STRING. Выход: NUMBER."
    INPUTS = [Port("in", PortType.STRING)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(len(str(inputs.get("in") or "")))}


class LetterKeysNode(Node):
    """
    Раздать элементам списка буквенные ключи: «а) …», «б) …».

    Без узла это делается вручную: список букв, `map` по двум спискам
    сразу (которого нет), склейка. На практике автор пишет их в текст
    руками и теряет соответствие, как только меняется число элементов.

    Ключи отдаются отдельным выходом, а не только в подписанном виде:
    ответом в таких заданиях бывает как раз последовательность ключей
    («расшифруйте слово» — это «абв»).
    """
    type_id = "letter_keys"
    category = "list"
    display_name = "Буквенная нумерация"
    description = ("Список → подписанный «а) …» и сами ключи. "
                   "Вход: LIST. Выходы: labelled, keys (LIST).")
    INPUTS = [Port("in", PortType.LIST)]
    OUTPUTS = [Port("labelled", PortType.LIST), Port("keys", PortType.LIST)]
    PARAMS_SCHEMA = {
        "alphabet": {"type": "string", "default": RUSSIAN_KEYS},
        "separator": {"type": "string", "default": ") ", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        items = inputs.get("in") or []
        if not isinstance(items, (list, tuple)):
            raise GraphValidationError(
                f"{self.node_ref()}: на вход нужен список.")
        alphabet = str(self.params.get("alphabet", RUSSIAN_KEYS) or
                       RUSSIAN_KEYS)
        if len(items) > len(alphabet):
            raise GraphValidationError(
                f"{self.node_ref()}: элементов {len(items)}, а букв для "
                f"нумерации {len(alphabet)}.")
        separator = str(self.params.get("separator", ") "))
        keys = [alphabet[i] for i in range(len(items))]
        return {"keys": keys,
                "labelled": [f"{k}{separator}{v}" for k, v in
                             zip(keys, items)]}


__all__ = ["RandomWordNode", "TextLengthNode", "LetterKeysNode",
           "LATIN", "RUSSIAN_KEYS"]
