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
from typing import List, Optional

from .content import Block


class Task(ABC):
    """Маркерный базовый класс для типизации."""
    meta: dict


@dataclass
class StaticTask(Task):
    """
    Задание формата 'условие → ответ'.

    statement — список блоков условия
    answer    — список блоков ответа
    meta      — служебные данные (partition_id, исходные параметры и т.п.)
    """
    statement: List[Block]
    answer: List[Block]
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-сериализуемое представление задания для веб-API."""
        return {
            "type": "static",
            "statement": [b.to_dict() for b in self.statement],
            "answer": [b.to_dict() for b in self.answer],
            "meta": _safe_meta(self.meta),
        }


@dataclass
class TurnResult:
    """Результат одного хода в интерактивной сессии."""
    correct: bool
    feedback: List[Block]
    next_prompt: Optional[List[Block]]   # None — если сессия завершилась

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
        }


class InteractiveTask(Task, ABC):
    """
    Задание-сессия. Сам по себе обладает состоянием.

    Не сериализуется целиком. В веб-сервисе живёт через session_id,
    клиент получает только результат каждого хода — там уже работает
    TurnResult.to_dict().
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
