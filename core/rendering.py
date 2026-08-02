"""
Инфраструктурные функции рендеринга.

Вся логика нормализации LaTeX вынесена в core/latex.py. Здесь только
конкретные пайплайны рендера: matplotlib mathtext, PIL → Qt, и т.п.
"""

from __future__ import annotations
import io
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .latex import canonical_latex

# Qt импортируется ЛЕНИВО — внутри функций, которые его действительно
# используют. Иначе ядро не получится импортировать в headless-окружении
# (FastAPI-микросервис, тесты, серверная сборка) без установленного PyQt6, а
# оно там и не нужно: сервер отдаёт блоки через to_dict(), а не рисует их.
# Аннотации остаются строками благодаря `from __future__ import annotations`.
if TYPE_CHECKING:
    from PyQt6.QtGui import QPixmap


# ============================================================
# Матрицы: mathtext не умеет \begin{matrix}, поэтому рисуем сетку сами
# ============================================================

# Окружение → пара скобок-ограничителей.
_MATRIX_DELIMS = {
    "matrix": ("", ""),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"),
    "Vmatrix": (r"\|", r"\|"),
    "smallmatrix": ("", ""),
}

# Скобки-ограничители вокруг \begin{matrix} (sympy кладёт их как \left[...\right]).
_LEFT_DELIM = {"[": ("[", "]"), "(": ("(", ")"), "|": ("|", "|"), "\\{": ("{", "}")}

_MATRIX_RE = re.compile(
    r"(?:\\left\s*(\[|\(|\||\\\{)\s*)?"
    r"\\begin\{(p|b|B|v|V|small)?matrix\}(.*?)\\end\{(?:p|b|B|v|V|small)?matrix\}"
    r"(?:\s*\\right\s*(?:\]|\)|\||\\\})?)?",
    re.DOTALL,
)


def parse_matrix_latex(latex: str):
    """
    Если latex содержит матрицу sympy (\\begin{...matrix}...\\end, опц. в
    \\left[...\\right]), вернуть (env_delims, rows, prefix, suffix):
      env_delims = (lb, rb) — символы скобок для отрисовки;
      rows       = list[list[str]] LaTeX-ячеек;
      prefix     = текст до матрицы (например 'A =' — уже с '='); suffix — после.
    Иначе None.
    """
    m = _MATRIX_RE.search(latex)
    if m is None:
        return None
    # Скобки: сперва из окружения (pmatrix→()), иначе из \left[ перед ним.
    env = (m.group(2) or "") + "matrix"
    if env in _MATRIX_DELIMS and _MATRIX_DELIMS[env] != ("", ""):
        delims = _MATRIX_DELIMS[env]
    elif m.group(1):
        delims = _LEFT_DELIM.get(m.group(1), ("[", "]"))
    else:
        delims = ("[", "]")          # матрицу без скобок всё равно обрамим
    body = m.group(3).strip()
    rows = []
    for rline in re.split(r"\\\\", body):
        rline = rline.strip()
        if rline == "":
            continue
        cells = [c.strip() for c in rline.split("&")]
        rows.append(cells)
    if not rows:
        return None
    return delims, rows, latex[:m.start()].strip(), latex[m.end():].strip()


