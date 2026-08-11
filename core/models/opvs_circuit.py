"""
Модель: логическая схема ОПВС.

Вторая модель по стандарту (§5, пункт 2) — и взята она следом за спектром
потому, что у схем УЖЕ есть символьное выражение (`to_sympy`), а значит
проверка ответа заработает сразу, без изобретения предметной семантики.

Что было. Узел `logic_circuit` отдаёт картинку и формулу СТРОКОЙ, а старый
`LogicCircuitGenerator` кладёт ответ в текстовый блок «Логическая функция:
…». То есть ровно то же, за что в §2 досталось линалу: ответ существует
как оформление, а не как величина. Проверить его нельзя — «выпишите
функцию по схеме» имеет бесконечно много правильных записей, и сравнение
строкой забракует все, кроме одной случайно выбранной.

Что стало. Модель отдаёт функцию величиной: `expr` — выражение sympy,
`truth_table` — таблица, `ones` — сколько наборов обращают функцию в
единицу. Проверка ответа сравнивает ФУНКЦИИ, а не записи, и принимает все
три обиходные системы обозначений (см. `boolean_text`). Это первый
настоящий потребитель `Instance.equivalent` — до сих пор ручка была
объявлена и покрыта тестами, но конвейер до неё не доходил.

Про «обратный вопрос». Стандарт обещал, что «схема по функции» и «функция
по схеме» — одна модель с разной разводкой. Наполовину это уже так:
формула стала величиной, поэтому её можно поставить в УСЛОВИЕ и спросить
таблицу или число единиц — проверяемо и работает сегодня. Полный обратный
вопрос — «нарисуйте схему» — упирается не в модель, а в интерактивный
холст (§6): принять ответ-чертёж пока нечем.
"""

from __future__ import annotations

import random

from .base import Instance, Model, ModelConfigError, ModelError, Output
from ..boolean_text import boolean_equivalent

#: Величины, ответ на которые — булева функция, а не число или строка.
#: Для них сравнение идёт по существу.
_FUNCTION_VALUES = ("expr", "simplified", "formula")


class CircuitInstance(Instance):
    """Экземпляр, знающий, что функция — не строка."""

    def equivalent(self, name: str, answer) -> bool:
        if name not in _FUNCTION_VALUES:
            return super().equivalent(name, answer)
        return boolean_equivalent(self.values["expr"], answer,
                                  self.values["variables"])


class LogicCircuitModel(Model):
    """Случайная логическая схема по ГОСТ 2.743-91 и её функция."""

    name = "opvs_circuit"
    title = "Логическая схема (модель)"
    description = (
        "Схема из вентилей И/ИЛИ/НЕ и её булева функция как величина: "
        "выражение, таблица истинности, число единичных наборов. Ответ "
        "«выпишите функцию» проверяется по существу, в любой из принятых "
        "систем обозначений."
    )
    category = "image"

    OUTPUTS = [
        Output("image", "image", "Схема",
               "Чертёж по ГОСТ 2.743-91 (картинка, как у logic_circuit — "
               "подпись навешивает узел image_block)."),
        Output("formula", "string", "Формула",
               "Запись функции в обозначениях схемы: not(A) v (B ^ C)."),
        Output("expr", "expr", "Выражение",
               "Та же функция выражением sympy — для проверки и упрощения."),
        Output("simplified", "expr", "Упрощённое выражение",
               "Минимальная форма: ответ на «упростите выражение»."),
        Output("variables", "list", "Входы",
               "Имена входов схемы по алфавиту."),
        Output("truth_table", "list", "Таблица истинности",
               "Строки [значения входов…, результат] нулями и единицами."),
        Output("ones", "number", "Единичных наборов",
               "На скольких наборах функция истинна."),
        Output("gates", "number", "Вентилей",
               "Сколько логических элементов на схеме."),
    ]

    PARAMS = {
        "inputs": {"type": "int", "default": 3},
        "attempts": {"type": "int", "default": 20, "optional": True},
    }

    def normalize_params(self, params: dict) -> dict:
        try:
            inputs = int(params.get("inputs", 3))
        except (TypeError, ValueError):
            raise ModelConfigError("inputs должно быть целым числом.")
        if not 2 <= inputs <= 5:
            # Больше пяти входов — таблица на 64 строки: столько не
            # заполняют руками, а меньше двух не схема.
            raise ModelConfigError("входов должно быть от 2 до 5.")
        try:
            attempts = int(params.get("attempts", 20))
        except (TypeError, ValueError):
            raise ModelConfigError("attempts должно быть целым числом.")
        return {"inputs": inputs, "attempts": max(1, attempts)}

    def build(self, rng, **params) -> Instance:
        import sympy as sp
        from sympy.logic.boolalg import simplify_logic

        cfg = self.normalize_params(params)
        elements = self._elements(rng, cfg)

        root = elements[-1]
        names = sorted(e.name for e in elements if e.type == "INPUT")
        symbols = [sp.Symbol(n) for n in names]
        expr = root.to_sympy()

        return CircuitInstance(
            values={
                "formula": str(root.get_logic_str()),
                "expr": expr,
                "simplified": simplify_logic(expr),
                "variables": names,
                "truth_table": _truth_table(expr, symbols),
                "ones": _ones(expr, symbols),
                "gates": sum(1 for e in elements if e.type != "INPUT"),
            },
            blocks={"image": self._image(elements)},
            params=dict(cfg),
        )

    # --- мост к существующему генератору ---

    def _elements(self, rng, cfg: dict) -> list:
        """
        Схема из `png_generator`.

        Генератор старый и берёт случайность из ГЛОБАЛЬНОГО random, а
        стандарт требует воспроизводимости от переданного rng. Мост —
        засеять глобальный генератор из нашего и вернуть его состояние
        обратно. Восстановление обязательно: исполнитель графа сеет
        глобальный random один раз на попытку, и молча сбить его посреди
        исполнения значило бы менять результат соседних узлов.
        """
        from exercises.opvs.png_generator import make_function

        state = random.getstate()
        random.seed(rng.getrandbits(64))
        try:
            return make_function(max_attempts=cfg["attempts"],
                                 n_inputs=cfg["inputs"])
        except RuntimeError as e:
            raise ModelError(str(e))
        finally:
            random.setstate(state)

    def _image(self, elements: list):
        """
        Картинка, а не готовый блок.

        Тип IMAGE в языке означает PIL.Image, и подпись навешивает
        отдельный узел `image_block`. Возвращать отсюда собранный
        ImageBlock значило бы решить за автора, как схема подписана, —
        то самое оформление, от которого модель отстранена (§4.3).
        """
        from exercises.opvs.png_generator import render_circuit

        return render_circuit(elements)


def _rows(count: int):
    """Наборы значений входов в обычном порядке: 000, 001, 010, …"""
    for mask in range(2 ** count):
        yield [(mask >> (count - 1 - i)) & 1 for i in range(count)]


def _truth_table(expr, symbols: list) -> list:
    return [row + [1 if _value(expr, symbols, row) else 0]
            for row in _rows(len(symbols))]


def _ones(expr, symbols: list) -> int:
    return sum(1 for row in _rows(len(symbols)) if _value(expr, symbols, row))


def _value(expr, symbols: list, row: list) -> bool:
    return bool(expr.subs(dict(zip(symbols, [bool(v) for v in row]))))


MODEL = LogicCircuitModel()
