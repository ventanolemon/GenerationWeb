"""
GraphDocument — редактируемая модель графа для визуального редактора.

ЧИСТЫЙ модуль (без Qt): хранит узлы с экранными позициями, рёбра и meta,
сериализуется в тот же GraphSpec-словарь, что исполняет движок. Это позволяет
покрыть логику холста (добавление/удаление узлов и проводов, обрезку висячих
рёбер, round-trip) headless-тестами, не поднимая PyQt6.

Позиции узлов хранятся в meta["layout"] = {node_id: [x, y]} — движок их
игнорирует, формат узла (id/type/params) остаётся прежним.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from .errors import GraphError, GraphValidationError
from .node import Port
from .nodes import DEFAULT_REGISTRY
from .port_types import PortType
from .registry import NodeRegistry
from .spec import GraphSpec


@dataclass
class DocNode:
    """Узел на холсте: тип, параметры, позиция."""
    id: str
    type: str
    params: dict = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0


@dataclass
class DocEdge:
    """Провод: выход одного узла → вход другого."""
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.from_node, self.from_port, self.to_node, self.to_port)


def _edge_key(src_node: str, src_port: str, dst_node: str, dst_port: str) -> str:
    """
    Ключ ребра для meta-хранилищ, завязанных на конкретный провод (bends).
    Не индекс в списке DocEdge: индексы едут при вставке/удалении рёбер, и
    данные, привязанные к позиции в списке, молча уехали бы на чужой провод.
    """
    return f"{src_node}:{src_port}->{dst_node}:{dst_port}"


class GraphDocument:
    """Изменяемый граф (узлы + рёбра + meta). Источник правды для редактора."""

    def __init__(self, registry: NodeRegistry | None = None):
        self.registry = registry or DEFAULT_REGISTRY
        self.nodes: dict[str, DocNode] = {}
        self.edges: list[DocEdge] = []
        self.meta: dict = {"max_attempts": 100, "seed": None}
        # Документ — вложенное тело (цикл/map/ветвь case)? Узлы-задания (TASK)
        # там запрещены; редактор помечает их и не даёт добавлять новые.
        self.is_subgraph: bool = False

    # ---------- Идентификаторы ----------

    def unique_id(self, type_id: str) -> str:
        i = 1
        while f"{type_id}_{i}" in self.nodes:
            i += 1
        return f"{type_id}_{i}"

    # ---------- Мутации узлов ----------

    def add_node(self, type_id: str, params: dict | None = None,
                 x: float = 0.0, y: float = 0.0,
                 node_id: str | None = None) -> DocNode:
        if not self.registry.has(type_id):
            raise GraphValidationError(f"Неизвестный тип узла: {type_id!r}")
        nid = node_id or self.unique_id(type_id)
        if nid in self.nodes:
            raise GraphValidationError(f"Узел с id {nid!r} уже существует.")
        node = DocNode(id=nid, type=type_id, params=dict(params or {}),
                       x=float(x), y=float(y))
        self.nodes[nid] = node
        return node

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges
                      if e.from_node != node_id and e.to_node != node_id]
        # Перегибы и подписи рёбер узла — вслед за самими рёбрами: иначе
        # осиротевший ключ переживёт узел и всплывёт, если id переиспользуют.
        self._drop_orphan_edge_meta()
        self.set_node_expanded(node_id, False)

    def set_params(self, node_id: str, params: dict) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].params = dict(params)

    def set_pos(self, node_id: str, x: float, y: float) -> None:
        node = self.nodes.get(node_id)
        if node is not None:
            node.x, node.y = float(x), float(y)

    # ---------- Мутации рёбер ----------

    def add_edge(self, from_node: str, from_port: str,
                 to_node: str, to_port: str) -> DocEdge:
        # Один провод на вход: удаляем существующий в (to_node, to_port).
        self.edges = [e for e in self.edges
                      if not (e.to_node == to_node and e.to_port == to_port)]
        edge = DocEdge(from_node, from_port, to_node, to_port)
        self.edges.append(edge)
        # Вытесненный провод уносит свои перегибы и подпись: они были
        # сделаны про него, а не про вход, в который он приходил.
        self._drop_orphan_edge_meta()
        # Новый провод мог подключить типизированный вход к источнику другого
        # типа — протолкнуть тип по цепочке (см. propagate_types_from_node).
        self.propagate_types_from_node(from_node)
        return edge

    def remove_edge(self, edge: DocEdge) -> None:
        self.edges = [e for e in self.edges if e.as_tuple() != edge.as_tuple()]
        # Перегиб и подпись без ребра — мусор, который никогда не
        # отрисуется заново.
        self._drop_orphan_edge_meta()

    def edges_for(self, node_id: str) -> list[DocEdge]:
        return [e for e in self.edges
                if e.from_node == node_id or e.to_node == node_id]

    # ---------- Порты ----------

    def ports(self, node_id: str) -> tuple[list[Port], list[Port]]:
        node = self.nodes[node_id]
        return self.safe_ports(node.type, node.params)

    def safe_ports(self, type_id: str, params: dict) -> tuple[list[Port], list[Port]]:
        """
        Порты узла по его параметрам. Для динамических узлов (var_dict/block_list)
        порты зависят от params; если params ещё некорректны — откатываемся к
        статическому шаблону класса, чтобы узел всё равно отрисовался.
        """
        cls = self.registry.get(type_id)
        try:
            inst = cls("_probe", dict(params or {}))
            return list(inst.input_ports()), list(inst.output_ports())
        except Exception:
            return list(cls.INPUTS), list(cls.OUTPUTS)

    # ---------- Проброс типов по типизированным узлам ----------
    #
    # Часть узлов выбирает тип своих портов параметром-перечислением
    # (Node.TYPE_PARAM/TYPE_PARAM_MAP — list_new.elem_type, select.value_type,
    # input_var.type и т.п., см. node.py). Без проброса смена такого
    # параметра на одном блоке требует вручную поправить elem_type на КАЖДОМ
    # подключённом узле — то, о чём и был вопрос. Правила:
    #
    #   Правило A (обычный скалярный порт): провод несёт порт src.type;
    #   если порт назначения — из type_param_ports() узла-приёмника (то есть
    #   САМ управляется TYPE_PARAM), приёмник ретайпится под src.type, если
    #   тот вообще выразим в его TYPE_PARAM_MAP.
    #
    #   Правило B (граница LIST): PortType.LIST не несёт тип элемента на
    #   проводе (list[Any]), поэтому список_new.out → list_get.list не ловится
    #   правилом A (list_get.list не входит в его type_param_ports() — оттуда
    #   типизирован только "out"). Здесь элементный тип синхронизируется
    #   НАПРЯМУЮ по строковому ключу TYPE_PARAM между двумя типизированными
    #   LIST-узлами, раз уж это концептуально «тот же список».
    #
    # После ретайпа продолжаем с новых выходов приёмника — так смена одного
    # источника расходится по всей цепочке потребителей автоматически.

    def _type_param_ports(self, node: DocNode) -> set[str]:
        cls = self.registry.get(node.type)
        if not getattr(cls, "TYPE_PARAM", None):
            return set()
        try:
            inst = cls("_probe", dict(node.params or {}))
            return inst.type_param_ports()
        except Exception:
            return set()

    def _propagate_edge(self, src_node: DocNode, src_port: Port,
                        dst_node: DocNode, dst_port: Port,
                        visited: set) -> set[str]:
        dst_cls = self.registry.get(dst_node.type)
        dst_tp = getattr(dst_cls, "TYPE_PARAM", None)
        if not dst_tp:
            return set()

        changed = False
        if dst_port.name in self._type_param_ports(dst_node):
            # Правило A.
            key = dst_cls.type_param_key_for(src_port.type)
            if key is not None and dst_node.params.get(dst_tp) != key:
                dst_node.params[dst_tp] = key
                changed = True
        elif dst_port.type is PortType.LIST:
            # Правило B: проброс elem_type через границу LIST, если оба конца
            # — типизированные списковые узлы с совпадающим по имени ключом.
            src_cls = self.registry.get(src_node.type)
            src_tp = getattr(src_cls, "TYPE_PARAM", None)
            if src_tp and src_port.type is PortType.LIST:
                src_key = src_node.params.get(src_tp)
                if src_key in dst_cls.TYPE_PARAM_MAP and \
                        dst_node.params.get(dst_tp) != src_key:
                    dst_node.params[dst_tp] = src_key
                    changed = True

        if not changed:
            return set()
        result = {dst_node.id}
        _, dst_outs = self.safe_ports(dst_node.type, dst_node.params)
        for p in dst_outs:
            result |= self._propagate_from_output(dst_node.id, p.name, visited)
        return result

    def _propagate_from_output(self, node_id: str, port_name: str,
                               visited: set) -> set[str]:
        key = (node_id, port_name)
        if key in visited:
            return set()          # защита от зацикливания при странном графе
        visited.add(key)

        src_node = self.nodes.get(node_id)
        if src_node is None:
            return set()
        _, src_outs = self.safe_ports(src_node.type, src_node.params)
        src_port = next((p for p in src_outs if p.name == port_name), None)
        if src_port is None:
            return set()

        changed: set[str] = set()
        for e in self.edges:
            if e.from_node != node_id or e.from_port != port_name:
                continue
            dst_node = self.nodes.get(e.to_node)
            if dst_node is None:
                continue
            dst_ins, _ = self.safe_ports(dst_node.type, dst_node.params)
            dst_port = next((p for p in dst_ins if p.name == e.to_port), None)
            if dst_port is None:
                continue
            changed |= self._propagate_edge(src_node, src_port, dst_node, dst_port, visited)
        return changed

    def propagate_types_from_node(self, node_id: str) -> set[str]:
        """
        Протолкнуть типы со всех выходов node_id по подключённым проводам —
        после того, как параметры node_id изменились (добавлен провод из его
        выхода, или пользователь сам поменял elem_type/value_type/type в
        инспекторе). Возвращает id узлов, чьи параметры реально изменились
        (редактор перестраивает их порты и, если нужно, обрезает повисшие
        провода — прежний тип мог перестать совпадать с портом дальше по цепи).

        node_id САМ не обязан быть типизированным (TYPE_PARAM) — обычный
        expr_const/formula тоже ретайпит подключённый governed-порт
        назначения (правило A решается со стороны ПРИЁМНИКА, см.
        _propagate_edge); TYPE_PARAM у источника нужен только правилу B
        (проброс elem_type через границу LIST).
        """
        node = self.nodes.get(node_id)
        if node is None:
            return set()
        _, outs = self.safe_ports(node.type, node.params)
        visited: set = set()
        changed: set[str] = set()
        for p in outs:
            changed |= self._propagate_from_output(node_id, p.name, visited)
        return changed

    # ---------- Сводка узла (текст на теле узла) ----------

    def node_summary(self, node_id: str) -> str:
        """Однострочная сводка содержания узла (Node.summary) для холста.
        Безопасна к некорректным params — как safe_ports: не отрисовалось,
        значит пусто, узел всё равно рисуется."""
        node = self.nodes.get(node_id)
        if node is None:
            return ""
        cls = self.registry.get(node.type)
        try:
            return str(cls("_probe", dict(node.params or {})).summary() or "")
        except Exception:
            return ""

    def prune_invalid_edges(self) -> None:
        """Удалить рёбра, ссылающиеся на порты, которых больше нет."""
        valid_in: dict[str, set[str]] = {}
        valid_out: dict[str, set[str]] = {}
        for nid, node in self.nodes.items():
            ins, outs = self.safe_ports(node.type, node.params)
            valid_in[nid] = {p.name for p in ins}
            valid_out[nid] = {p.name for p in outs}
        self.edges = [
            e for e in self.edges
            if e.from_node in valid_out and e.from_port in valid_out[e.from_node]
            and e.to_node in valid_in and e.to_port in valid_in[e.to_node]
        ]
        self._drop_orphan_edge_meta()

    # ---------- Сериализация ----------

    def to_spec_dict(self) -> dict:
        meta = dict(self.meta)
        meta["layout"] = {nid: [n.x, n.y] for nid, n in self.nodes.items()}
        return {
            "version": 1,
            "nodes": [
                {"id": n.id, "type": n.type, "params": n.params}
                for n in self.nodes.values()
            ],
            "edges": [
                {"from": f"{e.from_node}:{e.from_port}",
                 "to": f"{e.to_node}:{e.to_port}"}
                for e in self.edges
            ],
            "meta": meta,
        }

    def to_spec(self) -> GraphSpec:
        return GraphSpec.parse(self.to_spec_dict())

    @classmethod
    def from_spec_dict(cls, data: "str | dict | GraphSpec",
                       registry: NodeRegistry | None = None) -> "GraphDocument":
        spec = GraphSpec.parse(data)
        doc = cls(registry=registry)

        raw_layout = spec.meta.get("layout")
        layout = raw_layout if isinstance(raw_layout, dict) else {}

        doc.meta = {k: v for k, v in spec.meta.items() if k != "layout"}
        doc.meta.setdefault("max_attempts", 100)
        doc.meta.setdefault("seed", None)

        for i, ns in enumerate(spec.nodes):
            pos = layout.get(ns.id)
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                try:
                    x, y = float(pos[0]), float(pos[1])
                except (TypeError, ValueError):
                    x, y = cls.auto_pos(i)
            else:
                x, y = cls.auto_pos(i)
            doc.add_node(ns.type, ns.params, x, y, node_id=ns.id)

        for es in spec.edges:
            doc.edges.append(
                DocEdge(es.from_node, es.from_port, es.to_node, es.to_port)
            )
        return doc

    @staticmethod
    def auto_pos(index: int, cols: int = 4,
                 dx: float = 230, dy: float = 150,
                 x0: float = 40, y0: float = 40) -> tuple[float, float]:
        """Сетка по индексу — раскладка для графов без сохранённых позиций."""
        row, col = divmod(index, cols)
        return (x0 + col * dx, y0 + row * dy)

    # ---------- Раскладка по слоям (иерархическая) ----------

    def layer_of_nodes(self) -> dict[str, int]:
        """
        Слой каждого узла = длина самого длинного пути от источника (узла без
        входящих рёбер). Провода идут слева направо: источник — слой 0, его
        потребители — 1 и т.д. Циклы (движок их не допускает) обрываются на 0,
        раскладка остаётся определённой.
        """
        pred: dict[str, list[str]] = {n: [] for n in self.nodes}
        for e in self.edges:
            if e.from_node in self.nodes and e.to_node in self.nodes:
                pred[e.to_node].append(e.from_node)

        layer: dict[str, int] = {}
        visiting: set[str] = set()

        def depth(n: str) -> int:
            if n in layer:
                return layer[n]
            if n in visiting:            # ребро цикла — не углубляемся
                return 0
            visiting.add(n)
            ps = pred[n]
            d = 1 + max((depth(p) for p in ps), default=-1)
            visiting.discard(n)
            layer[n] = d
            return d

        for n in self.nodes:
            depth(n)
        return layer

    def layered_positions(self, x_gap: float = 260.0, y_gap: float = 150.0,
                          x0: float = 40.0, y0: float = 40.0) -> dict[str, tuple]:
        """
        Позиции узлов раскладкой «по слоям»: столбец = слой (см. layer_of_nodes).
        Внутри столбца ≥1 узлы упорядочены по МЕДИАННОЙ Y-координате своих
        источников (приём трассировщика ОПВС, см. calculate_positions в
        exercises/opvs/png_generator.py): потребитель ложится напротив своих
        входов, что структурно снижает число пересечений проводов ещё до
        трассировки; медиана устойчивее среднего к выбросам. Слой 0 — в
        порядке добавления (стабильность). Возвращает {node_id: (x, y)};
        исполнение графа не затрагивает (только meta.layout).
        """
        from statistics import median

        layer = self.layer_of_nodes()
        by_layer: dict[int, list[str]] = {}
        for nid in self.nodes:                # порядок добавления — стабильность
            by_layer.setdefault(layer.get(nid, 0), []).append(nid)

        preds: dict[str, list[str]] = {n: [] for n in self.nodes}
        for e in self.edges:
            if e.from_node in self.nodes and e.to_node in self.nodes:
                preds[e.to_node].append(e.from_node)

        pos: dict[str, tuple] = {}
        for col, nids in sorted(by_layer.items()):
            if col > 0:
                def _median_src_y(nid: str) -> float:
                    ys = sorted(pos[p][1] for p in preds[nid] if p in pos)
                    # Узлы без размещённых источников — вниз столбца,
                    # между собой в порядке добавления (sort стабилен).
                    return float(median(ys)) if ys else float("inf")
                nids = sorted(nids, key=_median_src_y)
            for row, nid in enumerate(nids):
                pos[nid] = (x0 + col * x_gap, y0 + row * y_gap)
        return pos

    def apply_layered_layout(self, **kwargs) -> dict[str, tuple]:
        """Расставить узлы по слоям и записать позиции в модель."""
        pos = self.layered_positions(**kwargs)
        for nid, (x, y) in pos.items():
            self.set_pos(nid, x, y)
        return pos

    # ---------- Рамки-комментарии (аннотации, вне исполнения) ----------
    #
    # Комментарии — прямоугольники с текстом для группировки/пояснений на
    # холсте. Живут в meta["comments"] (list of dict), движок их не читает,
    # сериализация — общая (round-trip через to_spec_dict/from_spec_dict).

    def comments(self) -> list[dict]:
        raw = self.meta.get("comments")
        return raw if isinstance(raw, list) else []

    def _set_comments(self, items: list[dict]) -> None:
        if items:
            self.meta["comments"] = items
        else:
            self.meta.pop("comments", None)

    def unique_comment_id(self) -> str:
        used = {c.get("id") for c in self.comments()}
        i = 1
        while f"cmt_{i}" in used:
            i += 1
        return f"cmt_{i}"

    def add_comment(self, x: float = 40.0, y: float = 40.0,
                    w: float = 260.0, h: float = 160.0,
                    text: str = "Комментарий",
                    color: str | None = None,
                    comment_id: str | None = None) -> dict:
        cid = comment_id or self.unique_comment_id()
        item = {"id": cid, "x": float(x), "y": float(y),
                "w": float(w), "h": float(h), "text": str(text)}
        if color:
            item["color"] = color
        items = list(self.comments())
        items.append(item)
        self._set_comments(items)
        return item

    def update_comment(self, comment_id: str, **fields) -> None:
        items = list(self.comments())
        for c in items:
            if c.get("id") == comment_id:
                c.update(fields)
                break
        self._set_comments(items)

    def remove_comment(self, comment_id: str) -> None:
        items = [c for c in self.comments() if c.get("id") != comment_id]
        self._set_comments(items)

    # ---------- Ручные точки перегиба провода (meta, вне соединения) ----------
    #
    # Трассировщик кладёт провода сам; ручная поправка — точки перегиба —
    # живёт в meta["bends"] = {edge_key: [[x, y], ...]}, РЯДОМ с layout и
    # comments, а не в самом DocEdge. Причина — синк: конфликт по
    # РАСПОЛОЖЕНИЮ безвреден (LWW по проводу — просто взять чью-то версию),
    # конфликт по ЛОГИКЕ (кто с кем соединён) осмыслен и требует разбора.
    # Смешать значило бы ловить LWW-конфликты из-за того, что двое просто
    # подвигали провод. Ключ строится _edge_key — не индексом в self.edges,
    # см. её докстроку.

    def bends(self) -> dict[str, list]:
        raw = self.meta.get("bends")
        return raw if isinstance(raw, dict) else {}

    def edge_bends(self, src_node: str, src_port: str,
                   dst_node: str, dst_port: str) -> list[list[float]]:
        """
        Точки перегиба провода. Мусорная запись (не список пар чисел)
        читается как «перегибов нет», а не роняет вызов: meta приходит по
        синку от чужого клиента и из файлов, сохранённых старой версией.
        """
        raw = self.bends().get(_edge_key(src_node, src_port, dst_node, dst_port))
        if not isinstance(raw, list):
            return []
        points: list[list[float]] = []
        for p in raw:
            if isinstance(p, (list, tuple)) and len(p) == 2:
                try:
                    points.append([float(p[0]), float(p[1])])
                except (TypeError, ValueError):
                    continue      # одна кривая точка не должна топить весь провод
        return points

    def set_edge_bends(self, src_node: str, src_port: str,
                       dst_node: str, dst_port: str,
                       points: list) -> None:
        """Пустой points СТИРАЕТ ключ, а не оставляет []: иначе meta пухнет
        мусором и диффы синка шумят на пустом месте."""
        key = _edge_key(src_node, src_port, dst_node, dst_port)
        bends = dict(self.bends())
        if points:
            bends[key] = [[float(x), float(y)] for x, y in points]
        else:
            bends.pop(key, None)
        if bends:
            self.meta["bends"] = bends
        else:
            self.meta.pop("bends", None)

    def clear_bends(self) -> None:
        self.meta.pop("bends", None)

    # ---------- Подписи проводов (meta, рядом с bends) ----------
    #
    # Пожелание §7 июльского разбора: подписи есть только у узлов, а
    # объяснять в большом графе чаще нужно как раз провод — почему
    # величина уходит именно сюда. Хранение — то же, что у bends, и по
    # тем же причинам: meta, ключ по паре портов, движок не читает.

    def edge_notes(self) -> dict[str, str]:
        raw = self.meta.get("edge_notes")
        return raw if isinstance(raw, dict) else {}

    def edge_note(self, src_node: str, src_port: str,
                  dst_node: str, dst_port: str) -> str:
        raw = self.edge_notes().get(
            _edge_key(src_node, src_port, dst_node, dst_port))
        return raw if isinstance(raw, str) else ""

    def set_edge_note(self, src_node: str, src_port: str,
                      dst_node: str, dst_port: str, text: str) -> None:
        """Пустая подпись СТИРАЕТ ключ (как set_edge_bends)."""
        key = _edge_key(src_node, src_port, dst_node, dst_port)
        notes = dict(self.edge_notes())
        value = str(text or "").strip()
        if value:
            notes[key] = value
        else:
            notes.pop(key, None)
        if notes:
            self.meta["edge_notes"] = notes
        else:
            self.meta.pop("edge_notes", None)

    def _drop_orphan_edge_meta(self) -> None:
        """
        Выбросить перегибы и подписи проводов, которых больше нет.

        Нужно там, где рёбра исчезают НЕ через remove_edge: обрезка по
        пропавшим портам и вытеснение провода на занятом входе. Осиротевший
        ключ пережил бы своё ребро и всплыл на новом проводе между теми же
        портами — с текстом и изгибами, сделанными про другое.
        """
        alive = {_edge_key(*e.as_tuple()) for e in self.edges}
        for field in ("bends", "edge_notes"):
            raw = self.meta.get(field)
            if not isinstance(raw, dict):
                continue
            kept = {k: v for k, v in raw.items() if k in alive}
            if len(kept) == len(raw):
                continue
            if kept:
                self.meta[field] = kept
            else:
                self.meta.pop(field, None)

    # ---------- Валидация ----------

    def validate(self) -> None:
        """Собрать граф движком (полная структурная проверка). Бросает GraphError."""
        from .executor import GraphExecutor
        GraphExecutor(self.to_spec())

    def has_task_sink(self) -> bool:
        """Есть ли финальный узел (неподключённый выход TASK)."""
        from .executor import GraphExecutor
        try:
            return GraphExecutor(self.to_spec()).result is not None
        except GraphError:
            return False

    # ---------- Финальный узел (для подсветки в редакторе) ----------

    def _task_output_ports(self, node_id: str) -> list[str]:
        node = self.nodes[node_id]
        _ins, outs = self.safe_ports(node.type, node.params)
        return [p.name for p in outs if p.type is PortType.TASK]

    def task_node_ids(self) -> list[str]:
        """Все узлы, имеющие выход типа TASK (независимо от подключения)."""
        return [nid for nid in self.nodes if self._task_output_ports(nid)]

    def task_sink_ids(self) -> list[str]:
        """
        Узлы со свободным (никуда не подключённым) выходом TASK — кандидаты
        в финал. Ровно один такой узел = корректный финал графа; несколько —
        конфликт (движок откажется собирать граф).

        В отличие от has_task_sink, не требует валидности всего графа —
        считается прямо по модели, поэтому пригодно для живой подсветки.
        """
        consumed = {(e.from_node, e.from_port) for e in self.edges}
        return [
            nid for nid in self.nodes
            if any((nid, port) not in consumed
                   for port in self._task_output_ports(nid))
        ]

    def branches(self):
        """
        Ветки «условие»/«ответ» по всему графу (core/graph/branches.py).

        Не хранится и не кэшируется: считается по графу, который тут же и
        лежит, а любой кэш пришлось бы сбрасывать на каждой правке —
        включая те, о которых холст узнаёт не сразу.
        """
        from .branches import EdgeRef, compute_branches
        return compute_branches(
            node_types={nid: n.type for nid, n in self.nodes.items()},
            node_params={nid: n.params for nid, n in self.nodes.items()},
            edges=[EdgeRef(*e.as_tuple()) for e in self.edges],
            sinks=self.task_sink_ids(),
            input_ports=lambda nid: [p.name for p in self.ports(nid)[0]],
        )

    def type_has_task_output(self, type_id: str) -> bool:
        """Есть ли у типа узла (с параметрами по умолчанию) выход TASK."""
        if not self.registry.has(type_id):
            return False
        _ins, outs = self.safe_ports(type_id, {})
        return any(p.type is PortType.TASK for p in outs)

    # ---------- Развёрнутые рамки циклов (состояние вида, в meta) ----------
    #
    # Развёрнутый узел цикла рисуется на холсте рамкой-структурой с телом
    # внутри (LabVIEW-style). Список id хранится в meta["expanded_nodes"]:
    # движок исполнения meta не интерпретирует, а сериализация общая.

    def expanded_nodes(self) -> set[str]:
        raw = self.meta.get("expanded_nodes")
        return {str(x) for x in raw} if isinstance(raw, list) else set()

    def is_node_expanded(self, node_id: str) -> bool:
        return node_id in self.expanded_nodes()

    def set_node_expanded(self, node_id: str, expanded: bool) -> None:
        cur = self.expanded_nodes()
        if expanded:
            cur.add(node_id)
        else:
            cur.discard(node_id)
        if cur:
            self.meta["expanded_nodes"] = sorted(cur)
        else:
            self.meta.pop("expanded_nodes", None)
