"""
Инфраструктурные функции рендеринга.

Вся логика нормализации LaTeX вынесена в core/latex.py. Здесь только
конкретные пайплайны рендера: matplotlib mathtext, PIL → Qt, конвертация
формул в PNG-байты.

Все Qt-зависимости загружаются лениво (внутри функций), а не на уровне
модуля — это позволяет использовать ядро в headless-окружении (FastAPI,
тесты, серверная сборка) без установленного PyQt6.

Базовая функция — latex_to_png_bytes. Через неё реализованы и
latex_to_pixmap (Qt-предпросмотр), и latex_to_docx_image (вставка
формулы как картинки в docx), и to_dict у FormulaBlock.
"""

from __future__ import annotations
import io
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .latex import canonical_latex

if TYPE_CHECKING:
    from PyQt6.QtGui import QPixmap


# ============================================================
# Базовый рендер: LaTeX → PNG-байты
# ============================================================

def latex_to_png_bytes(latex: str, fontsize: int = 14, dpi: int = 200) -> bytes:
    """
    Отрендерить LaTeX-формулу в PNG-байты через matplotlib.mathtext.

    Базовая функция всего рендеринга формул в проекте. На её основе
    построены и Qt-, и docx-, и веб-пайплайны.

    Бросает Exception при неудачном рендере (некорректный LaTeX,
    отсутствие matplotlib и т.п.). Вызывающий сам решает, что делать
    с ошибкой — отдать None в JSON, нарисовать заглушку в Qt или
    вставить сырой LaTeX в docx.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import mathtext, font_manager

    s = canonical_latex(latex)
    buf = io.BytesIO()
    prop = font_manager.FontProperties(size=fontsize)
    mathtext.math_to_image(f"${s}$", buf, prop=prop, dpi=dpi, format="png")
    return buf.getvalue()


# ============================================================
# Рендер LaTeX в QPixmap (Qt-предпросмотр)
# ============================================================

def latex_to_pixmap(latex: str, fontsize: int = 14, dpi: int = 130) -> "Optional[QPixmap]":
    """
    Отрендерить LaTeX-формулу в QPixmap. Lazy-импортирует Qt только
    при вызове — на сервере, где Qt не установлен, функция просто
    не зовётся и не падает.

    Возвращает None при любой ошибке (некорректный LaTeX, Qt недоступен).
    """
    try:
        png = latex_to_png_bytes(latex, fontsize, dpi)
    except Exception:
        return None

    try:
        from PyQt6.QtGui import QImage, QPixmap
        img = QImage()
        img.loadFromData(png, "PNG")
        return QPixmap.fromImage(img)
    except Exception:
        return None


def latex_to_docx_image(doc, latex: str, fontsize: int = 14, dpi: int = 200) -> None:
    """
    Вставить LaTeX-формулу в docx-документ как изображение.
    При ошибке рендера — вставляем как текст с долларами (визуально видно
    пользователю, что именно сломалось).
    """
    try:
        png = latex_to_png_bytes(latex, fontsize, dpi)
        doc.add_picture(io.BytesIO(png))
    except Exception:
        doc.add_paragraph(f"${latex}$")


# ============================================================
# Конвертация PIL.Image / bytes / путь → QPixmap
# ============================================================

def pil_to_qpixmap(image) -> "Optional[QPixmap]":
    """Конвертировать PIL.Image / bytes / путь в QPixmap. Lazy Qt."""
    try:
        from PyQt6.QtGui import QImage, QPixmap
    except ImportError:
        return None

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


# ============================================================
# Конвертация PIL.Image / bytes / путь → bytes (PNG)
# ============================================================

def image_to_png_bytes(image) -> Optional[bytes]:
    """
    Привести изображение к PNG-байтам. Принимает PIL.Image, bytes,
    bytearray или путь к файлу. Возвращает None, если входной формат
    неподдерживаемый или операция не удалась.

    Используется в ImageBlock.to_dict() для веб-сериализации.
    """
    from PIL import Image as PILImage

    try:
        if isinstance(image, (str, Path)):
            with open(str(image), "rb") as f:
                return f.read()
        if isinstance(image, (bytes, bytearray)):
            return bytes(image)
        if isinstance(image, PILImage.Image):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None
    return None
