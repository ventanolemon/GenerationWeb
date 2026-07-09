"""
Реестр нейропровайдеров (system_topology.md §5).

Абстракция «нечёткой задачи»: task_type → провайдер → структурированный
результат. Агенты петли — S1 (llm.generate_graph) и S5 (llm.critic) — те же
провайдеры, что будущие «нейросети для произношения»: добавление модели =
конфиг-запись, не архитектурная правка (калька с NodeRegistry).
"""

from .base import Provider, ProviderError, ProviderRegistry
from .mock import MockProvider
from .anthropic import AnthropicProvider

__all__ = [
    "Provider", "ProviderError", "ProviderRegistry",
    "MockProvider", "AnthropicProvider",
    "build_registry",
]

TASK_GENERATE = "llm.generate_graph"
TASK_CRITIC = "llm.critic"


def build_registry(backend: str) -> ProviderRegistry:
    """Собрать реестр по имени бэкенда ('mock' | 'anthropic')."""
    reg = ProviderRegistry()
    if backend == "anthropic":
        reg.register(AnthropicProvider(TASK_GENERATE))
        reg.register(AnthropicProvider(TASK_CRITIC))
    elif backend == "mock":
        reg.register(MockProvider(TASK_GENERATE))
        reg.register(MockProvider(TASK_CRITIC))
    else:
        raise ValueError(f"Неизвестный бэкенд провайдеров: {backend!r}")
    return reg
