"""
Узлы, построенные из моделей.

Стандарт (docs/architecture/models_on_july.md, §4.2) говорит: модель
попадает в Июль узлом, выходные порты которого строятся по её `OUTPUTS`.
Здесь это и делается — но не одним универсальным узлом «Модель» с
выпадающим списком, а ОТДЕЛЬНЫМ КЛАССОМ УЗЛА НА КАЖДУЮ МОДЕЛЬ,
собираемым автоматически.

Почему так, а не как написано в §4.2. Форма параметров в редакторе (и на
вебе, и на десктопе) строится из `PARAMS_SCHEMA` класса — она статическая
и достаётся из палитры. У одного узла «Модель» набор полей менялся бы при
смене модели, а палитра этого выразить не умеет: пришлось бы менять
контракт каталога, инспектор на React и инспектор на Qt — три места ради
одного выпадающего списка. Класс на модель даёт то же самое даром:
собственные порты, собственная форма, собственное имя в палитре (автор
ищет «Матрица с известным спектром», а не «Модель», в которой ещё надо
угадать пункт списка) — и ноль правок в редакторах.

Автор модели при этом по-прежнему не пишет ни строчки кода узла: класс
собирается из объявления. Ровно то, ради чего стандарт и заводился.
"""

from __future__ import annotations

from typing import Type

from ...models.base import Model, ModelConfigError, ModelError
from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


def _coerce(value, kind: str):
    """Значение из формы редактора → тип, которого ждёт модель."""
    if kind == "int":
        return int(value)
    if kind == "number":
        return float(value)
    if kind == "bool":
        # Из JSON приходит и настоящий bool, и строка — форма на вебе
        # хранит галочку булевым, а импортированный граф может принести
        # "false", которое в питоне истинно.
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "да")
        return bool(value)
    if kind == "list":
        return list(value) if isinstance(value, (list, tuple)) else [value]
    return value


def model_node_class(model: Model) -> Type[Node]:
    """Собрать класс узла по объявлению модели."""
    outputs = [Port(out.name, PortType(out.type)) for out in model.OUTPUTS]
    schema = dict(model.PARAMS)

    class ModelNode(Node):
        type_id = f"model_{model.name}"
        category = model.category or "compute"
        display_name = model.title or model.name
        description = model.description
        OUTPUTS = outputs
        PARAMS_SCHEMA = schema

        #: Ссылка на модель — по ней узел и работает. Держим на классе,
        #: а не в params: выбор модели зафиксирован типом узла.
        MODEL = model

        def validate_params(self) -> None:
            for key, spec in self.PARAMS_SCHEMA.items():
                if key not in self.params:
                    continue
                try:
                    _coerce(self.params[key], str(spec.get("type", "string")))
                except (TypeError, ValueError):
                    raise GraphValidationError(
                        f"{self.node_ref()}: параметр {key!r} — "
                        f"{self.params[key]!r} не подходит под тип "
                        f"{spec.get('type')!r}."
                    )
            # Смысл параметров знает только модель: что различных λ в
            # диапазоне должно хватить на размер матрицы, из формы не
            # видно. Спрашиваем её здесь, при правке формы, — иначе автор
            # узнал бы о противоречии лишь по исчерпанным попыткам
            # генерации, где настоящей причины уже не разглядеть.
            try:
                self.MODEL.normalize_params(self._call_params())
            except ModelConfigError as e:
                raise GraphValidationError(f"{self.node_ref()}: {e}")
            except ModelError:
                # Невезение на этапе проверки формы не обсуждается: это
                # дело исполнителя, а не редактора.
                pass

        def _call_params(self) -> dict:
            out = {}
            for key, spec in self.PARAMS_SCHEMA.items():
                kind = str(spec.get("type", "string"))
                if key in self.params and self.params[key] not in (None, ""):
                    out[key] = _coerce(self.params[key], kind)
                elif "default" in spec:
                    out[key] = spec["default"]
            return out

        def compute(self, inputs, ctx: ExecContext):
            try:
                instance = self.MODEL.build(ctx.rng, **self._call_params())
                self.MODEL.check_instance(instance)
            except ModelConfigError as e:
                # Противоречивые параметры не чинятся перебросом зерна.
                raise GraphValidationError(f"{self.node_ref()}: {e}")
            except ModelError as e:
                # Модель не смогла построить экземпляр на этом зерне —
                # это обычный отказ стохастического источника, а не
                # поломка графа: исполнитель перебросит зерно.
                raise RetryGeneration(f"{self.node_ref()}: {e}")
            out = {}
            for declared in self.MODEL.OUTPUTS:
                here = instance.blocks if declared.is_block else instance.values
                out[declared.name] = here[declared.name]
            return out

        def summary(self) -> str:
            bits = []
            for key in self.PARAMS_SCHEMA:
                if key in self.params and self.params[key] not in (None, ""):
                    bits.append(f"{key}={self.params[key]}")
            return ", ".join(bits)

    ModelNode.__name__ = _class_name(model.name)
    ModelNode.__qualname__ = ModelNode.__name__
    ModelNode.__doc__ = model.description or model.title
    return ModelNode


def _class_name(name: str) -> str:
    """`linal_eigen` → `LinalEigenModelNode` (имя видно в трассировках)."""
    return "".join(part.capitalize() for part in name.split("_")) + "ModelNode"


def model_node_classes(registry) -> list[Type[Node]]:
    """Классы узлов для всех моделей реестра — в порядке имён."""
    return [model_node_class(registry.get(name)) for name in registry.names()]
