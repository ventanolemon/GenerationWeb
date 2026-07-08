"""
Реестр конвертеров типов — «у меня есть X, хочу Y, какой узел вставить».

Делает явной и программно доступной карту преобразований, которая иначе
размазана по узлам. Используется редактором (подсказка «вставить конвертер»
при несовместимом соединении) и как справочник.

Здесь только ОДНОУЗЛОВЫЕ преобразования представления (X→Y одним узлом), не
семантические операции (matrix_rank — это не «конвертер MATRIX→NUMBER», а
вычисление ранга). Авто-повышения (BLOCK→BLOCK_LIST, NUMBER→EXPR, *→ANY)
конвертера не требуют — для них find_converter вернёт None.
"""

from __future__ import annotations

from .port_types import PortType, is_compatible


# (тип-источник, тип-приёмник) → type_id узла-конвертера.
# Универсальный рендер «* → BLOCK» обрабатывается в find_converter отдельно
# (через to_block с входом ANY), поэтому здесь его нет.
CONVERTERS: dict[tuple[PortType, PortType], str] = {
    (PortType.EXPR, PortType.NUMBER): "expr_eval",
    (PortType.LIST, PortType.MATRIX): "list_to_matrix",
    (PortType.LIST, PortType.NUMBER): "list_length",
    (PortType.LIST, PortType.STRING): "list_join",
    (PortType.WORDS, PortType.TASK): "words_trainer",
    (PortType.SENTENCES, PortType.BLOCK_LIST): "sentence_fill",
}

# Типы, которые to_block умеет отрендерить в BLOCK (его вход ANY принимает
# вообще всё, но осмысленны именно эти «значимые» типы).
_TO_BLOCK_SOURCES = {
    PortType.NUMBER, PortType.STRING, PortType.BOOL,
    PortType.EXPR, PortType.MATRIX, PortType.IMAGE,
}


def find_converter(src: PortType, dst: PortType) -> str | None:
    """
    type_id узла, который превратит выход типа src во вход типа dst, либо None.

    None означает «конвертер не нужен или не существует»:
      * типы уже совместимы (равны или авто-повышение) — None;
      * нет подходящего одноузлового конвертера — None.
    Для приёмника BLOCK/BLOCK_LIST из «значимого» источника возвращается
    универсальный to_block (его выход BLOCK сам авто-повысится до BLOCK_LIST).
    """
    if is_compatible(src, dst):
        return None
    if dst in (PortType.BLOCK, PortType.BLOCK_LIST) and src in _TO_BLOCK_SOURCES:
        return "to_block"
    return CONVERTERS.get((src, dst))


def conversion_table() -> list[tuple[str, str, str]]:
    """
    Все известные преобразования как (источник, приёмник, узел) — для справки.
    Включает универсальный to_block и авто-повышения движка.
    """
    rows: list[tuple[str, str, str]] = [
        (PortType.BLOCK.value, PortType.BLOCK_LIST.value, "(авто-повышение)"),
        (PortType.NUMBER.value, PortType.EXPR.value, "(авто-повышение)"),
    ]
    for src in sorted(_TO_BLOCK_SOURCES, key=lambda t: t.value):
        rows.append((src.value, PortType.BLOCK.value, "to_block"))
    for (src, dst), tid in CONVERTERS.items():
        rows.append((src.value, dst.value, tid))
    return rows
