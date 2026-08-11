"""
Модель: матрица с известным спектром.

Первая модель по стандарту (§4) — и выбрана она не случайно. Узлы
`random_matrix` → `matrix_eigenvalues` в языке есть уже сейчас, но
собрать из них задание «найдите собственные значения» нельзя по двум
причинам, и обе показательны:

* у случайной целочисленной матрицы собственные значения иррациональные —
  ответ вида `1/3 - (17/54 + sqrt(2)*I/2)**(1/3)` студенту не предъявишь;
* `matrix_eigenvalues` отдаёт BLOCK_LIST — готовое оформление, а не
  величины. Спросить «чему равно λ₂» нельзя: в проводе едет картинка
  ответа, а не сам ответ.

Модель решает и то, и другое: спектр ЗАДАЁТСЯ, матрица строится под него
(«конструируй так, чтобы свойство выполнялось» — тот же приём, что у
префиксных кодов и матриц с известным определителем), а наружу выходят
типизированные величины. Каким заданием это станет — «найдите спектр» по
матрице, «восстановите матрицу» по спектру и векторам, «выпишите
характеристический многочлен» — решает разводка проводов, а не модель.

Построение: A = S·D·S⁻¹, где D = diag(λ₁…λₙ), а S — целочисленная
матрица с определителем 1, собранная из элементарных операций
«к строке i прибавить c·строку j». Каждая такая операция обратима в
целых, поэтому и S⁻¹, и A целочисленные, а спектр в точности равен
заданному. Столбец i матрицы S — собственный вектор для λᵢ:
A·S = S·D по построению.

Граница построения, о которой стоит знать автору задания: такая матрица
ВСЕГДА диагонализируема (геометрическая кратность равна алгебраической).
Жорданову клетку — то есть матрицу с дефектом — этим способом не
получить; если она понадобится, это отдельный параметр и отдельная
ветка построения, а не побочный эффект.
"""

from __future__ import annotations

from .base import Instance, Model, ModelConfigError, ModelError, Output


class EigenInstance(Instance):
    """
    Экземпляр со знанием о том, что собственный вектор задан С ТОЧНОСТЬЮ
    ДО МНОЖИТЕЛЯ.

    Ровно тот случай, ради которого `equivalent` вообще существует:
    ответ `(1, 2, 3)` и ответ `(2, 4, 6)` одинаково верны, а сравнение
    «по значению» — хоть строкой, хоть символьно — забракует второй.
    Знание это предметное, и жить ему больше негде.
    """

    def equivalent(self, name: str, answer) -> bool:
        if name != "eigenvectors":
            return super().equivalent(name, answer)
        expected = self.get(name)
        given = answer if isinstance(answer, (list, tuple)) else [answer]
        if len(expected) != len(given):
            return False
        return all(_collinear(a, b) for a, b in zip(expected, given))


def _collinear(left, right) -> bool:
    """Пропорциональны ли два ненулевых вектора-столбца."""
    import sympy as sp

    try:
        a = left if isinstance(left, sp.MatrixBase) else sp.Matrix(left)
        b = right if isinstance(right, sp.MatrixBase) else sp.Matrix(right)
    except Exception:
        return False
    if a.shape != b.shape:
        return False
    if all(x == 0 for x in b):
        return False           # нулевой вектор собственным не бывает
    # Ранг матрицы из двух столбцов равен 1 ⇔ они пропорциональны.
    return sp.Matrix.hstack(a, b).rank() == 1


