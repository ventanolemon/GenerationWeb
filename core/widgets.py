"""
Реестр виджетов ответа.

План, §3: разнообразие форматов динамики живёт НЕ в типе задания и не в
перечислении форматов. Каждый виджет объявляет, какие спецификации ответа
он умеет обслуживать, и «выбрать формат» превращается в выбор **из
совместимых**, а не в свободное меню, где половина пунктов не работает.

Что здесь есть и чего здесь нет
-------------------------------
Здесь — **объявление**: имя, человекочитаемое название, список видов
спецификаций, которые виджет обслуживает. Реализация — на своей
платформе: Qt-виджет в десктопе, React-компонент во фронте. Ядро
headless и о них ничего не знает; связь идёт по имени, ровно как блоки
связаны с фронтом полем `type`.

Такое разделение — то же, что уже работает у реестра узлов: новый формат
это новая запись в реестре, ядро не трогается.

Почему список видов, а не «умеет всё»
-------------------------------------
Виджет «поле ввода» физически не может обслужить выбор из вариантов, а
радиокнопки — выражение с палитрой формул. Совместимость — свойство
пары (спецификация, виджет), и объявить её обязан виджет: спецификация
про новые виджеты знать не должна, иначе каждый новый формат правит ядро.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .answers import AnswerSpec


@dataclass(frozen=True)
class Widget:
    """
    Объявление виджета ответа.

    name   — идентификатор, по которому платформа находит реализацию.
             Уезжает в JSON и в снимок сессии, поэтому менять его нельзя
             так же, как нельзя менять "type" у блока.
    title  — что показать преподавателю в списке форматов.
    kinds  — виды спецификаций (`AnswerSpec.kind`), которые обслуживает.
    hint   — короткое пояснение к выбору, необязательное.
    """

    name: str
    title: str
    kinds: frozenset
    hint: str = ""

    def serves(self, spec: AnswerSpec) -> bool:
        return spec.kind in self.kinds

    def to_dict(self) -> dict:
        out = {
            "name": self.name,
            "title": self.title,
            "kinds": sorted(self.kinds),
        }
        if self.hint:
            out["hint"] = self.hint
        return out


class WidgetRegistry:
    """
    Хранилище объявлений виджетов.

    Повторная регистрация того же имени — ошибка, а не тихая замена:
    имя виджета лежит в снимках сессий, и подмена реализации под тем же
    именем меняет поведение уже выданных заданий.
    """

    def __init__(self) -> None:
        self._items: Dict[str, Widget] = {}

    def register(self, widget: Widget) -> Widget:
        if widget.name in self._items:
            raise ValueError(f"Виджет {widget.name!r} уже зарегистрирован.")
        self._items[widget.name] = widget
        return widget

    def get(self, name: str) -> Optional[Widget]:
        return self._items.get(name)

    def all(self) -> List[Widget]:
        return list(self._items.values())

    def for_spec(self, spec: AnswerSpec) -> List[Widget]:
        """Виджеты, совместимые со спецификацией. Порядок — регистрации."""
        return [w for w in self._items.values() if w.serves(spec)]

    def default_for(self, spec: AnswerSpec) -> Optional[Widget]:
        """
        Виджет по умолчанию — первый совместимый.

        Порядок регистрации в `_register_builtin` подобран так, что первым
        идёт самый общий вариант: он работает всегда, а специализированные
        преподаватель выбирает сам.
        """
        compatible = self.for_spec(spec)
        if not compatible:
            return None
        # Спецификация вправе попросить конкретный виджет: совместимых по
        # виду ответа бывает несколько, и выбор между ними зависит не от
        # вида, а от формы — набор слотов рисуется полями, а тот же набор
        # с объявленной формой сеткой.
        wanted = getattr(spec, "preferred_widget", "")
        if wanted:
            for widget in compatible:
                if widget.name == wanted:
                    return widget
        return compatible[0]

    def resolve(self, spec: AnswerSpec, name: str = "") -> Optional[Widget]:
        """
        Найти виджет для спецификации: по имени, если оно задано и
        совместимо, иначе — умолчание.

        Несовместимое имя молча не подменяется: это ошибка настройки
        задания, и вернуть вместо него что-то работающее значит спрятать
        её до момента, когда студент увидит не тот способ ввода.
        """
        if not name:
            return self.default_for(spec)
        widget = self.get(name)
        if widget is None:
            raise KeyError(f"Виджет {name!r} не зарегистрирован.")
        if not widget.serves(spec):
            raise ValueError(
                f"Виджет {name!r} не обслуживает спецификацию {spec.kind!r}.")
        return widget


# ======================================================================
#  Встроенные виджеты
# ======================================================================
#
# Ровно те, для которых на первом этапе есть спецификации. Выбор одного и
# нескольких, последовательность и пары появятся вместе со своими
# спецификациями — реестр для этого не меняется.

TEXT_INPUT = Widget(
    name="text_input",
    title="Поле ввода",
    kinds=frozenset({"number", "text", "expression", "logic",
                     "equation"}),
    hint="Одна строка. Работает для любого одиночного ответа.",
)

FORMULA_INPUT = Widget(
    name="formula_input",
    title="Поле ввода с палитрой формул",
    kinds=frozenset({"expression", "equation"}),
    hint="То же поле, плюс палитра конструкций: дробь, корень, степень.",
)

CHOICE_ONE = Widget(
    name="choice_one",
    title="Выбор одного варианта",
    kinds=frozenset({"number", "text", "expression", "logic",
                     "equation"}),
    hint="Тест: верный ответ среди правдоподобных неверных. Варианты "
         "порождает сама спецификация — та же типизация, что даёт проверку.",
)

TEXT_AREA = Widget(
    name="text_area",
    title="Многострочное поле",
    kinds=frozenset({"output"}),
    hint="Несколько строк. Нужно там, где строки — часть ответа: вывод "
         "программы.",
)

SLOT_FIELDS = Widget(
    name="slot_fields",
    title="Отдельные поля",
    kinds=frozenset({"slots"}),
    hint="По полю на каждый слот. Порядок полей задаётся спецификацией.",
)

GRID_FIELDS = Widget(
    name="grid_fields",
    title="Сетка полей",
    kinds=frozenset({"slots"}),
    hint="Таблица полей по форме ответа: матрица, расписание, "
         "таблица истинности.",
)

SLOT_INLINE = Widget(
    name="slot_inline",
    title="Пропуски в тексте",
    kinds=frozenset({"slots"}),
    hint="Поля прямо в условии, на месте пропусков.",
)


def _register_builtin(registry: "WidgetRegistry") -> "WidgetRegistry":
    for widget in (TEXT_INPUT, FORMULA_INPUT, CHOICE_ONE, TEXT_AREA,
                   SLOT_FIELDS, GRID_FIELDS, SLOT_INLINE):
        registry.register(widget)
    return registry


registry = _register_builtin(WidgetRegistry())
"""Общий реестр приложения. Свои виджеты платформа дорегистрирует сама."""


def widgets_for(spec: AnswerSpec) -> List[Widget]:
    """Совместимые виджеты из общего реестра."""
    return registry.for_spec(spec)


def resolve_widget(spec: AnswerSpec, name: str = "") -> Optional[Widget]:
    """Виджет для спецификации из общего реестра."""
    return registry.resolve(spec, name)


__all__ = [
    "Widget", "WidgetRegistry", "registry", "widgets_for", "resolve_widget",
    "TEXT_INPUT", "FORMULA_INPUT", "CHOICE_ONE", "SLOT_FIELDS", "GRID_FIELDS",
    "SLOT_INLINE",
]
