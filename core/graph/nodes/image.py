"""
Узлы изображений и ОПВС (категория image).

Изображения переносятся существующим типом PortType.IMAGE (PIL.Image в памяти).
Узлы:
  logic_circuit — процедурная логическая схема ОПВС (ГОСТ 2.743-91): выдаёт
                  картинку схемы и её булеву формулу. По образцу
                  LogicCircuitGenerator, но как источник графа.
  image_file    — загрузить картинку из файла (PNG/JPG) → IMAGE. По образцу
                  words_file: параметр file выбирается в инспекторе.
  image_block   — обернуть IMAGE в ImageBlock (с подписью) → BLOCK.

Логика генерации/рендера схем переиспользуется из exercises.opvs.png_generator.
Импорт ленивый: рендер тянет PIL/Qt, а движок графа в остальном headless.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class LogicCircuitNode(Node):
    """
    Логическая схема ОПВС: случайная схема из вентилей И/ИЛИ/НЕ (3-4 входа).
    Выходы: image (картинка схемы, IMAGE) и formula (булева формула, STRING).
    Источник; воспроизводимо через глобальный random (его сидит исполнитель).
    """
    type_id = "logic_circuit"
    category = "image"
    display_name = "Логическая схема"
    description = ("Случайная логическая схема ОПВС (ГОСТ 2.743-91). "
                   "Источник. Выходы: image (IMAGE), formula (STRING).")
    OUTPUTS = [Port("image", PortType.IMAGE), Port("formula", PortType.STRING)]

    def compute(self, inputs, ctx: ExecContext):
        from exercises.opvs.png_generator import make_function, render_circuit
        try:
            elements = make_function()
        except RuntimeError as e:
            # Не удалось собрать валидную схему — попросить пере-генерацию графа.
            raise RetryGeneration(f"logic_circuit {self.node_id!r}: {e}")
        image = render_circuit(elements)
        formula = elements[-1].get_logic_str()
        return {"image": image, "formula": str(formula)}


class ImageFileNode(Node):
    """
    Изображение из файла (PNG/JPG/…). Источник IMAGE.

    Параметр file — путь к картинке (выбирается в инспекторе через QFileDialog).
    Картинка загружается как PIL.Image при исполнении.
    """
    type_id = "image_file"
    category = "image"
    display_name = "Изображение из файла"
    description = ("Картинка из файла (PNG/JPG). Источник. Выход: IMAGE.")
    OUTPUTS = [Port("out", PortType.IMAGE)]
    PARAMS_SCHEMA = {
        "file": {"type": "file", "default": "",
                 "filter": "Изображения (*.png *.jpg *.jpeg *.bmp *.gif)"},
    }

    def validate_params(self) -> None:
        if not str(self.params.get("file", "")).strip():
            raise GraphValidationError(
                f"Узел {self.node_id!r}: укажите файл изображения."
            )

    def compute(self, inputs, ctx: ExecContext):
        from pathlib import Path
        from PIL import Image
        path = str(self.params.get("file", "")).strip()
        p = Path(path)
        if not p.exists():
            raise GraphValidationError(f"Файл изображения не найден: {path!r}")
        try:
            img = Image.open(p)
            img.load()                      # прочитать сразу (файл может закрыться)
        except Exception as e:
            raise RetryGeneration(f"image_file {self.node_id!r}: {e}")
        return {"out": img}


class ImageBlockNode(Node):
    """Блок-изображение из IMAGE (с подписью). IMAGE → BLOCK."""
    type_id = "image_block"
    category = "image"
    display_name = "Блок изображения"
    description = ("Обернуть изображение в блок задания (с подписью). "
                   "Вход: IMAGE. Выход: BLOCK.")
    INPUTS = [Port("in", PortType.IMAGE)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {"caption": {"type": "string", "default": "", "optional": True}}

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import ImageBlock          # ленивый: тянет Qt
        image = inputs.get("in")
        if image is None:
            raise RetryGeneration(
                f"image_block {self.node_id!r}: на вход не пришло изображение."
            )
        caption = str(self.params.get("caption", ""))
        return {"out": ImageBlock(image, caption=caption)}
