"""
GraphSpec — сериализуемое описание графа (инвариант, от которого зависит всё).

Хранится в Partitions.generation_parametrs для разделов с constracted=4.
Формат:

  {
    "version": 1,
    "nodes": [ {"id": "n1", "type": "random_real", "params": {...}}, ... ],
    "edges": [ {"from": "n1:out", "to": "n3:v"}, ... ],
    "meta":  {"max_attempts": 100, "seed": null}
  }

Конечная точка провода кодируется как "node_id:port_name".
GraphSpec не исполняет граф и не знает о реестре узлов — только структура.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field

from .errors import GraphValidationError


@dataclass(frozen=True)
class NodeSpec:
    id: str
    type: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSpec:
    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass
class GraphSpec:
    nodes: list[NodeSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    version: int = 1

    # ---------- Загрузка ----------

    @classmethod
    def parse(cls, data: "str | dict | GraphSpec") -> "GraphSpec":
        if isinstance(data, GraphSpec):
            return data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                raise GraphValidationError(f"Граф не является валидным JSON: {e}")
        if not isinstance(data, dict):
            raise GraphValidationError("Описание графа должно быть dict или JSON-строкой.")

        nodes: list[NodeSpec] = []
        for raw in data.get("nodes", []):
            if not isinstance(raw, dict) or "id" not in raw or "type" not in raw:
                raise GraphValidationError(
                    f"Некорректное описание узла: {raw!r} (нужны 'id' и 'type')."
                )
            params = raw.get("params", {})
            if not isinstance(params, dict):
                raise GraphValidationError(
                    f"Узел {raw['id']!r}: 'params' должен быть объектом."
                )
            nodes.append(NodeSpec(id=str(raw["id"]), type=str(raw["type"]),
                                  params=dict(params)))

        edges: list[EdgeSpec] = []
        for raw in data.get("edges", []):
            if not isinstance(raw, dict) or "from" not in raw or "to" not in raw:
                raise GraphValidationError(
                    f"Некорректное описание ребра: {raw!r} (нужны 'from' и 'to')."
                )
            fn, fp = cls._split_endpoint(raw["from"])
            tn, tp = cls._split_endpoint(raw["to"])
            edges.append(EdgeSpec(fn, fp, tn, tp))

        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            raise GraphValidationError("'meta' должен быть объектом.")

        return cls(nodes=nodes, edges=edges, meta=dict(meta),
                   version=int(data.get("version", 1)))

    @staticmethod
    def _split_endpoint(raw: object) -> tuple[str, str]:
        if not isinstance(raw, str) or ":" not in raw:
            raise GraphValidationError(
                f"Конечная точка провода должна иметь вид 'node:port', получено {raw!r}."
            )
        node, port = raw.split(":", 1)
        node, port = node.strip(), port.strip()
        if not node or not port:
            raise GraphValidationError(f"Пустой node или port в {raw!r}.")
        return node, port

    # ---------- Выгрузка ----------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "nodes": [
                {"id": n.id, "type": n.type, "params": n.params} for n in self.nodes
            ],
            "edges": [
                {"from": f"{e.from_node}:{e.from_port}",
                 "to": f"{e.to_node}:{e.to_port}"}
                for e in self.edges
            ],
            "meta": self.meta,
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)
