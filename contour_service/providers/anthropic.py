"""
AnthropicProvider — боевой провайдер обеих LLM-задач петли.

Ключ — из окружения (ANTHROPIC_API_KEY), модель — CONTOUR_LLM_MODEL.
SDK импортируется лениво: юнит-тесты и dev без ключа не должны требовать
пакета anthropic. Сетевые вызовы в юнит-тестах ЗАПРЕЩЕНЫ — интеграционный
тест (contour_service/tests/) скипается без ключа.

Constrained-вывод: Messages API не даёт грамматического декодинга, поэтому
формат держат (а) жёсткая инструкция «только JSON», (б) prefill '{' в
ответе ассистента, (в) разбор с вырезанием možного markdown-заборчика.
Невалидный JSON — не отказ провайдера, а ошибка ГРАФА: она возвращается
loop'у текстом и уходит в repair-раунд (жжёт V), см. loop._parse_graph.
"""

from __future__ import annotations
import json
import os

from .base import Provider, ProviderError

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicProvider(Provider):
    """Провайдер llm.generate_graph / llm.critic через Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, task_type: str, model: str = "",
                 api_key: str = "", max_tokens: int = 8192) -> None:
        self.task_type = task_type
        self.model = model or os.environ.get("CONTOUR_LLM_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.max_tokens = max_tokens
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY не задан — провайдер anthropic недоступен "
                "(для dev/тестов используйте CONTOUR_PROVIDER=mock)."
            )
        try:
            import anthropic
        except ImportError:
            raise ProviderError(
                "Пакет anthropic не установлен (pip install anthropic)."
            )
        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def invoke(self, payload: dict) -> dict:
        client = self._ensure_client()
        system = str(payload.get("system", ""))
        if self.task_type == "llm.critic":
            user = json.dumps(payload.get("input", {}), ensure_ascii=False)
        else:
            user = str(payload.get("user", ""))
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[
                    {"role": "user", "content": user},
                    # prefill: заставляет ответ начаться с JSON-объекта
                    {"role": "assistant", "content": "{"},
                ],
            )
        except Exception as e:  # сетевые/квотные отказы SDK
            raise ProviderError(f"anthropic: {e}")

        text = "{" + "".join(
            block.text for block in resp.content if block.type == "text"
        )
        usage = {"input_tokens": getattr(resp.usage, "input_tokens", 0),
                 "output_tokens": getattr(resp.usage, "output_tokens", 0)}

        out: dict = {"text": _strip_fences(text), "usage": usage}
        try:
            parsed = json.loads(out["text"])
        except json.JSONDecodeError:
            parsed = None       # разберёт/забракует loop (ошибка графа, не транспорта)
        if self.task_type == "llm.critic":
            if isinstance(parsed, dict):
                out.update(parsed)
        else:
            out["graph"] = parsed if isinstance(parsed, dict) else None
        return out


def _strip_fences(text: str) -> str:
    """Убрать markdown-заборчик ```json ... ```, если модель его добавила."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()
