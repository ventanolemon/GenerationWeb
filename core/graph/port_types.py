"""
Типы портов (проводов) визуального графа.

Каждый вход/выход узла типизирован. Совместимость соединений проверяется
и в редакторе (при попытке протянуть провод), и при загрузке графа из БД.
"""

from __future__ import annotations
from enum import Enum


class PortType(Enum):
    """Тип данных, переносимый проводом между узлами."""

    NUMBER = "number"            # одиночное число (int/float)
    STRING = "string"            # текст
    NUMBER_DICT = "number_dict"  # dict[str, float] — словарь именованных значений
    IMAGE = "image"              # PIL.Image в памяти
    BLOCK = "block"              # объект core.Block любого подтипа
    BLOCK_LIST = "block_list"    # list[Block]
    BOOL = "bool"                # результат проверки
    LIST = "list"                # list[Any] — универсальная коллекция (для map)
    EXPR = "expr"                # символьное выражение sympy (алгебра/анализ)
    MATRIX = "matrix"            # sympy.Matrix (в т.ч. вектор-столбец n×1)
    WORDS = "words"              # dict[str, str] — словарь term→translation (англ.)
    SENTENCES = "sentences"      # list[dict] — предложения с пропусками (англ.)
    TASK = "task"                # StaticTask / InteractiveTask — финал графа
    ANY = "any"                  # полиморфный порт: принимает значение любого
                                 # типа (узел сам диспетчеризует по факт. типу)


def is_compatible(src: PortType, dst: PortType) -> bool:
    """
    Можно ли соединить выход типа `src` со входом типа `dst`.

    Базово — строгое равенство типов. Допускаются удобные авто-повышения,
    убирающие лишние «служебные» узлы:
      * ANY: полиморфный порт совместим с любым типом. Используется входом
        узла-диспетчера (например, to_block: ANY → BLOCK), который сам
        разбирает фактический тип значения в compute().
      * BLOCK → BLOCK_LIST: одиночный блок можно подать туда, где ждут список
        (исполнитель обернёт его в [block]). Это избавляет от обязательного
        block_list для задания из одного блока.
      * NUMBER → EXPR: число — частный случай символьного выражения.
    Само оборачивание делает исполнитель (см. executor: _coerce_input).
    """
    if src == dst:
        return True
    if src is PortType.ANY or dst is PortType.ANY:
        return True
    if src is PortType.BLOCK and dst is PortType.BLOCK_LIST:
        return True
    if src is PortType.NUMBER and dst is PortType.EXPR:
        return True
    return False


def coerce_value(value, src: PortType, dst: PortType):
    """
    Привести значение от выхода типа src ко входу типа dst при авто-повышении.
    Для равных типов и для ANY-портов — без изменений (значение разбирает узел).
    """
    if src == dst:
        return value
    if src is PortType.BLOCK and dst is PortType.BLOCK_LIST:
        return [value]
    return value