class MatrixSpectrumModel(Model):
    """Матрица с целым, заранее выбранным спектром."""

    name = "linal_eigen"
    title = "Матрица с известным спектром"
    description = (
        "Целочисленная матрица, собственные значения которой заданы, а не "
        "получены как повезёт. Величины: сама матрица, спектр, собственные "
        "векторы, характеристический многочлен, след и определитель."
    )
    category = "linalg"

    OUTPUTS = [
        Output("matrix", "matrix", "Матрица",
               "Матрица A с заданным спектром."),
        Output("eigenvalues", "list", "Собственные значения",
               "Список λ по возрастанию, с учётом кратности."),
        Output("eigenvectors", "list", "Собственные векторы",
               "Столбцы-векторы, по одному на каждое λ в том же порядке."),
        Output("char_poly", "expr", "Характеристический многочлен",
               "Раскрытый определитель det(A − λE)."),
        Output("trace", "number", "След", "Сумма диагонали, она же сумма λ."),
        Output("determinant", "number", "Определитель",
               "Он же произведение λ."),
    ]

    PARAMS = {
        "size": {"type": "int", "default": 3},
        "min": {"type": "int", "default": -3, "optional": True},
        "max": {"type": "int", "default": 4, "optional": True},
        "repeated": {"type": "bool", "default": False, "optional": True},
        "complexity": {"type": "int", "default": 3, "optional": True},
        "max_entry": {"type": "int", "default": 20, "optional": True},
    }

    # --- параметры ---

    def normalize_params(self, params: dict) -> dict:
        def whole(key, default):
            try:
                return int(params.get(key, default))
            except (TypeError, ValueError):
                raise ModelConfigError(f"{key} должно быть целым числом.")

        size = whole("size", 3)
        if not 2 <= size <= 6:
            raise ModelConfigError("размер матрицы должен быть от 2 до 6.")
        lo, hi = whole("min", -3), whole("max", 4)
        if lo > hi:
            raise ModelConfigError("min не может быть больше max.")
        repeated = bool(params.get("repeated", False))
        if not repeated and hi - lo + 1 < size:
            raise ModelConfigError(
                f"различных собственных значений нужно {size}, а в диапазоне "
                f"[{lo}, {hi}] их только {hi - lo + 1}."
            )
        complexity = max(0, whole("complexity", 3))
        max_entry = whole("max_entry", 20)
        if max_entry < 1:
            raise ModelConfigError("max_entry должен быть положительным.")
        return {"size": size, "min": lo, "max": hi, "repeated": repeated,
                "complexity": complexity, "max_entry": max_entry}

    # --- построение ---

    def build(self, rng, **params) -> Instance:
        import sympy as sp

        cfg = self.normalize_params(params)
        n = cfg["size"]
        lam = sp.Symbol("lambda")

        for _ in range(200):
            values = self._draw_spectrum(rng, cfg)
            S, S_inv = self._unimodular(rng, n, cfg["complexity"], sp)
            A = S * sp.diag(*values) * S_inv
            if max(abs(int(x)) for x in A) > cfg["max_entry"]:
                continue
            if A.is_upper or A.is_lower:
                # Треугольная (и тем более диагональная) матрица делает
                # задание бессодержательным: собственные значения стоят на
                # диагонали, и их видно без единого вычисления. Проверять
                # именно треугольность, а не только диагональность, —
                # замер: на 300 первых попытках при complexity=3
                # диагональная вышла ОДНА, а треугольных было 94. Проверка
                # «не диагональная» пропустила бы почти все из них.
                continue
            return EigenInstance(
                values={
                    "matrix": A,
                    "eigenvalues": list(values),
                    # Столбец i матрицы S — собственный вектор для λᵢ:
                    # A·S = S·D по построению. Считать их заново через
                    # eigenvects() значило бы получить те же подпространства
                    # в другой нормировке и потерять готовое соответствие
                    # «i-е λ ↔ i-й вектор».
                    "eigenvectors": [S.col(i) for i in range(n)],
                    "char_poly": sp.expand((A - lam * sp.eye(n)).det()),
                    "trace": int(A.trace()),
                    "determinant": int(A.det()),
                },
                params=dict(cfg),
            )
        raise ModelError(
            "не удалось построить матрицу в заданных границах — "
            "попробуйте увеличить max_entry или уменьшить complexity."
        )

    def _draw_spectrum(self, rng, cfg: dict) -> list[int]:
        """
        Спектр по возрастанию. Порядок нужен: собственные векторы едут
        параллельным списком, и пары «λᵢ ↔ vᵢ» держатся именно на нём.
        """
        lo, hi, n = cfg["min"], cfg["max"], cfg["size"]
        if cfg["repeated"]:
            return sorted(rng.randint(lo, hi) for _ in range(n))
        return sorted(rng.sample(range(lo, hi + 1), k=n))

    def _unimodular(self, rng, n: int, ops: int, sp):
        """
        Пара (S, S⁻¹) целочисленных матриц с определителем 1.

        Собирается из элементарных операций «к строке i прибавить c·строку
        j». Обратная НЕ вычисляется через `S.inv()`, а набирается
        параллельно: обратная к такой операции — «вычесть c·строку j», а
        обратная к произведению — произведение обратных в обратном
        порядке, что справа даёт те же операции над СТОЛБЦАМИ. Так
        целочисленность A = S·D·S⁻¹ получается по построению, а не как
        свойство, на которое остаётся надеяться и потом проверять.
        """
        S = sp.eye(n)
        S_inv = sp.eye(n)
        for _ in range(ops):
            i, j = rng.sample(range(n), k=2)
            c = rng.choice([-2, -1, 1, 1, 2])
            S = S.elementary_row_op("n->n+km", row=i, k=c, row2=j)
            S_inv = S_inv.elementary_col_op("n->n+km", col=j, k=-c, col2=i)
        return S, S_inv


MODEL = MatrixSpectrumModel()
