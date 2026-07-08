"""
Исключения движка графа.

GraphError            — базовое.
GraphValidationError  — граф некорректен (неизвестный узел, висячий провод,
                        несовместимые типы, цикл, незаполненный обязательный вход).
                        Бросается при сборке/загрузке, до исполнения.
RetryGeneration       — узел сообщает: текущая попытка непригодна, нужно
                        пере-сгенерировать граф целиком (новые случайные значения).
                        Используется узлом constraint и формулой при числовой
                        ошибке — это аналог `continue` в fisic_generater.generate_task.
"""

from __future__ import annotations


class GraphError(Exception):
    """Базовая ошибка движка графа."""


class GraphValidationError(GraphError):
    """Граф структурно некорректен (обнаруживается до исполнения)."""


class RetryGeneration(GraphError):
    """Сигнал: пере-сгенерировать весь граф (whole-graph retry)."""
