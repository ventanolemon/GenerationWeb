"""
База знаний: два правила формата, каждое со своей причиной.

Оба записаны заранее (open_items §5) как решения, которые надо соблюсти,
когда до документации дойдут руки, — и оба бесполезны без проверки,
потому что нарушаются они молча.

  1. **Адрес фрагмента объявлен, а не выведен** — ни из заголовка, ни из
     имени файла. Ссылки на документацию расходятся по чатам и чужим
     материалам; выведенный из заголовка якорь ломается на первой правке
     формулировки, а править формулировки приходится постоянно.

  2. **Снимки экрана генерируются.** Снимок, снятый руками, устаревает
     беззвучно: на картинке остаётся кнопка, которой в продукте больше
     нет. Читатель при этом верит картинке больше, чем тексту.

Запуск:
    python -m unittest core.test_guide
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from core import guide


class FormatTests(unittest.TestCase):
    """Что вообще считается страницей базы."""

    def test_pages_parse(self):
        self.assertTrue(guide.load_pages())

    def test_every_page_declares_id_and_title(self):
        for page in guide.load_pages():
            with self.subTest(page=page.source):
                self.assertTrue(page.id)
                self.assertTrue(page.title)

    def test_page_ids_are_unique(self):
        ids = [p.id for p in guide.load_pages()]
        self.assertEqual(len(set(ids)), len(ids))

    def test_page_id_is_not_the_file_name(self):
        """
        Имя файла несёт ПОРЯДОК (`01-start.md`), а адрес — смысл
        (`start`). Совпади они, порядок нельзя было бы поменять, не сломав
        ссылки, — и однажды кто-нибудь поменяет.
        """
        for page in guide.load_pages():
            with self.subTest(page=page.source):
                self.assertNotEqual(page.id, Path(page.source).stem)

    def test_heading_without_an_anchor_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text(
                "---\nid: x\ntitle: X\n---\n\n## Заголовок без адреса\n",
                encoding="utf-8")
            with self.assertRaises(guide.GuideError) as ctx:
                guide.parse_page(path)
            self.assertIn("{#", str(ctx.exception))

    def test_page_without_front_matter_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text("# Просто текст\n", encoding="utf-8")
            with self.assertRaises(guide.GuideError):
                guide.parse_page(path)

    def test_duplicate_anchor_inside_a_page_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text(
                "---\nid: x\ntitle: X\n---\n\n"
                "## Раз {#a}\n\n## Два {#a}\n", encoding="utf-8")
            with self.assertRaises(guide.GuideError):
                guide.parse_page(path)


class MarkupTests(unittest.TestCase):
    """
    Разметка — закрытый набор, и это проверяется.

    Без проверки формат «расширяется» молча: автор пишет таблицу,
    рендерер про таблицы не знает, и в документации появляется абзац из
    палок. Поймано ровно так — нумерованный список схлопнулся в один
    абзац, и увидеть это можно было только глазами на собранной странице.
    """

    def _parse(self, body: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.md"
            path.write_text(f"---\nid: x\ntitle: X\n---\n\n{body}\n",
                            encoding="utf-8")
            return guide.parse_page(path)

    def test_unsupported_markup_is_refused(self):
        cases = {
            "таблица": "| а | б |",
            "цитата": "> цитата",
            "глубокий заголовок": "#### Слишком глубоко {#x}",
            "заголовок первого уровня": "# Заголовок",
            "картинка по пути": "![подпись](/img/x.png)",
            "внешняя ссылка": "[текст](https://example.com)",
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(guide.GuideError):
                    self._parse(body)

    def test_supported_markup_passes(self):
        page = self._parse(
            "## Раздел {#s}\n\nАбзац с **жирным** и `кодом`.\n\n"
            "* пункт\n\n1. шаг\n\n[ссылка](guide:x/s)\n\n"
            "![снимок](shot:generator-main)")
        self.assertEqual([s.id for s in page.sections], ["s"])
        self.assertEqual(page.shots, ["generator-main"])
        self.assertEqual(page.links, ["x/s"])

    def test_code_fence_may_contain_anything(self):
        # Во врезке кода живут примеры разметки и путей — запрещать их
        # там значило бы запретить документации показывать формат.
        page = self._parse("```\n| таблица |\n> цитата\n#### глубина\n```")
        self.assertTrue(page.body)


class AnchorRegistryTests(unittest.TestCase):
    """
    Реестр адресов. Смысл не в порядке ради порядка: опубликованный адрес
    нельзя убрать между делом, а увидеть его пропажу больше неоткуда.
    """

    def test_registry_matches_the_sources(self):
        actual = guide.all_anchors(guide.load_pages())
        listed = guide.registry()
        missing = sorted(set(actual) - set(listed))
        gone = sorted(set(listed) - set(actual))
        self.assertEqual(
            (missing, gone), ([], []),
            f"новые адреса надо внести в anchors.json: {missing}; "
            f"исчезли опубликованные адреса: {gone}")

    def test_anchors_are_unique_across_the_whole_base(self):
        anchors = guide.all_anchors(guide.load_pages())
        self.assertEqual(len(set(anchors)), len(anchors))

    def test_registry_is_not_empty(self):
        # Пустой реестр прошёл бы сравнение с пустой базой, ничего не
        # проверив.
        self.assertGreaterEqual(len(guide.registry()), 5)


class LinkTests(unittest.TestCase):

    def test_internal_links_point_at_existing_anchors(self):
        pages = guide.load_pages()
        known = set(guide.all_anchors(pages))
        for page in pages:
            for target in page.links:
                with self.subTest(page=page.id, link=target):
                    self.assertIn(target, known)


class ShotTests(unittest.TestCase):
    """Снимки: сгенерированы, на месте, и никто не подложил своих."""

    def test_referenced_shots_are_generated(self):
        listed = set(guide.generated_shots())
        for page in guide.load_pages():
            for shot in page.shots:
                with self.subTest(page=page.id, shot=shot):
                    self.assertIn(
                        shot, listed,
                        "снимок не значится у генератора: снят руками?")

    def test_referenced_shots_exist_on_disk(self):
        for page in guide.load_pages():
            for shot in page.shots:
                with self.subTest(page=page.id, shot=shot):
                    self.assertTrue(
                        (guide.SHOTS_DIR / f"{shot}.png").is_file())

    def test_no_stray_screenshots(self):
        """
        Файл в каталоге снимков, которого нет у генератора, — это снимок,
        положенный руками. Он и есть та самая молча устаревающая картинка,
        от которой уходили.
        """
        if not guide.SHOTS_DIR.exists():
            self.skipTest("снимки ещё не собирали")
        listed = set(guide.generated_shots())
        stray = sorted(p.name for p in guide.SHOTS_DIR.glob("*.png")
                       if p.stem not in listed)
        self.assertEqual(stray, [])

    def test_generator_and_manifest_agree(self):
        from scripts.guide_shots import SHOTS
        self.assertEqual(sorted(SHOTS), sorted(guide.generated_shots()))


class ExportTests(unittest.TestCase):
    """Выгрузка для веб-клиента: разбор один, а не по разбору на сторону."""

    def test_export_has_every_page(self):
        data = guide.to_json()
        self.assertEqual(len(data["pages"]), len(guide.load_pages()))

    def test_export_is_json_serialisable(self):
        json.dumps(guide.to_json(), ensure_ascii=False)

    def test_export_keeps_the_order(self):
        orders = [p["order"] for p in guide.to_json()["pages"]]
        self.assertEqual(orders, sorted(orders))


class ClientExportTests(unittest.TestCase):
    """
    Выгрузка для веб-клиента обязана совпадать с источниками.

    Она попадает в сборку обычным импортом, поэтому расхождение означает
    ровно одно: в приложении показывается вчерашняя документация, и
    заметить это можно только глазами.
    """

    def test_export_file_exists(self):
        self.assertTrue(guide.EXPORT_FILE.is_file(),
                        "соберите: python -m scripts.guide_export")

    def test_export_matches_the_sources(self):
        stored = json.loads(guide.EXPORT_FILE.read_text(encoding="utf-8"))
        self.assertEqual(stored, guide.to_json(),
                         "выгрузка отстала от docs/guide — пересоберите: "
                         "python -m scripts.guide_export")


class ContentTests(unittest.TestCase):
    """Немного о самом тексте — то, что проверяемо механически."""

    def test_no_page_is_a_stub(self):
        for page in guide.load_pages():
            with self.subTest(page=page.id):
                self.assertGreater(len(page.body.strip()), 400,
                                   "страница-заглушка хуже отсутствующей: "
                                   "она обещает ответ и не даёт его")

    def test_every_page_has_sections(self):
        for page in guide.load_pages():
            with self.subTest(page=page.id):
                self.assertTrue(page.sections)

    def test_no_latin_placeholders_left(self):
        # Заглушки вида TODO/TBD в опубликованной документации читаются
        # как «здесь никто не дописал» — и это правда.
        bad = re.compile(r"\b(TODO|TBD|FIXME|Lorem)\b")
        for page in guide.load_pages():
            with self.subTest(page=page.id):
                self.assertIsNone(bad.search(page.body))


if __name__ == "__main__":
    unittest.main()
