"""
Узлы линейной алгебры (категория linalg).

Матрицы переносятся между узлами через PortType.MATRIX как объекты sympy.Matrix
(round-trip без потерь). Вектор — это матрица-столбец n×1 (то же значение типа
MATRIX), так что матричные операции (например, A·v) работают с векторами без
конверсий. Рендер в задание — узлом matrix_block (MATRIX→BLOCK через FormulaBlock
с окружением pmatrix).

PR-1 (ядро + алгебра): источники (matrix_const, random_matrix, identity),
операции (det/inverse/transpose/rank/mul/add/scalar/power), рендер. Системы и
операторы (rref/solve/eigen/nullspace) и вектор-геометрия (dot/cross/нормы,
прямые/плоскости) — следующими PR того же образца.

sympy импортируется лениво (см. core.graph.symbolic): движок графа headless.
"""

from __future__ import annotations

import math

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType
from ..symbolic import (
    as_expr, as_matrix, build_symbols, is_matrix, parse_matrix,
    substitute_values, sympy, to_latex,
)


# ---------- Источники ----------

class MatrixConstNode(Node):
    """
    Матрица из текста. Строки разделяются ';', элементы — ','. Например
    '1,2;3,4'; вектор-столбец '1;2;3'. Элементы могут быть буквами-плейсхолдерами
    ('a,1;0,b') — тогда подключите вход values (NUMBER_DICT, напр. от var_dict со
    случайными числами), и они подставятся: так получается случайная матрица
    нужной структуры. Без values — литерал как есть. Источник MATRIX.
    """
    type_id = "matrix_const"
    category = "linalg"
    display_name = "Матрица"
    description = ("Матрица из текста '1,2;3,4'. Буквы-плейсхолдеры + вход values "
                   "(NUMBER_DICT) → случайные значения. Выход: MATRIX.")
    INPUTS = [Port("values", PortType.NUMBER_DICT, required=False)]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"data": {"type": "string", "default": "1,0;0,1"}}

    def validate_params(self) -> None:
        parse_matrix(self.params.get("data", ""))

    def compute(self, inputs, ctx: ExecContext):
        M = parse_matrix(self.params.get("data", ""))
        return {"out": substitute_values(M, inputs.get("values"))}


class RandomMatrixNode(Node):
    """
    Случайная «красивая» целочисленная матрица. Источник MATRIX.

    Параметры: rows, cols; min/max — диапазон элементов; invertible — требовать
    квадратную невырожденную матрицу с небольшим определителем (для обратимых
    задач). Воспроизводимость — через ctx.rng (как у random_natural).
    """
    type_id = "random_matrix"
    category = "linalg"
    display_name = "Случайная матрица"
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {
        "rows": {"type": "int", "default": 3},
        "cols": {"type": "int", "default": 3},
        "min": {"type": "int", "default": -3, "optional": True},
        "max": {"type": "int", "default": 3, "optional": True},
        "invertible": {"type": "enum", "values": ["no", "yes"], "default": "no",
                       "optional": True},
        "max_det": {"type": "int", "default": 12, "optional": True},
    }

    def validate_params(self) -> None:
        for k in ("rows", "cols"):
            try:
                if int(self.params.get(k, 3)) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                raise GraphValidationError(
                    f"Узел {self.node_id!r}: {k} должно быть целым ≥ 1."
                )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        rows = int(self.params.get("rows", 3))
        cols = int(self.params.get("cols", 3))
        lo = int(self.params.get("min", -3))
        hi = int(self.params.get("max", 3))
        invertible = str(self.params.get("invertible", "no")) == "yes"
        try:
            cap = int(self.params.get("max_det", 12))
        except (TypeError, ValueError):
            cap = 12
        rng = ctx.rng

        def draw():
            return sp.Matrix([[rng.randint(lo, hi) for _ in range(cols)]
                              for _ in range(rows)])

        if not invertible:
            return {"out": draw()}
        if rows != cols:
            raise RetryGeneration(
                f"random_matrix {self.node_id!r}: обратимая матрица должна быть квадратной."
            )
        for _ in range(300):
            M = draw()
            d = M.det()
            if d != 0 and abs(int(d)) <= cap:
                return {"out": M}
        raise RetryGeneration(
            f"random_matrix {self.node_id!r}: не удалось подобрать обратимую матрицу."
        )


