"""
Сценарий прохождения — сущность, которой не было.

План, §4. Именно её отсутствие делает так, что «режимы» некуда положить.
Сегодня `attempts` не знает, в каком режиме была попытка: есть `user_id`,
`partition_id`, `assignment_id`, `payload`, `correct` — и всё. Одно и то же
задание в свободной тренировке и в зачёте пишется одинаково, и различить
их задним числом будет нечем.

Четыре группы параметров и их владельцы
---------------------------------------
| Группа                          | Владелец      | Когда действует     |
|---------------------------------|---------------|---------------------|
| параметры генерации             | заданию       | в статике и динамике|
| параметры приёма ответа         | спецификации  | только в динамике   |
| формат (виджет)                 | заданию       | только в динамике   |
| адаптация, лимиты, засчитывается| ПРОХОЖДЕНИЮ   | только в динамике   |

Здесь живёт четвёртая. Первые три уже лежат по своим местам: генерация — в
`generation_params` раздела, приём ответа — в `core.answers`, виджет — в
`core.widgets`.

Почему это отдельная сущность, а не поля сессии
----------------------------------------------
Четыре режима — это четыре разных **контракта о записи попытки**, а не
четыре набора настроек. «Тренировка без статистики» отличается от
«тренировки со статистикой» не значением параметра, а тем, что в первом
случае писать попытку нельзя вовсе. Свести это к флагу значит потерять
причину, по которой строки нет.

Что реализовано
---------------
Модель описывает все четыре режима — это дёшево сейчас и невосстановимо
потом. Достижимы из API пока два (см. `IMPLEMENTED_MODES`): ДЗ и зачёт
требуют дисциплины выдачи, которой ещё нет, и записывать попытки с
пометкой «зачёт», не обеспечив условий зачёта, — ровно та статистика,
которая тихо врёт.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional

from .answers import CheckMode


# ======================================================================
#  Режимы
# ======================================================================

class SessionMode(str, Enum):
    """Четыре контракта о записи попытки."""

    PRACTICE_FREE = "practice_free"
    """Тренировка без статистики: попытки не пишутся вовсе."""

    PRACTICE = "practice"
    """Тренировка со статистикой: попытки пишутся и считаются."""

    HOMEWORK = "homework"
    """Домашнее задание: пишется, считается, адаптация выключена."""

    EXAM = "exam"
    """Зачёт: одна попытка, ответ не показывается, адаптация запрещена."""


@dataclass(frozen=True)
class RecordingContract:
    """
    Что режим обещает про запись попытки и что разрешает менять.

    `records_attempts` и `counts_toward_stats` — разные вещи. Первое про
    то, появится ли строка; второе про то, попадёт ли она в успеваемость.
    Режим, который пишет, но не считает, понадобится для разбора ошибок:
    строка нужна, а на оценку влиять не должна.
    """

    records_attempts: bool
    counts_toward_stats: bool
    adaptation_allowed: bool
    defaults: Mapping[str, Any]


MAX_ATTEMPTS = "max_attempts"
CHECK_MODE = "check_mode"
REVEAL_ANSWER = "reveal_answer"
ADAPTIVE = "adaptive"

PARAMETERS = (MAX_ATTEMPTS, CHECK_MODE, REVEAL_ANSWER, ADAPTIVE)
"""
Набор параметров ОДИН на все режимы (§4).

