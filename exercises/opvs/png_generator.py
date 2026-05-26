"""
Генератор изображений логических схем по ГОСТ 2.743-91.

Гарантии трассировщика:
  • Все сегменты строго ортогональны (только горизонталь или вертикаль).
  • Горизонтальные сегменты разных трейсов не накладываются.
  • Вертикальные сегменты разных трейсов не накладываются.
  • Трейсы не перекрывают тела логических элементов.
  • Пересечение (горизонталь × вертикаль) допустимо, если ни один сегмент
    не заканчивается точно в точке пересечения.
"""

import random
from statistics import median
from dataclasses import dataclass, field
from typing import Optional, Set

from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

from sympy import Symbol, And, Or, Not, satisfiable
from sympy.core.expr import Expr as SympyExpr


# ─── Параметры ГОСТ 2.743-91 ─────────────────────────────────────────────────
GOST = {
    "gate_width":         60,   # ширина прямоугольника логического элемента
    "gate_height":        60,   # базовая высота (масштабируется под число входов)
    "layer_spacing":     180,   # шаг между столбцами слоёв по X
    "element_spacing":    90,   # шаг между центрами элементов одного слоя по Y
    "line_width":          2,   # толщина линий
    "font_size":          14,
    "avoidance_margin":   25,   # зазор вокруг элемента — трейсы не заходят ближе
    "track_separation":   15,   # минимальное расстояние между параллельными трейсами
    "min_port_spacing":   18,   # минимальный шаг между портами входов элемента
    "output_wire_length": 60,   # длина выходного проводника
    "flyover_margin":     45,   # отступ «перелётного» трека над верхними элементами
}

INPUT_RADIUS = 8   # радиус кружка входа / выхода схемы


# ─── Логический элемент ───────────────────────────────────────────────────────
class LogicElement:
    """Узел логической схемы. Поддерживает типы: INPUT, NOT, AND, OR."""

    def __init__(self, element_type: str, inputs=None, name: str = None):
        self.type     = element_type
        self.inputs   = inputs or []
        self.name     = name
        self.position = (0, 0)       # центр элемента на холсте (px)
        self.output_pos      = (0, 0)  # точка правого (выходного) вывода
        self.input_positions = []      # точки левых (входных) выводов
        self.size = self._compute_size()

    # ── размер элемента ───────────────────────────────────────────────────────
    def _compute_size(self) -> tuple:
        if self.type == 'INPUT':
            return (30, 30)
        if self.type == 'NOT':
            # NOT всегда одновходовой — фиксированный размер + кружок инверсии
            return (GOST["gate_width"] + 10, GOST["gate_height"])
        # AND / OR: высота масштабируется под количество входов
        n = max(1, len(self.inputs))
        h = max(GOST["gate_height"],
                (n - 1) * GOST["min_port_spacing"] + 20)
        return (GOST["gate_width"], h)

    # ── ограничивающий прямоугольник (для проверки наложений) ────────────────
    def get_bounding_box(self) -> tuple:
        x, y = self.position
        w, h = self.size
        hw, hh = w // 2, h // 2
        if self.type == 'INPUT':
            r = INPUT_RADIUS
            return (x - r, y - r, x + r, y + r)
        return (x - hw - 10, y - hh - 10,
                x + hw + 10, y + hh + 10)

    # ── отрисовка элемента ────────────────────────────────────────────────────
    def draw(self, draw_ctx):
        """Рисует элемент и заполняет output_pos / input_positions."""
        x, y = self.position
        w, h = self.size
        hw, hh = w // 2, h // 2

        if self.type == 'INPUT':
            r = INPUT_RADIUS
            draw_ctx.ellipse([x - r, y - r, x + r, y + r],
                             outline="black", width=GOST["line_width"])
            draw_ctx.text((x - 25, y - 7), self.name,
                          fill="black", font=self._font())
            self.output_pos = (x + r, y)

        elif self.type == 'NOT':
            draw_ctx.rectangle([x - hw, y - hh, x + hw, y + hh],
                               outline="black", width=GOST["line_width"])
            cx = x + hw
            draw_ctx.ellipse([cx - 5, y - 5, cx + 5, y + 5],
                             outline="black", width=GOST["line_width"])
            self.output_pos      = (cx + 5, y)
            self.input_positions = [(x - hw + 5, y)]

        else:  # AND / OR
            draw_ctx.rectangle([x - hw, y - hh, x + hw, y + hh],
                               outline="black", width=GOST["line_width"])
            label = "&" if self.type == "AND" else "1"
            lx = x - (7 if label == "&" else 5)
            draw_ctx.text((lx, y - 7), label,
                          fill="black", font=self._font())
            self.output_pos = (x + hw, y)

            n = len(self.inputs)
            if n <= 1:
                self.input_positions = [(x - hw + 5, y)]
            else:
                # Равномерно распределяем порты по высоте элемента
                spacing = (h - 10) / (n - 1)
                self.input_positions = [
                    (x - hw + 5,
                     int(round(y + (i - (n - 1) / 2) * spacing)))
                    for i in range(n)
                ]

    def _font(self):
        try:
            return ImageFont.truetype("arial.ttf", GOST["font_size"])
        except Exception:
            return ImageFont.load_default()

    # ── логическое выражение ──────────────────────────────────────────────────
    def get_logic_str(self) -> str:
        if self.type == "INPUT":
            return self.name
        if self.type == "NOT":
            return f"not({self.inputs[0].get_logic_str()})"
        sep = " ^ " if self.type == "AND" else " v "
        return "(" + sep.join(i.get_logic_str() for i in self.inputs) + ")"

    def to_sympy(self) -> SympyExpr:
        """
        Рекурсивно строит символьное выражение sympy из дерева логических элементов.

        Используется модулем валидации для верификации булевой эквивалентности.
        Поддерживаемые типы: INPUT → Symbol, NOT → Not, AND → And, OR → Or.
        """
        if self.type == "INPUT":
            return Symbol(self.name)
        if self.type == "NOT":
            return Not(self.inputs[0].to_sympy())
        operands = [inp.to_sympy() for inp in self.inputs]
        if self.type == "AND":
            return And(*operands)
        if self.type == "OR":
            return Or(*operands)
        raise ValueError(f"Неизвестный тип элемента: {self.type}")

    def __eq__(self, other):
        return (isinstance(other, LogicElement)
                and self.type   == other.type
                and self.name   == other.name
                and self.inputs == other.inputs)

    # Хэш по идентификатору объекта: каждый экземпляр уникален
    # (определение __eq__ без __hash__ делает объект не-хэшируемым)
    __hash__ = object.__hash__

    def __repr__(self):
        body = self.name if self.name else ", ".join(map(str, self.inputs))
        return f"{self.type}({body})"

    __str__ = __repr__


