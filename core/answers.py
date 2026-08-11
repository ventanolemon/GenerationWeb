"""
Спецификация ответа: типизированные данные + правило сравнения.

Центральное решение плана (docs/architecture/interactive_tasks_plan.md, §1):

    Ответ — это данные с правилом сравнения, а блок для показа выводится
    из них. Не наоборот.

Сегодня `StaticTask.answer: List[Block]` — уже отрендеренный для глаз
результат: `FormulaBlock` с латехом, `TextBlock` с «увеличится вдвое».
Сверить с ним ввод пользователя нельзя в принципе. Здесь заводится вторая,
проверяемая форма ответа; `display_blocks()` порождает из неё привычные
блоки, поэтому существующий показ не ломается.

Что уже есть:
  * NumberSpec      — число с допуском и размерностью
  * TextSpec        — строка с нормализацией и опечатками
  * ExpressionSpec  — выражение, два режима сравнения
  * SlotsSpec       — набор именованных слотов (линал, «заполни пропуски»)

Чего сознательно НЕТ (следующие этапы плана):
  * выбор одного/нескольких, последовательность, пары — §3, вместе с
    реестром виджетов;
  * алгебра размерностей (м/с² против м·с⁻²) — размерность сравнивается
    как строка после нормализации;
  * хранение в БД и запись режима в попытку — §11, этап 3. Здесь режим
    уже лежит в `Verdict.mode`, чтобы этап 3 не пришлось делать задним
    числом.

Модуль headless: ни Qt, ни БД. Единственная тяжёлая зависимость — sympy,
и она импортируется лениво, внутри разбора выражений.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (Any, ClassVar, Dict, List, Optional, Sequence,
                    Tuple)

from .content import Block


# ======================================================================
#  Режим сравнения
# ======================================================================

class CheckMode(str, Enum):
    """
    Режим приёма ответа.

    Значений два (§5.1), и это СОЗНАТЕЛЬНО перечисление, а не `bool`.
    Булево поле нельзя дорастить до третьего варианта, не тронув каждое
    место, где оно читается, и каждую сохранённую строку. Перечисление из
    двух значений стоит сегодня ровно столько же и ничего не стоит завтра.

    Тумблер в интерфейсе остаётся тумблером: он представление над полем,
    а не его тип.

    Наследование от `str` — чтобы значение уходило в JSON и в БД как
    "soft"/"strict", а не как 0/1: строку в логе и в дампе видно, число —
    нет.
    """

    SOFT = "soft"
    """Мягкий: алгебраическая эквивалентность, допуск, опечатки."""

    STRICT = "strict"
    """Строгий: совпадение формы ответа с ожидаемой — ПОСЛЕ нормализации."""


DEFAULT_MODE = CheckMode.SOFT
"""
Умолчание — мягкий режим.

