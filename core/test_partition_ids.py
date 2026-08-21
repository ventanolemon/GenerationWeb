"""
Номер раздела выводится из имени, а не из положения файла.

Дефект, ради которого написано: `pid = 1000 + i` по месту файла в
отсортированном списке. На сервере 20 словарей, на десктопе 12 — и номер
1001 означает `complete_vocabulary` на одном и `complete_words` на другом.
Синхронизация переносит разделы ПО НОМЕРУ, поэтому задание, выданное на
сервере, открывает на десктопе другой словарь. Молча.

Проверяется не «функция что-то возвращает», а три свойства, каждое из
которых при старой схеме нарушалось:

    1. номер не зависит от того, какие ещё файлы лежат рядом;
    2. номер одинаков в разных запусках Python;
    3. динамическая выдача не заходит в полосы, которыми владеет код.

Запуск:
    python -m unittest core.test_partition_ids
"""

from __future__ import annotations

import subprocess
import sys
import unittest

from core import partition_ids as P


class StabilityTests(unittest.TestCase):

    def test_id_does_not_depend_on_neighbours(self):
        """
        Главное свойство. Раньше добавление файла, встающего раньше по
        алфавиту, сдвигало номера ВСЕХ последующих словарей — вместе с
        уже выданными по ним заданиями.
        """
        few = ["unit1_history", "unit2_types"]
        many = ["aaa_new_dictionary", *few, "zzz_another"]
        first = P.assign(few, P.ENGLISH_WORDS)
        second = P.assign(many, P.ENGLISH_WORDS)
        for stem in few:
            with self.subTest(stem=stem):
                self.assertEqual(first[stem], second[stem])

    def test_id_survives_a_new_python_process(self):
        """
        `hash()` в Python рандомизируется от запуска к запуску: номер,
        посчитанный через него, разъезжался бы даже на одной машине.
        Поэтому проверяем в ОТДЕЛЬНОМ процессе, а не в этом.
        """
        code = ("import sys; sys.path.insert(0, '.');"
                " from core import partition_ids as P;"
                " print(P.english_words_id('unit3_hardware'))")
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, check=True)
        self.assertEqual(int(out.stdout.strip()),
                         P.english_words_id("unit3_hardware"))

    def test_case_and_spacing_do_not_change_the_id(self):
        self.assertEqual(P.english_words_id("Unit1_History"),
                         P.english_words_id(" unit1_history "))

    def test_words_and_transcription_are_different_sections(self):
        """
        Словарный тренажёр и «выбери транскрипцию» — два разных раздела
        одного файла. Пересечься их номера не могут: полосы разные.
        """
        stem = "term_4_unit1_internet"
        self.assertIn(P.english_words_id(stem), P.ENGLISH_WORDS)
        self.assertIn(P.english_transcription_id(stem), P.ENGLISH_TRANSCRIPTION)
        self.assertNotEqual(P.english_words_id(stem),
                            P.english_transcription_id(stem))

    def test_real_dictionary_names_do_not_collide(self):
        stems = [
            "complete_abbreveations", "complete_vocabulary", "complete_words",
            "term_4_complete_vocabulary", "term_4_unit1_internet",
            "term_4_unit2_search_engines", "term_4_unit3_programming_languages",
            "term_4_unit4_web_design", "term_4_unit5_malware_cybercrime",
            "term_4_unit6_data_security", "term_4_unit7_future_of_it",
            "term_4_unit8_professions_in_it", "term_4_z_sentences_it",
            "unit1_history", "unit2_types", "unit3_hardware",
            "unit4_primary_storage", "unit5_secondary_storage",
            "unit6_software", "unit7_networks",
        ]
        ids = P.assign(stems, P.ENGLISH_WORDS)
        self.assertEqual(len(set(ids.values())), len(stems))


class CollisionTests(unittest.TestCase):

    def test_collision_is_loud(self):
        """
        Разрешать столкновение подбором свободного места нельзя: подбор
        вернул бы зависимость номера от того, какие файлы лежат рядом, —
        то есть ровно исходный дефект. Поэтому — исключение.
        """
        narrow = range(0, 4)          # четыре места на пять имён
        names = [f"name{i}" for i in range(5)]
        with self.assertRaises(P.PartitionIdCollision):
            P.assign(names, narrow)

    def test_same_name_twice_is_not_a_collision(self):
        ids = P.assign(["unit1_history", "unit1_history"], P.ENGLISH_WORDS)
        self.assertEqual(len(ids), 1)


class DynamicAllocationTests(unittest.TestCase):

    def test_next_id_continues_after_the_largest_dynamic(self):
        self.assertEqual(P.next_dynamic_id([1, 2, 1017, 1018, 1033]), 1034)

    def test_next_id_jumps_over_a_reserved_band(self):
        """
        Так и появился дефект: автоинкремент SQLite дорос до 1000+ и
        начал раздавать номера внутри полосы словарей — разделы «Группа»
        и «Группа_2» получили 1017 и 1018.
        """
        candidate = P.next_dynamic_id([P.MODEL_TASKS.start - 1])
        self.assertFalse(P.is_reserved(candidate))
        self.assertEqual(candidate, P.MODEL_TASKS.stop)

    def test_reserved_ids_are_ignored_when_continuing(self):
        """Раздел из полосы кода не должен толкать динамическую выдачу."""
        self.assertEqual(P.next_dynamic_id([5, P.ENGLISH_WORDS.start + 7]), 6)

    def test_empty_database_starts_at_one(self):
        self.assertEqual(P.next_dynamic_id([]), 1)


class BandTests(unittest.TestCase):

    def test_bands_do_not_overlap(self):
        bands = list(P.RESERVED) + [P.LEGACY_ENGLISH]
        for i, a in enumerate(bands):
            for b in bands[i + 1:]:
                with self.subTest(a=a, b=b):
                    self.assertFalse(max(a.start, b.start)
                                     < min(a.stop, b.stop))

    def test_legacy_band_is_not_reserved_anymore(self):
        """
        Старая полоса 1000..1999 освобождена намеренно: пользовательские
        разделы «Группа»/«Группа_2» уже стоят внутри неё, и переносить их
        не за чем — новые словари туда больше не приходят.
        """
        self.assertFalse(P.is_reserved(P.LEGACY_ENGLISH.start))
        self.assertFalse(P.is_reserved(1017))


if __name__ == "__main__":
    unittest.main()
