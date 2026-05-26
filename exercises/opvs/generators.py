"""
Адаптеры модулей ОПВС.

Логические схемы (png_generator) — изображение + ответ-формула.
Генератор C-кода (opvs_new) — листинг кода + ожидаемый вывод.

Эти разделы не лежат в текущей БД, но добавляются в реестр на случай,
если их захочется подключить через новые записи в Partitions.
"""

from __future__ import annotations

from core import (
    TaskGenerator, StaticTask, Capability,
    TextBlock, ImageBlock, CodeBlock,
    STATIC_DEFAULT,
)
from .png_generator import make_function, render_circuit
from .opvs_new import CCodeGenerator


class LogicCircuitGenerator(TaskGenerator):
    """Логическая схема по ГОСТ 2.743-91 + её формула как ответ."""

    name = "Логическая схема"
    capabilities = (
        Capability.STATIC | Capability.GROUPABLE
        | Capability.EXPORTABLE | Capability.HAS_IMAGES
    )

    def __init__(self, partition_id: int | None = None):
        if partition_id is not None:
            self.partition_id = partition_id

    def generate(self) -> StaticTask:
        elements = make_function()
        image = render_circuit(elements)        # PIL.Image, без сохранения
        formula = elements[-1].get_logic_str()
        return StaticTask(
            statement=[
                TextBlock(
                    "Постройте таблицу истинности для приведённой "
                    "логической схемы и упростите выражение."
                ),
                ImageBlock(image, caption="Логическая схема"),
            ],
            answer=[
                TextBlock(f"Логическая функция: {formula}"),
            ],
            meta={"partition_id": self.partition_id},
        )


class CCodeMistakesGenerator(TaskGenerator):
    """Сгенерировать C-код с N синтаксическими ошибками — задание 'найти ошибки'."""

    name = "Найти ошибки в C-коде"
    capabilities = STATIC_DEFAULT

    def __init__(self, partition_id: int | None = None, mistakes_count: int = 5):
        if partition_id is not None:
            self.partition_id = partition_id
        self.mistakes_count = mistakes_count

    def configure(self, params: dict) -> None:
        # Если в БД конфигурация — сохраняем количество ошибок
        if "mistakes_count" in params:
            self.mistakes_count = int(params["mistakes_count"])

    def generate(self) -> StaticTask:
        gen = CCodeGenerator()
        gen.generate_code()
        valid = str(gen)
        expected_output = gen.get_expected_output()
        mistakes = gen.introduce_mistakes(self.mistakes_count)
        broken_code = str(gen)

        return StaticTask(
            statement=[
                TextBlock(
                    f"В коде ниже допущено {self.mistakes_count} "
                    "синтаксических ошибок. Найдите их."
                ),
                CodeBlock(broken_code, language="c"),
            ],
            answer=[
                TextBlock("Корректный код:"),
                CodeBlock(valid, language="c"),
                TextBlock("Ожидаемый вывод программы:"),
                CodeBlock(expected_output, language="text"),
                TextBlock("Список ошибок:"),
                TextBlock("\n".join(f"  • {m}" for m in mistakes)),
            ],
        )


def all_generators() -> list[TaskGenerator]:
    """Возвращает экземпляры; partition_id не выставлены, потому что в БД их нет."""
    return [LogicCircuitGenerator(), CCodeMistakesGenerator()]
