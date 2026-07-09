"""
MockProvider — детерминированный провайдер для тестов и dev без LLM-ключа.

Отдаёт заранее заданные («канные») ответы по очереди и записывает каждый
полученный payload в .calls — тесты петли проверяют по ним инварианты
контракта (например, что repair-сообщение содержит ДОСЛОВНЫЙ текст
GraphValidationError и ПОЛНЫЙ предыдущий граф, а критик никогда не видит
невалидный граф).

Без скрипта ведёт себя как «вежливая заглушка»: генератор возвращает
минимальный валидный граф-эхо описания, критик — accept. Это позволяет
поднять сервис локально вообще без ключей.
"""

from __future__ import annotations
import copy
import json
from typing import Callable, Optional

from .base import Provider, ProviderError


def _default_generate(payload: dict) -> dict:
    """Минимальный валидный граф: описание → статическое задание-эхо."""
    user = str(payload.get("user", ""))[:200] or "пустое описание"
    graph = {
        "version": 1,
        "nodes": [
            {"id": "cond", "type": "text",
             "params": {"text": f"Задание по запросу: {user}"}},
            {"id": "ans", "type": "text", "params": {"text": "Ответ: см. решение."}},
            {"id": "task", "type": "static_task"},
        ],
        "edges": [
            {"from": "cond:out", "to": "task:statement"},
            {"from": "ans:out", "to": "task:answer"},
        ],
        "meta": {},
    }
    return {"graph": graph, "text": json.dumps(graph, ensure_ascii=False)}


def _default_critic(payload: dict) -> dict:
    return {"verdict": "accept", "failures": [], "confidence": 0.9,
            "summary": "Mock-критик: принято без замечаний."}


class MockProvider(Provider):
    """Провайдер с очередью канных ответов (или дефолтным поведением)."""

    name = "mock"

    def __init__(self, task_type: str,
                 script: Optional[list] = None,
                 fail_times: int = 0) -> None:
        """
        script     — список ответов (dict) ЛИБО callable(payload)->dict,
                     выдаются по одному на вызов; исчерпание скрипта =
                     повтор последнего элемента (петля может звать больше раз).
        fail_times — первые N вызовов бросают ProviderError (тест ретраев).
        """
        self.task_type = task_type
        self.script = list(script) if script else []
        self._cursor = 0
        self._fail_left = fail_times
        self.calls: list[dict] = []

    def invoke(self, payload: dict) -> dict:
        self.calls.append(copy.deepcopy(payload))
        if self._fail_left > 0:
            self._fail_left -= 1
            raise ProviderError("mock: имитация отказа провайдера")
        if self.script:
            item = self.script[min(self._cursor, len(self.script) - 1)]
            self._cursor += 1
            if callable(item):
                return copy.deepcopy(item(payload))
            return copy.deepcopy(item)
        if self.task_type == "llm.critic":
            return _default_critic(payload)
        return _default_generate(payload)


def graph_response(graph: dict) -> dict:
    """Ответ mock-генератора из готового GraphSpec-словаря."""
    return {"graph": copy.deepcopy(graph),
            "text": json.dumps(graph, ensure_ascii=False)}
