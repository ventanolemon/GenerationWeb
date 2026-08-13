"""
Ветки «условие» и «ответ»: кто в графе на что работает.

Жалоба из july_language_wishlist (§8): в большом графе не видно, что
готовит условие, а что — ответ; они «различаются лишь тем, куда в итоге
приходит провод».

Ключевое решение — эта принадлежность НЕ хранится. Формулировка «нет
разграничения» подразумевает пометку, которую надо завести, но куда
приходит провод, уже известно из самого графа. Пометка на второй правке
разошлась бы с проводами и врала бы ровно там, где на неё смотрят;
вычисленная обратным обходом не может устареть в принципе.

Модуль ЧИСТЫЙ: ни Qt, ни документа редактора — узлы, рёбра и функция,
отдающая входные порты узла. Поэтому одна и та же логика годится и
десктопному холсту, и любому другому потребителю. У веб-редактора своё
зеркало на TS (frontend/src/graph-editor/model.ts, `branchMap`) — по той
же причине, по которой у него зеркало правил портов: контракт редактора
разрешает клиенту считать это локально, а гонять граф на сервер ради
подсветки было бы странно.
"""

from __future__ import annotations

from typing import Callable, Iterable, Literal, NamedTuple

Branch = Literal["statement", "answer", "both"]


class EdgeRef(NamedTuple):
    """Ребро в терминах этого модуля — четыре строки, без класса документа."""
    from_node: str
    from_port: str
    to_node: str
    to_port: str

    def key(self) -> str:
        return (f"{self.from_node}:{self.from_port}"
                f"->{self.to_node}:{self.to_port}")


class BranchMap(NamedTuple):
    nodes: dict[str, Branch]
    edges: dict[str, Branch]
    #: Финал, от которого считали. None — финала нет или их несколько.
    sink: str | None


def _merge(was: Branch | None, add: Branch) -> Branch:
    if was is None:
        return add
    return was if was == add else "both"


def _marker_names(text: str) -> list[str]:
    from .nodes.compute import _marker_names as impl
    return impl(text)


def sink_port_branches(node_type: str, params: dict,
                       port_names: Iterable[str]) -> dict[str, Branch]:
    """
    Как входы ФИНАЛА делятся на условие и ответ.

    Знание точечное: финальных узлов в языке единицы, и деление у каждого
    своё. У `task` ответ — объявленные слоты и маркеры шаблона ответа,
    условие — маркеры текста условия; у `static_task` это прямо два
    порта. Незнакомый финал НЕ угадывается по имени порта: пусть лучше
    подсветки не будет, чем она покажет неправду.
    """
    out: dict[str, Branch] = {}
    if node_type == "task":
        from .nodes.answer_slots import parse_slots
        try:
            slots = {d.name for d in parse_slots(params.get("slots"))}
        except Exception:
            # Недописанное объявление слота — обычное состояние во время
            # правки. Подсветка не повод ронять холст.
            slots = set()
        in_answer = set(_marker_names(str(params.get("answer_template") or "")))
        in_statement = set(_marker_names(str(params.get("statement") or "")))
        for name in port_names:
            if name in slots:
                out[name] = "answer"
            elif name in in_statement:
                out[name] = "both" if name in in_answer else "statement"
            elif name in in_answer:
                out[name] = "answer"
            elif name in ("vars", "blocks"):
                # `vars` подставляется в текст условия, `blocks`
                # дописывается к нему блоками — обе в условие.
                out[name] = "statement"
    elif node_type == "static_task":
        for name in port_names:
            if name in ("statement", "answer"):
                out[name] = name  # type: ignore[assignment]
    return out


def compute_branches(
    node_types: dict[str, str],
    node_params: dict[str, dict],
    edges: Iterable[EdgeRef],
    sinks: list[str],
    input_ports: Callable[[str], list[str]],
) -> BranchMap:
    """
    Раскрасить граф ветками обратным обходом от финала.

    Обход идёт по РЁБРАМ, а не по узлам: ветку получает и провод, и то,
    что в него приходит. Иначе провод от общей величины красился бы по
    узлу-источнику, и оба его конца выглядели бы одинаково — а интересно
    как раз то, что один и тот же узел уходит в две стороны.
    """
    nodes: dict[str, Branch] = {}
    marked: dict[str, Branch] = {}
    edge_list = list(edges)
    # Ноль финалов — граф не дособран; больше одного — он уже ошибочен, и
    # подсветка от произвольно выбранного финала вводила бы в заблуждение
    # поверх настоящей проблемы.
    if len(sinks) != 1 or sinks[0] not in node_types:
        return BranchMap({}, {}, None)
    sink = sinks[0]

    incoming: dict[str, list[EdgeRef]] = {}
    for e in edge_list:
        incoming.setdefault(e.to_node, []).append(e)

    by_port = sink_port_branches(
        node_types[sink], node_params.get(sink, {}), input_ports(sink))
    queue: list[tuple[EdgeRef, Branch]] = []
    for e in incoming.get(sink, []):
        branch = by_port.get(e.to_port)
        if branch is not None:
            queue.append((e, branch))

    # Обход с ослаблением: узел переобходится, только если его ветка
    # РАСШИРИЛАСЬ (statement + answer → both). Циклов в графе нет, но
    # ромбы есть, и без этого условия общий предок обходился бы заново на
    # каждом ведущем к нему пути.
    while queue:
        edge, branch = queue.pop()
        key = edge.key()
        was_edge = marked.get(key)
        next_edge = _merge(was_edge, branch)
        marked[key] = next_edge
        was_node = nodes.get(edge.from_node)
        next_node = _merge(was_node, branch)
        nodes[edge.from_node] = next_node
        if was_node == next_node and was_edge == next_edge:
            continue
        for up in incoming.get(edge.from_node, []):
            queue.append((up, next_node))

    nodes[sink] = "both"
    return BranchMap(nodes, marked, sink)