Заводить «параметры преподавателя» и «параметры студента» как разные
сущности не нужно: различие не в наборе, а в том, что заперто.
"""


CONTRACTS: Mapping[SessionMode, RecordingContract] = {
    SessionMode.PRACTICE_FREE: RecordingContract(
        records_attempts=False,
        counts_toward_stats=False,
        adaptation_allowed=True,
        defaults={MAX_ATTEMPTS: 3, CHECK_MODE: CheckMode.SOFT,
                  REVEAL_ANSWER: True, ADAPTIVE: False},
    ),
    SessionMode.PRACTICE: RecordingContract(
        records_attempts=True,
        counts_toward_stats=True,
        adaptation_allowed=True,
        defaults={MAX_ATTEMPTS: 3, CHECK_MODE: CheckMode.SOFT,
                  REVEAL_ANSWER: True, ADAPTIVE: False},
    ),
    SessionMode.HOMEWORK: RecordingContract(
        records_attempts=True,
        counts_toward_stats=True,
        adaptation_allowed=False,
        defaults={MAX_ATTEMPTS: 2, CHECK_MODE: CheckMode.SOFT,
                  REVEAL_ANSWER: True, ADAPTIVE: False},
    ),
    SessionMode.EXAM: RecordingContract(
        records_attempts=True,
        counts_toward_stats=True,
        adaptation_allowed=False,
        defaults={MAX_ATTEMPTS: 1, CHECK_MODE: CheckMode.STRICT,
                  REVEAL_ANSWER: False, ADAPTIVE: False},
    ),
}


IMPLEMENTED_MODES = frozenset({SessionMode.PRACTICE_FREE, SessionMode.PRACTICE})
"""
Режимы, достижимые из API сегодня.

