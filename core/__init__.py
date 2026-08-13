"""
Публичный API ядра. Всё, что нужно модулям, — импортируется отсюда.

Пример:
    from core import TaskGenerator, StaticTask, TextBlock, FormulaBlock, Capability
"""

from .content import Block
from .blocks import (TextBlock, FormulaBlock, ImageBlock, CodeBlock,
                     TableBlock, block_from_dict, blocks_from_dicts)
from .dynamic_blocks import FillInTheBlankBlock, WordCorrectionBlock
from .task import Task, StaticTask, InteractiveTask, TurnResult
from .generator import (TaskGenerator, Capability, STATIC_DEFAULT,
                        CHECKABLE_DEFAULT)
from .answers import (AnswerSpec, CheckMode, ExpressionSpec, InputField,
                      NumberSpec, SlotsSpec, TextSpec, Tolerance,
                      ToleranceKind, Verdict)
from .widgets import Widget, widgets_for, resolve_widget
from .scenarios import (Scenario, SessionMode, Layer, Setting,
                        default_scenario)
from .attempts import AttemptRecord, attempts_from_session
from .interactive import (Question, Outcome, SpecSession,
                          session_from_task, session_from_tasks)
from .registry import GeneratorRegistry, GeneratorFactory
from .composites import GroupGenerator, TestGenerator
from .repository import Repository, Subject, Partition
from .word_stats import WordStat, WordStatsStore

__all__ = [
    # content
    "Block",
    "TextBlock", "FormulaBlock", "ImageBlock", "CodeBlock", "TableBlock",
    "block_from_dict", "blocks_from_dicts",
    "FillInTheBlankBlock", "WordCorrectionBlock",
    # tasks
    "Task", "StaticTask", "InteractiveTask", "TurnResult",
    # generator contract
    "TaskGenerator", "Capability", "STATIC_DEFAULT", "CHECKABLE_DEFAULT",
    # спецификация ответа
    "AnswerSpec", "CheckMode", "NumberSpec", "TextSpec", "ExpressionSpec",
    "SlotsSpec", "Tolerance", "ToleranceKind", "Verdict", "InputField",
    # виджеты и общая сессия
    "Widget", "widgets_for", "resolve_widget",
    # сценарий прохождения и попытка
    "Scenario", "SessionMode", "Layer", "Setting", "default_scenario",
    "AttemptRecord", "attempts_from_session",
    "Question", "Outcome", "SpecSession",
    "session_from_task", "session_from_tasks",
    # registry
    "GeneratorRegistry", "GeneratorFactory",
    # composites
    "GroupGenerator", "TestGenerator",
    # data
    "Repository", "Subject", "Partition",
    "WordStat", "WordStatsStore",
]