def _render_matrix_figure(delims, rows, prefix, suffix, fontsize, dpi,
                          align="center"):
    """Нарисовать матрицу/cases как сетку ячеек со скобками. PNG-байты."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Ячейки могут содержать \text{...} (из cases) — канонизуем под mathtext.
    rows = [[canonical_latex(c) for c in row] for row in rows]
    nrows = len(rows)
    ncols = max(len(r) for r in rows)
    lb, rb = delims

    # Ширина ячейки растёт с длиной самого длинного выражения в столбце-наборе.
    max_cell_len = max((len(c) for row in rows for c in row), default=1)
    cell_w = max(0.55, min(1.4, 0.12 * max_cell_len + 0.4))
    cell_h = 0.62
    # Ширина префикса/суффикса грубо пропорциональна длине строки.
    pre_w = (0.13 * len(prefix) + 0.2) if prefix else 0.0
    suf_w = (0.13 * len(suffix) + 0.2) if suffix else 0.0
    bracket_w = 0.28
    width = pre_w + bracket_w * 2 + ncols * cell_w + suf_w + 0.4
    height = max(0.9, nrows * cell_h + 0.3)
    bracket_fs = fontsize * (1.0 + 0.85 * nrows)

    fig = plt.figure(figsize=(width, height), dpi=dpi)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.set_xlim(0, width); ax.set_ylim(0, height)
    cy_mid = height / 2

    x = 0.1
    if prefix:
        ax.text(x, cy_mid, f"${prefix}$", ha="left", va="center", fontsize=fontsize)
        x += pre_w
    if lb:
        ax.text(x, cy_mid, f"${lb}$", ha="left", va="center", fontsize=bracket_fs)
    x += bracket_w
    grid_left = x
    left_align = (align == "left")
    for i, row in enumerate(rows):
        for j in range(ncols):
            c = row[j] if j < len(row) else ""
            if left_align:
                cx = grid_left + j * cell_w + 0.1
                ha = "left"
            else:
                cx = grid_left + j * cell_w + cell_w / 2
                ha = "center"
            cy = height - 0.15 - (i + 0.5) * cell_h
            if c:
                ax.text(cx, cy, f"${c}$", ha=ha, va="center", fontsize=fontsize)
    x = grid_left + ncols * cell_w
    if rb:
        ax.text(x, cy_mid, f"${rb}$", ha="left", va="center", fontsize=bracket_fs)
    x += bracket_w
    if suffix:
        ax.text(x, cy_mid, f"${suffix}$", ha="left", va="center", fontsize=fontsize)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, transparent=True,
                bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _matrix_png(latex: str, fontsize: int, dpi: int):
    """PNG-байты для матрицы/cases в latex, либо None если ни то ни другое."""
    parsed = parse_matrix_latex(latex)
    if parsed is not None:
        delims, rows, prefix, suffix = parsed
        try:
            return _render_matrix_figure(delims, rows, prefix, suffix, fontsize, dpi)
        except Exception:
            return None
    cs = parse_cases_latex(latex)
    if cs is not None:
        rows, prefix, suffix = cs
        try:
            # cases: левая фигурная скобка, ячейки выровнены влево.
            return _render_matrix_figure(("\\{", ""), rows, prefix, suffix,
                                         fontsize, dpi, align="left")
        except Exception:
            return None
    return None


_CASES_RE = re.compile(r"\\begin\{cases\}(.*?)\\end\{cases\}", re.DOTALL)


def parse_cases_latex(latex: str):
    """\\begin{cases}…\\end → (rows, prefix, suffix) или None. Каждая ветвь —
    одна строка; '&' внутри разбивает на «значение» и «условие»."""
    m = _CASES_RE.search(latex)
    if m is None:
        return None
    rows = []
    for rline in re.split(r"\\\\", m.group(1).strip()):
        rline = rline.strip()
        if rline == "":
            continue
        # \text{for}: и \text{otherwise} оставляем как есть — canonical_latex
        # превратит \text в \mathrm, mathtext отрисует.
        cells = [c.strip() for c in rline.split("&")]
        rows.append(cells)
    if not rows:
        return None
    return rows, latex[:m.start()].strip(), latex[m.end():].strip()


# ============================================================
# Рендер LaTeX в QPixmap (Qt-предпросмотр)
# ============================================================

def latex_to_pixmap(latex: str, fontsize: int = 14, dpi: int = 130) -> Optional[QPixmap]:
    """
    Отрендерить LaTeX-формулу в QPixmap через matplotlib.mathtext.
    Матрицы (\\begin{...matrix}) рисуются сеткой отдельно — mathtext их не умеет.
    Возвращает None при ошибке (формула некорректна или matplotlib недоступен).
    """
    try:
        from PyQt6.QtGui import QImage, QPixmap
    except ImportError:
        return None          # headless-окружение: предпросмотра нет и не надо
    png = _matrix_png(latex, fontsize, dpi)
    if png is not None:
        img = QImage()
        img.loadFromData(png, "PNG")
        return QPixmap.fromImage(img) if not img.isNull() else None
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import mathtext
        from matplotlib import font_manager
    except Exception:
        return None

    try:
        buf = io.BytesIO()
        prop = font_manager.FontProperties(size=fontsize)
        s = canonical_latex(latex)
        mathtext.math_to_image(f"${s}$", buf, prop=prop, dpi=dpi, format="png")
        buf.seek(0)
        img = QImage()
        img.loadFromData(buf.getvalue(), "PNG")
        return QPixmap.fromImage(img)
    except Exception:
        return None


def latex_to_docx_image(doc, latex: str, fontsize: int = 14, dpi: int = 200) -> None:
    """
    Вставить LaTeX-формулу в docx-документ как изображение.
    При ошибке рендера — вставляем как текст с долларами (визуально видно
    пользователю, что именно сломалось).
    """
    png = _matrix_png(latex, fontsize, dpi)
    if png is not None:
        doc.add_picture(io.BytesIO(png))
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import mathtext
        from matplotlib import font_manager

        buf = io.BytesIO()
        prop = font_manager.FontProperties(size=fontsize)
        s = canonical_latex(latex)
        mathtext.math_to_image(f"${s}$", buf, prop=prop, dpi=dpi, format="png")
        buf.seek(0)
        doc.add_picture(buf)
    except Exception:
        doc.add_paragraph(f"${latex}$")


# ============================================================
# Конвертация PIL.Image / bytes / путь → QPixmap
# ============================================================

def pil_to_qpixmap(image) -> Optional[QPixmap]:
    """Конвертировать PIL.Image / bytes / путь в QPixmap."""
    try:
        from PyQt6.QtGui import QImage, QPixmap
    except ImportError:
        return None          # см. latex_to_pixmap
    from PIL import Image as PILImage

    try:
        if isinstance(image, (str, Path)):
            pix = QPixmap(str(image))
            return pix if not pix.isNull() else None

        if isinstance(image, (bytes, bytearray)):
            img = QImage()
            img.loadFromData(bytes(image))
            return QPixmap.fromImage(img) if not img.isNull() else None

        if isinstance(image, PILImage.Image):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            buf.seek(0)
            qimg = QImage()
            qimg.loadFromData(buf.getvalue(), "PNG")
            return QPixmap.fromImage(qimg) if not qimg.isNull() else None
    except Exception:
        pass
    return None