# ─── Результат символьной валидации ──────────────────────────────────────────
@dataclass
class ValidationResult:
    """
    Сводка результатов символьной верификации логической схемы.

    Атрибуты:
        valid         — True, если схема прошла все проверки.
        satisfiable   — True, если функция выполнима (не противоречие).
        tautology     — True, если функция является тавтологией (всегда True).
        missing_vars  — Переменные, объявленные на входе, но не вошедшие
                        в итоговое выражение.
        sympy_expr    — Построенное символьное выражение.
        error         — Сообщение об ошибке, если valid == False.
    """
    valid:        bool
    satisfiable:  bool
    tautology:    bool
    missing_vars: Set[str]
    sympy_expr:   Optional[SympyExpr]
    error:        str = ""


def validate_circuit(elements: list) -> ValidationResult:
    """
    Символьная верификация сгенерированной логической схемы.

    Алгоритм проверки:
      1. Рекурсивный обход DAG через ``to_sympy()`` — строится символьное
         выражение sympy, независимое от текстового представления.
      2. Проверка выполнимости (satisfiable): функция не должна быть
         противоречием (всегда False), иначе схема бессмысленна.
      3. Проверка нетавтологичности: функция не должна быть тавтологией
         (всегда True), так как такое задание лишено учебной ценности.
      4. Проверка полноты: каждая входная переменная обязана присутствовать
         в итоговом выражении; «мёртвый» вход сигнализирует об ошибке
         генератора.

    Булева эквивалентность между деревом элементов и выражением гарантируется
    тем, что ``to_sympy()`` обходит тот же DAG, что используется при
    отрисовке, — верификация обнаруживает структурные нарушения дерева
    (например, не подключённые узлы).

    Аргументы:
        elements — список LogicElement в топологическом порядке
                   (последний элемент — корень схемы).

    Возвращает:
        ValidationResult с подробным описанием результата.
    """
    root   = elements[-1]
    inputs = [e for e in elements if e.type == "INPUT"]

    try:
        expr = root.to_sympy()
    except Exception as exc:
        return ValidationResult(
            valid=False, satisfiable=False, tautology=False,
            missing_vars=set(), sympy_expr=None,
            error=f"Ошибка построения sympy-выражения: {exc}"
        )

    # ── 1. Выполнимость ───────────────────────────────────────────────────────
    is_sat = bool(satisfiable(expr))

    # ── 2. Нетавтологичность (¬F должна быть выполнима) ─────────────────────
    is_tautology = not bool(satisfiable(Not(expr)))

    # ── 3. Полнота входных переменных ─────────────────────────────────────────
    declared  = {Symbol(e.name) for e in inputs}
    used      = expr.free_symbols
    missing   = {str(s) for s in declared - used}

    # ── Формируем итоговый результат ──────────────────────────────────────────
    errors = []
    if not is_sat:
        errors.append("функция является противоречием (всегда False)")
    if is_tautology:
        errors.append("функция является тавтологией (всегда True)")
    if missing:
        errors.append(f"переменные не вошли в выражение: {sorted(missing)}")

    valid = not errors
    return ValidationResult(
        valid=valid,
        satisfiable=is_sat,
        tautology=is_tautology,
        missing_vars=missing,
        sympy_expr=expr,
        error="; ".join(errors) if errors else ""
    )


