"""
Маршрутизация сетями и ручные перегибы — этап 8 плана (§7.2).

Что здесь проверяется и почему именно это:

  * **веер укладывается деревом, а не пучком отдельных проводов.**
    Раньше каждое соединение шло само по себе, честной буквой «П».
    Провода одной сети накладываться ИМЕЮТ ПРАВО (это один сигнал), и на
    экране это почти похоже на ствол — но провода при этом длиннее, а
    ветвление нигде не обозначено. Замер: нарисованного провода на 20–49 %
    меньше, смотря по ширине веера;

  * **точки ветвления выпадают сами.** Их не назначают при укладке и не
    заводят под них сущность в документе (она попала бы в диффы синка):
    ветвление считается по НАРИСОВАННОМУ — там, где сходится больше двух
    отрезков или конец одного упирается в середину другого;

  * **порт — не ветвление.** Из выходного порта веера тоже выходит
    несколько проводов, но точка на порту читается как «здесь контакт», а
    контакт там и так нарисован портом;

  * **перекрёсток — не ветвление.** Провода разных сетей пересекаются, и
    кружок в этом месте показал бы соединение, которого нет;

  * **ручной перегиб исполняется, а не улучшается.** Автор поправил провод
    именно потому, что автомат его не устроил.
"""

from __future__ import annotations

import unittest

from core.graph.routing import STUB, TRACK_SEP, EdgeSpec, route_edges


def _fan(count: int, *, gap: float = 110.0):
    """Один выход → `count` входов; возвращает (rects, specs)."""
    rects = {"src": (0.0, 200.0, 180.0, 120.0)}
    specs = []
    for i in range(count):
        nid = f"dst{i}"
        rects[nid] = (420.0, 40.0 + i * gap, 180.0, 80.0)
        specs.append(EdgeSpec(key=f"e{i}", src=(180.0, 250.0),
                              dst=(420.0, 80.0 + i * gap),
                              net="src:out", src_node="src", dst_node=nid))
    return rects, specs


def _drawn_length(polylines) -> float:
    """
    Длина ПОКАЗАННОГО провода: общий участок считается один раз.

    Именно эту величину и уменьшает дерево. Сумма длин ломаных обманывает:
    у наложенных проводов она растёт, а на экране ничего не меняется.
    """
    lines: dict = {}
    for pts in polylines:
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) > 1e-6:
                lines.setdefault(("v", round(a[0], 3)), []).append(
                    (min(a[1], b[1]), max(a[1], b[1])))
            elif abs(a[1] - b[1]) < 1e-6 and abs(a[0] - b[0]) > 1e-6:
                lines.setdefault(("h", round(a[1], 3)), []).append(
                    (min(a[0], b[0]), max(a[0], b[0])))
    total = 0.0
    for spans in lines.values():
        spans.sort()
        lo, hi = spans[0]
        for s0, s1 in spans[1:]:
            if s0 <= hi + 1e-6:
                hi = max(hi, s1)
            else:
                total += hi - lo
                lo, hi = s0, s1
        total += hi - lo
    return total


def _orthogonal(route) -> bool:
    return all(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6
               for a, b in zip(route, route[1:]))


class NetIsRoutedAsATreeTests(unittest.TestCase):

    def test_every_branch_starts_and_ends_at_its_ports(self):
        rects, specs = _fan(4)
        result = route_edges(rects, specs)
        for s in specs:
            route = result.routes[s.key]
            self.assertEqual(route[0], s.src)
            self.assertEqual(route[-1], s.dst)
            self.assertTrue(_orthogonal(route), route)

    def test_branches_share_a_trunk(self):
        """
        Общий ствол — не совпадение, а смысл затеи: у всех ветвей есть
        общий вертикальный отрезок на одном X.
        """
        rects, specs = _fan(4)
        routes = route_edges(rects, specs).routes
        verticals = []
        for route in routes.values():
            xs = {round(a[0], 3) for a, b in zip(route, route[1:])
                  if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) > 1e-6}
            verticals.append(xs)
        common = set.intersection(*verticals)
        self.assertEqual(len(common), 1, f"ствол не один: {verticals}")

    def test_drawn_wire_is_shorter_than_the_bounding_detour(self):
        """
        Верхняя граница — длина, которую дал бы честный пучок из N букв
        «П» с разными вертикалями. Дерево обязано быть заметно короче.
        """
        rects, specs = _fan(6)
        drawn = _drawn_length(list(route_edges(rects, specs).routes.values()))
        naive = sum(abs(s.dst[0] - s.src[0]) + abs(s.dst[1] - s.src[1])
                    for s in specs)
        self.assertLess(drawn, naive * 0.75, f"{drawn:.0f} против {naive:.0f}")

    def test_a_single_edge_net_is_not_a_tree(self):
        """Одиночному проводу ветвиться не с чем, и кружка на нём быть не должно."""
        rects, specs = _fan(1)
        self.assertEqual(route_edges(rects, specs).junctions, {})


