"""
Ортогональная трассировка проводов холста — ЧИСТЫЙ модуль (ноль Qt).

Перенос дисциплины трассировщика ОПВС (exercises/opvs/png_generator.py) на
свободный канвас граф-редактора. Гарантии те же:

  • сегменты строго ортогональны;
  • горизонтальные сегменты РАЗНЫХ цепей не накладываются (общий видимый
    отрезок у проводов одной цепи — одного выходного порта — допустим:
    это один и тот же сигнал, как в ОПВС);
  • вертикальные сегменты разных цепей не накладываются;
  • трейсы не проходят сквозь тела узлов (с зазором node_margin);
  • пересечение «горизонталь × вертикаль» допустимо — минимизируется
    порядком назначения треков, но не запрещается.

Ключевые приёмы из ОПВС:
  1. Реестры занятых сегментов (h_tracks/v_tracks) + предикаты наложения
     с минимальным зазором track_sep.
  2. Канальное правило: соединения одного канала сортируются по start_y
     возрастающе, а вертикальные треки назначаются справа налево — тогда
     горизонтальные отрезки на общей Y-координате получают
     непересекающиеся X-диапазоны (см. комментарий в route_connections
     ОПВС — здесь оно же, обобщённое на свободные позиции узлов).
  3. Поиск свободной позиции рядом с желаемой (_free_x/_free_y), здесь —
     двунаправленный (0, +sep, −sep, +2sep, …), чтобы трасса оставалась
     близко к геометрически естественной.
  4. Обратные рёбра (вход левее выхода) — «перелёт» над/под узлами, как
     несмежные слои в ОПВС.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

STUB = 18.0          # «ус» от порта, всегда свободен (принадлежит порту)
TRACK_SEP = 12.0     # минимальный зазор между параллельными трейсами
NODE_MARGIN = 14.0   # зазор вокруг тел узлов
SEARCH_STEPS = 40    # максимум шагов поиска свободной позиции

Point = tuple[float, float]
Rect = tuple[float, float, float, float]   # x, y, w, h


@dataclass
class EdgeSpec:
    """Одно соединение: точки портов в координатах сцены + цепь (net).

    net — идентификатор выходного порта-источника: провода одной цепи
    могут делить сегменты (это один сигнал), разных — нет."""
    key: object
    src: Point               # центр выходного порта
    dst: Point               # центр входного порта
    net: object
    src_node: Optional[str] = None
    dst_node: Optional[str] = None
    bends: tuple[Point, ...] = ()
    """
    Ручные точки перегиба — провод обязан пройти через них.

    Живут они не здесь, а в `meta["bends"]` документа (§7.2 плана): в
    соединении им нельзя, потому что тогда синк начнёт ловить
    LWW-конфликты из-за того, что двое просто подвигали провода.
    Сюда они приезжают на время укладки.

    Заданы — трассировщик не выбирает маршрут, а исполняет заданный.
    Автор поправил провод руками именно потому, что автомат его не
    устроил, и «улучшать» поправку значит спорить с автором.
    """


@dataclass
class _Tracks:
    """Реестры занятых сегментов, с принадлежностью цепи."""
    h: list[tuple[float, float, float, object]] = field(default_factory=list)
    v: list[tuple[float, float, float, object]] = field(default_factory=list)

    def h_free(self, y: float, x0: float, x1: float, net: object) -> bool:
        x0, x1 = min(x0, x1), max(x0, x1)
        for (ty, t0, t1, tnet) in self.h:
            if tnet == net:
                continue
            if abs(ty - y) >= TRACK_SEP:
                continue
            if max(x0, t0) < min(x1, t1):    # касание концами допустимо
                return False
        return True

    def v_free(self, x: float, y0: float, y1: float, net: object) -> bool:
        y0, y1 = min(y0, y1), max(y0, y1)
        for (tx, t0, t1, tnet) in self.v:
            if tnet == net:
                continue
            if abs(tx - x) >= TRACK_SEP:
                continue
            if max(y0, t0) < min(y1, t1):
                return False
        return True

    def add_h(self, y: float, x0: float, x1: float, net: object) -> None:
        self.h.append((y, min(x0, x1), max(x0, x1), net))

    def add_v(self, x: float, y0: float, y1: float, net: object) -> None:
        self.v.append((x, min(y0, y1), max(y0, y1), net))


class _Obstacles:
    """Тела узлов (раздутые на NODE_MARGIN) — трейсы их не пересекают."""

    def __init__(self, rects: dict[str, Rect]):
        self.rects = {
            nid: (x - NODE_MARGIN, y - NODE_MARGIN,
                  x + w + NODE_MARGIN, y + h + NODE_MARGIN)
            for nid, (x, y, w, h) in rects.items()
        }

    def h_hits(self, y: float, x0: float, x1: float,
               skip: tuple = ()) -> bool:
        x0, x1 = min(x0, x1), max(x0, x1)
        for nid, (l, t, r, b) in self.rects.items():
            if nid in skip:
                continue
            if t < y < b and max(x0, l) < min(x1, r):
                return True
        return False

    def v_hits(self, x: float, y0: float, y1: float,
               skip: tuple = ()) -> bool:
        y0, y1 = min(y0, y1), max(y0, y1)
        for nid, (l, t, r, b) in self.rects.items():
            if nid in skip:
                continue
            if l < x < r and max(y0, t) < min(y1, b):
                return True
        return False


def _offsets(step: float = TRACK_SEP):
    """0, +step, −step, +2·step, −2·step, … — поиск от желаемой позиции."""
    yield 0.0
    for i in range(1, SEARCH_STEPS):
        yield i * step
        yield -i * step


def _find_free_v(x_hint: float, y0: float, y1: float, net: object,
                 tracks: _Tracks, obst: _Obstacles,
                 lo: Optional[float] = None, hi: Optional[float] = None,
                 skip: tuple = ()) -> Optional[float]:
    """Свободная X-позиция вертикали [y0,y1] рядом с x_hint (в границах
    lo..hi); None — в границах свободного места нет."""
    for off in _offsets():
        x = x_hint + off
        if lo is not None and x < lo:
            continue
        if hi is not None and x > hi:
            continue
        if tracks.v_free(x, y0, y1, net) and not obst.v_hits(x, y0, y1, skip):
            return x
    return None


def _free_v(x_hint: float, y0: float, y1: float, net: object,
            tracks: _Tracks, obst: _Obstacles,
            lo: Optional[float] = None, hi: Optional[float] = None,
            skip: tuple = ()) -> float:
    found = _find_free_v(x_hint, y0, y1, net, tracks, obst, lo, hi, skip)
    return x_hint if found is None else found


def _free_h(y_hint: float, x0: float, x1: float, net: object,
            tracks: _Tracks, obst: _Obstacles, skip: tuple = ()) -> float:
    best = y_hint
    for off in _offsets():
        y = y_hint + off
        if tracks.h_free(y, x0, x1, net) and not obst.h_hits(y, x0, x1, skip):
            return y
    return best


def _simplify(points: list[Point]) -> list[Point]:
    """Убрать дубли и коллинеарные промежуточные точки."""
    out: list[Point] = []
    for p in points:
        if out and abs(p[0] - out[-1][0]) < 1e-6 and abs(p[1] - out[-1][1]) < 1e-6:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 1e-6 and abs(b[0] - c[0]) < 1e-6) or \
           (abs(a[1] - b[1]) < 1e-6 and abs(b[1] - c[1]) < 1e-6):
            out.pop(i)
        else:
            i += 1
    return out


@dataclass
class RouteResult:
    """
    Проложенные провода и точки ветвления.

    Точки ветвления возвращаются, а не рисуются вызывающим по догадке:
    место, где сеть расходится, знает только тот, кто её проложил. И
    отдельной сущности «узел-контакт» для них не заводится — она попала
    бы в документ и засорила диффы (§7.2 плана); это чисто
    геометрический результат укладки, живущий ровно до следующей.
    """
    routes: dict[object, list[Point]] = field(default_factory=dict)
    junctions: dict[object, list[Point]] = field(default_factory=dict)
    """
    Точки ветвления ПО СЕТЯМ, а не общим списком.

    Сеть у точки спрашивают сразу же: рисуется она цветом своего
    сигнала, как и провода. Общий список заставил бы вызывающего искать
    хозяина по координатам — то есть заново решать задачу, ответ на
    которую здесь уже есть.
    """

    # Совместимости со «просто словарём», который возвращался раньше,
    # здесь нарочно нет. Пробовал `__getitem__` — и получил ровно тот
    # случай, ради которого её и не делают: `set(result)` не упало, а
    # тихо пошло по старому протоколу итерации и вернуло НЕ ТО. Явная
    # ошибка на границе лучше молчаливой подмены; вызывающих двое.


def _merge_segments(polylines: list[list[Point]]) -> list[tuple[Point, Point]]:
    """
    То, что РЕАЛЬНО нарисовано: совпадающие куски соседних ветвей — один
    отрезок, а не два.

    Без склейки ветвление считается неверно. Провода одной сети идут по
    стволу вместе, и в точке, где стоит обычный угол, сходятся четыре
    конца отрезков — по два от каждой ветви, лежащих друг на друге. По
    счёту концов это ветвление, на экране — угол. Считать надо по
    нарисованному.
    """
    lines: dict[tuple[str, float], list[tuple[float, float]]] = {}
    for pts in polylines:
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
                continue
            if abs(a[0] - b[0]) < 1e-6:
                key = ("v", round(a[0], 3))
                span = (min(a[1], b[1]), max(a[1], b[1]))
            else:
                key = ("h", round(a[1], 3))
                span = (min(a[0], b[0]), max(a[0], b[0]))
            lines.setdefault(key, []).append(span)

    out: list[tuple[Point, Point]] = []
    for (kind, coord), spans in lines.items():
        spans.sort()
        lo, hi = spans[0]
        for s0, s1 in spans[1:]:
            if s0 <= hi + 1e-6:
                hi = max(hi, s1)
            else:
                out.append(_span_points(kind, coord, lo, hi))
                lo, hi = s0, s1
        out.append(_span_points(kind, coord, lo, hi))
    return out


def _span_points(kind: str, coord: float,
                 lo: float, hi: float) -> tuple[Point, Point]:
    if kind == "v":
        return ((coord, lo), (coord, hi))
    return ((lo, coord), (hi, coord))


def _junctions_of(polylines: list[list[Point]],
                  ports: set[Point]) -> list[Point]:
    """
    Точки, где сеть расходится.

    Считаются ПО НАРИСОВАННОМУ, а не назначаются при укладке. Так они и
    «выпадают сами», как требует §7.2: ветвление — это место, где к
    одной точке сходится больше двух отрезков, либо конец одного
    отрезка упирается в середину другого (T-образный отвод). Дерево при
    этом нигде не описано отдельно и не может разойтись с тем, что
    видит глаз.

    Сами порты исключаются. Из выходного порта веера тоже выходит
    несколько проводов, и формально это ветвление — но точка на порту
    читается как «здесь контакт», а контакт там и так нарисован самим
    портом.
    """
    segments = _merge_segments(polylines)
    ends: dict[Point, int] = {}
    for a, b in segments:
        for p in (a, b):
            key = (round(p[0], 3), round(p[1], 3))
            ends[key] = ends.get(key, 0) + 1

    out: list[Point] = []
    for point, count in ends.items():
        if point in ports:
            continue
        if count >= 3:
            out.append(point)
            continue
        for a, b in segments:
            if _strictly_inside(point, a, b):
                out.append(point)
                break
    out.sort()
    return out


def _strictly_inside(p: Point, a: Point, b: Point) -> bool:
    """Точка внутри отрезка, не совпадая с его концами."""
    if abs(a[0] - b[0]) < 1e-6:                      # вертикаль
        if abs(p[0] - a[0]) > 1e-6:
            return False
        lo, hi = min(a[1], b[1]), max(a[1], b[1])
        return lo + 1e-6 < p[1] < hi - 1e-6
    if abs(a[1] - b[1]) < 1e-6:                      # горизонталь
        if abs(p[1] - a[1]) > 1e-6:
            return False
        lo, hi = min(a[0], b[0]), max(a[0], b[0])
        return lo + 1e-6 < p[0] < hi - 1e-6
    return False


def _route_manual(e: EdgeSpec, tracks: _Tracks) -> list[Point]:
    """
    Провод по заданным вручную точкам перегиба.

    Обход препятствий здесь НЕ делается, и это не упущение: точки
    поставил человек, глядя на холст, — если провод идёт сквозь узел,
    значит так и просили. Автомат, «исправляющий» ручную поправку,
    выглядел бы поломкой, а не помощью.

    Между соседними точками — колено: сначала по горизонтали, потом по
    вертикали. Из выходного порта провод обязан выйти горизонтально, и
    во входной зайти тоже горизонтально, иначе он утыкается в тело узла
    сбоку.

    Последний участок — ступенька, а не колено. Коленом (вертикаль, потом
    горизонталь) провод возвращался бы по той же вертикали, по которой
    только что пришёл в перегиб; `_simplify` такой шпиль схлопывает, и
    ручная точка ПРОПАДАЛА, молча. Ступенька «горизонталь — вертикаль —
    горизонталь» и через перегиб проходит, и в порт заходит сбоку.
    """
    pts: list[Point] = [e.src]
    cur = e.src
    for bend in e.bends:
        pts.append((bend[0], cur[1]))
        pts.append((bend[0], bend[1]))
        cur = (bend[0], bend[1])

    if abs(cur[1] - e.dst[1]) < 1e-6:
        pts.append(e.dst)
    else:
        step_x = (cur[0] + e.dst[0]) / 2.0
        # Ступенька обязана остаться между перегибом и портом: иначе
        # провод уходит назад и рисует петлю.
        step_x = min(max(step_x, min(cur[0], e.dst[0])), e.dst[0] - STUB) \
            if e.dst[0] - STUB > min(cur[0], e.dst[0]) else step_x
        pts.append((step_x, cur[1]))
        pts.append((step_x, e.dst[1]))
        pts.append(e.dst)

    route = _simplify(pts)
    # Регистрируем занятое: следующие провода обязаны видеть ручную
    # трассу, иначе автомат уложит свои поверх неё.
    for a, b in zip(route, route[1:]):
        if abs(a[0] - b[0]) < 1e-6:
            tracks.add_v(a[0], a[1], b[1], e.net)
        else:
            tracks.add_h(a[1], a[0], b[0], e.net)
    return route


def _route_net_tree(edges: list[EdgeSpec], tracks: _Tracks,
                    obst: _Obstacles) -> Optional[dict[object, list[Point]]]:
    """
    Веер из одного выхода — деревом с общим стволом (§7.2).

    Маршрутизируется СЕТЬ, а не каждое соединение по отдельности. По
    отдельности каждый провод честно идёт своей буквой «П», они
    накладываются (одна сеть — накладываться можно), и на экране это
    выглядит почти как ствол, но провода при этом втрое длиннее, а
    ветвление нигде не обозначено.

    Дерево простое, как и предписано («в приближении жадное»): один
    вертикальный ствол между источником и приёмниками, от него
    горизонтальные отводы. Ствол обязан быть чистым сразу для всех
    ветвей — иначе `None`, и сеть раскладывается по-старому, поштучно.
    Деградация без падения здесь важнее красоты: зажатый веер должен
    остаться нарисованным.
    """
    net = edges[0].net
    sx, sy = edges[0].src
    src_node = edges[0].src_node

    lo = sx + STUB
    hi = min(e.dst[0] for e in edges) - STUB
    if lo > hi:
        return None

    ys = [sy] + [e.dst[1] for e in edges]
    y0, y1 = min(ys), max(ys)
    # Ствол ближе к приёмникам: отводы тогда короткие и не тянутся через
    # весь канал, а общий участок наоборот длинный — ради него всё и
    # затевалось.
    x_hint = lo + (hi - lo) * 0.6

    trunk_x = None
    for off in _offsets():
        x = x_hint + off
        if x < lo or x > hi:
            continue
        # Ствол проходит мимо ЧУЖИХ узлов: свой у него только источник.
        if not tracks.v_free(x, y0, y1, net) or \
                obst.v_hits(x, y0, y1, (src_node,) if src_node else ()):
            continue
        if not tracks.h_free(sy, sx, x, net) or \
                obst.h_hits(sy, sx + STUB, x, (src_node,) if src_node else ()):
            continue
        if any(not tracks.h_free(e.dst[1], x, e.dst[0], net) or
               obst.h_hits(e.dst[1], x, e.dst[0] - STUB,
                           tuple(n for n in (src_node, e.dst_node) if n))
               for e in edges):
            continue
        trunk_x = x
        break
    if trunk_x is None:
        return None

    tracks.add_h(sy, sx, trunk_x, net)
    tracks.add_v(trunk_x, y0, y1, net)

    out: dict[object, list[Point]] = {}
    for e in edges:
        dx, dy = e.dst
        # Каждая ветвь — полный путь от порта-источника: провод остаётся
        # проводом, его можно выделить и подсветить целиком. Общий кусок
        # у соседей совпадает точка в точку, поэтому рисуется он один
        # раз и стволом и выглядит.
        out[e.key] = _simplify([(sx, sy), (trunk_x, sy),
                                (trunk_x, dy), (dx, dy)])
        tracks.add_h(dy, trunk_x, dx, net)
    return out


def route_edges(node_rects: dict[str, Rect],
                edges: list[EdgeSpec]) -> RouteResult:
    """
    Проложить все провода холста разом (совместная укладка — в этом смысл:
    поодиночке провода не знают о треках друг друга и накладываются).

    Веера (один выход → несколько входов) укладываются СЕТЬЮ, деревом с
    общим стволом, — см. `_route_net_tree`. Остальное по-прежнему
    поштучно.
    """
    tracks = _Tracks()
    obst = _Obstacles(node_rects)
    routes: dict[object, list[Point]] = {}

    # ── Ручные трассы — первыми ──────────────────────────────────────────
    # Занятое ими место автомат обязан видеть с самого начала: иначе он
    # разложит свои провода, а поправленный руками ляжет поверх.
    manual = [e for e in edges if e.bends]
    for e in manual:
        routes[e.key] = _route_manual(e, tracks)
    auto = [e for e in edges if not e.bends]

    forward = [e for e in auto
               if e.dst[0] - e.src[0] >= 2 * STUB + TRACK_SEP]

    # ── Веера: сеть целиком, деревом ─────────────────────────────────────
    # Раньше остальных: ствол занимает место осмысленно, и одиночным
    # проводам достаётся то, что осталось, а не наоборот.
    fans: dict[object, list[EdgeSpec]] = {}
    for e in forward:
        fans.setdefault(e.net, []).append(e)
    routed_by_tree: set = set()
    for net, group in fans.items():
        if len(group) < 2:
            continue
        tree = _route_net_tree(group, tracks, obst)
        if tree is None:
            continue
        routes.update(tree)
        routed_by_tree.update(e.key for e in group)

    forward = [e for e in forward if e.key not in routed_by_tree]
    # Уложенные деревом сюда попасть не должны: их уже нет ни в `forward`,
    # ни в остатке, и повторная укладка перечеркнула бы ствол.
    backward = [e for e in auto
                if e.key not in routed_by_tree and e not in forward]

    # ── Прямые рёбра: канал между источником и приёмником ────────────────
    # Группировка по каналу (пара X-колонок с округлением: после раскладки
    # по слоям колонки совпадают точно; от руки — близкие сливаются).
    channels: dict[tuple[int, int], list[EdgeSpec]] = {}
    for e in forward:
        chan = (int(e.src[0] // 40), int(e.dst[0] // 40))
        channels.setdefault(chan, []).append(e)

    # Узкие каналы раньше широких: их треки геометрически зажаты сильнее.
    for chan in sorted(channels, key=lambda c: (c[1] - c[0], c[0])):
        conns = channels[chan]
        # Канальное правило ОПВС: sort по start_y возрастающе,
        # треки — справа налево.
        conns.sort(key=lambda e: (e.src[1], e.dst[1]))
        n = len(conns)
        ch_left = max(e.src[0] for e in conns) + STUB
        ch_right = min(e.dst[0] for e in conns) - STUB
        if ch_left > ch_right:
            ch_left = min(e.src[0] for e in conns) + STUB
            ch_right = max(e.dst[0] for e in conns) - STUB
        width = max(ch_right - ch_left, TRACK_SEP)

        for idx, e in enumerate(conns):
            slot = n - 1 - idx                       # меньший start_y → правее
            if n > 1:
                x_hint = ch_left + (slot + 0.5) * (width / n)
            else:
                x_hint = (ch_left + ch_right) / 2.0
            routes[e.key] = _route_forward(e, x_hint, ch_left, ch_right,
                                           tracks, obst)

    # ── Обратные/вертикальные рёбра: перелёт вокруг узлов ────────────────
    backward.sort(key=lambda e: (e.src[1], e.src[0]))
    for e in backward:
        routes[e.key] = _route_flyover(e, tracks, obst)

    # Ветвления считаются по сетям: провода РАЗНЫХ сетей пересекаются, и
    # точка пересечения — не ветвление, а перекрёсток. Нарисовать там
    # кружок значило бы показать соединение, которого нет.
    by_net: dict[object, list[list[Point]]] = {}
    ports: set[Point] = set()
    for e in edges:
        ports.add((round(e.src[0], 3), round(e.src[1], 3)))
        ports.add((round(e.dst[0], 3), round(e.dst[1], 3)))
        route = routes.get(e.key)
        if route:
            by_net.setdefault(e.net, []).append(route)
    junctions: dict[object, list[Point]] = {}
    for net, polylines in by_net.items():
        if len(polylines) < 2:
            continue
        found = _junctions_of(polylines, ports)
        if found:
            junctions[net] = found

    return RouteResult(routes=routes, junctions=junctions)


def _route_forward(e: EdgeSpec, x_hint: float, lo: float, hi: float,
                   tracks: _Tracks, obst: _Obstacles) -> list[Point]:
    (sx, sy), (dx, dy) = e.src, e.dst
    skip = tuple(n for n in (e.src_node, e.dst_node) if n)

    # Вертикальный трек: рядом с назначенным слотом. Кандидат обязан давать
    # ЧИСТУЮ простую П-форму относительно тел узлов: вертикаль по реальному
    # размаху (sy..dy) и обе горизонтали не сквозь узлы. Конфликты с чужими
    # ПРОВОДАМИ на горизонталях лечатся детурами ниже, а вот узел на пути —
    # нет: если ни один x канала не даёт чистой формы (ребро «через колонку»
    # с узлом посередине), идём перелётом вокруг, как обратное ребро.
    lo_b, hi_b = min(lo, hi), max(lo, hi)
    track_x = None
    for off in _offsets():
        x = x_hint + off
        if x < lo_b or x > hi_b:
            continue
        if not tracks.v_free(x, sy, dy, e.net):
            continue
        if obst.v_hits(x, sy, dy, skip):
            continue
        if obst.h_hits(sy, sx + STUB, x, skip):
            continue
        if obst.h_hits(dy, x, dx - STUB, skip):
            continue
        track_x = x
        break
    if track_x is None:
        return _route_flyover(e, tracks, obst)

    pts: list[Point] = [(sx, sy)]

    # Сегмент от источника до трека. Конфликт по чужой горизонтали на той же
    # Y → короткий ус от порта + переход на свободный уровень.
    seg_a_y = sy
    if not tracks.h_free(sy, sx, track_x, e.net) or \
            obst.h_hits(sy, sx + STUB, track_x, skip):
        seg_a_y = _free_h(sy, sx + STUB, track_x, e.net, tracks, obst, skip)
        if abs(seg_a_y - sy) > 1e-6:
            stub_x = _free_v(sx + STUB, sy, seg_a_y, e.net, tracks, obst)
            pts += [(stub_x, sy), (stub_x, seg_a_y)]
            tracks.add_h(sy, sx, stub_x, e.net)
            tracks.add_v(stub_x, sy, seg_a_y, e.net)
    pts.append((track_x, seg_a_y))
    tracks.add_h(seg_a_y, pts[-2][0], track_x, e.net)

    # Вертикаль по треку.
    pts.append((track_x, dy))
    tracks.add_v(track_x, seg_a_y, dy, e.net)

    # Сегмент от трека до входа. Конфликт → обходной уровень + спуск перед
    # входом (детур ОПВС: alt_y + pre_x), причём ВСЕ четыре затронутых
    # сегмента (продлённая вертикаль трека, обходная горизонталь, спуск,
    # финальный заход) подбираются совместно — иначе детур сам создаёт
    # наложение (регистрация без проверки).
    if not tracks.h_free(dy, track_x, dx, e.net) or \
            obst.h_hits(dy, track_x, dx - STUB, skip):
        found = None
        for y_off in _offsets():
            alt_y = dy - TRACK_SEP + y_off
            if not tracks.v_free(track_x, seg_a_y, alt_y, e.net):
                continue
            if obst.v_hits(track_x, seg_a_y, alt_y, skip):
                continue
            for x_off in _offsets():
                pre_x = dx - STUB + x_off
                if not (track_x + TRACK_SEP <= pre_x <= dx - STUB / 2):
                    continue
                if not tracks.h_free(alt_y, track_x, pre_x, e.net) or \
                        obst.h_hits(alt_y, track_x, pre_x, skip):
                    continue
                if not tracks.v_free(pre_x, alt_y, dy, e.net) or \
                        obst.v_hits(pre_x, alt_y, dy, skip):
                    continue
                if not tracks.h_free(dy, pre_x, dx, e.net) or \
                        obst.h_hits(dy, pre_x, dx - STUB, skip):
                    continue
                found = (alt_y, pre_x)
                break
            if found:
                break
        if found:
            alt_y, pre_x = found
            pts[-1] = (track_x, alt_y)
            tracks.v.pop()
            tracks.add_v(track_x, seg_a_y, alt_y, e.net)
            pts += [(pre_x, alt_y), (pre_x, dy)]
            tracks.add_h(alt_y, track_x, pre_x, e.net)
            tracks.add_v(pre_x, alt_y, dy, e.net)
            tracks.add_h(dy, pre_x, dx, e.net)
        else:
            # Совсем зажато — регистрируем прямой заход как есть (деградация
            # без падения; следующие рёбра его хотя бы увидят).
            tracks.add_h(dy, track_x, dx, e.net)
    else:
        tracks.add_h(dy, track_x, dx, e.net)

    pts.append((dx, dy))
    return _simplify(pts)


def _route_flyover(e: EdgeSpec, tracks: _Tracks,
                   obst: _Obstacles) -> list[Point]:
    """Обратное/зажатое ребро: выход вправо, перелёт над (или под) узлами,
    заход во вход слева — как несмежные слои в ОПВС."""
    (sx, sy), (dx, dy) = e.src, e.dst
    skip = tuple(n for n in (e.src_node, e.dst_node) if n)

    # Перелёт: ближняя из сторон (над или под обоими узлами). Сначала
    # уровень перелёта по грубому X-диапазону, затем вертикали по их
    # РЕАЛЬНЫМ размахам (sy..fly_y и fly_y..dy).
    tops, bots = [], []
    for nid in skip:
        rect = obst.rects.get(nid)
        if rect:
            tops.append(rect[1])
            bots.append(rect[3])
    y_above = (min(tops) if tops else min(sy, dy)) - 2 * TRACK_SEP
    y_below = (max(bots) if bots else max(sy, dy)) + 2 * TRACK_SEP
    mid = (sy + dy) / 2.0
    y_hint = y_above if abs(mid - y_above) <= abs(mid - y_below) else y_below
    rough_lo = min(dx - STUB, sx + STUB)
    rough_hi = max(dx - STUB, sx + STUB)

    def _pick_out_x(fly: float) -> Optional[float]:
        for off in _offsets():
            x = sx + STUB + off
            if x < sx + STUB / 2:
                continue
            if not tracks.v_free(x, sy, fly, e.net) or \
                    obst.v_hits(x, sy, fly, skip):
                continue
            if not tracks.h_free(sy, sx, x, e.net) or \
                    obst.h_hits(sy, sx + STUB / 2, x, skip):
                continue
            return x
        return None

    def _pick_in_x(fly: float) -> Optional[float]:
        for off in _offsets():
            x = dx - STUB + off
            if x > dx - STUB / 2:
                continue
            if not tracks.v_free(x, fly, dy, e.net) or \
                    obst.v_hits(x, fly, dy, skip):
                continue
            if not tracks.h_free(dy, x, dx, e.net) or \
                    obst.h_hits(dy, x, dx - STUB / 2, skip):
                continue
            return x
        return None

    # Совместный подбор: уровень перелёта × обе вертикали × все горизонтали.
    fly_y, out_x, in_x = y_hint, sx + STUB, dx - STUB
    for off in _offsets():
        fly = y_hint + off
        if not tracks.h_free(fly, rough_lo, rough_hi, e.net) or \
                obst.h_hits(fly, rough_lo, rough_hi):
            continue
        ox = _pick_out_x(fly)
        ix = _pick_in_x(fly)
        if ox is None or ix is None:
            continue
        span = (min(ix, ox), max(ix, ox))
        if not tracks.h_free(fly, span[0], span[1], e.net) or \
                obst.h_hits(fly, span[0], span[1]):
            continue
        fly_y, out_x, in_x = fly, ox, ix
        break

    pts = [(sx, sy), (out_x, sy), (out_x, fly_y),
           (in_x, fly_y), (in_x, dy), (dx, dy)]
    tracks.add_h(sy, sx, out_x, e.net)
    tracks.add_v(out_x, sy, fly_y, e.net)
    tracks.add_h(fly_y, out_x, in_x, e.net)
    tracks.add_v(in_x, fly_y, dy, e.net)
    tracks.add_h(dy, in_x, dx, e.net)
    return _simplify(pts)