# ─── Генерация случайной логической функции ───────────────────────────────────
def make_function(max_attempts: int = 20) -> list:
    """
    Генерирует трёхслойную логическую схему для функции от 3-4 переменных.

    Структура:
      Слой 0: входные переменные (A, B, C[, D])
      Слой 1: 2-3 вентиля над входными переменными
      Слой 2: 1-2 вентиля над первым слоем
      Слой 3: выходной вентиль, объединяющий незадействованные узлы

    После построения DAG выполняется символьная верификация через
    ``validate_circuit()``. Если схема является тавтологией, противоречием
    или содержит мёртвые входы — генерация повторяется (до max_attempts раз).

    Возвращает список элементов в топологическом порядке.
    Вызывает RuntimeError, если за max_attempts попыток не удалось
    получить валидную схему.
    """
    for attempt in range(1, max_attempts + 1):
        elements = _build_random_circuit()
        vr = validate_circuit(elements)
        if vr.valid:
            return elements
        # Генерация повторяется — ошибочная схема отбрасывается
    raise RuntimeError(
        f"Не удалось сгенерировать валидную схему за {max_attempts} попыток."
    )


def _build_random_circuit() -> list:
    """Одна попытка стохастической сборки DAG (вызывается из make_function)."""
    n_inputs = random.randint(3, 4)
    inputs   = [LogicElement('INPUT', name=chr(ord('A') + i))
                for i in range(n_inputs)]
    unused   = list(inputs)    # элементы без потребителя на текущий момент
    used_not = []              # предотвращаем дублирующиеся NOT-вентили

    def _make_gate(pool: list) -> LogicElement:
        """Создаёт случайный вентиль с входами из pool."""
        gtype = random.choice(["AND", "AND", "OR", "OR", "NOT"])
        if gtype == "NOT":
            sample = [random.choice(pool)]
            if sample in used_not:
                gtype  = random.choice(["AND", "OR"])
                sample = random.sample(pool, k=min(2, len(pool)))
            else:
                used_not.append(sample)
        else:
            sample = random.sample(pool, k=min(2, len(pool)))
        return LogicElement(gtype, inputs=sample)

    # Слой 1
    first_layer = []
    for _ in range(random.randint(2, 3)):
        gate = _make_gate(inputs)
        for e in gate.inputs:
            try: unused.remove(e)
            except ValueError: pass
        first_layer.append(gate)
        unused.append(gate)

    # Слой 2 (входы берём из первого слоя, а не из raw inputs — исправлен баг)
    second_layer = []
    for _ in range(random.randint(1, 2)):
        gate = _make_gate(first_layer)
        for e in gate.inputs:
            try: unused.remove(e)
            except ValueError: pass
        second_layer.append(gate)
        unused.append(gate)

    # Выходной вентиль: принимает все узлы без потребителя
    root_type = random.choice(["AND", "OR"])
    root      = LogicElement(root_type, inputs=list(unused))

    return inputs + first_layer + second_layer + [root]


