"""
Чистая логика graph-API: каталог узлов, валидация, предпросмотр.

Реализует docs/architecture/graph_editor_api_contract.md §2. Функции здесь НЕ
знают про HTTP — их вызывают и тонкий роутер generator_service (веб-редактор),
и будущий contour_service (S0 заземление = каталог, S2 сборка = валидация).
Это единственный источник истины по формату графа для обоих канвасов (Qt/веб):
проводная форма — ровно GraphSpec.to_dict().

fastapi в целевом окружении может отсутствовать — поэтому вся логика лежит в
этом headless-модуле (core), а роутер лишь адаптирует HTTP↔эти функции.
"""

from __future__ import annotations
import hashlib
from typing import Optional

from .graph.conversions import conversion_table
from .graph.errors import GraphError, GraphValidationError
from .graph.executor import GraphExecutor
from .graph.nodes import DEFAULT_REGISTRY
from .graph.port_types import PortType
from .graph.registry import NodeRegistry
from .graph.spec import GraphSpec
from . import graph_probe


def catalog_version(registry: NodeRegistry = DEFAULT_REGISTRY) -> str:
    """Хэш выгрузки каталога = sha256 отсортированных type_id (первые 16 hex).
    Совпадает с provenance-полем корпуса (training_example_schema.json)."""
    payload = ",".join(sorted(registry.type_ids()))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _ports(port_objs) -> list[dict]:
    return [{"name": p.name, "type": p.type.value, "required": p.required}
            for p in port_objs]


def build_catalog(registry: NodeRegistry = DEFAULT_REGISTRY) -> dict:
    """
    Каталог для палитры и заземления: version, port_types, conversions, nodes.
    Порты берём с классов (статический шаблон); динамические узлы (var_dict,
    block_list, туннели) клиент доопределяет по params_schema — как десктоп.
    """
    nodes = []
    for cls in registry:
        nodes.append({
            "type_id": cls.type_id,
            "category": cls.category,
            "display_name": cls.display_name or cls.type_id,
            "description": cls.description,
            "inputs": _ports(cls.INPUTS),
            "outputs": _ports(cls.OUTPUTS),
            "params_schema": cls.PARAMS_SCHEMA,
        })
    nodes.sort(key=lambda n: (n["category"], n["type_id"]))
    return {
        "catalog_version": catalog_version(registry),
        "port_types": [{"id": t.value} for t in PortType],
        "conversions": [
            {"from": src, "to": dst, "via": via}
            for (src, dst, via) in conversion_table()
        ],
        "nodes": nodes,
    }


def validate_graph(spec_dict: dict) -> dict:
    """
    Обёртка над сборкой GraphExecutor. Возвращает {ok, errors, result_node,
    catalog_version}. errors — ДОСЛОВНЫЕ тексты GraphValidationError (они уже
    называют узлы по id — та же петля исправления, что в контуре).
    """
    try:
        executor = GraphExecutor(GraphSpec.parse(spec_dict))
    except GraphValidationError as e:
        return {"ok": False, "errors": [str(e)], "result_node": None,
                "catalog_version": catalog_version()}
    result_node = executor.result[0] if executor.result else None
    return {"ok": True, "errors": [], "result_node": result_node,
            "catalog_version": catalog_version()}


def _blocks_json(task, field: str) -> list[dict]:
    """Блоки условия/ответа задания как список BlockJSON (Block.to_dict).
    Для интерактивных заданий поле statement — синтетический текстовый блок
    из начального промпта, answer — пуст."""
    blocks = getattr(task, field, None)
    if blocks is not None:
        return [b.to_dict() for b in blocks]
    if field == "statement":
        stmt, _ = graph_probe.task_plain(task)
        return [{"type": "text", "content": stmt}]
    return []


def preview_graph(spec_dict: dict, seeds: Optional[list[int]] = None,
                  max_seeds: int = 8) -> dict:
    """
    Исполнить граф на seeds и вернуть блоки условия/ответа (BlockJSON) —
    рендерятся существующим frontend BlockRenderer. Тот же probe-механизм,
    что у контура, но с тяжёлыми блоками для UI (probe_graph — без них).
    """
    seeds = (seeds if seeds is not None else graph_probe.DEFAULT_SEEDS)[:max_seeds]
    try:
        executor = GraphExecutor(GraphSpec.parse(spec_dict))
    except GraphValidationError as e:
        return {"ok": False, "errors": [str(e)], "runs": []}

    runs = []
    for seed in seeds:
        res = graph_probe.run_once(executor, seed)
        if res.task is None or res.error is not None:
            runs.append({"seed": seed, "statement": [], "answer": [],
                         "attempts": res.attempts, "wall_ms": round(res.wall_ms, 2),
                         "error": res.error or "не удалось собрать задание"})
            continue
        try:
            statement = _blocks_json(res.task, "statement")
            answer = _blocks_json(res.task, "answer")
            err = None
        except Exception as e:  # рендер блока упал — не роняем весь предпросмотр
            statement, answer, err = [], [], f"ошибка рендера блока: {e}"
        runs.append({"seed": seed, "statement": statement, "answer": answer,
                     "attempts": res.attempts, "wall_ms": round(res.wall_ms, 2),
                     "error": err})
    return {"ok": True, "errors": [], "runs": runs}