Из двух ошибок дешевле та, которую замечают: ложный отказ студент видит
сразу и посреди работы, а излишняя мягкость — это качество оценки, которое
преподаватель подтянет сам.
"""


# ======================================================================
#  Вердикт
# ======================================================================

class Reason(str, Enum):
    """Почему вердикт такой. Коды для аналитики и для подсказок, не текст."""

    EXACT = "exact"                 # совпало посимвольно после нормализации
    EQUIVALENT = "equivalent"       # алгебраически равно
    WITHIN_TOLERANCE = "tolerance"  # число попало в допуск
    TYPO = "typo"                   # принято как опечатка
    MISMATCH = "mismatch"           # не совпало
    WRONG_FORM = "wrong_form"       # значение верное, форма не та (строгий режим)
    WRONG_UNIT = "wrong_unit"       # число верное, размерность не та
    RESTATED = "restated"           # эквивалентно, но повторяет условие (§5)
    UNPARSED = "unparsed"           # ввод не разобран
    EMPTY = "empty"                 # пустой ввод


@dataclass(frozen=True)
class InputField:
    """
    Описание одного поля ввода — то, что можно показать ОТВЕЧАЮЩЕМУ.

    Виджет говорит, каким компонентом рисовать (`widgets.py`), а это —
    сколько полей и что подписать. Для числа, строки и выражения поле
    одно; у набора слотов их столько, сколько слотов, и без имён
    нарисовать их невозможно.

    Главное свойство — **здесь нет ответа**. В подсказку идёт то, что и
    так есть в условии: размерность, имена переменных. Значение,
    синонимы, допуск и канонический вид записи сюда не попадают, и это
    закреплено тестом: описание полей едет студенту, а спецификация — нет.
    """

    name: str = ""
    """Имя слота. Пусто — поле единственное и безымянное."""

    label: str = ""
    kind: str = "text"
    """Вид спецификации поля: number / text / expression."""

    hint: str = ""

    def to_dict(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.name:
            out["name"] = self.name
        if self.label:
            out["label"] = self.label
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass(frozen=True)
class Verdict:
    """
    Результат проверки одного ответа.

    `mode` здесь не для отладки. Преподаватель переключает тумблер — и все
    прошлые попытки задним числом меняют смысл, а статистика по курсу
    начинает смешивать два разных «верно». Поэтому режим, при котором
    вердикт вынесен, едет вместе с вердиктом и на этапе 3 ляжет в попытку.
    """

    accepted: bool
    mode: CheckMode
    reason: Reason
    normalized_input: str = ""
    detail: str = ""
    slots: Tuple[Tuple[str, "Verdict"], ...] = ()
    """Повердиктно по слотам — пусто для одиночных спецификаций."""

    def to_dict(self) -> dict:
        out: dict = {
            "accepted": self.accepted,
            "mode": self.mode.value,
            "reason": self.reason.value,
            "normalized_input": self.normalized_input,
        }
        if self.detail:
            out["detail"] = self.detail
        if self.slots:
            out["slots"] = {name: v.to_dict() for name, v in self.slots}
        return out


# ======================================================================
#  Пол нормализации
# ======================================================================
#
# Применяется в ОБОИХ режимах, до любого сравнения. Без него «строго»
# означает «наберите те же символы, что и я», и режим бесполезен (§5.1).
# Строгость начинается ПОСЛЕ приведения к канону, а не вместо него.

_DASHES = {
    "−": "-",   # −  минус
    "–": "-",   # –  en dash
    "—": "-",   # —  em dash
    "‐": "-",   # ‐  hyphen
    "‑": "-",   # ‑  non-breaking hyphen
}

_TIMES = {
    "×": "*",   # ×
    "·": "*",   # ·
    "∙": "*",   # ∙
    "⋅": "*",   # ⋅
}

_DIVIDE = {"÷": "/"}   # ÷

_SPACES = {
    " ": " ",   # неразрывный
    " ": " ",   # цифровой
    " ": " ",   # узкий неразрывный
    " ": " ",   # тонкий
}

_SUPERSCRIPT = {
    "⁰": "^0", "¹": "^1", "²": "^2", "³": "^3",
    "⁴": "^4", "⁵": "^5", "⁶": "^6", "⁷": "^7",
    "⁸": "^8", "⁹": "^9", "⁻": "^-",
}

_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def normalize(text: str) -> str:
    """
    Пол нормализации, общий для всех спецификаций и обоих режимов.

    Что делает:
      * юникодные тире и минусы  → дефис
      * ×, ·, ∙, ⋅               → *
      * ÷                        → /
      * надстрочные цифры        → ^n
      * неразрывные пробелы      → обычный
      * запятая МЕЖДУ ЦИФРАМИ    → точка
      * схлопывает пробелы, обрезает края

    Чего НЕ делает:
      * не понижает регистр — «м» и «М» это милли и мега, а `x` и `X` в
        выражении разные символы. Регистр — настройка спецификации;
      * не трогает незначащие нули — это разбор числа, а не текста, и
        живёт в NumberSpec;
      * не убирает пробелы внутри — «1 000» останется как есть, потому
        что для строки это может быть значимо. Пробелы в числе снимает
        разбор числа.

    Запятая переводится в точку только между цифрами: «1,5» → «1.5», но
    «красный, синий» остаётся списком.
    """
    if not text:
        return ""
    out = []
    for ch in text:
        out.append(
            _DASHES.get(ch)
            or _TIMES.get(ch)
            or _DIVIDE.get(ch)
            or _SPACES.get(ch)
            or _SUPERSCRIPT.get(ch)
            or ch
        )
    s = "".join(out)
    s = _DECIMAL_COMMA.sub(".", s)
    return " ".join(s.split())


# ======================================================================
#  Допуск
# ======================================================================

class ToleranceKind(str, Enum):
    EXACT = "exact"
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    SIGNIFICANT = "significant"


@dataclass(frozen=True)
class Tolerance:
    """
    Правило «насколько мимо ещё считается попаданием».

    EXACT        — совпадение с точностью до погрешности float
    ABSOLUTE     — |ввод − ожидание| ≤ amount
    RELATIVE     — |ввод − ожидание| ≤ amount · |ожидание|   (amount — доля)
    SIGNIFICANT  — совпадение после округления до amount значащих цифр
    """

    kind: ToleranceKind = ToleranceKind.EXACT
    amount: float = 0.0

    def accepts(self, user: float, expected: float) -> bool:
        if self.kind is ToleranceKind.EXACT:
            return math.isclose(user, expected, rel_tol=1e-12, abs_tol=1e-12)
        if self.kind is ToleranceKind.ABSOLUTE:
            return abs(user - expected) <= abs(self.amount) + 1e-12
        if self.kind is ToleranceKind.RELATIVE:
            return abs(user - expected) <= abs(self.amount * expected) + 1e-12
        if self.kind is ToleranceKind.SIGNIFICANT:
            digits = max(1, int(self.amount))
            return _round_sig(user, digits) == _round_sig(expected, digits)
        return False

    def describe(self) -> str:
        if self.kind is ToleranceKind.EXACT:
            return "точное значение"
        if self.kind is ToleranceKind.ABSOLUTE:
            return f"±{_fmt(self.amount)}"
        if self.kind is ToleranceKind.RELATIVE:
            return f"±{_fmt(self.amount * 100)}%"
        return f"{max(1, int(self.amount))} значащих цифр"

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "amount": self.amount}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Tolerance":
        if not data:
            return cls()
        return cls(
            kind=ToleranceKind(data.get("kind", "exact")),
            amount=float(data.get("amount", 0.0)),
        )


def _round_sig(x: float, digits: int) -> float:
    if x == 0.0:
        return 0.0
    return round(x, -int(math.floor(math.log10(abs(x)))) + (digits - 1))


def _fmt(x: float) -> str:
    """Число без хвоста .0 у целых — для человекочитаемых подсказок."""
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


# ======================================================================
#  Базовый класс
# ======================================================================

class AnswerSpec(ABC):
    """
    Спецификация ответа: что считается верным и как сравнивать.

    Три обязанности:
      * `check`          — вынести вердикт по вводу пользователя;
      * `display_blocks` — породить блоки показа (инверсия из §1);
      * `accepted_examples` — показать преподавателю, ЧТО ПРИМУТ.

    Третья не менее важна первой. Без списка «эти ответы будут засчитаны»
    рядом с переключателем механизм выключают на второй день, потому что
    не доверяют (§5). Инвариант, закреплённый тестом: каждый пример,
    возвращённый `accepted_examples()`, обязан проходить `check()`.
    """

    kind: ClassVar[str] = ""

    mode: CheckMode = DEFAULT_MODE
    tuning: dict = {}

    # ---------- обязательное ----------

    @abstractmethod
    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        """Проверить ввод. `mode` перекрывает режим спецификации на один раз."""

    @abstractmethod
    def display_blocks(self) -> List[Block]:
        """Блоки для показа ответа. Выводятся из данных, а не наоборот."""

    @abstractmethod
    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        """Кандидаты в примеры. Отсев делает `accepted_examples`."""

    @abstractmethod
    def _payload(self) -> dict:
        """Поля подкласса для сериализации, без общих."""

    # ---------- общее ----------

    def accepted_examples(self, *,
                          mode: Optional[CheckMode] = None) -> List[str]:
        """
        Примеры ответов, которые будут засчитаны в данном режиме.

        Каждый кандидат прогоняется через собственный `check`, и что не
        прошло — отбрасывается. Инвариант «предпросмотр не врёт» держится
        по построению, а не по добросовестности подкласса: показать
        меньше верных примеров не страшно, показать один неверный —
        страшно, потому что механизму перестают доверять целиком.
        """
        active = self.effective_mode(mode)
        seen, out = set(), []
        for candidate in self._candidate_examples(active):
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if self.check(candidate, mode=active).accepted:
                out.append(candidate)
        return out

    def distractors(self, count: int = 3, *,
                    mode: Optional[CheckMode] = None) -> List[str]:
        """
        Правдоподобные НЕВЕРНЫЕ варианты — материал теста.

        Ключевое решение плана (§2): тест это не третий тип задания, а
        режим показа ответа, и порождает варианты **та же типизация,
        которая даёт проверку**. Число можно возмутить, у выражения
        сменить знак, из размерности сделать характерную ошибку — и всё
        это знает сама спецификация, потому что она знает, что за
        величина перед ней.

        Инвариант зеркальный к `accepted_examples`: каждый кандидат
        прогоняется через собственный `check`, и что ПРОШЛО —
        отбрасывается. Дистрактор, который принимается как верный
        ответ, — это не «мягкая проверка», а тест с двумя правильными
        ответами, и заметит его студент, а не автор.

        Возвращается не больше `count`. Меньше — законно: лучше тест из
        трёх вариантов, чем из четырёх, где четвёртый тоже верен.
        """
        active = self.effective_mode(mode)
        correct = {normalize(text)
                   for text in self.accepted_examples(mode=active)}
        seen, out = set(), []
        for candidate in self._candidate_distractors(active):
            text = (candidate or "").strip()
            key = normalize(text)
            if not text or key in seen or key in correct:
                continue
            seen.add(key)
            if self.check(text, mode=active).accepted:
                continue
            out.append(text)
            if len(out) >= count:
                break
        return out

    def options(self, count: int = 4, *,
                mode: Optional[CheckMode] = None) -> List[str]:
        """
        Варианты для теста: верный ответ вперемешку с дистракторами.

        Пусто, если собрать честный тест не из чего — нет принимаемого
        примера или не нашлось ни одного дистрактора. Тест из одного
        варианта не тест, и показать его хуже, чем не показать.

        Порядок детерминирован СОДЕРЖИМЫМ спецификации, а не случаен.
        Причина рабочая: сессия переживает перезапуск сервиса и переезд
        между процессами (`state()`/`restore()`), и варианты собираются
        заново на той стороне. Случайная перетасовка означала бы, что
        студент между ходами видит другой порядок — а он уже запомнил
        «второй сверху».
        """
        active = self.effective_mode(mode)
        accepted = self.accepted_examples(mode=active)
        if not accepted:
            return []
        wrong = self.distractors(max(0, count - 1), mode=active)
        if not wrong:
            return []

        items = [accepted[0]] + wrong
        digest = hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True,
                       ensure_ascii=False).encode("utf-8")).hexdigest()
        random.Random(int(digest[:12], 16)).shuffle(items)
        return items

    def _candidate_distractors(self, mode: CheckMode) -> List[str]:
        """
        Кандидаты в неверные варианты. Отсев делает `distractors`.

        База не умеет ничего: у спецификации, не знающей, что за величина
        перед ней, правдоподобной ошибки не построить, а неправдоподобная
        хуже отсутствия — она выдаёт верный ответ методом исключения.
        """
        return []

    @property
    def preferred_widget(self) -> str:
        """
        Имя виджета, которого спецификация просит для себя.

        Пусто — «решает реестр, любой совместимый подойдёт». Нужно там,
        где совместимых виджетов несколько и выбор зависит не от вида
        ответа, а от его формы: набор слотов рисуется полями, а тот же
        набор с объявленной формой — сеткой.
        """
        return ""

    def input_fields(self) -> List[InputField]:
        """
        Поля ввода, которыми отвечают на эту спецификацию.

        По умолчанию одно безымянное поле вида самой спецификации:
        число, строка и выражение отличаются виджетом, а не количеством
        полей. Переопределяет только набор слотов.

        Содержимое обязано быть безопасным для показа отвечающему —
        см. `InputField`.
        """
        return [InputField(kind=self.kind)]

    def effective_mode(self, mode: Optional[CheckMode]) -> CheckMode:
        return mode if mode is not None else self.mode

    def to_dict(self) -> dict:
        """
        Сериализация. `tuning` НЕ пишется, когда пуст.

        Это половина требования «пустой слот инертен» (§5.1): отсутствие
        настройки и пустая настройка обязаны давать посимвольно одинаковое
        поведение. Вторая половина — что `check()` не читает из tuning
        ничего, чего там сегодня быть не может.
        """
        out = {"kind": self.kind, "mode": self.mode.value}
        out.update(self._payload())
        if self.tuning:
            out["tuning"] = dict(self.tuning)
        return out

    @staticmethod
    def from_dict(data: dict) -> "AnswerSpec":
        """Собрать спецификацию по полю `kind`."""
        kind = data.get("kind")
        builder = _REGISTRY.get(kind)
        if builder is None:
            raise ValueError(f"Неизвестный вид ответа: {kind!r}")
        return builder(data)


def _common(data: dict) -> dict:
    return {
        "mode": CheckMode(data.get("mode", DEFAULT_MODE.value)),
        "tuning": dict(data.get("tuning") or {}),
    }


# ======================================================================
#  Число
# ======================================================================

_NUMBER_HEAD = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
)

#: Показательная запись «мантисса ×10^степень» — та, которой пишут физику.
#: Ловится ПОСЛЕ нормализации, поэтому «×», «·» и надстрочные степени уже
#: стали «*» и «^n»; отдельно допускается «10^n» без мантиссы.
_POWER_OF_TEN = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))?\s*\*?\s*10\s*\^\s*([+-]?\d+)"
)


@dataclass
class NumberSpec(AnswerSpec):
    """
    Число с допуском и размерностью.

    Режимы:
      * мягкий  — значение в допуске; размерность, если объявлена, обязана
        совпасть после нормализации;
      * строгий — то же плюс ФОРМА записи: число значащих цифр как в
        ожидаемом. Так «0.5» не проходит там, где просили «0.50».

    Размерность сравнивается как строка. Алгебры единиц здесь нет и на
    этом этапе не планируется: «м/с^2» и «м·с^-2» — разные строки, и это
    честнее, чем половина алгебры, которая молча ошибается.
    """

    kind: ClassVar[str] = "number"

    value: float = 0.0
    tolerance: Tolerance = field(default_factory=Tolerance)
    unit: str = ""
    written: str = ""
    """
    Канонический вид записи, если он важен: «0.50», «1.0e-3».

    Нужен, потому что `float` теряет форму: 0.50 и 0.5 — одно значение и
    разное число значащих цифр. Строгий режим сравнивает форму, поэтому
    ему нужен эталон записи, а не только величина. Пусто — форма берётся
    из самого значения.
    """
    mode: CheckMode = DEFAULT_MODE
    tuning: dict = field(default_factory=dict)

    # ---------- проверка ----------

    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        active = self.effective_mode(mode)
        text = normalize(user_input)
        if not text:
            return Verdict(False, active, Reason.EMPTY, text,
                           "Ответ не введён.")

        number_text, unit_text = _split_number_and_unit(text)
        if number_text is None:
            return Verdict(False, active, Reason.UNPARSED, text,
                           "Не удалось прочитать число.")

        try:
            user_value = float(number_text.replace(" ", ""))
        except ValueError:
            return Verdict(False, active, Reason.UNPARSED, text,
                           "Не удалось прочитать число.")

        if self.unit and normalize(unit_text) != normalize(self.unit):
            return Verdict(
                False, active, Reason.WRONG_UNIT, text,
                f"Ожидалась размерность «{self.unit}».")

        if not self.tolerance.accepts(user_value, self.value):
            return Verdict(False, active, Reason.MISMATCH, text,
                           "Значение не совпадает.")

        if active is CheckMode.STRICT:
            want = significant_digits(self.written or _fmt(self.value))
            got = significant_digits(number_text)
            if got != want:
                return Verdict(
                    False, active, Reason.WRONG_FORM, text,
                    f"Ожидалось {want} значащих цифр, получено {got}.")

        exact = user_value == self.value
        return Verdict(
            True, active,
            Reason.EXACT if exact else Reason.WITHIN_TOLERANCE, text)

    # ---------- показ ----------

    def display_blocks(self) -> List[Block]:
        from .blocks import TextBlock
        return [TextBlock(self._written())]

    def input_fields(self) -> List[InputField]:
        # Размерность — не подсказка к ответу, а часть условия: её и так
        # видно в вопросе. Зато рядом с полем она снимает половину
        # «неверно» из-за того, что человек написал число без единиц.
        return [InputField(kind=self.kind, hint=self.unit)]

    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        out = [self._written()]
        if self.unit:
            # То же число с обычным пробелом перед размерностью — частый
            # результат копирования из вёрстки.
            out.append(f"{self.written or _fmt(self.value)} {self.unit}")
        if mode is CheckMode.SOFT:
            edge = self._tolerance_edge()
            if edge is not None:
                out.append(self._written(edge))
            # Запятая вместо точки — самый частый ввод с русской
            # раскладки, и он проходит благодаря полу нормализации.
            out.append(self._written().replace(".", ",", 1))
        return out

    # ---------- вспомогательное ----------

    def _written(self, value: Optional[float] = None) -> str:
        if value is None:
            head = self.written or _fmt(self.value)
        else:
            head = _fmt(value)
        return f"{head} {self.unit}".strip()

    def _tolerance_edge(self) -> Optional[float]:
        """Значение на краю допуска — самый убедительный пример «примут»."""
        if self.tolerance.kind is ToleranceKind.ABSOLUTE:
            return self.value + abs(self.tolerance.amount)
        if self.tolerance.kind is ToleranceKind.RELATIVE:
            return self.value + abs(self.tolerance.amount * self.value)
        return None

    def _candidate_distractors(self, mode: CheckMode) -> List[str]:
        """
        Характерные ошибки числового ответа, а не случайные числа.

        Дистрактор обязан быть правдоподобным: вариант «яблоко» среди
        чисел выдаёт верный ответ методом исключения, то есть превращает
        тест в подарок. Поэтому берутся ошибки, которые студент
        действительно делает: потерянный знак, порядок величины,
        перепутанные множитель и делитель, ответ без размерности.
        """
        value = self.value
        # Возмущение округляется до той же значимости, что и показанный
        # ответ: «0.9800000000000001» выдаёт машинное происхождение
        # варианта, и студент отбрасывает его не думая.
        digits = significant_digits(self.written or _fmt(value))
        def shifted(factor: float) -> str:
            return self._written(round_significant(value * factor, digits))

        out: List[str] = []
        if value:
            out.append(self._written(-value))          # потерянный знак
            out.append(shifted(10))                    # порядок величины
            out.append(shifted(0.1))
            out.append(shifted(2))                     # забытая двойка
            out.append(shifted(0.5))
        if self.unit:
            # Ответ без размерности — самая частая ошибка там, где
            # размерность объявлена, и самый полезный дистрактор: он учит
            # тому, ради чего размерность и объявлена.
            out.append(_fmt(value))
        return out

    def _payload(self) -> dict:
        out: dict = {"value": self.value, "tolerance": self.tolerance.to_dict()}
        if self.unit:
            out["unit"] = self.unit
        if self.written:
            out["written"] = self.written
        return out


def _split_number_and_unit(text: str) -> Tuple[Optional[str], str]:
    """
    Отделить числовую голову от размерности: «9.8 м/с^2» → («9.8», «м/с^2»).

    Показательная запись разбирается наравне с обычной: «8.7×10^4 Дж» →
    («8.7e4», «Дж»). Без этого целый пласт заданий непроверяем — физика
    печатает так всё, что больше 10^4 или меньше 10^-3, то есть заметную
    часть своих ответов, и задание отвергало бы собственный показанный
    ответ, считая «*10^4» размерностью.
    """
    compact = text.replace(" ", "")

    power = _POWER_OF_TEN.match(compact)
    if power is not None:
        mantissa = power.group(1) or "1"
        return f"{mantissa}e{power.group(2)}", compact[power.end():]

    match = _NUMBER_HEAD.match(compact)
    if match is None:
        return None, ""
    return match.group(0), compact[match.end():]


def round_significant(value: float, digits: int) -> float:
    """Округлить до заданного числа значащих цифр."""
    if value == 0.0:
        return 0.0
    digits = max(1, int(digits))
    return round(value, -int(math.floor(math.log10(abs(value)))) + (digits - 1))


def significant_digits(text: str) -> int:
    """
    Сколько значащих цифр в ЗАПИСИ числа.

    Публичная: этим считает не только строгий режим. Генератор, который
    ПОКАЗЫВАЕТ округлённый ответ, обязан принимать ровно то, что показал,
    и допуск ему нужно выводить из записи. Второй такой счётчик рядом
    разошёлся бы с этим — молча и не сразу.

    «0.50» → 2, «0.5» → 1, «1.50» → 3, «0.050» → 2.
    У целого с нулями на конце («100» → 3) число значащих цифр по записи
    определить нельзя; считаем их значащими — это соглашение, и другого
    без явной пометки не построить.

    Показательная запись считается по мантиссе: «8.70×10^4» → 3.
    """
    s = str(text).strip().lstrip("+-").replace(" ", "")
    s = re.split(r"[*×]", s, maxsplit=1)[0] or s
    if "e" in s.lower():
        s = re.split("[eE]", s)[0]
    if "." in s:
        head, frac = s.split(".", 1)
        head = head.lstrip("0")
        digits = frac.lstrip("0") if head == "" else head + frac
        return len(digits) or 1
    return len(s.lstrip("0")) or 1


# ======================================================================
#  Строка
# ======================================================================

@dataclass
class TextSpec(AnswerSpec):
    """
    Строковый ответ с нормализацией.

    Режимы:
      * мягкий  — принимает синонимы и опечатки в пределах порога
        (расстояние Левенштейна), регистр по настройке;
      * строгий — совпадение после нормализации, опечатки не проходят.

    Обобщает `tolerant` из тренировки английских слов: там тот же
    Левенштейн зашит внутрь `WordsSession`, здесь он свойство ответа.
    """

    kind: ClassVar[str] = "text"

    value: str = ""
    alternatives: Tuple[str, ...] = ()
    """Синонимы, которые тоже засчитываются."""

    wrong_options: Tuple[str, ...] = ()
    """
    Правдоподобные НЕВЕРНЫЕ варианты — материал теста.

    Названо не `distractors`, потому что так называется МЕТОД базового
    класса, общий для всех видов ответа: поле с тем же именем затенило бы
    его, и «строка вдруг не умеет порождать варианты» выяснилось бы в
    рантайме. Пара по смыслу — `alternatives`: там принимаемые синонимы,
    здесь отвергаемые двойники.

    Отдельное поле, а не `tuning`: `tuning` это пустой слот под тонкую
    настройку ПРОВЕРКИ (§5.1), а неверные варианты — данные об ответе, и
    лежать они должны там же, где синонимы.

    Их нельзя вывести из самой строки. Опечатка не годится: мягкий режим
    её примет, строгий даст вариант, который никто не выберет.
    Осмысленные неверные варианты для «Найдите столицу» — другие города,
    и знает их только автор задания.
    """

    case_sensitive: bool = False
    max_edits: int = 1
    mode: CheckMode = DEFAULT_MODE
    tuning: dict = field(default_factory=dict)

    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        active = self.effective_mode(mode)
        text = normalize(user_input)
        if not text:
            return Verdict(False, active, Reason.EMPTY, text,
                           "Ответ не введён.")

        candidates = [self.value, *self.alternatives]
        probe = text if self.case_sensitive else text.casefold()

        for candidate in candidates:
            target = normalize(candidate)
            if not self.case_sensitive:
                target = target.casefold()
            if probe == target:
                return Verdict(True, active, Reason.EXACT, text)

        if active is CheckMode.SOFT and self.max_edits > 0:
            for candidate in candidates:
                target = normalize(candidate)
                if self.case_sensitive and probe.casefold() == target.casefold():
                    # Различие только в регистре, а регистр объявлен
                    # значимым. Это неверный ответ, а не опечатка: иначе
                    # допуск на опечатки молча отменял бы настройку —
                    # «ом» проходило бы вместо «Ом».
                    continue
                if not self.case_sensitive:
                    target = target.casefold()
                budget = self._edit_budget(target)
                if budget and _levenshtein(probe, target) <= budget:
                    return Verdict(True, active, Reason.TYPO, text,
                                   f"Принято как опечатка в «{candidate}».")

        return Verdict(False, active, Reason.MISMATCH, text,
                       "Ответ не совпадает.")

    def _edit_budget(self, target: str) -> int:
        """
        Сколько правок считать опечаткой в ответе такой длины.

        Не `max_edits` как есть — иначе короткий ответ принимает что
        угодно. У ответа «е» расстояние до «и», «ы», «щ» и вообще любой
        буквы равно единице, то есть задание «вставьте пропущенную
        букву» засчитывало ЛЮБОЙ ввод. Поймано на генераторе по
        русскому (при-/пре-), где ответ ровно одна буква.

        Правило простое и объяснимое: одна правка на каждые четыре
        символа. Короче четырёх — правок нет вовсе, потому что в слове
        из трёх букв опечатка неотличима от другого слова. Объявленный
        `max_edits` при этом остаётся верхней границей: он ослабляет
        проверку, но не может её отменить.
        """
        return min(self.max_edits, len(target) // 4)

    def display_blocks(self) -> List[Block]:
        from .blocks import TextBlock
        return [TextBlock(self.value)]

    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        out = [self.value, *self.alternatives]
        if not self.case_sensitive and self.value:
            out.append(self.value.upper())
        if mode is CheckMode.SOFT and self._edit_budget(normalize(self.value)):
            typo = _make_typo(self.value)
            if typo is not None:
                out.append(typo)
        return out

    def _candidate_distractors(self, mode: CheckMode) -> List[str]:
        """
        Только объявленные автором. Выдумать их из строки нельзя: опечатка
        не годится — мягкий режим её примет, строгий даст вариант, который
        никто не выберет. Осмысленные неверные варианты для «Найдите
        столицу» это другие города, и знает их только автор задания.
        """
        return [str(item) for item in self.wrong_options]

    def _payload(self) -> dict:
        out: dict = {"value": self.value}
        if self.wrong_options:
            out["wrong_options"] = list(self.wrong_options)
        if self.alternatives:
            out["alternatives"] = list(self.alternatives)
        if self.case_sensitive:
            out["case_sensitive"] = True
        if self.max_edits != 1:
            out["max_edits"] = self.max_edits
        return out


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            ))
        previous = current
    return previous[-1]


def _make_typo(word: str) -> Optional[str]:
    """
    Правдоподобная опечатка для предпросмотра — пропущенная буква.

    Именно пропуск, а не перестановка соседних букв: перестановка по
    Левенштейну стоит ДВЕ правки, и при бюджете по умолчанию (одна) такой
    пример не прошёл бы собственную проверку. Пропуск стоит ровно одну и
    укладывается в любой ненулевой бюджет.
    """
    stripped = word.strip()
    if len(stripped) < 4:
        return None
    i = len(stripped) // 2
    return stripped[:i] + stripped[i + 1:]


# ======================================================================
#  Выражение
# ======================================================================
#
# Разбор пользовательского ввода в sympy — это исполнение выражения.
# `parse_expr` под капотом пользуется eval, поэтому вход проходит через
# белый список символов и имён ДО разбора. Это та же дыра, о которой
# говорит §9 плана, и закрывать её дешевле сразу, чем потом.

_EXPR_ALLOWED = re.compile(r"^[0-9A-Za-zА-Яа-я_+\-*/^().\s]*$")

HOLE = "\u25af"
"""
Пустое место в формуле — то, что вставляет палитра (этап 7, §10.2).