# ─── Разметка уровней ─────────────────────────────────────────────────────────
def _calc_levels(elements: list) -> dict:
    """
    Возвращает {level: [elements]} согласно топологической сортировке.
    Уровень элемента = max(уровень входов) + 1; для INPUT — 0.
    """
    levels = defaultdict(list)
    for elem in elements:
        if elem.type == 'INPUT':
            lvl = 0
        elif not elem.inputs:
            lvl = 1
        else:
            lvl = max(
                next((l for l, es in levels.items() if inp in es), 0) + 1
                for inp in elem.inputs
            )
        levels[lvl].append(elem)
    return levels


# ─── Расчёт позиций на холсте ─────────────────────────────────────────────────
def calculate_positions(elements: list) -> tuple:
    """
    Расставляет элементы по сетке слоёв.
    Возвращает (ширина_холста, высота_холста) в пикселях.
    """
    levels    = _calc_levels(elements)
    max_level = max(levels)
    max_count = max(len(v) for v in levels.values())

    canvas_w = int((max_level + 1) * GOST["layer_spacing"] + 300)
    canvas_h = int(max(600, max_count * GOST["element_spacing"] + 300))

    for level in sorted(levels):
        x     = 120 + level * GOST["layer_spacing"]
        layer = levels[level]

        if level == 0:
            layer.sort(key=lambda e: e.name or '')
        else:
            def _median_input_y(e):
                """
                Медианная Y-координата входов элемента.

                Медиана устойчивее к выбросам, чем среднее: при нечётном числе
                входов она точно совпадает с Y-координатой центрального входа,
                что снижает число пересечений соединительных линий по сравнению
                со средним арифметическим.
                """
                ys = sorted(inp.position[1] for inp in e.inputs)
                return median(ys) if ys else 0.0
            layer.sort(key=_median_input_y)

        for i, elem in enumerate(layer):
            elem.position = (x, 150 + i * GOST["element_spacing"])

    return canvas_w, canvas_h


# ─── Вспомогательные функции для трассировки ─────────────────────────────────

def _h_overlaps(seg1: tuple, seg2: tuple) -> bool:
    """
    Два горизонтальных сегмента (y, x_min, x_max) накладываются?

    Наложение засчитывается только при общем участке длиннее нуля
    (касание в одной точке — допустимо).
    """
    y1, a0, a1 = seg1
    y2, b0, b1 = seg2
    if abs(y1 - y2) >= GOST["track_separation"]:
        return False
    return max(a0, b0) < min(a1, b1)   # строгое неравенство


def _v_overlaps(seg1: tuple, seg2: tuple) -> bool:
    """
    Два вертикальных сегмента (x, y_min, y_max) накладываются?
    """
    x1, a0, a1 = seg1
    x2, b0, b1 = seg2
    a0, a1 = min(a0, a1), max(a0, a1)
    b0, b1 = min(b0, b1), max(b0, b1)
    if abs(x1 - x2) >= GOST["track_separation"]:
        return False
    return max(a0, b0) < min(a1, b1)


def _find_free_y(y_hint: int,
                 h_tracks: list,
                 x0: int, x1: int,
                 direction: int = -1,
                 max_iter: int = 30) -> int:
    """
    Ищет ближайший к y_hint свободный горизонтальный уровень
    для сегмента с X-диапазоном [x0, x1].
    Двигается в сторону direction (−1 = вверх, +1 = вниз).
    """
    y = y_hint
    for _ in range(max_iter):
        test = (y, min(x0, x1), max(x0, x1))
        if not any(_h_overlaps(test, ex) for ex in h_tracks):
            return y
        y += direction * GOST["track_separation"]
    return y


def _find_free_x_vert(x_hint: int,
                      v_tracks: list,
                      y0: int, y1: int,
                      direction: int,
                      max_iter: int = 20) -> int:
    """
    Ищет свободную X-позицию для вертикального сегмента [y0, y1].
    """
    x = x_hint
    for _ in range(max_iter):
        test = (x, min(y0, y1), max(y0, y1))
        if not any(_v_overlaps(test, ex) for ex in v_tracks):
            return x
        x += direction * GOST["track_separation"]
    return x


