"""
core.graph — headless-движок визуального node-graph конструктора заданий.

Публичный API. Модуль НЕ зависит от PyQt6 на уровне импорта: его можно
использовать без GUI (тесты, будущее безоконное/потоковое исполнение).
Qt подгружается лениво только узлами-блоками контента в момент исполнения.

Пример:
    from core.graph import GraphSpec, GraphExecutor
    spec = GraphSpec.parse(config_dict)
    task = GraphExecutor(spec).run()        # → StaticTask
"""

from __future__ import annotations

from .conversions import conversion_table, find_converter
from .errors import GraphError, GraphValidationError, RetryGeneration
from .executor import GraphExecutor
from .node import ExecContext, Node, Port
from .port_types import PortType, is_compatible
from .registry import NodeRegistry
from .spec import EdgeSpec, GraphSpec, NodeSpec
from .document import DocEdge, DocNode, GraphDocument
from .nodes import DEFAULT_REGISTRY, build_default_registry

__all__ = [
    "PortType", "is_compatible", "find_converter", "conversion_table",
    "Node", "Port", "ExecContext",
    "NodeRegistry", "DEFAULT_REGISTRY", "build_default_registry",
    "GraphSpec", "NodeSpec", "EdgeSpec",
    "GraphDocument", "DocNode", "DocEdge",
    "GraphExecutor",
    "GraphError", "GraphValidationError", "RetryGeneration",
]