Символ объявлен ЗДЕСЬ, рядом с проверкой, хотя ставит его клиент:
проверка обязана узнавать его, чтобы сказать «остались незаполненные
места» вместо «недопустимые символы». Клиентская копия (`frontend/
src/formula/fields.ts`) обязана совпадать с этой.
"""
_IDENTIFIER = re.compile(r"[A-Za-zА-Яа-я_][A-Za-zА-Яа-я_0-9]*")

_EXPR_FUNCTIONS = frozenset({
    "sin", "cos", "tan", "cot", "sec", "csc",
    "asin", "acos", "atan", "acot",
    "sinh", "cosh", "tanh",
    "sqrt", "exp", "log", "ln", "abs", "Abs",
    "pi", "E", "I", "oo", "factorial",
})

_EMPTY_PARENS = re.compile(r"\(\s*\)")
"""
Пустые скобки: `()`, `sin( )`.

Ловится ДО `parse_expr`, а не после его отказа — потому что отказа может
не быть. `parse_expr("()")` не бросает исключение, а тихо возвращает
пустой кортеж, и это ломается только ниже по цепочке, на сравнении
выражений, с сообщением про внутренности sympy. Дешёвая проверка строки
дешевле такого падения.
"""

_OP_CHARS = "+-*/^"
_OP_DISPLAY = {"-": "−"}
"""Знак минуса в подсказке — типографский, не дефис: так его пишут в учебнике."""


def _op_symbol(ch: str) -> str:
    return _OP_DISPLAY.get(ch, ch)


def _bracket_mismatch(source: str) -> Optional[str]:
    """
    Баланс круглых скобок — самая надёжная из эвристик: это подсчёт, а не
    попытка понять грамматику. Отрицательный баланс в процессе (`)(`)
    считается лишней закрывающей, положительный в конце — недостающими
    закрывающими.
    """
    depth = 0
    extra = 0
    for ch in source:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                extra += 1
            else:
                depth -= 1
    if extra == 1:
        return "Лишняя закрывающая скобка."
    if extra > 1:
        return f"Лишних закрывающих скобок: {extra}."
    if depth == 1:
        return "Не хватает одной закрывающей скобки."
    if depth > 1:
        return f"Не хватает {depth} закрывающих скобок."
    return None


def _trailing_operator(source: str) -> Optional[str]:
    """Выражение обрывается на знаке операции — оставленная на потом мысль."""
    stripped = source.rstrip()
    if stripped and stripped[-1] in _OP_CHARS:
        return (f"Выражение обрывается на знаке «{_op_symbol(stripped[-1])}» "
                "— после него нужен операнд.")
    return None


_OPERAND_MISSING_IN_PARENS = re.compile(r"([+\-*/^])\s*\)")


def _operand_missing_before_paren(source: str) -> Optional[str]:
    """
    Знак операции стоит прямо перед закрывающей скобкой: `sqrt(-)`,
    `(2+)`. Частый случай — недописанный аргумент функции.
    """
    match = _OPERAND_MISSING_IN_PARENS.search(source)
    if match is None:
        return None
    return (f"Внутри скобок выражение обрывается на знаке "
            f"«{_op_symbol(match.group(1))}» — после него нужен операнд.")


def _adjacent_operator_pair(source: str) -> Optional[str]:
    """
    Два знака операции подряд — кроме двух сочетаний, которые sympy
    понимает: второй знак «+»/«-» как унарный при первом («2*-3» —
    «2 умножить на минус 3») и пара «**» как возведение в степень.
    Остальные сочетания всегда синтаксическая ошибка, потому и хватает
    посимвольного перебора без разбора грамматики.
    """
    for i in range(len(source) - 1):
        a, b = source[i], source[i + 1]
        if a not in _OP_CHARS or b not in _OP_CHARS:
            continue
        if b in "+-":
            continue
        if a == "*" and b == "*":
            continue
        return f"Два знака подряд: «{_op_symbol(a)}{_op_symbol(b)}»."
    return None


def _diagnose_syntax(source: str) -> Optional[str]:
    """
    Назвать причину отказа `parse_expr` на языке школьной математики —
    без токенов, позиций в строке и имён функций разбора.

    Вызывается ТОЛЬКО из ветки `except` вокруг уже провалившегося
    разбора (§10.2 плана): эвристики ниже — счётчик и поиск по строке,
    дешёвые сами по себе, но гонять их на каждый верный ответ незачем,
    раз для верного ответа результат заведомо `None`.

    Порядок — от самой надёжной эвристики к самой общей: несовпадение
    скобок распознаётся однозначным подсчётом, а «два знака подряд»
    ловит любую оставшуюся пару, до которой не добрались более точные
    проверки. `None` — эвристики не опознали причину, включается общее
    сообщение.
    """
    return (_bracket_mismatch(source)
            or _trailing_operator(source)
            or _operand_missing_before_paren(source)
            or _adjacent_operator_pair(source))


#: Точки, в которых сравниваются выражения перед символьным упрощением.
#: Иррациональные и не круглые нарочно: в 0, 1 и 2 слишком многое
#: случайно совпадает, а на π/7 и e/3 — почти ничего.
_PROBE_POINTS = (0.4363323129985824, 1.2817181715409552,
                 2.6180339887498949, 0.9061798459386640)


def _differs_numerically(user, expected) -> bool:
    """
    Доказать, что выражения РАЗНЫЕ, не прибегая к упрощению.

    Возвращает True, только если нашлась точка, где значения заметно
    расходятся, — это доказательство неравенства. Во всех прочих
    случаях (совпало, не посчиталось, слишком много переменных,
    комплексные значения) возвращается False, и решение принимает
    `simplify`. Ложного «не совпало» здесь быть не может: отсев
    срабатывает только на доказанном различии.

    Зачем: `simplify` на производной средней тяжести занимает около
    секунды и ничем не ограничен сверху, а неверный ответ — самый частый
    случай в тренировке. Численная проверка стоит доли миллисекунды.
    """
    try:
        import sympy
    except ImportError:
        return False

    free = sorted(user.free_symbols | expected.free_symbols, key=str)
    if len(free) > 3:
        # Много переменных — перебор точек перестаёт быть дешёвым, а
        # выигрыш от отсева всё равно съедается подстановками.
        return False

    for shift, point in enumerate(_PROBE_POINTS):
        values = {s: sympy.Float(point + 0.13 * index + 0.07 * shift)
                  for index, s in enumerate(free)}
        try:
            a = complex(user.evalf(subs=values))
            b = complex(expected.evalf(subs=values))
        except (TypeError, ValueError, ZeroDivisionError, AttributeError):
            # Символы остались, полюс, комплексная ветвь — не наш случай.
            continue
        except Exception:                              # noqa: BLE001
            return False
        if not (math.isfinite(a.real) and math.isfinite(a.imag)
                and math.isfinite(b.real) and math.isfinite(b.imag)):
            continue
        # Порог относительный: у больших значений абсолютная разница
        # накапливается на самом вычислении, а не на разнице выражений.
        if abs(a - b) > 1e-6 * max(1.0, abs(b)):
            return True
    return False


def _expr_transformations():
    """
    Преобразования разбора выражений.

    Кроме стандартных — «^» как степень и НЕЯВНОЕ УМНОЖЕНИЕ: «2x+1» и
    «2*x+1» это одна и та же запись, а не разные ответы. Отвергать первую
    значит отвергать то, как математику пишут от руки, — причём с
    вердиктом «не разобрано», из которого человеку неясно, что не так.

    Берётся `implicit_multiplication`, а НЕ `..._application`: последнее
    превращает «f(x)» в «f*x» для необъявленных имён и «sin x» в вызов —
    то есть начинает домысливать за отвечающего. Здесь домысливать нельзя.
    """
    from sympy.parsing.sympy_parser import (
        convert_xor, implicit_multiplication, standard_transformations)
    return standard_transformations + (convert_xor, implicit_multiplication)


_EXPR_TRANSFORMATIONS = None


def _transformations():
    global _EXPR_TRANSFORMATIONS
    if _EXPR_TRANSFORMATIONS is None:
        _EXPR_TRANSFORMATIONS = _expr_transformations()
    return _EXPR_TRANSFORMATIONS


#: До скольких операций выражения ещё имеет смысл показывать его
#: альтернативные формы в предпросмотре.
_EXAMPLE_FORMS_LIMIT = 40


class ExpressionError(ValueError):
    """Ввод не прошёл проверку до разбора или не разобрался."""


@dataclass
class ExpressionSpec(AnswerSpec):
    """
    Ответ-выражение. Здесь живёт главная опасность из §5.

    Опасность не в строгости, а в НАПРАВЛЕНИИ проверки. Для задания
    «упростите выражение» проверка `simplify(ввод − ответ) == 0` не просто
    мягкая, а катастрофически неверная: под неё проходит само исходное
    выражение, то есть задание принимает нерешённое.

    Отсюда два механизма:

      * `mode`             — мягкий (алгебраическая эквивалентность) против
        строгого (совпадение дерева выражения после канонизации). Строгий
        отвергает `(x-1)*(x+1)` там, где ожидалось `x**2-1`;
      * `reject_equivalent_to` — формы, которые эквивалентны, но задание
        не решают. Обычно туда кладут само условие. Работает и в мягком
        режиме — именно он без этого и ломается.

    Без второго механизма мягкий режим по умолчанию означал бы «принимаем
    условие обратно», поэтому он здесь, а не в следующем этапе.
    """

    kind: ClassVar[str] = "expression"

    value: str = "0"
    symbols: Tuple[str, ...] = ()
    reject_equivalent_to: Tuple[str, ...] = ()
    mode: CheckMode = DEFAULT_MODE
    tuning: dict = field(default_factory=dict)

    # ---------- проверка ----------

    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        active = self.effective_mode(mode)
        text = normalize(user_input)
        if not text:
            return Verdict(False, active, Reason.EMPTY, text,
                           "Ответ не введён.")

        try:
            user_expr = self._parse(text)
            expected = self._parse(self.value)
        except ExpressionError as exc:
            return Verdict(False, active, Reason.UNPARSED, text, str(exc))

        for forbidden in self.reject_equivalent_to:
            try:
                banned = self._parse(forbidden)
            except ExpressionError:
                continue
            if user_expr == banned:
                return Verdict(
                    False, active, Reason.RESTATED, text,
                    "Это повторяет условие — задание требует преобразования.")

        if user_expr == expected:
            return Verdict(True, active, Reason.EXACT, text)

        if active is CheckMode.STRICT:
            return Verdict(False, active, Reason.WRONG_FORM, text,
                           "Верно по значению, но форма не та.")

        # Быстрый отсев ПЕРЕД symbolic-упрощением. Замер на реальных
        # заданиях матана: неверный ответ на производную стоил до секунды,
        # и вся эта секунда уходила в `simplify` — внутри синхронного
        # веб-запроса, без какого-либо предела сверху.
        #
        # Численное расхождение ДОКАЗЫВАЕТ неравенство, поэтому отсев
        # вердикта не меняет: он только сокращает путь там, где ответ и
        # так неверен. Совпадение в точках ничего не доказывает —
        # оттуда по-прежнему идём в `simplify`.
        if _differs_numerically(user_expr, expected):
            return Verdict(False, active, Reason.MISMATCH, text,
                           "Выражение не совпадает.")

        import sympy
        try:
            equal = sympy.simplify(user_expr - expected) == 0
        except Exception:
            equal = False
        if equal:
            return Verdict(True, active, Reason.EQUIVALENT, text)

        return Verdict(False, active, Reason.MISMATCH, text,
                       "Выражение не совпадает.")

    # ---------- показ ----------

    def display_blocks(self) -> List[Block]:
        """
        Показ выводится из данных: латех получаем из разобранного
        выражения, а не храним отдельной строкой, которая разъедется.
        """
        from .blocks import FormulaBlock, TextBlock
        try:
            import sympy
            return [FormulaBlock(sympy.latex(self._parse(self.value)))]
        except Exception:
            return [TextBlock(self.value)]

    def input_fields(self) -> List[InputField]:
        # Имена переменных названы в условии; в подсказке они экономят
        # попытку, потраченную на «а какой буквой обозначать».
        hint = ("переменные: " + ", ".join(self.symbols)) if self.symbols else ""
        return [InputField(kind=self.kind, hint=hint)]

    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        out = [self.value]
        if mode is not CheckMode.SOFT:
            return out
        try:
            import sympy
            expr = self._parse(self.value)
            # Порог по размеру выражения, а не по времени. Замер на
            # матане: `factor()` неявной логарифмической производной —
            # 3.5 секунды, и предела сверху у неё нет, а предпросмотр
            # живёт внутри синхронного запроса преподавателя.
            #
            # Дело не только в скорости. Развёрнутая и разложенная формы
            # выражения из двухсот узлов — это не «пример принимаемого
            # ответа», а три строки нечитаемого; показать одну
            # каноническую запись честнее и полезнее.
            if sympy.count_ops(expr) <= _EXAMPLE_FORMS_LIMIT:
                for form in (sympy.expand(expr), sympy.factor(expr)):
                    out.append(str(form))
        except Exception:
            pass
        return out

    # ---------- разбор ----------

    def _candidate_distractors(self, mode: CheckMode) -> List[str]:
        """
        Ошибки преобразования: знак, степень, потерянное слагаемое.

        Всё это строится из РАЗОБРАННОГО выражения, а не из строки:
        подменить «x**2» на «x**3» текстом можно, но тогда «2*x**2 + 1»
        превратится в бессмыслицу. Дерево выражения знает, где степень.
        """
        try:
            expr = self._parse(self.value)
        except Exception:                              # noqa: BLE001
            return []

        out: List[str] = []
        try:
            out.append(str(-expr))                     # сменённый знак
        except Exception:                              # noqa: BLE001
            pass

        symbols = sorted(expr.free_symbols, key=str)
        if symbols:
            variable = symbols[0]
            for shift in (1, -1):
                try:
                    # Степень мимо на единицу — ошибка дифференцирования
                    # и интегрирования одновременно.
                    out.append(str(expr.replace(
                        lambda node: node.is_Pow and node.base == variable,
                        lambda node: variable ** (node.exp + shift))))
                except Exception:                      # noqa: BLE001
                    continue

        if expr.is_Add and len(expr.args) > 1:
            # Потерянное слагаемое — самая частая ошибка в длинном ответе.
            out.append(str(expr - expr.args[-1]))
            out.append(str(expr.args[-1]))
        return out

    def _allowed_names(self) -> frozenset:
        if self.symbols:
            return frozenset(self.symbols) | _EXPR_FUNCTIONS
        # Разбор ответа ради одних только имён — самая дорогая часть
        # проверки, когда ответ большой (производная в матане). Зависит
        # он только от `value`, который у спецификации не меняется,
        # поэтому считается один раз.
        cached = getattr(self, "_names_cache", None)
        if cached is not None:
            return cached
        try:
            from sympy.parsing.sympy_parser import parse_expr
            expr = parse_expr(self.value.replace("^", "**"),
                              transformations=_transformations(),
                              evaluate=True)
            names = frozenset(
                str(s) for s in expr.free_symbols) | _EXPR_FUNCTIONS
        except Exception:
            names = _EXPR_FUNCTIONS
        object.__setattr__(self, "_names_cache", names)
        return names

    def _parse(self, text: str):
        """
        Разобрать выражение, предварительно убедившись, что в нём нет
        ничего, кроме разрешённых символов и имён.

        Белый список — до разбора, а не после: `parse_expr` исполняет
        ввод, и проверять уже разобранное дерево поздно.
        """
        source = normalize(text)
        if HOLE in source:
            # Пустое место из палитры формул (этап 7). Клиент кнопку
            # «Ответить» при этом не даёт, но ответ мог прийти и не от
            # него — набранным руками или из другого клиента. «Есть
            # недопустимые символы» здесь особенно бестолково: студент
            # видит в своей формуле пустой квадратик и ровно про него
            # спрашивает.
            raise ExpressionError(
                "В формуле остались незаполненные места.")
        if not _EXPR_ALLOWED.match(source):
            raise ExpressionError("В выражении есть недопустимые символы.")
        if "__" in source:
            raise ExpressionError("В выражении есть недопустимые символы.")
        if _EMPTY_PARENS.search(source):
            # `parse_expr("()")` не бросает исключение — тихо возвращает
            # пустой кортеж, который ломается только ниже по цепочке
            # сравнения. Ловим здесь, а не ждём отказа, которого не будет.
            raise ExpressionError(
                "Внутри скобок ничего нет — там должен быть операнд.")

        allowed = self._allowed_names()
        for name in _IDENTIFIER.findall(source):
            if name not in allowed:
                raise ExpressionError(f"Неизвестное имя: {name}.")

        from sympy.parsing.sympy_parser import parse_expr
        try:
            return parse_expr(source, transformations=_transformations(),
                              evaluate=True)
        except Exception as exc:
            # Причина устанавливается ТОЛЬКО здесь, после того как обычный
            # разбор уже провалился (§10.2 плана) — на пути верного ответа
            # эти эвристики не запускаются ни разу.
            raise ExpressionError(
                _diagnose_syntax(source) or "Выражение не разобрано.") from exc

    def _payload(self) -> dict:
        out: dict = {"value": self.value}
        if self.symbols:
            out["symbols"] = list(self.symbols)
        if self.reject_equivalent_to:
            out["reject_equivalent_to"] = list(self.reject_equivalent_to)
        return out


# ======================================================================
#  Логическая функция
# ======================================================================


@dataclass
class LogicSpec(AnswerSpec):
    """
    Ответ — булева функция, а не её запись.

    Отдельный вид, а не `expression` с другой настройкой, по двум
    причинам, и первая решающая. `ExpressionSpec` разбирает ввод как
    АЛГЕБРУ: `A ^ B` там — исключающее ИЛИ (питоновский `^`), а в схеме и
    в учебнике это конъюнкция. Ошибка молчаливая: студент пишет верный
    ответ и получает «неправильно». Вторая причина — эквивалентность:
    у функции она проверяется по таблице истинности, а не через
    `simplify(a − b)`, которое над булевыми значениями не имеет смысла.

    Режимы. Мягкий принимает ЛЮБУЮ запись той же функции — это ответ на
    «выпишите функцию по схеме», где правильных записей бесконечно много.
    Строгий дополнительно требует, чтобы запись была не длиннее
    минимальной, — это ответ на «упростите выражение», где исходная
    формула эквивалентна, но задание не решает. Ровно та же опасность,
    из-за которой у `ExpressionSpec` есть `reject_equivalent_to`: мягкая
    проверка приняла бы условие обратно.
    """

    kind: ClassVar[str] = "logic"

    value: str = ""
    """Эталон в обозначениях схемы: `not(A) v (B ^ C)`."""

    variables: Tuple[str, ...] = ()
    """
    Имена входов. Обязательны: без них опечатка `Q` стала бы новой
    переменной, и ответ про другую схему прошёл бы как «просто другая
    функция».
    """

    mode: CheckMode = DEFAULT_MODE
    tuning: dict = field(default_factory=dict)

    # ---------- проверка ----------

    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        from .boolean_text import BooleanTextError, parse_boolean

        active = self.effective_mode(mode)
        text = normalize(user_input)
        if not text:
            return Verdict(False, active, Reason.EMPTY, text,
                           "Ответ не введён.")
        try:
            given = parse_boolean(text, self.variables)
            expected = parse_boolean(self.value, self.variables)
        except BooleanTextError as exc:
            return Verdict(False, active, Reason.UNPARSED, text, str(exc))

        if not self._same(expected, given):
            return Verdict(False, active, Reason.MISMATCH, text,
                           "Функция не совпадает с той, что задаёт схема.")
        if active is not CheckMode.SOFT and not self._minimal(expected, given):
            return Verdict(False, active, Reason.WRONG_FORM, text,
                           "Функция верна, но запись не упрощена.")
        return Verdict(True, active, Reason.EQUIVALENT, text)

    @staticmethod
    def _same(expected, given) -> bool:
        import sympy
        from sympy.logic.boolalg import Xor

        return not sympy.satisfiable(Xor(expected, given))

    @staticmethod
    def _minimal(expected, given) -> bool:
        """
        Не длиннее минимальной формы — по числу вхождений переменных.

        Мера грубая намеренно. Требовать совпадения с конкретным выводом
        `simplify_logic` значило бы отвергать равноправные минимальные
        формы (у одной функции их бывает несколько), а это худший вид
        строгости: студент решил задачу и получил отказ за то, что пришёл
        к другой из правильных записей.
        """
        from sympy.logic.boolalg import simplify_logic

        return _literal_count(given) <= _literal_count(simplify_logic(expected))

    # ---------- показ ----------

    def display_blocks(self) -> List[Block]:
        from .blocks import TextBlock

        return [TextBlock(self.value)]

    def input_fields(self) -> List[InputField]:
        hint = ("входы: " + ", ".join(self.variables)) if self.variables else ""
        return [InputField(kind=self.kind, hint=hint)]

    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        """
        Эталон и его минимальная форма.

        Минимальная нужна отдельно: в строгом режиме эталон, если он не
        упрощён, сам не пройдёт собственную проверку — и `accepted_examples`
        честно его отбросит, оставив преподавателя без единого примера.
        """
        from .boolean_text import BooleanTextError, format_boolean, parse_boolean
        from sympy.logic.boolalg import simplify_logic

        out = [self.value]
        try:
            out.append(format_boolean(
                simplify_logic(parse_boolean(self.value, self.variables))))
        except (BooleanTextError, Exception):
            pass
        return out

    def _candidate_distractors(self, mode: CheckMode) -> List[str]:
        """
        Правдоподобно НЕВЕРНЫЕ функции: отрицание всей формулы и подмена
        одной связки. Такие ошибки студенты и делают, а случайная функция
        от тех же переменных распознаётся как чужая с одного взгляда и
        выдала бы верный ответ методом исключения.
        """
        from .boolean_text import BooleanTextError, format_boolean, parse_boolean

        try:
            expected = parse_boolean(self.value, self.variables)
        except BooleanTextError:
            return []
        import sympy

        out = [format_boolean(sympy.Not(expected))]
        swapped = self.value.replace(" ^ ", " § ").replace(" v ", " ^ ")
        out.append(swapped.replace(" § ", " v "))
        return out

    def _payload(self) -> dict:
        out: dict = {"value": self.value}
        if self.variables:
            out["variables"] = list(self.variables)
        return out


def _literal_count(expr) -> int:
    """Сколько раз в записи встречаются переменные."""
    import sympy

    if isinstance(expr, sympy.Symbol):
        return 1
    if not getattr(expr, "args", ()):
        return 0
    return sum(_literal_count(arg) for arg in expr.args)


# ======================================================================
#  Вывод программы
# ======================================================================


@dataclass
class OutputSpec(AnswerSpec):
    """
    Ответ — то, что программа напечатает. Величина МНОГОСТРОЧНАЯ.

    Почему не `text`. Общая нормализация схлопывает любые пробелы, включая
    переводы строк (см. `normalize`), — а для «выполните программу на
    бумаге» строки и есть ответ: три величины на трёх строках и те же три
    в одну строку либо в другом порядке это разные ответы. Плюс у строки
    по умолчанию включён допуск на опечатку, и `sum=86` вместо `sum=85`
    прошло бы как описка. Молча: автор задания об этом не узнает.

    Что прощается: хвостовые пробелы и лишние переводы строки в конце —
    это следствие того, чем набирали текст, а не ответ. Что значимо:
    состав строк и их порядок.
    """

    kind: ClassVar[str] = "output"

    value: str = ""
    mode: CheckMode = DEFAULT_MODE
    tuning: dict = field(default_factory=dict)

    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        active = self.effective_mode(mode)
        if not (user_input or "").strip():
            return Verdict(False, active, Reason.EMPTY, "",
                           "Ответ не введён.")
        from .program_output import same_output

        if same_output(self.value, user_input):
            return Verdict(True, active, Reason.EXACT, user_input.strip())
        return Verdict(False, active, Reason.MISMATCH, user_input.strip(),
                       "Программа печатает не это.")

    def display_blocks(self) -> List[Block]:
        from .blocks import CodeBlock

        # Листингом, а не абзацем: в выводе значимы пробелы и переносы, а
        # обычный абзац их и схлопнет, и перенесёт по ширине окна.
        return [CodeBlock(self.value, language="text")]

    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        return [self.value]

    def _payload(self) -> dict:
        return {"value": self.value}


# ======================================================================
#  Набор слотов
# ======================================================================

SLOT_SEPARATORS = re.compile(r"[;\n]")


@dataclass
class SlotsSpec(AnswerSpec):
    """
    Несколько именованных полей ответа: матрица в линале, «заполни
    пропуски», ответ «скорость и время».

    Каждый слот — самостоятельная спецификация со своим правилом
    сравнения, поэтому в одном задании соседствуют число с допуском и
    строка с синонимами.

    Собственного режима у набора нет: `mode`, переданный в `check`,
    передаётся вниз слотам, а без него каждый слот берёт свой. Так
    «строгий режим на задание» работает, не переписывая слоты.
    """

    kind: ClassVar[str] = "slots"

    slots: Tuple[Tuple[str, AnswerSpec], ...] = ()
    shape: Optional[Tuple[int, int]] = None
    """
    Форма раскладки: (строк, столбцов), слоты идут построчно.

    Это ЕДИНСТВЕННОЕ, что отличает матрицу от набора полей, — и потому
    отдельного вида ответа для матриц нет. Матрица это сетка
    типизированных ячеек, а «сетка типизированных ячеек» уже есть: у
    каждого слота своя спецификация, свой вердикт и своё поле ввода.
    Форма добавляет к ним только геометрию.

    Отсюда же табличный ввод вообще: расписание, таблица истинности,
    заполнение пропусков в таблице — это тот же набор слотов с формой.
    Поэтому поле называется `shape`, а не `matrix_size`.
    """

    mode: CheckMode = DEFAULT_MODE
    tuning: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.shape is None:
            return
        rows, cols = self.shape
        if rows * cols != len(self.slots):
            raise ValueError(
                f"Форма {rows}×{cols} не сходится с числом слотов "
                f"({len(self.slots)}).")

    # ---------- сборка ----------

    @classmethod
    def from_grid(cls, rows, *, tolerance: Optional[Tolerance] = None,
                  mode: CheckMode = DEFAULT_MODE,
                  header: Optional[Sequence[str]] = None) -> "SlotsSpec":
        """
        Набор слотов из таблицы значений.

        Принимает что угодно, что итерируется по строкам и ячейкам:
        список списков, `sympy.Matrix` (через `.tolist()`), вектор-строку.
        Вид ячейки выводится из значения — число становится `NumberSpec`,
        всё прочее `ExpressionSpec`, — потому что в одной таблице
        соседствуют «5» и «sqrt(2)», и заставлять автора объявлять это
        поячеечно значило бы просить его описать то, что и так видно.

        Имена ячеек — `r1c1`, `r1c2`, … Они технические: в сетке подпись
        полю даёт его место, а не имя. Но имена нужны — по ним ходят
        вердикты и ответ по полям.
        """
        grid = _as_grid(rows)
        if not grid:
            raise ValueError("Пустая таблица: проверять нечего.")
        width = len(grid[0])
        if any(len(row) != width for row in grid):
            raise ValueError("Строки таблицы разной длины.")

        slots = []
        for r, row in enumerate(grid, start=1):
            for c, value in enumerate(row, start=1):
                slots.append((f"r{r}c{c}",
                              _cell_spec(value, tolerance, mode)))
        return cls(slots=tuple(slots), shape=(len(grid), width), mode=mode,
                   tuning={"header": list(header)} if header else {})

    def check(self, user_input: str, *,
              mode: Optional[CheckMode] = None) -> Verdict:
        active = self.effective_mode(mode)
        parts = self._split(user_input)
        results: List[Tuple[str, Verdict]] = []
        for index, (name, spec) in enumerate(self.slots):
            raw = parts.get(name, parts.get(str(index), ""))
            results.append((name, spec.check(raw, mode=mode)))

        accepted = bool(results) and all(v.accepted for _, v in results)
        if accepted:
            reason = Reason.EXACT
            detail = ""
        else:
            reason = Reason.MISMATCH
            wrong = [self.where(name) for name, v in results if not v.accepted]
            joiner = "; " if self.shape is not None else ", "
            detail = ("Не совпало: " + joiner.join(wrong) if wrong
                      else "Пустой ответ.")

        return Verdict(accepted, active, reason,
                       normalize(user_input), detail, tuple(results))

    def check_slots(self, values: Dict[str, str], *,
                    mode: Optional[CheckMode] = None) -> Verdict:
        """Проверка по словарю — путь виджета, у которого поля отдельные."""
        active = self.effective_mode(mode)
        results = [(name, spec.check(values.get(name, ""), mode=mode))
                   for name, spec in self.slots]
        accepted = bool(results) and all(v.accepted for _, v in results)
        wrong = [self.where(name) for name, v in results if not v.accepted]
        return Verdict(
            accepted, active,
            Reason.EXACT if accepted else Reason.MISMATCH,
            "", "" if accepted else "Не совпало: " + (
                "; " if self.shape is not None else ", ").join(wrong),
            tuple(results))

    def display_blocks(self) -> List[Block]:
        from .blocks import TableBlock, TextBlock
        if self.shape is not None:
            # Таблица, а не формула с квадратными скобками. Спецификация
            # не знает, матрица перед ней или расписание, и не должна
            # знать: `TableBlock` рисуется во всех трёх средах (Qt, веб,
            # .docx), а «сетка чисел» в них выглядит одинаково уместно.
            return [TableBlock(self._grid_text(), header=self._header())]
        out: List[Block] = []
        for name, spec in self.slots:
            shown = " ".join(b.render_plain() for b in spec.display_blocks())
            out.append(TextBlock(f"{name}: {shown}"))
        return out

    def _grid_text(self) -> List[List[str]]:
        from .blocks import FormulaBlock
        rows, cols = self.shape
        flat = []
        for _, spec in self.slots:
            parts = []
            for block in spec.display_blocks():
                # В ячейке таблицы `$\sqrt{2}$` — мусор: доллары нужны
                # печати, а не сетке.
                parts.append(block.latex if isinstance(block, FormulaBlock)
                             else block.render_plain())
            flat.append(" ".join(p for p in parts if p))
        return [flat[r * cols:(r + 1) * cols] for r in range(rows)]

    def where(self, name: str) -> str:
        """Человеческое имя слота: в сетке это место, а не идентификатор."""
        if self.shape is None:
            return name
        index = next((i for i, (n, _) in enumerate(self.slots) if n == name), -1)
        if index < 0:
            return name
        _, cols = self.shape
        return f"строка {index // cols + 1}, столбец {index % cols + 1}"

    def _header(self) -> Optional[List[str]]:
        header = (self.tuning or {}).get("header")
        return list(header) if header else None

    @property
    def preferred_widget(self) -> str:
        """Сетка знает про свою форму, поэтому и просит сеточный виджет."""
        return "grid_fields" if self.shape is not None else ""

    def input_fields(self) -> List[InputField]:
        """
        По полю на слот. Единственная спецификация, где количество полей
        не единица, — и единственная, для которой без имён виджет
        нарисовать нельзя.

        Подсказка берётся у самого слота, поэтому «м/с» у числового и
        список переменных у символьного работают внутри набора так же,
        как поодиночке.
        """
        out: List[InputField] = []
        for name, spec in self.slots:
            inner = spec.input_fields()
            hint = inner[0].hint if inner else ""
            kind = inner[0].kind if inner else spec.kind
            # В сетке подпись полю даёт его МЕСТО. Имена там технические
            # («r1c2»), и печатать их рядом с ячейкой — шум, который
            # мешает читать таблицу как таблицу.
            label = "" if self.shape is not None else name
            out.append(InputField(name=name, label=label, kind=kind, hint=hint))
        return out

    def _candidate_examples(self, mode: CheckMode) -> List[str]:
        if not self.slots:
            return []
        parts = []
        for name, spec in self.slots:
            examples = spec.accepted_examples(mode=mode)
            if not examples:
                return []      # слот без примеров — собрать честный нечем
            parts.append(f"{name}={examples[0]}")
        return ["; ".join(parts)]

    def _split(self, text: str) -> Dict[str, str]:
        """
        Разобрать одну строку в значения слотов.

        Две записи: «a=1; b=2» — по именам, «1; 2» — по порядку. Именованная
        имеет приоритет, потому что порядок полей пользователю не виден.
        """
        parts: Dict[str, str] = {}
        chunks = [c.strip() for c in SLOT_SEPARATORS.split(text or "") if c.strip()]
        positional: List[str] = []
        for chunk in chunks:
            if "=" in chunk:
                name, _, value = chunk.partition("=")
                parts[name.strip()] = value.strip()
            else:
                positional.append(chunk)
        for index, value in enumerate(positional):
            parts.setdefault(str(index), value)
        return parts

    def _payload(self) -> dict:
        out: dict = {"slots": [{"name": name, "spec": spec.to_dict()}
                               for name, spec in self.slots]}
        if self.shape is not None:
            out["shape"] = list(self.shape)
        return out


# ======================================================================
#  Сборка из словаря
# ======================================================================

def _as_grid(rows) -> List[list]:
    """
    Привести что угодно табличное к списку списков.

    `sympy.Matrix` отдаёт себя через `.tolist()`; одиночная строка чисел
    считается таблицей из одной строки — вектор-строку авторы пишут
    именно так, и требовать от них лишней вложенности незачем.
    """
    tolist = getattr(rows, "tolist", None)
    if callable(tolist):
        rows = tolist()
    out: List[list] = []
    for row in rows:
        if isinstance(row, (str, bytes)) or not hasattr(row, "__iter__"):
            return [list(rows)]
        out.append(list(row))
    return out


def _cell_spec(value: Any, tolerance: Optional[Tolerance],
               mode: CheckMode) -> AnswerSpec:
    """
    Спецификация одной ячейки по её значению.

    Вид выводится из значения, а не объявляется: в одной таблице
    соседствуют «5» и «sqrt(2)», и просить автора расписать это
    поячеечно значило бы просить его описать то, что и так видно.
    """
    if isinstance(value, bool):
        return TextSpec(value="да" if value else "нет", mode=mode)
    if isinstance(value, (int, float)):
        return NumberSpec(value=float(value), mode=mode,
                          tolerance=tolerance or Tolerance())
    text = str(value).strip()
    number = _NUMBER_HEAD.fullmatch(text)
    if number is not None:
        return NumberSpec(value=float(text), written=text, mode=mode,
                          tolerance=tolerance or Tolerance())
    return ExpressionSpec(value=text, mode=mode)


def _build_number(data: dict) -> NumberSpec:
    return NumberSpec(
        value=float(data.get("value", 0.0)),
        tolerance=Tolerance.from_dict(data.get("tolerance")),
        unit=str(data.get("unit", "")),
        written=str(data.get("written", "")),
        **_common(data))


def _build_text(data: dict) -> TextSpec:
    return TextSpec(
        value=str(data.get("value", "")),
        alternatives=tuple(data.get("alternatives") or ()),
        wrong_options=tuple(data.get("wrong_options") or ()),
        case_sensitive=bool(data.get("case_sensitive", False)),
        max_edits=int(data.get("max_edits", 1)),
        **_common(data))


def _build_expression(data: dict) -> ExpressionSpec:
    return ExpressionSpec(
        value=str(data.get("value", "0")),
        symbols=tuple(data.get("symbols") or ()),
        reject_equivalent_to=tuple(data.get("reject_equivalent_to") or ()),
        **_common(data))


def _build_logic(data: dict) -> LogicSpec:
    return LogicSpec(
        value=str(data.get("value", "")),
        variables=tuple(data.get("variables") or ()),
        **_common(data))


def _build_output(data: dict) -> OutputSpec:
    return OutputSpec(value=str(data.get("value", "")), **_common(data))


def _build_slots(data: dict) -> SlotsSpec:
    return SlotsSpec(
        slots=tuple(
            (entry["name"], AnswerSpec.from_dict(entry["spec"]))
            for entry in data.get("slots") or ()),
        shape=tuple(data["shape"]) if data.get("shape") else None,
        **_common(data))


_REGISTRY = {
    NumberSpec.kind: _build_number,
    TextSpec.kind: _build_text,
    ExpressionSpec.kind: _build_expression,
    LogicSpec.kind: _build_logic,
    OutputSpec.kind: _build_output,
    SlotsSpec.kind: _build_slots,
}


__all__ = [
    "CheckMode", "DEFAULT_MODE", "Reason", "Verdict", "InputField",
    "normalize", "Tolerance", "ToleranceKind",
    "AnswerSpec", "NumberSpec", "TextSpec", "ExpressionSpec", "LogicSpec",
    "OutputSpec", "SlotsSpec",
    "ExpressionError", "significant_digits",
]
