"""
Произношение термина: транскрипция и звук.

Материал восстановлен из ветки `claude/zen-edison-BFxwD`, где он был
собран в июне и не доехал до master: три коммита (транскрипции, звук,
упражнение на выбор) остались на ветке после того, как в неё влили
несвязанную правку. Ничего не отменяли — просто не слили.

Проверяется не «файлы на месте», а то, ради чего материал восстановлен:

    1. звук адресуется идентификатором, а не путём — иначе он не
       переживёт границу между десктопом и вебом;
    2. выверенная автором запись побеждает сгенерированную;
    3. покрытие поставки — числом, а не словом «есть».

Третье важнее, чем кажется: «звук есть» может означать и два файла из
пятисот. Замер на восстановленной поставке — 462 термина со звуком из
463 и 405 с транскрипцией.

Запуск:
    python -m unittest core.test_pronunciation
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from core import pronunciation as P


class ResourceIdTests(unittest.TestCase):
    """Звук адресуется идентификатором — иначе он машинно-локален."""

    def test_audio_is_addressed_by_identifier(self):
        index = P.audio_index()
        if not index:
            self.skipTest("в этой поставке нет звука")
        for term, value in list(index.items())[:20]:
            with self.subTest(термин=term):
                self.assertTrue(value.startswith(P.AUDIO_PREFIX), value)

    def test_identifier_resolves_to_an_existing_file(self):
        from core.graph.resources import resolve
        index = P.audio_index()
        if not index:
            self.skipTest("в этой поставке нет звука")
        for term, value in list(index.items())[:20]:
            with self.subTest(термин=term):
                self.assertTrue(pathlib.Path(resolve(value)).exists())

    def test_terms_without_a_file_are_dropped(self):
        """Кнопка, ведущая в никуда, хуже отсутствующей."""
        from core.graph.resources import resolve
        for value in P.audio_index().values():
            self.assertTrue(pathlib.Path(resolve(value)).exists())

    def test_audio_kind_is_declared_as_a_resource(self):
        from core.graph.resources import KINDS
        self.assertIn("audio", KINDS)
        self.assertEqual(KINDS["audio"][1], (".wav",))


class LookupTests(unittest.TestCase):

    def test_inline_beats_the_generated_table(self):
        """
        Общая таблица собрана скриптом и местами приблизительна; запись в
        самом словаре — то, что автор выверил руками. Правило «своё важнее
        общего» и есть способ такую правку закрепить.
        """
        term = next(iter(P.transcriptions()), None)
        if term is None:
            self.skipTest("в этой поставке нет транскрипций")
        self.assertNotEqual(P.transcription_of(term), "/своё/")
        self.assertEqual(P.transcription_of(term, {term: "/своё/"}), "/своё/")

    def test_unknown_term_gives_none_rather_than_raising(self):
        self.assertIsNone(P.transcription_of("совершенно неизвестное слово"))
        self.assertIsNone(P.audio_of("совершенно неизвестное слово"))

    def test_empty_inline_value_does_not_shadow_the_table(self):
        term = next(iter(P.transcriptions()), None)
        if term is None:
            self.skipTest("в этой поставке нет транскрипций")
        self.assertEqual(P.transcription_of(term, {term: ""}),
                         P.transcription_of(term))


class InlineExtractionTests(unittest.TestCase):
    """Разбор поля `transcription` в самих словарях."""

    def test_single_unit_format(self):
        data = {"unit": 1, "vocabulary": [
            {"term": "cat", "translation": "кошка", "transcription": "/kæt/"},
            {"term": "dog", "translation": "собака"},
        ]}
        self.assertEqual(P.inline_transcriptions(data), {"cat": "/kæt/"})

    def test_combined_units_format(self):
        data = {"units": [
            {"vocabulary": [{"term": "a", "translation": "а",
                             "transcription": "/eɪ/"}]},
            {"vocabulary": [{"term": "b", "translation": "б",
                             "transcription": "/biː/"}]},
        ]}
        self.assertEqual(P.inline_transcriptions(data),
                         {"a": "/eɪ/", "b": "/biː/"})

    def test_old_flat_format_has_no_place_for_them(self):
        self.assertEqual(P.inline_transcriptions({"cat": "кошка"}), {})

    def test_blank_transcription_is_not_a_transcription(self):
        data = {"vocabulary": [{"term": "cat", "translation": "кошка",
                                "transcription": "  "}]}
        self.assertEqual(P.inline_transcriptions(data), {})


class ShippedCoverageTests(unittest.TestCase):
    """Сколько поставки покрыто — числом, а не словом «есть»."""

    def _terms(self) -> set[str]:
        from exercises.english.generators import (
            WordsTrainerGenerator, _read_json_lenient,
        )
        root = pathlib.Path(__file__).resolve().parent.parent
        found: set[str] = set()
        for path in sorted((root / "resources" / "words").glob("*.json")):
            try:
                found |= set(WordsTrainerGenerator._flatten_words(
                    _read_json_lenient(path)))
            except Exception:                   # noqa: BLE001
                continue
        return found

    def test_most_of_the_vocabulary_has_audio(self):
        terms = self._terms()
        if len(terms) < 50:
            self.skipTest("в этой поставке слишком мало слов")
        total, _ipa, sound = P.coverage(terms)
        self.assertGreater(sound / total, 0.9, f"со звуком {sound} из {total}")

    def test_most_of_the_vocabulary_has_a_transcription(self):
        terms = self._terms()
        if len(terms) < 50:
            self.skipTest("в этой поставке слишком мало слов")
        total, ipa, _sound = P.coverage(terms)
        self.assertGreater(ipa / total, 0.7, f"с транскрипцией {ipa} из {total}")

    def test_no_generator_placeholders_leaked_into_the_table(self):
        """
        Скрипт помечает ненайденное как `/<слово>/`. Такие записи в
        таблицу попасть не должны: показать студенту `/<adware>/` хуже,
        чем не показать ничего. В отчёте для разбора их 57 — в поставке
        должно быть ноль.
        """
        leaked = [f"{k} → {v}" for k, v in P.transcriptions().items()
                  if "<" in v or ">" in v]
        self.assertEqual(leaked, [])

    def test_every_transcription_looks_like_one(self):
        bad = [f"{k} → {v}" for k, v in P.transcriptions().items()
               if not (v.startswith("/") and v.endswith("/") and len(v) > 2)]
        self.assertEqual(bad[:5], [])


class MissingResourcesTests(unittest.TestCase):
    """Словарь без транскрипций и звука — норма, а не поломка."""

    def setUp(self):
        self.saved = (P.TRANSCRIPTIONS_PATH, P.AUDIO_DIR, P.AUDIO_INDEX_PATH)
        empty = pathlib.Path(tempfile.mkdtemp())
        P.TRANSCRIPTIONS_PATH = empty / "нет.json"
        P.AUDIO_DIR = empty / "audio"
        P.AUDIO_INDEX_PATH = P.AUDIO_DIR / "index.json"
        P.reset_cache()

    def tearDown(self):
        (P.TRANSCRIPTIONS_PATH, P.AUDIO_DIR, P.AUDIO_INDEX_PATH) = self.saved
        P.reset_cache()

    def test_absent_files_give_empty_tables(self):
        self.assertEqual(P.transcriptions(), {})
        self.assertEqual(P.audio_index(), {})

    def test_lookup_still_works(self):
        self.assertIsNone(P.transcription_of("cat"))
        self.assertIsNone(P.audio_of("cat"))

    def test_broken_json_is_not_a_crash(self):
        P.TRANSCRIPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        P.TRANSCRIPTIONS_PATH.write_text("{это не json", encoding="utf-8")
        P.reset_cache()
        self.assertEqual(P.transcriptions(), {})

    def test_wrong_shape_is_not_a_crash(self):
        P.TRANSCRIPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        P.TRANSCRIPTIONS_PATH.write_text(json.dumps(["список"]),
                                         encoding="utf-8")
        P.reset_cache()
        self.assertEqual(P.transcriptions(), {})


if __name__ == "__main__":
    unittest.main()