ДЗ и зачёт описаны в модели, но не открыты: им нужна дисциплина выдачи
(срок, единственная попытка, недоступность условия после сдачи), которой
ещё нет. Пометить попытку зачётом, не обеспечив условий зачёта, — значит
получить статистику, про которую нельзя сказать, что она означает.
"""


# ======================================================================
#  Каскад слоёв
# ======================================================================

class Layer(str, Enum):
    """Кто задал значение. Порядок — от умолчания к выбору студента."""

    TASK = "task"
    ASSIGNMENT = "assignment"
    STUDENT = "student"


_ORDER = {Layer.TASK: 0, Layer.ASSIGNMENT: 1, Layer.STUDENT: 2}


@dataclass(frozen=True)
class Setting:
    """
    Тройка «значение, кто задал, можно ли переопределить ниже» (§4).

    `locked` ставит только выдача. Это решение плана: замок — свойство
    выдачи, а не задания. Преподаватель, выдавая ДЗ, фиксирует нужное; в
    свободной тренировке те же параметры открыты студенту. Автор задания
    запирать не может — иначе он определял бы условия чужого занятия.
    """

    value: Any
    set_by: Layer
    locked: bool = False


class ScenarioError(ValueError):
    """Настройка противоречит контракту режима или замку выдачи."""


@dataclass(frozen=True)
class Scenario:
    """
    Сценарий прохождения: режим плюс разрешённые значения параметров.

    Сценарий задаёт ТОТ, КТО ВЫДАЁТ (решение плана), с необязательным
    умолчанием от автора задания. Одно и то же задание у разных
    преподавателей живёт по-разному, и это нормально.
    """

    mode: SessionMode
    settings: Mapping[str, Setting]

    # ---------- Сборка ----------

    @classmethod
    def for_mode(cls, mode: SessionMode) -> "Scenario":
        """Сценарий из умолчаний режима. Всё на слое задания, ничего не заперто."""
        contract = CONTRACTS[mode]
        return cls(
            mode=mode,
            settings={name: Setting(contract.defaults[name], Layer.TASK)
                      for name in PARAMETERS},
        )

    def with_layer(
        self,
        layer: Layer,
        values: Optional[Mapping[str, Any]] = None,
        *,
        lock: Iterable[str] = (),
    ) -> "Scenario":
        """
        Наложить слой поверх текущего сценария.

        Правила, каждое из которых защищает от своей ошибки:

          * значение, запертое слоем ВЫШЕ, менять нельзя — иначе замок не
            замок;
          * запирать может только выдача — см. `Setting`;
          * параметр вне `PARAMETERS` отвергается: опечатка в имени иначе
            молча ничего не сделает, и искать её будут в поведении;
          * адаптация в режиме, где она запрещена, отвергается ГРОМКО, а
            не приводится к False. Тихое приведение дало бы преподавателю
            уверенность, что адаптация включена, — а она нет.
        """
        values = dict(values or {})
        lock = frozenset(lock)

        unknown = (set(values) | lock) - set(PARAMETERS)
        if unknown:
            raise ScenarioError(
                f"Неизвестные параметры: {', '.join(sorted(unknown))}")

        if lock and layer is not Layer.ASSIGNMENT:
            raise ScenarioError(
                "Запирать параметры может только выдача: замок — её свойство.")

        if values.get(ADAPTIVE) and not CONTRACTS[self.mode].adaptation_allowed:
            raise ScenarioError(
                f"Режим {self.mode.value!r} не допускает адаптацию.")

        updated: Dict[str, Setting] = dict(self.settings)
        for name, value in values.items():
            current = updated[name]
            if current.locked and _ORDER[layer] > _ORDER[current.set_by]:
                raise ScenarioError(
                    f"Параметр {name!r} заперт слоем {current.set_by.value!r}.")
            updated[name] = Setting(value, layer,
                                    locked=name in lock)
        for name in lock:
            if name not in values:
                updated[name] = replace(updated[name], locked=True,
                                        set_by=layer)
        return Scenario(mode=self.mode, settings=updated)

    # ---------- Чтение ----------

    def value(self, name: str) -> Any:
        try:
            return self.settings[name].value
        except KeyError:
            raise ScenarioError(f"Неизвестный параметр: {name!r}") from None

    def is_locked(self, name: str) -> bool:
        return self.settings[name].locked

    def set_by(self, name: str) -> Layer:
        return self.settings[name].set_by

    def open_to_student(self) -> list:
        """Параметры, которые студент ещё может поменять."""
        return [n for n in PARAMETERS if not self.settings[n].locked]

    @property
    def contract(self) -> RecordingContract:
        return CONTRACTS[self.mode]

    @property
    def max_attempts(self) -> int:
        return int(self.value(MAX_ATTEMPTS))

    @property
    def check_mode(self) -> CheckMode:
        value = self.value(CHECK_MODE)
        return value if isinstance(value, CheckMode) else CheckMode(value)

    @property
    def reveal_answer(self) -> bool:
        return bool(self.value(REVEAL_ANSWER))

    @property
    def adaptive(self) -> bool:
        """
        Была ли адаптация. Помечает попытку (§4).

        Адаптация внутри сессии ломает сравнимость: если двум студентам
        выдавали разные последовательности разной сложности, «8 из 10» у
        них значит разное. Поэтому флаг едет в попытку, и аналитика
        обязана считать такие прохождения отдельно.
        """
        return bool(self.value(ADAPTIVE))

    # ---------- Сериализация ----------

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "settings": {
                name: {
                    "value": (s.value.value if isinstance(s.value, CheckMode)
                              else s.value),
                    "set_by": s.set_by.value,
                    "locked": s.locked,
                }
                for name, s in self.settings.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Scenario":
        mode = SessionMode(data["mode"])
        settings: Dict[str, Setting] = {}
        for name in PARAMETERS:
            raw = (data.get("settings") or {}).get(name)
            if raw is None:
                settings[name] = Setting(CONTRACTS[mode].defaults[name],
                                         Layer.TASK)
                continue
            value = raw["value"]
            if name == CHECK_MODE:
                value = CheckMode(value)
            settings[name] = Setting(value, Layer(raw.get("set_by", "task")),
                                     bool(raw.get("locked", False)))
        return cls(mode=mode, settings=settings)


def default_scenario() -> Scenario:
    """Сценарий по умолчанию: свободная тренировка без записи попыток."""
    return Scenario.for_mode(SessionMode.PRACTICE_FREE)


__all__ = [
    "SessionMode", "RecordingContract", "CONTRACTS", "IMPLEMENTED_MODES",
    "Layer", "Setting", "Scenario", "ScenarioError", "default_scenario",
    "PARAMETERS", "MAX_ATTEMPTS", "CHECK_MODE", "REVEAL_ANSWER", "ADAPTIVE",
]
