"""
Формула на проводе: исходник, а не картинка — этап 7 плана (§10.2).

Показ формул назван в плане самостоятельным дефектом, и замеры это
подтвердили. Ядро готовило base64-PNG от matplotlib и слало его в
условии; у типового задания матана это составляло **94 % ответа** (5432
байта из 5760) и стоило около 40 мс на каждую формулу — в синхронном
запросе, пока студент ждёт. Картинка при этом не выделяется, не
копируется, не ищется по странице, не масштабируется вместе с текстом и
не подстраивается под тему.

Веб рисует формулы KaTeX по исходнику. Проверяется здесь то, что должно
остаться верным, когда про эту причину забудут:

  * **на проводе только LaTeX.** Возврат картинки — не «оптимизация
    наоборот», а те же 94 % ни за что;
  * **исходник доезжает дословно.** Он теперь единственный источник
    показа: потерянная обратная косая раньше портила картинку, а
    теперь не покажет ничего;
  * **другие рендереры не задеты.** Qt и DOCX берут картинку своими
    путями, не через `to_dict`;
  * **картинки остаются картинками.** У `ImageBlock` исходника, из
    которого можно нарисовать заново, нет, и растр там по делу.
"""

from __future__ import annotations

import json
import unittest

from core.blocks import FormulaBlock, ImageBlock, TextBlock
from core.task import StaticTask


FORMULAS = [
    r"x^{2} - 1",
    r"\frac{d}{dx}\left(\sin x\right)",
    r"\int_{0}^{1} x^{2}\,dx = \frac{1}{3}",
    r"\begin{cases} x(t) = 2 t \\ y(t) = t^{2} \end{cases}",
    r"\lim_{n \to \infty} \frac{10^{n}}{6^{n}}",
]


class FormulaTravelsAsSourceTests(unittest.TestCase):

    def test_no_raster_on_the_wire(self):
        for latex in FORMULAS:
            with self.subTest(latex=latex):
                payload = FormulaBlock(latex).to_dict()
                self.assertNotIn("image_b64", payload)
                self.assertEqual(set(payload), {"type", "latex"})

    def test_source_survives_verbatim(self):
        """
        Исходник теперь единственное, из чего строится показ. Раньше
        потерянная косая портила картинку, а теперь не покажет ничего.
        """
        for latex in FORMULAS:
            with self.subTest(latex=latex):
                self.assertEqual(FormulaBlock(latex).to_dict()["latex"], latex)

    def test_the_payload_is_small(self):
        """
        Замер, а не пожелание: раньше одна формула стоила килобайты.
        Порог с большим запасом — он ловит возврат растра, а не следит
        за длиной самих формул.
        """
        task = StaticTask(statement=[TextBlock("Найдите производную."),
                                     FormulaBlock(FORMULAS[1])],
                          answer=[FormulaBlock(FORMULAS[0])])
        blob = json.dumps(task.to_dict(), ensure_ascii=False)
        self.assertLess(len(blob), 1000, f"ответ распух до {len(blob)} байт")

    def test_serialization_is_not_a_render(self):
        """
        Сериализация обязана быть дешёвой: она в горячем пути запроса.
        Рендер картинки стоил там десятки миллисекунд на формулу.
        """
        import time
        block = FormulaBlock(FORMULAS[2])
        block.to_dict()
        start = time.perf_counter()
        for _ in range(100):
            block.to_dict()
        each = (time.perf_counter() - start) / 100 * 1000
        self.assertLess(each, 1.0, f"{each:.2f} мс на формулу — это рендер")

    def test_plain_text_still_shows_the_source(self):
        self.assertEqual(FormulaBlock("x^2").render_plain(), "$x^2$")


class RasterStaysWhereItBelongsTests(unittest.TestCase):
    """
    У картинки исходника нет — её отдавать растром правильно. Тест стоит
    здесь же, потому что вопрос один и тот же: чем оправдан байт на
    проводе.
    """

    def _image(self):
        from PIL import Image
        return Image.new("RGB", (4, 4), (255, 0, 0))

    def test_image_block_still_carries_the_raster(self):
        payload = ImageBlock(self._image(), caption="схема").to_dict()
        self.assertEqual(payload["type"], "image")
        self.assertIsInstance(payload["image_b64"], str)
        self.assertGreater(len(payload["image_b64"]), 20)
        self.assertEqual(payload["caption"], "схема")

    def test_bytes_source_works(self):
        import io
        buf = io.BytesIO()
        self._image().save(buf, format="PNG")
        payload = ImageBlock(buf.getvalue()).to_dict()
        self.assertIsInstance(payload["image_b64"], str)

    def test_a_broken_source_is_none_not_an_exception(self):
        """
        Контракт `Block.to_dict` обещает `None` при неудаче. Раньше здесь
        вызывалась функция, которой в `rendering` нет вовсе, и ЛЮБОЕ
        задание с картинкой падало при сериализации с `ImportError` —
        то есть не показывалось в вебе никак. Заметить это было негде:
        единственный тест лежал в файле-скрипте, который
        `unittest discover` не собирает.
        """
        self.assertIsNone(ImageBlock(object()).to_dict()["image_b64"])
        self.assertIsNone(ImageBlock("/нет/такого/файла.png")
                          .to_dict()["image_b64"])


class WhatTheRenderersEmitTests(unittest.TestCase):
    """
    Конструкции, которые генераторы реально выдают, обязаны быть
    отрисовываемыми. `\\left\\{\\matrix{…}\\right.` не понимал НИ ОДИН из
    трёх рендереров: в mathtext окружений нет вовсе, а `\\matrix` — это
    plain-TeX, которого нет и в KaTeX. Формула молча вырождалась в
    исходник везде, и заметно это было только глазами.
    """

    def test_nobody_emits_plain_tex_matrix(self):
        import pathlib
        import re
        root = pathlib.Path(__file__).resolve().parent.parent
        pattern = re.compile(r"\\\\matrix\{")
        offenders = []
        for path in (root / "exercises").rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [],
                         "plain-TeX \\matrix не рисует ни один рендерер; "
                         "нужен \\begin{cases} или \\begin{matrix}")

    def test_cases_renders_where_it_must(self):
        """`cases` понимают оба: у matplotlib свой разбор, у KaTeX родной."""
        from core.rendering import latex_to_png_bytes, parse_cases_latex
        latex = FORMULAS[3]
        self.assertIsNotNone(parse_cases_latex(latex))
        self.assertGreater(len(latex_to_png_bytes(latex)), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