class IdentityNode(Node):
    """Единичная матрица n×n. Источник MATRIX."""
    type_id = "identity"
    category = "linalg"
    display_name = "Единичная матрица"
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"size": {"type": "int", "default": 3}}

    def validate_params(self) -> None:
        try:
            if int(self.params.get("size", 3)) < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: size должно быть целым ≥ 1."
            )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        return {"out": sp.eye(int(self.params.get("size", 3)))}


class ListToMatrixNode(Node):
    """
    Собрать матрицу из плоского списка чисел (построчно). Вход items:LIST —
    например, индексированный туннель вывода цикла (числа, накопленные по
    итерациям). Форма: rows/cols параметрами или входами; достаточно одного —
    второй выводится из длины списка; без обоих список должен быть полным
    квадратом (n² элементов → n×n). Несоответствие длины форме или нечисловой
    элемент → RetryGeneration (данные зависят от генерации). Выход MATRIX.
    """
    type_id = "list_to_matrix"
    category = "linalg"
    display_name = "Список → матрица"
    description = ("Плоский список чисел → матрица rows×cols (построчно). "
                   "Достаточно одного из rows/cols — второй выводится из длины; "
                   "без обоих — квадратная. Вход: LIST (+ rows/cols NUMBER). "
                   "Выход: MATRIX.")
    INPUTS = [
        Port("items", PortType.LIST),
        Port("rows", PortType.NUMBER, required=False),
        Port("cols", PortType.NUMBER, required=False),
    ]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {
        "rows": {"type": "int", "default": 0, "optional": True},
        "cols": {"type": "int", "default": 0, "optional": True},
    }

    def _dim(self, inputs, key: str) -> int:
        """Размер из входа (приоритетно) или параметра; ≤ 0 — не задан."""
        raw = inputs.get(key, self.params.get(key, 0))
        try:
            return int(round(float(raw)))
        except (TypeError, ValueError):
            return 0

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        items = inputs.get("items")
        if not isinstance(items, (list, tuple)):
            raise RetryGeneration(
                f"list_to_matrix {self.node_id!r}: на входе items не список "
                f"({type(items).__name__})."
            )
        vals = []
        for v in items:
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise RetryGeneration(
                    f"list_to_matrix {self.node_id!r}: элемент {v!r} не число."
                )
            vals.append(sp.Integer(round(f)) if abs(f - round(f)) < 1e-9
                        else sp.nsimplify(f, rational=True))

        n = len(vals)
        rows, cols = self._dim(inputs, "rows"), self._dim(inputs, "cols")
        if rows <= 0 and cols <= 0:
            side = math.isqrt(n) if n else 0
            if n == 0 or side * side != n:
                raise RetryGeneration(
                    f"list_to_matrix {self.node_id!r}: {n} элементов не образуют "
                    f"квадратную матрицу — задайте rows или cols."
                )
            rows = cols = int(side)
        elif rows <= 0:
            rows = n // cols if cols and n % cols == 0 else 0
        elif cols <= 0:
            cols = n // rows if rows and n % rows == 0 else 0
        if rows <= 0 or cols <= 0 or rows * cols != n:
            raise RetryGeneration(
                f"list_to_matrix {self.node_id!r}: {n} элементов не укладываются "
                f"в форму {rows or '?'}×{cols or '?'}."
            )
        return {"out": sp.Matrix(rows, cols, vals)}


# ---------- Операции над одной матрицей (MATRIX → …) ----------

class DeterminantNode(Node):
    """Определитель квадратной матрицы (MATRIX → EXPR)."""
    type_id = "matrix_det"
    category = "linalg"
    display_name = "Определитель"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_det {self.node_id!r}: матрица не квадратная.")
        return {"out": M.det()}


