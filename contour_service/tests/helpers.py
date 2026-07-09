"""
Общие фикстуры тестов контура: sys.path монорепо, in-memory очередь/корпус,
эталонные графы seed-rep-001 (битый и починенный).

Битый/починенный графы ВОСПРОИЗВОДЯТ
Generator/docs/training_seed_examples/seed-rep-001-broken-wire.json дословно
(они встроены сюда, чтобы тесты GenerationWeb были самодостаточны: golden-файл
живёт в git репозитория Generator — граница «git — эталоны, БД — поток» из
rbac_and_data_model.md §5). Ошибка провода s:res — та же, что в примере.
"""

from __future__ import annotations
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from contour_service.config import ContourConfig                    # noqa: E402
from contour_service.corpus import CorpusStore                      # noqa: E402
from contour_service.db import apply_migrations, connect_sqlite     # noqa: E402
from contour_service.loop import LoopDeps                           # noqa: E402
from contour_service.providers import (                             # noqa: E402
    MockProvider, ProviderRegistry, TASK_CRITIC, TASK_GENERATE,
)
from contour_service.queue import SqliteJobQueue                    # noqa: E402


def make_env(generator_script=None, critic_script=None,
             config: ContourConfig | None = None):
    """(queue, deps, conn, gen_mock, critic_mock) поверх in-memory SQLite."""
    conn = connect_sqlite(":memory:")
    apply_migrations(conn)
    queue = SqliteJobQueue(conn)
    gen = MockProvider(TASK_GENERATE, generator_script)
    critic = MockProvider(TASK_CRITIC, critic_script)
    reg = ProviderRegistry()
    reg.register(gen)
    reg.register(critic)
    deps = LoopDeps(providers=reg, corpus=CorpusStore(conn),
                    config=config or ContourConfig())
    return queue, deps, conn, gen, critic


# ---------- seed-rep-001: кинематика, битый провод s:res ----------

_NODES = [
    {"id": "v", "type": "random_natural", "params": {"min": 2, "max": 15}},
    {"id": "t", "type": "random_natural", "params": {"min": 3, "max": 20}},
    {"id": "s", "type": "formula", "params": {"expr": "v * t"}},
    {"id": "cond", "type": "text",
     "params": {"text": "Тело движется равномерно со скоростью #v# м/с "
                        "в течение #t# с. Найдите путь."}},
    {"id": "ans", "type": "text", "params": {"text": "S = #S# м"}},
    {"id": "task", "type": "static_task"},
]

_EDGES_COMMON = [
    {"from": "v:out", "to": "s:v"},
    {"from": "t:out", "to": "s:t"},
    {"from": "v:out", "to": "cond:v"},
    {"from": "t:out", "to": "cond:t"},
    {"from": "cond:out", "to": "task:statement"},
    {"from": "ans:out", "to": "task:answer"},
]

# Битая попытка: формула отдаёт выход out, а провод тянут из несуществующего s:res.
SEED_REP_001_BROKEN = {
    "version": 1,
    "nodes": _NODES,
    "edges": _EDGES_COMMON + [{"from": "s:res", "to": "ans:S"}],
    "meta": {},
}

SEED_REP_001_FIXED = {
    "version": 1,
    "nodes": _NODES,
    "edges": _EDGES_COMMON + [{"from": "s:out", "to": "ans:S"}],
    "meta": {},
}

SEED_REP_001_DESCRIPTION = (
    "Задача по кинематике: равномерное движение, скорость 2–15 м/с, "
    "время 3–20 с, найти пройденный путь."
)

# Дословный текст GraphValidationError движка для битого провода —
# то, что ОБЯЗАНО уйти в repair-сообщение без пересказа.
SEED_REP_001_ERROR = "Провод ссылается на несуществующий выход s:res."