# ─── Трассировка соединений ───────────────────────────────────────────────────
def route_connections(elements: list) -> list:
    """
    Строит строго ортогональные маршруты соединений.

    Алгоритм (смежные слои, diff == 1):
      Сортируем соединения по start_y по возрастанию и назначаем track_x
      в убывающем порядке (меньший start_y → правее трек). Это гарантирует,
      что горизонтальные сегменты на одной Y-координате имеют
      непересекающиеся X-диапазоны:
        — сегмент «от источника до трека» верхнего элемента идёт вправо
          до высокого track_x;
        — сегмент «от трека до получателя» нижнего источника заканчивается
          на низком (левом) track_x.
      Поскольку высокий track_x > низкий track_x, диапазоны не пересекаются.

    Алгоритм (несмежные слои, diff > 1):
      Дальний источник → dest_x ближе к gate; ближний → дальше. Это
      устраняет пересечения вертикальных спусков к элементу назначения.
      Перелётный горизонтальный сегмент расположен выше всех промежуточных
      элементов и проверяется на свободность перед добавлением.

    Возвращает список (route_points, src_element, dest_element).
    """
    levels   = _calc_levels(elements)
    level_of = {e: lvl for lvl, es in levels.items() for e in es}

    # ── собираем все соединения ───────────────────────────────────────────────
    connections = []
    for dest in elements:
        if dest.type == 'INPUT' or not dest.inputs:
            continue
        for i, src in enumerate(dest.inputs):
            start = (int(round(src.output_pos[0])),
                     int(round(src.output_pos[1])))
            if i < len(dest.input_positions):
                end = (int(round(dest.input_positions[i][0])),
                       int(round(dest.input_positions[i][1])))
            else:
                end = (int(dest.position[0] - dest.size[0] // 2 - 5),
                       int(dest.position[1]))
            connections.append((start, end, src, dest))

    # ── группируем по парам слоёв и обрабатываем сначала смежные ─────────────
    by_pair = defaultdict(list)
    for conn in connections:
        sl = level_of[conn[2]]
        dl = level_of[conn[3]]
        by_pair[(sl, dl)].append(conn)

    h_tracks = []   # зарегистрированные горизонтальные сегменты (y, x0, x1)
    v_tracks = []   # зарегистрированные вертикальные   сегменты (x, y0, y1)
    all_routes = []

    sorted_pairs = sorted(by_pair, key=lambda p: (p[1] - p[0], p[0]))

    for (sl, dl) in sorted_pairs:
        conns    = by_pair[(sl, dl)]
        diff     = dl - sl
        src_cx   = 120 + sl * GOST["layer_spacing"]
        dst_cx   = 120 + dl * GOST["layer_spacing"]

        # ── СМЕЖНЫЕ СЛОИ (diff == 1) ──────────────────────────────────────────
        if diff == 1:
            # Канал для вертикальных сегментов между двумя слоями
            if sl == 0:
                ch_left = src_cx + INPUT_RADIUS + GOST["avoidance_margin"]
            else:
                ch_left = src_cx + GOST["gate_width"] // 2 + GOST["avoidance_margin"]
            ch_right = dst_cx - GOST["gate_width"] // 2 - GOST["avoidance_margin"]
            if ch_left >= ch_right:
                ch_left  = src_cx + 25
                ch_right = dst_cx - 25
            ch_w = ch_right - ch_left

            # ── КЛЮЧЕВОЕ ПРАВИЛО предотвращения наложений ─────────────────────
            # Сортируем по start_y возрастающе; назначаем track_x убывающе.
            # Тогда для двух соединений A (start_y=150→end_y=240)
            # и B (start_y=240→end_y=330):
            #   A получает track_x = правый → его сегмент к gate идёт [track_A, gate_x]
            #   B получает track_x = левый  → его сегмент от src идёт  [src_x,  track_B]
            # Поскольку track_A > track_B, диапазоны на y=240 не пересекаются.
            sorted_c = sorted(conns, key=lambda c: c[0][1])   # asc по start_y
            n = len(sorted_c)

            for idx, (start, end, src, dest) in enumerate(sorted_c):
                # idx=0 (наименьший start_y) → слот (n-1) → правее
                slot = n - 1 - idx
                if n > 1:
                    track_x = int(ch_left + (slot + 0.5) * (ch_w / n))
                else:
                    track_x = int((ch_left + ch_right) / 2)

                seg1_y = start[1]
                seg2_y = end[1]

                # Регистрируем первый горизонтальный и вертикальный сегменты
                h_tracks.append((seg1_y,
                                  min(start[0], track_x),
                                  max(start[0], track_x)))
                v_tracks.append((track_x,
                                  min(seg1_y, seg2_y),
                                  max(seg1_y, seg2_y)))

                # Проверяем второй горизонтальный сегмент на наложение
                seg2_test = (seg2_y,
                             min(track_x, end[0]),
                             max(track_x, end[0]))
                if any(_h_overlaps(seg2_test, ex) for ex in h_tracks):
                    # Ищем свободный уровень чуть выше (обходной маршрут)
                    alt_y = _find_free_y(
                        seg2_y - GOST["track_separation"],
                        h_tracks, track_x, end[0],
                        direction=-1
                    )
                    # X-позиция «перед воротами» — в канале, не внутри элемента
                    pre_x = max(track_x + GOST["track_separation"],
                                end[0] - GOST["avoidance_margin"])

                    route = [
                        (start[0], seg1_y),
                        (track_x,  seg1_y),
                        (track_x,  alt_y),
                        (pre_x,    alt_y),
                        (pre_x,    seg2_y),
                        (end[0],   seg2_y),
                    ]
                    h_tracks.append((alt_y,
                                      min(track_x, pre_x),
                                      max(track_x, pre_x)))
                    h_tracks.append((seg2_y,
                                      min(pre_x, end[0]),
                                      max(pre_x, end[0])))
                    v_tracks.append((pre_x,
                                      min(alt_y, seg2_y),
                                      max(alt_y, seg2_y)))
                else:
                    route = [
                        (start[0], seg1_y),
                        (track_x,  seg1_y),
                        (track_x,  seg2_y),
                        (end[0],   seg2_y),
                    ]
                    h_tracks.append((seg2_y,
                                      min(track_x, end[0]),
                                      max(track_x, end[0])))

                all_routes.append((route, src, dest))

        # ── НЕСМЕЖНЫЕ СЛОИ (diff > 1) ─────────────────────────────────────────
        else:
            # Y для «перелётного» горизонтального сегмента — над всеми
            # промежуточными и исходными элементами.
            all_mid_ys = []
            for mid_l in range(sl, dl):
                for e in levels.get(mid_l, []):
                    all_mid_ys.append(e.position[1])
            fly_y_base = (min(all_mid_ys) - GOST["flyover_margin"]
                          if all_mid_ys else 100)

            # Сортируем: дальний источник (меньший sl) первым.
            # Дальний → dest_x ближе к gate (меньший отступ);
            # ближний → dest_x дальше от gate (больший отступ).
            # Это исключает перекрёстные вертикали у элемента-получателя.
            sorted_c = sorted(conns, key=lambda c: level_of[c[2]])

            gate_left = int(dst_cx - GOST["gate_width"] // 2)

            for idx, (start, end, src, dest) in enumerate(sorted_c):
                # dest_x: дальний (idx=0) → ближе к gate (малый отступ)
                dest_x_base = (gate_left
                               - GOST["avoidance_margin"]
                               - idx * GOST["track_separation"])

                # bend_x: горизонтальный отступ от источника
                if sl == 0:
                    bend_x_base = (src_cx + INPUT_RADIUS
                                   + GOST["avoidance_margin"]
                                   + idx * GOST["track_separation"])
                else:
                    bend_x_base = (src_cx + GOST["gate_width"] // 2
                                   + GOST["avoidance_margin"]
                                   + idx * GOST["track_separation"])

                # Высота перелёта для этого трейса
                fly_y_hint = fly_y_base - idx * GOST["track_separation"]

                # Подбираем свободный горизонтальный уровень
                fly_y = _find_free_y(
                    fly_y_hint, h_tracks,
                    bend_x_base, dest_x_base,
                    direction=-1
                )

                # Подбираем свободный bend_x (вертикальный подъём)
                bend_x = _find_free_x_vert(
                    bend_x_base, v_tracks,
                    start[1], fly_y,
                    direction=+1
                )

                # Подбираем свободный dest_x (вертикальный спуск)
                dest_x = _find_free_x_vert(
                    dest_x_base, v_tracks,
                    fly_y, end[1],
                    direction=-1
                )

                route = [
                    (start[0], start[1]),
                    (bend_x,   start[1]),
                    (bend_x,   fly_y),
                    (dest_x,   fly_y),
                    (dest_x,   end[1]),
                    (end[0],   end[1]),
                ]

                h_tracks.append((start[1],
                                  min(start[0], bend_x),
                                  max(start[0], bend_x)))
                h_tracks.append((fly_y,
                                  min(bend_x, dest_x),
                                  max(bend_x, dest_x)))
                h_tracks.append((end[1],
                                  min(dest_x, end[0]),
                                  max(dest_x, end[0])))
                v_tracks.append((bend_x,
                                  min(start[1], fly_y),
                                  max(start[1], fly_y)))
                v_tracks.append((dest_x,
                                  min(fly_y, end[1]),
                                  max(fly_y, end[1])))

                all_routes.append((route, src, dest))

    return all_routes


# ─── Отрисовка схемы ──────────────────────────────────────────────────────────
def render_circuit(elements: list):
    """
    Отрисовать схему и вернуть готовый PIL.Image, не сохраняя на диск.

    Это «сердце» рендера. Используется адаптерами, которым нужен объект
    изображения в памяти (например, для упаковки в ImageBlock).
    """
    canvas_w, canvas_h = calculate_positions(elements)
    img  = Image.new('RGB', (canvas_w, canvas_h), 'white')
    draw = ImageDraw.Draw(img)

    # 1. Отрисовываем элементы (заполняет output_pos и input_positions)
    for elem in elements:
        elem.draw(draw)

    # 2. Трассируем и рисуем соединения
    routes = route_connections(elements)
    for route, _src, _dest in routes:
        for i in range(len(route) - 1):
            draw.line([route[i], route[i + 1]],
                      fill="black", width=GOST["line_width"])

    # 3. Выходной проводник и кружок (по ГОСТ — такой же, как у входной переменной)
    levels     = _calc_levels(elements)
    last_layer = levels[max(levels)]
    if last_layer:
        out_elem   = last_layer[0]
        ox, oy     = out_elem.output_pos
        wire_end_x = ox + GOST["output_wire_length"]

        # Горизонтальный проводник от выхода последнего элемента
        draw.line([(ox, oy), (wire_end_x, oy)],
                  fill="black", width=GOST["line_width"])

        # Незаполненный кружок выхода (идентичен кружку входной переменной)
        r = INPUT_RADIUS
        draw.ellipse([wire_end_x - r, oy - r,
                      wire_end_x + r, oy + r],
                     outline="black", width=GOST["line_width"])

    # 4. Заголовок схемы
    font = elements[0]._font() if elements else ImageFont.load_default()
    draw.text((50, 20), elements[-1].get_logic_str(),
              fill="black", font=font)

    return img


def draw_circuit(elements: list, filename: str):
    """
    Вычисляет позиции, трассирует соединения и сохраняет схему в PNG-файл.

    Старый API сохранён: рендерим через render_circuit и сохраняем.
    """
    img = render_circuit(elements)
    img.save(filename)
    return img


# === ДЕМОНСТРАЦИЯ: Генерация 150 схем с замером времени ===
if __name__ == "__main__":
    import time
    import os

    # Создаём папку для результатов, если нет
    output_dir = "generated_schemes"
    os.makedirs(output_dir, exist_ok=True)

    NUM_IMAGES = 150
    print(f"Начинаю генерацию {NUM_IMAGES} схем...")

    # Замеряем время
    start_time = time.time()

    for i in range(NUM_IMAGES):
        # Генерируем новую функцию и схему
        circ = make_function()
        filename = os.path.join(output_dir, f"logic_circuit_{i + 1:03d}.png")
        draw_circuit(circ, filename)

        # Прогресс каждые 25 изображений
        if (i + 1) % 25 == 0:
            print(f"Сгенерировано: {i + 1}/{NUM_IMAGES}")

    # Конец замера
    end_time = time.time()
    total_seconds = end_time - start_time

    # Вывод результатов
    print(f"\n✅ Готово! Сгенерировано {NUM_IMAGES} схем.")
    print(f"⏱️  Общее время: {total_seconds:.2f} секунд")
    print(f"📊 Среднее время на схему: {total_seconds / NUM_IMAGES:.3f} сек")
    print(f"🚀 Производительность: {NUM_IMAGES / total_seconds:.2f} схем/сек")
    print(f"📁 Результаты сохранены в папке: {output_dir}/")