class InverseNode(Node):
    """Обратная матрица (MATRIX → MATRIX). Для вырожденной — пере-генерация."""
    type_id = "matrix_inv"
    category = "linalg"
    display_name = "Обратная матрица"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_inv {self.node_id!r}: матрица не квадратная.")
        try:
            if M.det() == 0:
                raise RetryGeneration(f"matrix_inv {self.node_id!r}: матрица вырождена.")
            return {"out": M.inv()}
        except RetryGeneration:
            raise
        except Exception as e:
            raise RetryGeneration(f"matrix_inv {self.node_id!r}: {e}")


class TransposeNode(Node):
    """Транспонирование (MATRIX → MATRIX)."""
    type_id = "matrix_transpose"
    category = "linalg"
    display_name = "Транспонирование"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": as_matrix(inputs["in"]).T}


class RankNode(Node):
    """Ранг матрицы (MATRIX → NUMBER)."""
    type_id = "matrix_rank"
    category = "linalg"
    display_name = "Ранг"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(as_matrix(inputs["in"]).rank())}


class TraceNode(Node):
    """След (сумма диагонали) квадратной матрицы (MATRIX → EXPR)."""
    type_id = "matrix_trace"
    category = "linalg"
    display_name = "След"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_trace {self.node_id!r}: матрица не квадратная.")
        return {"out": M.trace()}


class ScalarMultiplyNode(Node):
    """Умножение матрицы на скаляр (MATRIX × NUMBER → MATRIX)."""
    type_id = "matrix_scalar"
    category = "linalg"
    display_name = "Умножить на число"
    INPUTS = [Port("in", PortType.MATRIX), Port("k", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        M = as_matrix(inputs["in"])
        k = sp.nsimplify(inputs.get("k", 1))
        return {"out": M * k}


class MatrixPowerNode(Node):
    """Возведение квадратной матрицы в целую степень (MATRIX → MATRIX)."""
    type_id = "matrix_power"
    category = "linalg"
    display_name = "Степень матрицы"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"exponent": {"type": "int", "default": 2}}

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_power {self.node_id!r}: матрица не квадратная.")
        n = int(self.params.get("exponent", 2))
        try:
            return {"out": M ** n}
        except Exception as e:
            raise RetryGeneration(f"matrix_power {self.node_id!r}: {e}")


# ---------- Операции над двумя матрицами ----------

class MatrixMultiplyNode(Node):
    """Произведение матриц A·B (MATRIX × MATRIX → MATRIX). Включает A·v."""
    type_id = "matrix_mul"
    category = "linalg"
    display_name = "Произведение матриц"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        A = as_matrix(inputs["a"])
        B = as_matrix(inputs["b"])
        if A.cols != B.rows:
            raise RetryGeneration(
                f"matrix_mul {self.node_id!r}: несогласованные размеры "
                f"{A.shape}·{B.shape}."
            )
        return {"out": A * B}


class MatrixAddNode(Node):
    """Сумма/разность матриц (MATRIX × MATRIX → MATRIX)."""
    type_id = "matrix_add"
    category = "linalg"
    display_name = "Сумма матриц"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": ["add", "sub"], "default": "add"},
    }

    def compute(self, inputs, ctx: ExecContext):
        A = as_matrix(inputs["a"])
        B = as_matrix(inputs["b"])
        if A.shape != B.shape:
            raise RetryGeneration(
                f"matrix_add {self.node_id!r}: разные размеры {A.shape} и {B.shape}."
            )
        return {"out": A - B if self.params.get("op") == "sub" else A + B}


# ---------- Системы и операторы (PR-2) ----------

class RrefNode(Node):
    """Приведённый ступенчатый вид (Gauss-Jordan), MATRIX → MATRIX."""
    type_id = "matrix_rref"
    category = "linalg"
    display_name = "Ступенчатый вид (rref)"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        rref, _pivots = M.rref()
        return {"out": rref}


