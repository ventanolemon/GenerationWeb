"""
Слоты ответа финального узла: объявление на строке.

План, §7.1. Финальный узел принимает типизированные значения прямо в слоты
ответа, а не готовые блоки. Значит, ему нужен способ объявить, СКОЛЬКО
слотов и какого они вида — до исполнения, потому что от объявления зависит
состав входных портов.

Почему строки, а не структуры
-----------------------------
Оба редактора — десктопный (`ui/editors/graph_canvas/inspector.py`) и
веб-овый (`frontend/src/graph-editor/ParamInspector.tsx`) — строят форму
параметров из `PARAMS_SCHEMA`, и тип `list` там означает ровно одно:
многострочное поле, строка = элемент. Список словарей ни один из них
нарисовать не умеет.

Поэтому объявление слота — одна строка компактного вида. Это не «пока
так»: то же решение уже принято для `simple_task.variables`
(`имя:min:max[:тип]`), и заводить второй способ объявлять то же самое
было бы хуже, чем принять этот.

Форма
-----
    имя[:вид][:опция=значение]...

Вид: `number` (по умолчанию), `expr`, `text`, `matrix`, `logic`.

Опции числа      : unit=, abs=, rel=, sig=
Опции выражения  : vars=, reject=
Опции строки     : alt=, wrong=, case, typos=
Опции функции    : vars=
Общие            : label=, mode=, choices=, много

Примеры::

    v:number:unit=м/с:sig=3
    y:expr:vars=x:reject=(x-1)*(x+1)
    city:text:alt=Москва|Moscow:typos=1
    city:text:wrong=Казань|Тверь|Самара:choices=4
    пропуски:text:много:typos=0
    функция:logic:vars=A,B,C

Сколько полей — знают данные
----------------------------
`много` объявляет слот, число полей в котором приходит СПИСКОМ, а не
пишется в объявлении. Понадобилось это на «вставьте пропущенные слова»:
у одного предложения один пропуск, у другого три, а объявление слотов
одно на все выпуски задания. Без этого такое задание вообще не собрать
типизированно — и именно поэтому оно годами существовало блоками,
которые ничего не проверяют.

Поля получают технические имена `имя1`, `имя2`, … — тот же приём, что у
ячеек матрицы (`r1c1`): в списке подпись полю даёт его номер.

Разбор строгий: неизвестный вид, неизвестная опция, два взаимоисключающих
допуска — это `GraphValidationError`, а не молчаливое умолчание. Ошибка в
объявлении ответа тихо превращается в задание, которое принимает не то;
падение при сохранении графа дешевле.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from ..errors import GraphValidationError, RetryGeneration
from ..port_types import PortType


KINDS = ("number", "expr", "text", "matrix", "logic")

#: Опции, осмысленные для каждого вида, плюс общие. Список нужен не для
#: подсказки, а для отказа: `alt=` у числового слота почти наверняка значит,
#: что автор перепутал вид, и промолчать здесь — оставить его с ответом,
#: который проверяется не так, как он думает.
_OPTIONS: Dict[str, Tuple[str, ...]] = {
    "number": ("unit", "abs", "rel", "sig"),
    "expr": ("vars", "reject"),
    # `alt=` — синонимы, которые ЗАСЧИТЫВАЮТСЯ; `wrong=` — неверные
    # варианты для теста. Две разные вещи, и путать их нельзя:
    # синоним в списке неверных сделал бы тест с двумя верными.
    "text": ("alt", "wrong", "case", "typos"),
    # Матрица — та же сетка ячеек, поэтому и опции у неё числовые: допуск
    # применяется к КАЖДОЙ ячейке. Своего словаря настроек у матрицы нет,
    # и заводить его значило бы объявить её отдельной сущностью, каковой
    # она не является.
    "matrix": ("abs", "rel", "sig"),
    # Логическая функция: имена входов. Допусков у неё быть не может —
    # функция либо та же, либо другая, промежуточного нет.
    "logic": ("vars",),
}
#: `choices=N` — показать ответ ТЕСТОМ из N вариантов. Общая опция, а
#: не свойство вида: тестом задаётся и число, и выражение, и строка.
#: `много` — число полей приходит списком, см. модульную докстроку.
_COMMON_OPTIONS = ("label", "mode", "choices", "много")

#: Опции без значения. Их приходится знать разбору в лицо: `имя:case`
#: неотличимо от `имя:вид` без списка, и молчаливо принять «case» за вид
#: значило бы получить невнятное «неизвестный вид» вместо работы.
_BARE_FLAGS = ("case", "много")

_PORT_TYPES = {
    "number": PortType.NUMBER,
    # EXPR принимает и NUMBER: `is_compatible` повышает число до выражения,
    # поэтому слот-выражение работает и там, где ответ посчитан численно.
    "expr": PortType.EXPR,
    "text": PortType.STRING,
    "matrix": PortType.MATRIX,
    # Функция едет ВЫРАЖЕНИЕМ, а не строкой. Строковая запись формулы —
    # это её оформление; принимать её в слот значило бы проверять показ
    # вместо величины, с чего вся работа по стандарту и начиналась.
    "logic": PortType.EXPR,
}


@dataclass(frozen=True)
class SlotDecl:
    """Разобранное объявление одного слота ответа."""

    name: str
    kind: str = "number"
    options: Dict[str, str] = field(default_factory=dict)

    @property
    def many(self) -> bool:
        """Число полей приходит списком, а не написано в объявлении."""
        return "много" in self.options

    @property
    def port_type(self) -> PortType:
        # Список ответов — это LIST на входе, каким бы ни был вид ячеек:
        # вид описывает ЭЛЕМЕНТ, а по проводу едет весь список.
        return PortType.LIST if self.many else _PORT_TYPES[self.kind]

    @property
    def choices(self) -> int:
        """
        Сколько вариантов показать. 0 — обычное поле ввода.

        Меньше двух вариантов теста не бывает, и «choices=1» почти
        наверняка описка, а не намерение.
        """
        raw = self.options.get("choices")
        if raw is None:
            return 0
        try:
            count = int(str(raw).strip())
        except ValueError:
            raise GraphValidationError(
                f"Слот {self.name!r}: choices={raw!r} — ожидалось целое.")
        if count < 2:
            raise GraphValidationError(
                f"Слот {self.name!r}: вариантов должно быть хотя бы два.")
        return count

    @property
    def label(self) -> str:
        """Подпись для показа. По умолчанию — имя слота."""
        return self.options.get("label") or self.name

    @property
    def wants_wrong_port(self) -> bool:
        """
        Нужен ли слоту вход для неверных вариантов.

        Только у строкового теста: у числа и выражения варианты
        порождаются из самого ответа, а у строки их выдумать нельзя — и
        приходят они, как выяснилось на английском, ДАННЫМИ (чужие
        переводы из того же словаря), а не литералами в объявлении.
        Литеральный `wrong=` остаётся как статический запасной вариант —
        тот же приём, что у весов случайного выбора.

        Списочный слот сюда не попадает: тестом задаётся вопрос целиком,
        а не отдельное поле из нескольких.
        """
        return (self.kind == "text" and not self.many
                and bool(self.options.get("choices")))

    def build(self, value: Any, mode, wrong=None) -> "Any":
        """
        Собрать спецификацию ответа по объявлению и значению с порта.

        Значение приходит в исполнении, объявление известно заранее —
        отсюда разделение: порты считаются по объявлению, спецификация
        появляется только когда есть что проверять.
        """
        from core.answers import CheckMode

        slot_mode = self.options.get("mode")
        if slot_mode is not None:
            try:
                active = CheckMode(slot_mode)
            except ValueError:
                raise GraphValidationError(
                    f"Слот {self.name!r}: mode={slot_mode!r} — допустимы "
                    f"{', '.join(m.value for m in CheckMode)}.")
        else:
            active = mode

        if self.many:
            return self._many(value, active)
        return self._one(value, active, wrong)

    def _one(self, value: Any, active, wrong=None):
        if self.kind == "number":
            return self._number(value, active)
        if self.kind == "expr":
            return self._expression(value, active)
        if self.kind == "matrix":
            return self._matrix(value, active)
        if self.kind == "logic":
            return self._logic(value, active)
        return self._text(value, active, wrong)

    def _many(self, value: Any, active):
        """
        Набор полей по числу элементов списка.

        Отдельного вида ответа для «нескольких одинаковых» нет и не
        заводится: несколько именованных полей — это `SlotsSpec`, ровно
        то же, что обслуживает матрицу и ответ «скорость и время».
        Списочный слот добавляет к нему только одно: количество берётся
        из данных, а не из объявления.

        Формы (`shape`) здесь нет намеренно. Пропуски в предложении идут
        подряд, а не сеткой, и объявить их таблицей 1×N значило бы
        сказать клиенту «рисуй таблицу» там, где таблицы нет.
        """
        from core.answers import SlotsSpec

        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise GraphValidationError(
                f"Слот {self.name!r} объявлен списочным (много), а на вход "
                f"пришло {type(value).__name__}.")
        items = list(value)
        if not items:
            raise RetryGeneration(
                f"Слот {self.name!r}: пустой список — проверять нечего.")
        return SlotsSpec(
            slots=tuple((f"{self.name}{i}", self._one(item, active))
                        for i, item in enumerate(items, start=1)),
            mode=active)

    # ---------- сборка по видам ----------

    def _number(self, value: Any, mode):
        from core.answers import NumberSpec, Tolerance, ToleranceKind

        try:
            number = float(value)
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Слот {self.name!r}: на вход пришло {value!r}, а объявлено "
                f"число.")

        tolerance = Tolerance()
        written = ""
        if "abs" in self.options:
            tolerance = Tolerance(ToleranceKind.ABSOLUTE,
                                  self._float("abs"))
        elif "rel" in self.options:
            tolerance = Tolerance(ToleranceKind.RELATIVE,
                                  self._float("rel"))
        elif "sig" in self.options:
            digits = self._int("sig")
            tolerance = Tolerance(ToleranceKind.SIGNIFICANT, digits)
            # Показ обязан согласоваться с проверкой: если принимаем три
            # значащих цифры, то и печатать надо три, а не 3.3333333333.
            written = _format(_round_significant(number, digits))

        return NumberSpec(
            value=number,
            tolerance=tolerance,
            unit=self.options.get("unit", ""),
            written=written,
            mode=mode,
        )

    def _expression(self, value: Any, mode):
        from core.answers import ExpressionSpec

        text = _expr_text(value)
        symbols = tuple(_split_list(self.options.get("vars", "")))
        if not symbols:
            symbols = _free_symbols(value)
        return ExpressionSpec(
            value=text,
            symbols=symbols,
            reject_equivalent_to=tuple(
                _split_list(self.options.get("reject", ""), sep="|")),
            mode=mode,
        )

    def _logic(self, value: Any, mode):
        """
        Булева функция как ответ.

        Эталон хранится в обозначениях схемы (`not(A) v (B ^ C)`), а не в
        записи sympy: ключ читает тот же человек, который смотрит на
        чертёж по ГОСТ, и `~A | (B & C)` для него запись из другого мира.
        """
        from core.answers import LogicSpec
        from core.boolean_text import format_boolean

        names = tuple(_split_list(self.options.get("vars", "")))
        if not names:
            names = _free_symbols(value)
        if not names:
            raise GraphValidationError(
                f"Слот {self.name!r}: не удалось определить входы функции — "
                f"перечислите их через vars=.")
        try:
            text = format_boolean(value)
        except Exception:                                  # noqa: BLE001
            raise GraphValidationError(
                f"Слот {self.name!r}: на вход пришло {value!r}, а объявлена "
                f"логическая функция.")
        return LogicSpec(value=text, variables=names, mode=mode)

    def _matrix(self, value: Any, mode):
        """
        Матрица как набор ячеек с формой.

        Отдельного вида ответа для матриц нет и не заводится: матрица —
        это сетка типизированных ячеек, а сетка типизированных ячеек уже
        есть (`SlotsSpec` с `shape`). Отсюда же бесплатно получается
        табличный ввод вообще: расписание и таблица истинности собираются
        тем же способом.
        """
        from core.answers import SlotsSpec

        try:
            return SlotsSpec.from_grid(value, tolerance=self._tolerance(),
                                       mode=mode)
        except (TypeError, ValueError) as exc:
            raise GraphValidationError(
                f"Слот {self.name!r}: на вход пришло {type(value).__name__}, "
                f"а объявлена матрица ({exc}).")

    def _tolerance(self):
        """Допуск, общий для всех ячеек. Пусто — точное совпадение."""
        from core.answers import Tolerance, ToleranceKind

        if "abs" in self.options:
            return Tolerance(ToleranceKind.ABSOLUTE, self._float("abs"))
        if "rel" in self.options:
            return Tolerance(ToleranceKind.RELATIVE, self._float("rel"))
        if "sig" in self.options:
            return Tolerance(ToleranceKind.SIGNIFICANT, self._int("sig"))
        return None

    def _text(self, value: Any, mode, wrong=None):
        from core.answers import TextSpec

        return TextSpec(
            value="" if value is None else str(value),
            alternatives=tuple(
                _split_list(self.options.get("alt", ""), sep="|")),
            # Провод перекрывает литералы: словарь знает чужие переводы,
            # а объявление — нет.
            wrong_options=(tuple(str(w) for w in wrong if str(w).strip())
                           if wrong else
                           tuple(_split_list(self.options.get("wrong", ""),
                                             sep="|"))),
            case_sensitive="case" in self.options,
            max_edits=self._int("typos") if "typos" in self.options else 1,
            mode=mode,
        )

    # ---------- разбор значений опций ----------

    def _float(self, key: str) -> float:
        raw = self.options.get(key, "")
        try:
            return float(str(raw).replace(",", "."))
        except ValueError:
            raise GraphValidationError(
                f"Слот {self.name!r}: {key}={raw!r} — ожидалось число.")

    def _int(self, key: str) -> int:
        raw = self.options.get(key, "")
        try:
            return int(str(raw).strip())
        except ValueError:
            raise GraphValidationError(
                f"Слот {self.name!r}: {key}={raw!r} — ожидалось целое число.")


def parse_slots(specs) -> List[SlotDecl]:
    """
    Разобрать список объявлений. Пустые строки пропускаются, всё
    остальное обязано быть разборным.
    """
    if specs is None:
        return []
    if isinstance(specs, str):
        specs = specs.splitlines()
    if not isinstance(specs, (list, tuple)):
        raise GraphValidationError(
            "Слоты ответа: ожидался список строк вида 'имя[:вид][:опция=…]'.")

    out: List[SlotDecl] = []
    seen: set = set()
    for raw in specs:
        line = str(raw).strip()
        if not line:
            continue
        decl = _parse_one(line)
        if decl.name in seen:
            raise GraphValidationError(
                f"Слот {decl.name!r} объявлен дважды.")
        seen.add(decl.name)
        out.append(decl)
    return out


def _parse_one(line: str) -> SlotDecl:
    parts = [p.strip() for p in line.split(":")]
    name = parts[0]
    if not name:
        raise GraphValidationError(
            f"Объявление слота {line!r}: пустое имя.")
    if not name.isidentifier():
        # Имя слота становится именем ПОРТА, а порты адресуются по имени в
        # проводах: пробел или дефис здесь дал бы граф, который нельзя
        # починить, не переписав рёбра руками.
        raise GraphValidationError(
            f"Слот {name!r}: имя должно быть идентификатором "
            f"(буквы, цифры, подчёркивание; не с цифры).")

    kind = "number"
    rest = parts[1:]
    if rest and "=" not in rest[0] and rest[0] not in _BARE_FLAGS:
        kind = rest[0]
        rest = rest[1:]
        if kind not in KINDS:
            raise GraphValidationError(
                f"Слот {name!r}: неизвестный вид {kind!r}; "
                f"допустимы {', '.join(KINDS)}.")

    allowed = _OPTIONS[kind] + _COMMON_OPTIONS
    options: Dict[str, str] = {}
    for token in rest:
        if not token:
            continue
        key, _, value = token.partition("=")
        key = key.strip()
        if key not in allowed:
            raise GraphValidationError(
                f"Слот {name!r} ({kind}): неизвестная опция {key!r}; "
                f"допустимы {', '.join(allowed)}.")
        options[key] = value.strip()

    if sum(1 for k in ("abs", "rel", "sig") if k in options) > 1:
        raise GraphValidationError(
            f"Слот {name!r}: допуск задан несколькими способами "
            f"(abs/rel/sig) — оставьте один.")
    return SlotDecl(name=name, kind=kind, options=options)


# ======================================================================
#  Вспомогательное
# ======================================================================

def _split_list(raw: str, sep: str = ",") -> List[str]:
    return [p.strip() for p in str(raw or "").split(sep) if p.strip()]


def _round_significant(x: float, digits: int) -> float:
    import math
    if x == 0.0:
        return 0.0
    digits = max(1, int(digits))
    return round(x, -int(math.floor(math.log10(abs(x)))) + (digits - 1))


def _format(x: float) -> str:
    from .compute import _format_value
    return _format_value(x)


def _expr_text(value: Any) -> str:
    """
    Текст выражения для `ExpressionSpec`.

    Спецификация хранит выражение строкой и разбирает его сама — по своему
    белому списку имён. Готовый объект sympy сюда не кладём: тогда в
    системе оказались бы два разных разбора одного и того же, и
    сериализация через границу процесса (§9) вернула бы всё равно строку.
    """
    if value is None:
        return ""
    if type(value).__module__.split(".")[0] == "sympy":
        return str(value)
    return str(value)


def _free_symbols(value: Any) -> Tuple[str, ...]:
    """
    Имена переменных из самого выражения, если автор не перечислил их.

    Умолчание, а не догадка: `ExpressionSpec` с пустым `symbols` не примет
    ввод, содержащий буквы, и ответ «x^2» оказался бы непроверяемым. Взять
    имена из ожидаемого ответа — ровно то, что автор имел в виду.
    """
    if type(value).__module__.split(".")[0] != "sympy":
        return ()
    try:
        return tuple(sorted(str(s) for s in value.free_symbols))
    except Exception:                                  # noqa: BLE001
        return ()


__all__ = ["SlotDecl", "parse_slots", "KINDS"]
