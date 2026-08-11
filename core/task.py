"""
Task — единица результата генерации.

Существует в двух формах:
  * StaticTask      — готовое задание формата 'условие → ответ'
  * InteractiveTask — сессия с собственным циклом 'спроси → проверь → продолжи'

Любой генератор возвращает один из этих типов.

Веб-сериализация:
  StaticTask.to_dict()  — самостоятельный JSON-объект задания.
  TurnResult.to_dict()  — JSON-объект для ответа на /interactive/submit.
  InteractiveTask       — не сериализуется целиком, на стороне веба
                          живёт через session_id; initial_prompt() и
                          submit() возвращают блоки, которые сами умеют
                          в to_dict().
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from .content import Block

if TYPE_CHECKING:
    from .answers import AnswerSpec


class Task(ABC):
    """Маркерный базовый класс для типизации."""
    meta: dict


@dataclass
class StaticTask(Task):
    """
    Задание формата 'условие → ответ'.

    statement   — список блоков условия
    answer      — список блоков ответа (уже отрендеренных для глаз)
    answer_spec — необязательная проверяемая форма того же ответа
    meta        — служебные данные (partition_id, исходные параметры и т.п.)

    Про `answer_spec` — это точка обогащения из §1 плана. `answer` был и
    остаётся отрендеренным: `FormulaBlock` с латехом, `TextBlock` с
    «увеличится вдвое». Сверить с ним ввод пользователя нельзя, рендеринг
    односторонний и теряющий.

    Поэтому проверяемая форма ответа кладётся рядом, а не вместо: старый
    показ продолжает работать без единой правки, а там, где генератор
    заполнил спецификацию, задание становится интерактивным. Заменить
    `answer` спецификацией сразу означало бы переписать все генераторы
    одним движением — ровно то, чего план избегает.
    """
    statement: List[Block]
    answer: List[Block]
    meta: dict = field(default_factory=dict)
    answer_spec: Optional["AnswerSpec"] = None

    @property
    def is_checkable(self) -> bool:
        """
        Можно ли проверять ответ автоматически.

        Это и есть «интерактив стал вычислимым» из §1: свойство не
        объявляется генератором, а следует из того, есть ли чем
        проверять. Флаг `Capability.CHECKABLE` — отдельная вещь: он про
        витрину, которой нужен ответ ДО генерации задания.
        """
        return self.answer_spec is not None

    def to_dict(self) -> dict:
        """JSON-сериализуемое представление задания для веб-API."""
        out = {
            "type": "static",
            "statement": [b.to_dict() for b in self.statement],
            "answer": [b.to_dict() for b in self.answer],
            "meta": _safe_meta(self.meta),
            "is_checkable": self.is_checkable,
        }
        if self.answer_spec is not None:
            from .widgets import widgets_for
            out["answer_spec"] = self.answer_spec.to_dict()
            # Совместимые виджеты уезжают вместе со спецификацией: выбор
            # формата — это выбор ИЗ СОВМЕСТИМЫХ (§3), и вычислять их
            # заново на каждой платформе значило бы иметь три расходящихся
            # представления о совместимости.
            out["widgets"] = [w.to_dict() for w in widgets_for(self.answer_spec)]
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "StaticTask":
        """
        Собрать задание обратно из `to_dict()`.

        Нужно там, где задание пересекает границу процесса: исполнение
        графа вынесено в отдельный рабочий процесс без доступа к БД, и
        результат возвращается словарём.

        `widgets` при разборе игнорируются: они вычисляются из
        спецификации, и восстанавливать их из словаря значило бы завести
        второй источник правды о совместимости.
        """
        from .answers import AnswerSpec
        from .blocks import blocks_from_dicts
        spec = data.get("answer_spec")
        return cls(
            statement=blocks_from_dicts(data.get("statement")),
            answer=blocks_from_dicts(data.get("answer")),
            meta=dict(data.get("meta") or {}),
            answer_spec=AnswerSpec.from_dict(spec) if spec else None,
        )


@dataclass
class TurnResult:
    """Результат одного хода в интерактивной сессии."""
    correct: bool
    feedback: List[Block]
    next_prompt: Optional[List[Block]]   # None — если сессия завершилась

    same_question: bool = False
    """
    Вопрос НЕ закрыт: ответ неверен, но попытки остались.

    Клиенту это нужно, чтобы не стирать набранное. Отличить «та же
    попытка» от «следующий вопрос» по одному лишь `next_prompt` нельзя:
    у соседних вопросов условие бывает одинаковым, а у повторной попытки
    оно то же самое по определению.

    Сервер это и так знает — ровно на этом различии он решает, писать ли
    итог в статистику, — и не отдавал наружу. Цена молчания видна на
    холсте схемы: после неверного ответа собранная руками схема
    исчезала, и её приходилось строить заново.

    Умолчание `False` выбрано так, чтобы старый клиент вёл себя как
    прежде: не знает поля — чистит форму на каждом ходу.
    """

    def to_dict(self) -> dict:
        """JSON-сериализуемое представление результата хода для веб-API."""
        return {
            "correct": self.correct,
            "feedback": [b.to_dict() for b in self.feedback],
            "next_prompt": (
                [b.to_dict() for b in self.next_prompt]
                if self.next_prompt is not None else None
            ),
            "is_finished": self.next_prompt is None,
            "same_question": self.same_question,
        }


class InteractiveTask(Task, ABC):
    """
    Задание-сессия. Сам по себе обладает состоянием.

    Не сериализуется целиком: объект держит ссылки на хранилища и генератор.
    В веб-сервисе живёт через session_id, клиент получает только результат
    каждого хода — там уже работает TurnResult.to_dict().

    ОДНАКО состояние сессии — данные, и его можно снять и вернуть отдельно
    от объекта: `state()` / `restore()`. Это нужно, чтобы сессия пережила
    перезапуск сервиса и работала за балансировщиком: другой процесс
    пересоберёт задание из партиции генератором и вернёт ему состояние.
    Пара необязательна — `state()` по умолчанию возвращает None, что честно
    значит «моё состояние не снимается»; такая сессия просто живёт в памяти
    одного процесса, как и раньше.
    """

    meta: dict = {}

    @abstractmethod
    def initial_prompt(self) -> List[Block]:
        """Что показать пользователю в самом начале."""

    @abstractmethod
    def submit(self, user_input: str) -> TurnResult:
        """Принять ответ пользователя и вернуть результат хода."""

    @abstractmethod
    def is_finished(self) -> bool:
        """Закончилась ли сессия."""

    def state(self) -> Optional[dict]:
        """
        JSON-сериализуемый снимок прогресса или None, если тип задания
        снимать состояние не умеет.

        Снимать нужно ровно то, что нельзя восстановить из партиции:
        прогресс пользователя. Ссылки на хранилища, конфиг генератора и
        кеши, перечитываемые при сборке, в снимок не входят — их вернёт
        генератор, а дублирование только рассинхронизировало бы их с БД.
        """
        return None

    def restore(self, state: dict) -> None:
        """Вернуть снимок, снятый `state()`, в свежесобранное задание."""
        raise NotImplementedError(
            f"{type(self).__name__} не умеет restore(); "
            f"state() должен возвращать None.")


def _safe_meta(meta: dict) -> dict:
    """
    Защитная фильтрация meta: отбрасываем поля, которые не пройдут через
    json.dumps без кастомного encoder. Это редкий случай, но если
    кто-то положит туда PIL.Image или функцию — мы это аккуратно
    проглотим, а не уроним весь запрос.
    """
    out: dict = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = list(v) if all(
                isinstance(x, (str, int, float, bool, type(None)))
                for x in v
            ) else [str(x) for x in v]
        elif isinstance(v, dict):
            out[k] = _safe_meta(v)
        else:
            out[k] = str(v)
    return out
