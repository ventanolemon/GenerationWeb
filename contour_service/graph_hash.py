"""
Канонический хэш графа для дедупа корпуса (training_plan.md §3.5):

    топосорт → переименование id в n0..nk → JSON без meta → sha256

Инвариант: два графа, отличающиеся ТОЛЬКО именами узлов (и порядком
списков nodes/edges), дают один хэш. Детерминированность топосорта не
может опираться на исходные id (их мы и стираем) — порядок среди «готовых»
узлов Кана задают структурные метки:

  fwd-метка = sha256(type, params, отсортированные (порты, fwd-метки предков))
  bwd-метка = симметрично от потомков

Пара (fwd, bwd) различает узлы по их месту в графе, а не по имени; узлы
с совпавшими парами структурно взаимозаменяемы (автоморфны) — любой их
взаимный порядок даёт одинаковую каноническую сериализацию.

Ограничение (осознанное): вложенные тела циклов (repeat/map: params["body"])
канонизируются как текст params — разные id ВНУТРИ тела дадут разные хэши.
Это недо-дедуп (безопасно: дубль останется дублем в корпусе и вычистится
косинусной близостью описаний, training_plan §3.5), зато без рекурсивной
канонизации произвольных подграфов.
"""

from __future__ import annotations
import hashlib
import json


def _h(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _node_base(node: dict) -> str:
    params = node.get("params") or {}
    return _h(str(node.get("type", "")),
              json.dumps(params, sort_keys=True, ensure_ascii=False))


def _split(endpoint: str) -> tuple[str, str]:
    node, _, port = str(endpoint).partition(":")
    return node, port


def _structural_labels(nodes: list[dict], edges: list[dict]) -> dict[str, str]:
    """(fwd, bwd)-метка каждого узла, свёрнутая в одну строку."""
    base = {n["id"]: _node_base(n) for n in nodes}
    preds: dict[str, list[tuple[str, str, str]]] = {n["id"]: [] for n in nodes}
    succs: dict[str, list[tuple[str, str, str]]] = {n["id"]: [] for n in nodes}
    for e in edges:
        fn, fp = _split(e["from"])
        tn, tp = _split(e["to"])
        if fn in base and tn in base:
            preds[tn].append((fp, tp, fn))
            succs[fn].append((fp, tp, tn))

    def walk(nid: str, memo: dict, adj: dict, guard: set) -> str:
        if nid in memo:
            return memo[nid]
        if nid in guard:              # цикл (движок запрещает, но не падаем)
            return "cycle"
        guard.add(nid)
        neigh = sorted(_h(fp, tp, walk(other, memo, adj, guard))
                       for fp, tp, other in adj[nid])
        guard.discard(nid)
        memo[nid] = _h(base[nid], *neigh)
        return memo[nid]

    fwd: dict[str, str] = {}
    bwd: dict[str, str] = {}
    for n in nodes:
        walk(n["id"], fwd, preds, set())
        walk(n["id"], bwd, succs, set())
    return {n["id"]: _h(fwd[n["id"]], bwd[n["id"]]) for n in nodes}


def canonical_graph_hash(spec_dict: dict) -> str:
    """sha256-хэш канонической формы графа (meta отброшена целиком)."""
    nodes = list(spec_dict.get("nodes") or [])
    edges = list(spec_dict.get("edges") or [])
    label = _structural_labels(nodes, edges)
    by_id = {n["id"]: n for n in nodes}

    # Кан: считаем входящие степени, готовые узлы упорядочиваем меткой.
    indeg = {n["id"]: 0 for n in nodes}
    consumers: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        fn, _ = _split(e["from"])
        tn, _ = _split(e["to"])
        if fn in indeg and tn in indeg:
            indeg[tn] += 1
            consumers[fn].append(tn)

    ready = sorted((nid for nid, d in indeg.items() if d == 0),
                   key=lambda nid: label[nid])
    order: list[str] = []
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for c in consumers[nid]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
        ready.sort(key=lambda n: label[n])
    # Цикл (недостижимо для валидного графа) — дописываем остаток по метке.
    if len(order) < len(nodes):
        rest = sorted((nid for nid in indeg if nid not in set(order)),
                      key=lambda nid: label[nid])
        order.extend(rest)

    rename = {old: f"n{i}" for i, old in enumerate(order)}
    canon_nodes = []
    for old in order:
        n = by_id[old]
        canon_nodes.append({"id": rename[old], "type": n.get("type", ""),
                            "params": n.get("params") or {}})
    canon_edges = sorted(
        {f"{rename.get(_split(e['from'])[0], '?')}:{_split(e['from'])[1]}"
         + "->"
         + f"{rename.get(_split(e['to'])[0], '?')}:{_split(e['to'])[1]}"
         for e in edges}
    )
    payload = json.dumps(
        {"version": spec_dict.get("version", 1),
         "nodes": canon_nodes, "edges": canon_edges},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
