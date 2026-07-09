"""
Базовый контракт нейропровайдера: task_type → invoke(payload) → dict.

payload и результат — словари; конкретные ключи фиксируются задачей:

  llm.generate_graph:
      вход  {"system": str, "user": str}
            (user — описание ЛИБО JSON repair-сообщения контракта §2)
      выход {"graph": dict | None, "text": str, "usage": {...}}
            graph — если провайдер сам распарсил JSON; иначе loop парсит text.

  llm.critic:
      вход  {"system": str, "input": {request, graph, probe, catalog_version}}
            (input — дословно I/O критика, critic_taxonomy.md §4)
      выход {"verdict": ..., "failures": [...], "confidence": float,
             "summary": str, "usage": {...}}

Ошибки транспорта/API — ProviderError: оркестратор ретраит и, исчерпав
ретраи, валит джобу в failed БЕЗ расхода бюджета V (contour_integration §5 —
недоступность LLM не является ошибкой графа).
"""

from __future__ import annotations
from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Отказ провайдера (сеть, ключ, квота) — не ошибка генерируемого графа."""


class Provider(ABC):
    """Один провайдер одной нечёткой задачи."""

    task_type: str = ""
    name: str = "provider"

    @abstractmethod
    def invoke(self, payload: dict) -> dict:
        """Выполнить задачу. Бросает ProviderError при отказе транспорта."""


class ProviderRegistry:
    """task_type → Provider. Одна абстракция на агентов петли и ML-API."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if not provider.task_type:
            raise ValueError("У провайдера пустой task_type.")
        self._providers[provider.task_type] = provider

    def get(self, task_type: str) -> Provider:
        try:
            return self._providers[task_type]
        except KeyError:
            raise ProviderError(f"Нет провайдера для задачи {task_type!r}.")

    def has(self, task_type: str) -> bool:
        return task_type in self._providers
