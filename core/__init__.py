"""
Публичный API ядра. Всё, что нужно модулям, — импортируется отсюда.

Пример:
    from core import TaskGenerator, StaticTask, TextBlock, FormulaBlock, Capability
"""

from .content import Block
from .blocks import TextBlock, FormulaBlock, ImageBlock, CodeBlock, TableBlock
from .dynamic_blocks import FillInTheBlankBlock, WordCorrectionBlock
from .task import Task, StaticTask, InteractiveTask, TurnResult
from .generator import TaskGenerator, Capability, STATIC_DEFAULT
from .registry import GeneratorRegistry, GeneratorFactory
from .composites import GroupGenerator, TestGenerator
from .repository import Repository, Subject, Partition
from .word_stats import WordStat, WordStatsStore

__all__ = [
    # content
    "Block",
    "TextBlock", "FormulaBlock", "ImageBlock", "CodeBlock", "TableBlock",
    "FillInTheBlankBlock", "WordCorrectionBlock",
    # tasks
    "Task", "StaticTask", "InteractiveTask", "TurnResult",
    # generator contract
    "TaskGenerator", "Capability", "STATIC_DEFAULT",
    # registry
    "GeneratorRegistry", "GeneratorFactory",
    # composites
    "GroupGenerator", "TestGenerator",
    # data
    "Repository", "Subject", "Partition",
    "WordStat", "WordStatsStore",
]
