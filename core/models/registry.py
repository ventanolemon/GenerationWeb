"""
Реестр моделей.

Тот же приём, что уже работает в проекте трижды: зарегистрировал класс —
он появился везде (Block → во всех View, TaskGenerator → в списке
генераторов, Node → в палитре редактора). Модель регистрируется здесь, а
узел под неё строится автоматически (см. core/graph/nodes/model_nodes.py),
поэтому автору предметного модуля не нужно знать ни про Node, ни про
Port, ни про палитру.
"""

from __future__ import annotations

from typing import Iterator

from .base import OUTPUT_TYPES, Model


class ModelRegistry:
    """Хранилище моделей с поиском по имени."""

    def __init__(self) -> None:
        self._models: dict[str, Model] = {}

    def register(self, model: Model) -> Model:
        """Зарегистрировать ЭКЗЕМПЛЯР модели. Возвращает его же."""
        if not model.name:
            raise ValueError(
                f"модель {type(model).__name__} не имеет name."
            )
        if model.name in self._models:
            raise ValueError(f"модель {model.name!r} уже зарегистрирована.")
        _validate(model)
        self._models[model.name] = model
        return model

    def get(self, name: str) -> Model:
        try:
            return self._models[name]
        except KeyError:
            raise KeyError(
                f"неизвестная модель: {name!r}. "
                f"Доступны: {sorted(self._models)}"
            )

    def has(self, name: str) -> bool:
        return name in self._models

    def names(self) -> list[str]:
        return sorted(self._models)

    def __iter__(self) -> Iterator[Model]:
        return iter(self._models.values())

    def __len__(self) -> int:
        return len(self._models)


def _validate(model: Model) -> None:
    """
    Проверить объявление модели ПРИ РЕГИСТРАЦИИ, а не при исполнении.

    Опечатка в типе величины («matrics») иначе всплыла бы у автора графа
    в момент генерации задания — далеко от причины и в чужих терминах.
    Словарь типов берётся из `base.OUTPUT_TYPES`, а не из PortType:
    ссылка на граф отсюда замыкает цикл импорта (см. комментарий там).
    """
    if not model.OUTPUTS:
        raise ValueError(f"модель {model.name!r} не объявила ни одной величины.")
    seen: set[str] = set()
    for out in model.OUTPUTS:
        if not out.name:
            raise ValueError(f"модель {model.name!r}: величина без имени.")
        if out.name in seen:
            raise ValueError(
                f"модель {model.name!r}: величина {out.name!r} объявлена дважды."
            )
        seen.add(out.name)
        if out.type not in OUTPUT_TYPES:
            raise ValueError(
                f"модель {model.name!r}: величина {out.name!r} объявлена типом "
                f"{out.type!r}, которого нет. Доступны: {sorted(OUTPUT_TYPES)}"
            )


DEFAULT_MODELS = ModelRegistry()
