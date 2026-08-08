"""
Адаптер физического конструктора задач.

Один FisicConstructorGenerator обслуживает все физические разделы.
Каждый раздел в БД хранит свой JSON в generation_parametrs; адаптер
передаёт его в generate_task.

Нормализация типов (строки → числа, формулы в диапазонах, и т.п.)
делается уровнем ниже — в TaskConfig.parse / parse_variable_spec.
Адаптер просто передаёт конфиг как есть.

Проверяемый ответ
-----------------
Это первый обогащённый модуль (план, §1: «готовое задание не переписывают,
у него обогащают ответ»). Обогащение целиком помещается здесь, потому что
адаптер — ровно та граница, где домен встречается с ядром: физика считает
величину, размерность и запись, а перевод их в `NumberSpec` — работа
перевода, а не физики.

**Ни один конфиг в БД править не нужно.** Всё, из чего строится
спецификация, в конфигах уже есть: `formula` даёт величину, `dimension` —
размерность, `result.kind` — целочисленность. Необязательный блок
`answer.tolerance` добавлен для точечной настройки, но его отсутствие и
есть то поведение, которого от задачи ждут.
"""

from __future__ import annotations
import json

from core import (
    TaskGenerator, StaticTask, TextBlock, CHECKABLE_DEFAULT
)
from core.answers import NumberSpec, Tolerance, ToleranceKind, significant_digits
from .fisic_generater import FisicTask, generate_task


class FisicConstructorGenerator(TaskGenerator):
    """Универсальный генератор для физических задач из БД."""

    name = "Физическая задача"
    # CHECKABLE безусловно: физическая задача по построению имеет числовой
    # результат с формулой — нет варианта конфига, при котором проверять
    # было бы нечего. (У графа не так, там возможности зависят от графа.)
    capabilities = CHECKABLE_DEFAULT

    def __init__(self, partition_id: int, name: str, config: str | dict):
        self.partition_id = partition_id
        self.name = name
        self._config = self._to_dict(config)

    def configure(self, params: dict) -> None:
        """Обновить конфиг из БД (зовётся реестром при выдаче)."""
        if not params:
            return
        if "raw" in params:
            self._config = self._to_dict(params["raw"])
        else:
            # Repository вернул уже разобранный dict
            self._config = params

    def generate(self) -> StaticTask:
        task = generate_task(self._config)
        return StaticTask(
            statement=[TextBlock(task.condition)],
            answer=[TextBlock(task.solution)],
            meta={"partition_id": self.partition_id},
            answer_spec=_answer_spec(task),
        )

    @staticmethod
    def _to_dict(config: str | dict) -> dict:
        """Привести входной конфиг к dict. Поддерживает str и dict."""
        if isinstance(config, dict):
            return config
        if isinstance(config, str):
            try:
                data = json.loads(config)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        return {}


def _answer_spec(task: FisicTask) -> NumberSpec:
    """
    Проверяемая форма ответа физической задачи.

    Показ и проверка делаются из ОДНОЙ величины: `written` — та самая
    запись, что стоит в `solution`, поэтому ответ, переписанный с экрана,
    засчитывается по построению, а не по совпадению.
    """
    return NumberSpec(
        value=task.result,
        unit=task.dimension,
        written=task.written,
        tolerance=_tolerance(task),
    )


def _tolerance(task: FisicTask) -> Tolerance:
    """
    Допуск по умолчанию — «принимаем то, что показали».

    Здесь единственное решение пилота, которое стоило измерения.
    Физика печатает результат округлённым: 1/3 показывается как «0.333»,
    а в спецификации лежит 0.3333…. С точным допуском задача отвергала бы
    собственный напечатанный ответ — то есть автопроверка была бы не
    строгой, а сломанной.

    Поэтому:
      * целое (natural/integer) — точное совпадение: округления нет, и
        поблажка тут означала бы, что 12 сойдёт за 12.4;
      * вещественное — столько значащих цифр, сколько показано. Ответ с
        экрана проходит, ответ, посчитанный точнее, тоже, а ошибка в
        третьей цифре — нет.

    Явный `answer.tolerance` в конфиге перекрывает это: «±5 %» на задачах,
    где расходятся табличные константы, преподаватель поставит сам.
    """
    explicit = (task.meta or {}).get("answer_tolerance")
    if explicit:
        return Tolerance.from_dict(explicit)

    if (task.meta or {}).get("result_kind") in ("natural", "integer"):
        return Tolerance()

    digits = significant_digits(task.written) if task.written else 3
    return Tolerance(ToleranceKind.SIGNIFICANT, digits)