class JunctionsFallOutOfTheGeometryTests(unittest.TestCase):

    def test_count_matches_the_fan(self):
        """
        Веер из N ветвей даёт N−1 ветвление: два конца ствола — не
        развилки, а концы.
        """
        for count in (2, 3, 4, 6, 8):
            with self.subTest(count=count):
                rects, specs = _fan(count)
                result = route_edges(rects, specs)
                found = sum(len(v) for v in result.junctions.values())
                self.assertEqual(found, count - 1)

    def test_junctions_lie_on_the_trunk(self):
        rects, specs = _fan(5)
        result = route_edges(rects, specs)
        points = [p for v in result.junctions.values() for p in v]
        xs = {round(p[0], 3) for p in points}
        self.assertEqual(len(xs), 1, f"ветвления не на одной вертикали: {points}")

    def test_the_source_port_is_not_a_junction(self):
        """Контакт на порту и так нарисован портом."""
        rects, specs = _fan(4)
        result = route_edges(rects, specs)
        points = {(round(p[0], 3), round(p[1], 3))
                  for v in result.junctions.values() for p in v}
        self.assertNotIn((180.0, 250.0), points)

    def test_crossing_nets_are_not_junctions(self):
        """
        Провода РАЗНЫХ сетей пересекаются, и кружок там показал бы
        соединение, которого нет.
        """
        rects = {"a": (0.0, 0.0, 180.0, 80.0), "b": (0.0, 400.0, 180.0, 80.0),
                 "c": (500.0, 400.0, 180.0, 80.0), "d": (500.0, 0.0, 180.0, 80.0)}
        specs = [
            EdgeSpec(key="x", src=(180.0, 40.0), dst=(500.0, 440.0),
                     net="a:out", src_node="a", dst_node="c"),
            EdgeSpec(key="y", src=(180.0, 440.0), dst=(500.0, 40.0),
                     net="b:out", src_node="b", dst_node="d"),
        ]
        self.assertEqual(route_edges(rects, specs).junctions, {})

    def test_junctions_are_grouped_by_net(self):
        """Цвет точки берётся у её сети, поэтому хозяин известен сразу."""
        rects, specs = _fan(3)
        rects["src2"] = (0.0, 700.0, 180.0, 120.0)
        for i in range(2):
            nid = f"other{i}"
            rects[nid] = (420.0, 660.0 + i * 120.0, 180.0, 80.0)
            specs.append(EdgeSpec(key=f"o{i}", src=(180.0, 760.0),
                                  dst=(420.0, 700.0 + i * 120.0),
                                  net="src2:out", src_node="src2",
                                  dst_node=nid))
        result = route_edges(rects, specs)
        self.assertEqual(set(result.junctions), {"src:out", "src2:out"})


class ManualBendsAreObeyedTests(unittest.TestCase):

    RECTS = {"a": (0.0, 200.0, 180.0, 80.0), "b": (420.0, 200.0, 180.0, 80.0)}

    def _route(self, bends):
        spec = EdgeSpec(key="e", src=(180.0, 240.0), dst=(420.0, 240.0),
                        net="a:out", src_node="a", dst_node="b", bends=bends)
        return route_edges(self.RECTS, [spec]).routes["e"]

    def test_the_bend_is_on_the_route(self):
        """
        Точка обязана оказаться НА проводе. Ловится здесь тот случай,
        который и случился при разработке: колено в конце уводило провод
        обратно по той же вертикали, `_simplify` схлопывал шпиль, и
        ручная точка пропадала молча.
        """
        for bends in (((300.0, 120.0),),
                      ((300.0, 120.0), (360.0, 320.0)),
                      ((250.0, 400.0),)):
            with self.subTest(bends=bends):
                route = self._route(bends)
                for bend in bends:
                    self.assertIn(bend, route, route)

    def test_the_route_stays_orthogonal(self):
        route = self._route(((300.0, 120.0),))
        self.assertTrue(_orthogonal(route), route)

    def test_ports_are_still_the_ends(self):
        route = self._route(((300.0, 120.0),))
        self.assertEqual(route[0], (180.0, 240.0))
        self.assertEqual(route[-1], (420.0, 240.0))

    def test_it_enters_the_port_sideways(self):
        """Последний отрезок горизонтальный — иначе провод утыкается в тело."""
        route = self._route(((300.0, 120.0),))
        self.assertAlmostEqual(route[-1][1], route[-2][1])

    def test_without_bends_nothing_changes(self):
        self.assertEqual(self._route(()), [(180.0, 240.0), (420.0, 240.0)])

    def test_a_manual_edge_is_not_swallowed_by_the_tree(self):
        """
        Ручная поправка сильнее автомата, в том числе сильнее дерева:
        автор правил именно потому, что автомат его не устроил.
        """
        rects, specs = _fan(3)
        specs[1].bends = ((300.0, 20.0),)
        routes = route_edges(rects, specs).routes
        self.assertIn((300.0, 20.0), routes["e1"])

    def test_the_automat_sees_the_manual_track(self):
        """
        Ручная трасса кладётся первой и регистрируется: иначе автомат
        разложит свои провода и поправленный ляжет под ними.
        """
        rects, specs = _fan(2)
        specs[0].bends = ((300.0, 20.0),)
        result = route_edges(rects, specs)
        self.assertIn((300.0, 20.0), result.routes["e0"])
        self.assertTrue(_orthogonal(result.routes["e1"]))


class ResultShapeTests(unittest.TestCase):

    def test_result_is_not_a_dict_in_disguise(self):
        """
        Совместимости со «просто словарём» здесь нет намеренно. Пробовал
        `__getitem__` — и `set(result)` не упало, а тихо пошло по старому
        протоколу итерации и вернуло не то. Явная ошибка лучше.
        """
        rects, specs = _fan(2)
        result = route_edges(rects, specs)
        with self.assertRaises(TypeError):
            set(result)

    def test_stubs_and_separation_are_unchanged(self):
        self.assertGreater(STUB, 0)
        self.assertGreater(TRACK_SEP, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