class CharPolyNode(Node):
    """
    Характеристический многочлен det(A − λE), MATRIX + var:EXPR → EXPR.
    Переменная (символ λ) приходит на вход var.
    """
    type_id = "matrix_charpoly"
    category = "linalg"
    display_name = "Характеристический многочлен"
    INPUTS = [Port("in", PortType.MATRIX), Port("var", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        from ..symbolic import as_expr
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_charpoly {self.node_id!r}: матрица не квадратная.")
        var = as_expr(inputs["var"])
        try:
            return {"out": M.charpoly(var).as_expr()}
        except Exception as e:
            raise RetryGeneration(f"matrix_charpoly {self.node_id!r}: {e}")


class EigenvaluesNode(Node):
    """
    Собственные значения матрицы → BLOCK_LIST (по одному FormulaBlock на
    значение; кратность показывается как '(кратность k)'). Опц. префикс.
    """
    type_id = "matrix_eigenvalues"
    category = "linalg"
    display_name = "Собственные значения"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {"prefix": {"type": "string", "default": "\\lambda", "optional": True}}

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_eigenvalues {self.node_id!r}: матрица не квадратная.")
        try:
            vals = M.eigenvals()
        except Exception as e:
            raise RetryGeneration(f"matrix_eigenvalues {self.node_id!r}: {e}")
        prefix = str(self.params.get("prefix", "")).strip()
        blocks = []
        # Детерминированный порядок: по строковому представлению.
        for val, mult in sorted(vals.items(), key=lambda kv: str(kv[0])):
            latex = to_latex(val)
            if prefix:
                latex = f"{prefix} = {latex}"
            if mult > 1:
                latex += f"\\quad (\\text{{кратность }} {mult})"
            blocks.append(FormulaBlock(latex))
        return {"out": blocks}


class EigenvectorsNode(Node):
    """
    Собственные векторы матрицы → BLOCK_LIST (для каждого собственного значения —
    базисные векторы его собственного подпространства, в виде λ: вектор).
    """
    type_id = "matrix_eigenvectors"
    category = "linalg"
    display_name = "Собственные векторы"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        sp = sympy()
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_eigenvectors {self.node_id!r}: матрица не квадратная.")
        try:
            data = M.eigenvects()
        except Exception as e:
            raise RetryGeneration(f"matrix_eigenvectors {self.node_id!r}: {e}")
        blocks = []
        for val, _mult, vecs in sorted(data, key=lambda t: str(t[0])):
            for v in vecs:
                latex = (f"\\lambda = {to_latex(val)}:\\quad "
                         f"{sp.latex(v, mat_delim='', mat_str='pmatrix')}")
                blocks.append(FormulaBlock(latex))
        return {"out": blocks}


class NullspaceNode(Node):
    """
    Базис ядра (фундаментальная система решений Ax=0) → BLOCK_LIST векторов.
    Пустое ядро (только нулевой вектор) → один блок с пометкой.
    """
    type_id = "matrix_nullspace"
    category = "linalg"
    display_name = "Ядро (нуль-пространство)"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        sp = sympy()
        M = as_matrix(inputs["in"])
        basis = M.nullspace()
        if not basis:
            return {"out": [FormulaBlock("\\{\\vec{0}\\}")]}
        return {"out": [FormulaBlock(sp.latex(v, mat_delim="", mat_str="pmatrix"))
                        for v in basis]}


class LinSolveNode(Node):
    """
    Решение СЛАУ A·x = b → BLOCK_LIST. Вход a — матрица коэффициентов,
    b — вектор-столбец правых частей. Совместная определённая система даёт один
    блок-вектор решения; недоопределённая — параметрическое решение; несовместная
    → пустой список (нет решений).
    """
    type_id = "matrix_linsolve"
    category = "linalg"
    display_name = "Решить систему (Ax=b)"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {"prefix": {"type": "string", "default": "x", "optional": True}}

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        sp = sympy()
        A = as_matrix(inputs["a"])
        b = as_matrix(inputs["b"])
        # b должен быть вектором-столбцом высотой как число строк A.
        if b.cols != 1 or b.rows != A.rows:
            raise RetryGeneration(
                f"matrix_linsolve {self.node_id!r}: правая часть b должна быть "
                f"столбцом {A.rows}×1 (получено {b.shape})."
            )
        try:
            sol = sp.linsolve((A, b))
        except Exception as e:
            raise RetryGeneration(f"matrix_linsolve {self.node_id!r}: {e}")
        prefix = str(self.params.get("prefix", "")).strip()
        blocks = []
        for tup in sol:  # FiniteSet кортежей
            vec = sp.Matrix(list(tup))
            latex = sp.latex(vec, mat_delim="", mat_str="pmatrix")
            if prefix:
                latex = f"\\vec{{{prefix}}} = {latex}"
            blocks.append(FormulaBlock(latex))
        return {"out": blocks}


# ---------- Вектор-геометрия (PR-3) ----------

def _as_vector(M, sp):
    """Привести MATRIX к плоскому списку компонент (вектор-строка/столбец)."""
    if M.rows != 1 and M.cols != 1:
        raise RetryGeneration("ожидался вектор (строка или столбец).")
    return list(M)


class DotProductNode(Node):
    """Скалярное произведение векторов (MATRIX × MATRIX → EXPR)."""
    type_id = "vec_dot"
    category = "linalg"
    display_name = "Скалярное произведение"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        a = _as_vector(as_matrix(inputs["a"]), sp)
        b = _as_vector(as_matrix(inputs["b"]), sp)
        if len(a) != len(b):
            raise RetryGeneration(f"vec_dot {self.node_id!r}: разная размерность.")
        return {"out": sum((ai * bi for ai, bi in zip(a, b)), sp.Integer(0))}


class CrossProductNode(Node):
    """Векторное произведение (трёхмерные векторы) → MATRIX (вектор-столбец)."""
    type_id = "vec_cross"
    category = "linalg"
    display_name = "Векторное произведение"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        a = _as_vector(as_matrix(inputs["a"]), sp)
        b = _as_vector(as_matrix(inputs["b"]), sp)
        if len(a) != 3 or len(b) != 3:
            raise RetryGeneration(f"vec_cross {self.node_id!r}: нужны трёхмерные векторы.")
        return {"out": sp.Matrix(a).cross(sp.Matrix(b))}


class TripleProductNode(Node):
    """Смешанное произведение (a, b, c) = a·(b×c) → EXPR (объём параллелепипеда)."""
    type_id = "vec_triple"
    category = "linalg"
    display_name = "Смешанное произведение"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX),
              Port("c", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        a = _as_vector(as_matrix(inputs["a"]), sp)
        b = _as_vector(as_matrix(inputs["b"]), sp)
        c = _as_vector(as_matrix(inputs["c"]), sp)
        if not (len(a) == len(b) == len(c) == 3):
            raise RetryGeneration(f"vec_triple {self.node_id!r}: нужны трёхмерные векторы.")
        return {"out": sp.Matrix([a, b, c]).det()}


class NormNode(Node):
    """Длина (евклидова норма) вектора (MATRIX → EXPR)."""
    type_id = "vec_norm"
    category = "linalg"
    display_name = "Длина вектора"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        v = sp.Matrix(_as_vector(as_matrix(inputs["in"]), sp))
        return {"out": v.norm()}


class VectorAngleNode(Node):
    """Угол между векторами в радианах: acos(a·b/(|a||b|)) (MATRIX × MATRIX → EXPR)."""
    type_id = "vec_angle"
    category = "linalg"
    display_name = "Угол между векторами"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        a = sp.Matrix(_as_vector(as_matrix(inputs["a"]), sp))
        b = sp.Matrix(_as_vector(as_matrix(inputs["b"]), sp))
        if a.shape[0] != b.shape[0]:
            raise RetryGeneration(f"vec_angle {self.node_id!r}: разная размерность.")
        na, nb = a.norm(), b.norm()
        if na == 0 or nb == 0:
            raise RetryGeneration(f"vec_angle {self.node_id!r}: нулевой вектор.")
        return {"out": sp.acos(sp.simplify(a.dot(b) / (na * nb)))}


_COORD_NAMES = ["x", "y", "z", "w"]


def _coord_symbols(sp, n):
    return [sp.Symbol(_COORD_NAMES[i] if i < len(_COORD_NAMES) else f"x_{i}")
            for i in range(n)]


class PlaneFromPointNormalNode(Node):
    """
    Уравнение плоскости по точке и нормали: n·(r − p) = 0 → EXPR (левая часть
    общего уравнения Ax+By+Cz+D). point и normal — векторы (MATRIX).
    """
    type_id = "plane_point_normal"
    category = "linalg"
    display_name = "Плоскость (точка+нормаль)"
    INPUTS = [Port("point", PortType.MATRIX), Port("normal", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        p = sp.Matrix(_as_vector(as_matrix(inputs["point"]), sp))
        n = sp.Matrix(_as_vector(as_matrix(inputs["normal"]), sp))
        if p.shape[0] != n.shape[0]:
            raise RetryGeneration(f"plane_point_normal {self.node_id!r}: разная размерность.")
        r = sp.Matrix(_coord_symbols(sp, p.shape[0]))
        return {"out": sp.expand(n.dot(r - p))}


class PointPlaneDistanceNode(Node):
    """
    Расстояние от точки до плоскости n·(r−p0)=0: |n·(q−p0)|/|n| (MATRIX×3 → EXPR).
    Входы: q (точка), p0 (точка плоскости), normal (нормаль).
    """
    type_id = "point_plane_distance"
    category = "linalg"
    display_name = "Расстояние точка–плоскость"
    INPUTS = [Port("q", PortType.MATRIX), Port("p0", PortType.MATRIX),
              Port("normal", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        q = sp.Matrix(_as_vector(as_matrix(inputs["q"]), sp))
        p0 = sp.Matrix(_as_vector(as_matrix(inputs["p0"]), sp))
        n = sp.Matrix(_as_vector(as_matrix(inputs["normal"]), sp))
        if n.norm() == 0:
            raise RetryGeneration(f"point_plane_distance {self.node_id!r}: нулевая нормаль.")
        return {"out": sp.simplify(sp.Abs(n.dot(q - p0)) / n.norm())}


class LineCanonicalNode(Node):
    """
    Каноническое уравнение прямой по точке и направляющему вектору:
    (x−px)/vx = (y−py)/vy = (z−pz)/vz → BLOCK (FormulaBlock).
    Входы point и direction — векторы (MATRIX).
    """
    type_id = "line_canonical"
    category = "linalg"
    display_name = "Прямая (каноническая)"
    INPUTS = [Port("point", PortType.MATRIX), Port("direction", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        sp = sympy()
        p = _as_vector(as_matrix(inputs["point"]), sp)
        v = _as_vector(as_matrix(inputs["direction"]), sp)
        if len(p) != len(v):
            raise RetryGeneration(f"line_canonical {self.node_id!r}: разная размерность.")
        coords = _coord_symbols(sp, len(p))
        parts = []
        for i in range(len(p)):
            num = sp.latex(coords[i] - p[i])
            parts.append(r"\frac{" + num + "}{" + sp.latex(v[i]) + "}")
        return {"out": FormulaBlock(" = ".join(parts))}


# ---------- Квадратичные формы и замена базиса (PR-4) ----------

def _signature(sp, A):
    """Сигнатура симметричной матрицы (n+, n−, n0) по знакам собственных значений."""
    evs = A.eigenvals()
    npos = sum(m for e, m in evs.items() if e.is_positive)
    nneg = sum(m for e, m in evs.items() if e.is_negative)
    nzero = sum(m for e, m in evs.items() if e.is_zero)
    if npos + nneg + nzero != A.rows:
        # Знак части собственных значений не определился символически.
        raise RetryGeneration("не удалось определить сигнатуру (знаки λ неясны).")
    return npos, nneg, nzero


class QuadFormToMatrixNode(Node):
    """
    Матрица квадратичной формы: A = ½·гессиан(Q) (симметричная). Вход in:EXPR —
    квадратичная форма; переменные задаются параметром vars (список имён).
    EXPR → MATRIX.
    """
    type_id = "quadform_to_matrix"
    category = "linalg"
    display_name = "Матрица квадр. формы"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"vars": {"type": "list", "default": ["x", "y"]}}

    def _vars(self, sp):
        names = self.params.get("vars") or ["x", "y"]
        return [build_symbols([str(n)])[str(n)] for n in names]

    def validate_params(self) -> None:
        names = self.params.get("vars") or []
        if not names:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: укажите переменные формы (vars)."
            )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        Q = as_expr(inputs["in"])
        vs = self._vars(sp)
        try:
            A = sp.hessian(Q, vs) / 2
        except Exception as e:
            raise RetryGeneration(f"quadform_to_matrix {self.node_id!r}: {e}")
        return {"out": sp.Matrix(A)}


class MatrixToQuadFormNode(Node):
    """
    Квадратичная форма по матрице: Q = vᵀ·A·v. Вход in:MATRIX (симметричная),
    переменные — параметр vars. MATRIX → EXPR.
    """
    type_id = "matrix_to_quadform"
    category = "linalg"
    display_name = "Квадр. форма по матрице"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {"vars": {"type": "list", "default": ["x", "y"]}}

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        A = as_matrix(inputs["in"])
        names = self.params.get("vars") or ["x", "y"]
        if len(names) != A.rows:
            raise RetryGeneration(
                f"matrix_to_quadform {self.node_id!r}: число переменных ≠ размеру матрицы."
            )
        v = sp.Matrix([build_symbols([str(n)])[str(n)] for n in names])
        return {"out": sp.expand((v.T * A * v)[0])}


class QuadFormCanonicalNode(Node):
    """
    Канонический вид квадратичной формы (метод собственных значений):
    λ₁ξ₁² + λ₂ξ₂² + … Вход in:MATRIX (симметричная) → EXPR (в переменных xi_i).
    """
    type_id = "quadform_canonical"
    category = "linalg"
    display_name = "Канонический вид формы"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        A = as_matrix(inputs["in"])
        if A.rows != A.cols:
            raise RetryGeneration(f"quadform_canonical {self.node_id!r}: матрица не квадратная.")
        try:
            evs = A.eigenvals()
        except Exception as e:
            raise RetryGeneration(f"quadform_canonical {self.node_id!r}: {e}")
        lambdas = [e for e, m in sorted(evs.items(), key=lambda kv: str(kv[0]))
                   for _ in range(m)]
        terms = []
        for i, lam in enumerate(lambdas, start=1):
            xi = sp.Symbol(f"xi_{i}")
            terms.append(lam * xi**2)
        return {"out": sp.Add(*terms) if terms else sp.Integer(0)}


class QuadFormSignatureNode(Node):
    """
    Сигнатура и тип квадратичной формы (закон инерции) → BLOCK.
    Показывает (n₊, n₋, n₀) и вывод о знакоопределённости.
    """
    type_id = "quadform_signature"
    category = "linalg"
    display_name = "Сигнатура формы"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        sp = sympy()
        A = as_matrix(inputs["in"])
        if A.rows != A.cols:
            raise RetryGeneration(f"quadform_signature {self.node_id!r}: матрица не квадратная.")
        npos, nneg, nzero = _signature(sp, A)
        if nzero == 0 and nneg == 0:
            kind = r"\text{положительно определена}"
        elif nzero == 0 and npos == 0:
            kind = r"\text{отрицательно определена}"
        elif nneg == 0:
            kind = r"\text{положительно полуопределена}"
        elif npos == 0:
            kind = r"\text{отрицательно полуопределена}"
        else:
            kind = r"\text{знакопеременна}"
        latex = (f"\\sigma = ({npos},\\, {nneg},\\, {nzero}),\\quad {kind}")
        return {"out": FormulaBlock(latex)}


class ChangeBasisOperatorNode(Node):
    """
    Матрица оператора в новом базисе: A' = P⁻¹·A·P (преобразование подобия).
    Входы a:MATRIX (оператор), p:MATRIX (матрица перехода, столбцы — новый базис).
    """
    type_id = "change_basis_operator"
    category = "linalg"
    display_name = "Оператор в новом базисе"
    INPUTS = [Port("a", PortType.MATRIX), Port("p", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        A = as_matrix(inputs["a"])
        P = as_matrix(inputs["p"])
        if P.rows != P.cols:
            raise RetryGeneration(f"change_basis_operator {self.node_id!r}: P не квадратная.")
        try:
            if P.det() == 0:
                raise RetryGeneration(f"change_basis_operator {self.node_id!r}: P вырождена.")
            return {"out": P.inv() * A * P}
        except RetryGeneration:
            raise
        except Exception as e:
            raise RetryGeneration(f"change_basis_operator {self.node_id!r}: {e}")


class CoordinatesInBasisNode(Node):
    """
    Координаты вектора в базисе: решение P·c = v (столбцы P — базисные векторы).
    Входы vector:MATRIX, basis:MATRIX (матрица из базисных столбцов). → MATRIX.
    """
    type_id = "coordinates_in_basis"
    category = "linalg"
    display_name = "Координаты в базисе"
    INPUTS = [Port("vector", PortType.MATRIX), Port("basis", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        v = as_matrix(inputs["vector"])
        P = as_matrix(inputs["basis"])
        if P.rows != P.cols:
            raise RetryGeneration(f"coordinates_in_basis {self.node_id!r}: базис не квадратный.")
        try:
            if P.det() == 0:
                raise RetryGeneration(f"coordinates_in_basis {self.node_id!r}: базис вырожден.")
            return {"out": P.inv() * v}
        except RetryGeneration:
            raise
        except Exception as e:
            raise RetryGeneration(f"coordinates_in_basis {self.node_id!r}: {e}")


class GramSchmidtNode(Node):
    """
    Ортогонализация Грама–Шмидта набора векторов → BLOCK_LIST.
    Векторы задаются столбцами входной матрицы in:MATRIX. normalize=yes даёт
    ортонормированный базис.
    """
    type_id = "gram_schmidt"
    category = "linalg"
    display_name = "Грам–Шмидт"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "normalize": {"type": "enum", "values": ["no", "yes"], "default": "no"},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock
        sp = sympy()
        M = as_matrix(inputs["in"])
        cols = [M.col(j) for j in range(M.cols)]
        normalize = str(self.params.get("normalize", "no")) == "yes"
        try:
            ortho = sp.GramSchmidt(cols, normalize)
        except Exception as e:
            raise RetryGeneration(f"gram_schmidt {self.node_id!r}: {e}")
        return {"out": [FormulaBlock(sp.latex(v, mat_delim="", mat_str="pmatrix"))
                        for v in ortho]}


# ---------- Рендер ----------

_MATRIX_ENVS = {"pmatrix": "p", "bmatrix": "b", "vmatrix": "v", "Vmatrix": "V"}


class MatrixBlockNode(Node):
    """
    Формульный блок из матрицы (MATRIX → BLOCK через FormulaBlock).

    env — окружение LaTeX: pmatrix (круглые), bmatrix (квадратные),
    vmatrix (определитель |·|), Vmatrix (норма ‖·‖). Опц. префикс 'A = …'.
    """
    type_id = "matrix_block"
    category = "linalg"
    display_name = "Матричный блок"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {
        "env": {"type": "enum", "values": list(_MATRIX_ENVS), "default": "pmatrix"},
        "prefix": {"type": "string", "default": "", "optional": True},
        "relation": {"type": "string", "default": "=", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock          # ленивый: тянет Qt
        from .compute import _join_prefix
        sp = sympy()
        M = as_matrix(inputs["in"])
        env = self.params.get("env", "pmatrix")
        latex = _join_prefix(self.params.get("prefix", ""),
                             sp.latex(M, mat_delim="", mat_str=env),
                             self.params.get("relation", "="))
        return {"out": FormulaBlock(latex)}
