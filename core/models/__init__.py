"""
Модели: питоновские модули, отдающие именованные типизированные величины.

Стандарт описан в `base.py` и в docs/architecture/models_on_july.md, §4.
Здесь — только сборка реестра по умолчанию: добавить модель = написать
модуль с классом-наследником Model и дописать его сюда. Узел в палитре,
порты по OUTPUTS и форма параметров по PARAMS появятся сами (см.
core/graph/nodes/model_nodes.py) — автору модели ничего про граф знать не
нужно.
"""

from __future__ import annotations

from .base import (
    Instance, Model, ModelConfigError, ModelError, Output, values_equivalent,
)
from .registry import DEFAULT_MODELS, ModelRegistry
from .linal_eigen import MODEL as LINAL_EIGEN
from .opvs_ccode import MODEL as OPVS_CCODE
from .opvs_circuit import MODEL as OPVS_CIRCUIT

DEFAULT_MODELS.register(LINAL_EIGEN)
DEFAULT_MODELS.register(OPVS_CIRCUIT)
DEFAULT_MODELS.register(OPVS_CCODE)

__all__ = [
    "DEFAULT_MODELS", "Instance", "Model", "ModelConfigError", "ModelError",
    "ModelRegistry", "Output", "values_equivalent",
]
