"""
Узлы информатики (категория informatics).

Появились после разбора восьми старых генераторов заданий по информатике
(docs/architecture/informatics_on_july.md). Разбор показал, что половина
из них собирается на языке как есть — свёртка последовательности, выборка
без повторов, перестановка, работа со списками уже были, — а упирается
всё в несколько узкопредметных вещей, которых в языке нет и которые
через существующие узлы выражаются десятками элементов.

Ни один узел здесь не заводит нового типа порта: всё едет числами,
строками и списками. Это сознательно — §7.4 плана требует не растить
ядро под предметные области, а держать их в пакетах узлов.
"""

from __future__ import annotations

from ..errors import GraphValidationError
from ..node import ExecContext, Node, Port
from ..port_types import PortType


_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

#: Основания, у которых есть общепринятое имя. Показывать «в 2-ичной»
#: правильнее, чем «в основании 2»: так пишут в учебнике и в задании.
_BASE_NAMES = {2: "двоичной", 8: "восьмеричной", 10: "десятичной",
               16: "шестнадцатеричной"}


def to_base(value: int, base: int, *, upper: bool = False) -> str:
    """
    Целое в позиционной записи по основанию `base`.

    Отдельная функция, а не метод узла: та же запись нужна и в проверке
    ответа, и в тестах, и вызывать ради неё узел графа неудобно.
    """
    if base < 2 or base > 36:
        raise ValueError("основание должно быть от 2 до 36")
    number = int(value)
    if number == 0:
        return "0"
    sign = "-" if number < 0 else ""
    number = abs(number)
    out: list[str] = []
    while number:
        number, rest = divmod(number, base)
        out.append(_DIGITS[rest])
    text = "".join(reversed(out))
    return sign + (text.upper() if upper else text)


def from_base(text: str, base: int) -> int:
    """Позиционная запись → целое. Пустая строка и мусор — ValueError."""
    if base < 2 or base > 36:
        raise ValueError("основание должно быть от 2 до 36")
    cleaned = str(text).strip()
    if not cleaned:
        raise ValueError("пустая запись числа")
    return int(cleaned, base)


class NumberBaseNode(Node):
    """
    Число в другой системе счисления — и обратно.

    Направление параметром, а не двумя узлами: «перевести в двоичную» и
    «прочитать двоичную» — это одно действие с двух сторон, как
    направление перевода у словаря. Разводить их значило бы удвоить и
    узел, и его описание.

    На выходе строка, а не число: `1011` в двоичной и `1011` в десятичной
    — разные величины, и число здесь потеряло бы главное, ради чего
    задание и существует. Обратное направление, наоборот, даёт NUMBER.
    """
    type_id = "number_base"
    category = "informatics"
    display_name = "Система счисления"
    description = ("Перевод числа в основание 2..36 и обратно. "
                   "Вход: NUMBER или STRING. Выход: STRING или NUMBER.")
    INPUTS = [Port("in", PortType.ANY)]
    OUTPUTS = [Port("out", PortType.ANY)]
    PARAMS_SCHEMA = {
        "base": {"type": "int", "default": 2},
        "direction": {"type": "enum", "values": ["to_base", "to_decimal"],
                      "default": "to_base"},
        "upper": {"type": "enum", "values": ["no", "yes"], "default": "no",
                  "optional": True},
    }

    def _base(self) -> int:
        try:
            base = int(self.params.get("base", 2))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: основание должно быть целым.")
        if not 2 <= base <= 36:
            raise GraphValidationError(
                f"{self.node_ref()}: основание {base} вне 2..36 — "
                f"цифр для записи не хватит.")
        return base

    def _to_base(self) -> bool:
        return str(self.params.get("direction", "to_base")) == "to_base"

    def validate_params(self) -> None:
        self._base()

    def summary(self) -> str:
        base = self.params.get("base", 2)
        return f"→ {base}" if self._to_base() else f"{base} → 10"

    def input_ports(self):
        # Тип входа известен из направления, и объявить его точно лучше,
        # чем принимать ANY: несовместимый провод поймается при сборке
        # графа, а не при выдаче задания.
        return [Port("in", PortType.NUMBER if self._to_base()
                     else PortType.STRING)]

    def output_ports(self):
        return [Port("out", PortType.STRING if self._to_base()
                     else PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        base = self._base()
        value = inputs.get("in")
        if self._to_base():
            try:
                return {"out": to_base(int(value), base,
                                       upper=str(self.params.get("upper",
                                                                 "no")) == "yes")}
            except (TypeError, ValueError):
                raise GraphValidationError(
                    f"{self.node_ref()}: на вход пришло {value!r}, "
                    f"а нужно целое число.")
        try:
            return {"out": from_base(str(value), base)}
        except ValueError:
            raise GraphValidationError(
                f"{self.node_ref()}: {value!r} — не запись числа в "
                f"основании {base}.")


class BaseNameNode(Node):
    """
    Название системы счисления словом: 2 → «двоичной».

    Мелочь, но без неё условие приходится собирать вручную для каждого
    основания, а с ней текст пишется один раз: «в #имя# системе». Для
    оснований без общепринятого имени — «N-ичной», как и говорят.
    """
    type_id = "base_name"
    category = "informatics"
    display_name = "Название системы счисления"
    description = ("Основание → название («двоичной»). "
                   "Вход: NUMBER. Выход: STRING.")
    INPUTS = [Port("in", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.STRING)]

    def compute(self, inputs, ctx: ExecContext):
        try:
            base = int(inputs.get("in"))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: основание должно быть целым.")
        return {"out": _BASE_NAMES.get(base, f"{base}-ичной")}


__all__ = ["NumberBaseNode", "BaseNameNode", "to_base", "from_base"]
