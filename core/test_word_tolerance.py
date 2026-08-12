"""
Допуск опечатки в словарном диктанте.

Главное свойство формулируется одной фразой и проверяется прогоном по
НАСТОЯЩИМ словарям, а не рассуждением о константах:

    другое слово словаря не может быть принято как опечатка.

Оно не подобрано, а следует из правила: порог ограничен расстоянием до
ближайшего соседа. Поэтому тест «столкновений нет» — это проверка
устройства, а не удачного выбора чисел.

Что было до правила (замер на поставочных словарях, 160 слов): 17 пар,
неразличимых проверкой, — LAN принимал MAN, WAN и WLAN, AI принимал AR,
hardware принимал shareware. Все они лежат в тех же словарях как разные
термины.

Запуск:
    python -m unittest core.test_word_tolerance
"""

from __future__ import annotations

import pathlib
import unittest

from core import word_tolerance as WT

#: Настоящий фрагмент курса: четыре сетевых термина в одном юните — тот
#: самый случай, на котором старое правило и ломалось.
NETWORK = {"lan": "локальная сеть", "wan": "глобальная сеть",
           "man": "городская сеть", "wlan": "беспроводная сеть"}


class DistanceTests(unittest.TestCase):

    def test_known_values(self):
        self.assertEqual(WT.levenshtein("cat", "cat"), 0)
        self.assertEqual(WT.levenshtein("cat", "cot"), 1)
        self.assertEqual(WT.levenshtein("", "abc"), 3)
        self.assertEqual(WT.levenshtein("kitten", "sitting"), 3)

    def test_symmetric(self):
        for a, b in (("lan", "wan"), ("hardware", "shareware"), ("", "x")):
            with self.subTest(pair=(a, b)):
                self.assertEqual(WT.levenshtein(a, b), WT.levenshtein(b, a))


class BudgetTests(unittest.TestCase):

    def test_short_words_get_no_budget_at_all(self):
        """
        В слове из трёх букв опечатка неотличима от другого слова:
        расстояние 1 отделяет «cat» от «cot», «bat» и «car». Допуск здесь
        означал бы «принимаем любую букву».
        """
        for word in ("ai", "lan", "ssl"):
            with self.subTest(word=word):
                self.assertEqual(WT.length_budget(word), 0)

    def test_budget_grows_with_length(self):
        self.assertEqual(WT.length_budget("book"), 1)
        self.assertEqual(WT.length_budget("necessary"), 2)

    def test_vocabulary_tightens_the_budget(self):
        # Без словаря «hardware» допускает две правки; рядом лежащее
        # «shareware» на расстоянии двух — значит, можно только одну.
        self.assertEqual(WT.budget("hardware"), 2)
        self.assertEqual(
            WT.budget("hardware", ["hardware", "shareware", "software"]), 1)

    def test_vocabulary_never_widens_the_budget(self):
        # Окрестность может только ужать: словарь из одного слова не даёт
        # права принимать больше, чем позволяет длина.
        for word in ("book", "necessary", "accommodation"):
            with self.subTest(word=word):
                self.assertLessEqual(WT.budget(word, [word]),
                                     WT.length_budget(word))

    def test_missing_vocabulary_falls_back_to_length(self):
        # Честный откат: набор слов неизвестен (одиночный слот ответа) —
        # остаётся политика по длине, а не «разрешим побольше».
        self.assertEqual(WT.budget("necessary", None),
                         WT.length_budget("necessary"))


class TheInvariantTests(unittest.TestCase):
    """То, ради чего всё и делалось."""

    def test_another_word_of_the_vocabulary_is_never_accepted(self):
        for word in NETWORK:
            for other in NETWORK:
                if other == word:
                    continue
                with self.subTest(word=word, answer=other):
                    self.assertFalse(WT.accepts(word, other, NETWORK))

    def test_no_collisions_in_a_tight_vocabulary(self):
        self.assertEqual(WT.vocabulary_collisions(NETWORK), [])

    def test_no_collisions_in_the_shipped_dictionaries(self):
        """
        Прогон по НАСТОЯЩЕЙ поставке, а не по придуманному примеру.
        Именно он и обнаружил дефект: на выдуманных словах старое правило
        выглядело разумным.
        """
        words = _shipped_words()
        if len(words) < 50:
            self.skipTest("в этой поставке слишком мало слов")
        self.assertEqual(WT.vocabulary_collisions(words), [])

    def test_the_old_rule_did_collide(self):
        """
        Регрессия наоборот: показываем, что старое правило (порог только
        по длине) на этом же словаре пары ПРИНИМАЛО. Без этого проверка
        выше не отличается от «правило всегда работало».
        """
        old_threshold = lambda w: 1 if len(w) <= 6 else 2   # noqa: E731
        collisions = [
            (a, b) for a in NETWORK for b in NETWORK
            if a != b and WT.levenshtein(a, b) <= old_threshold(a)
        ]
        self.assertTrue(collisions, "старое правило должно было сталкиваться")


class TyposStillPassTests(unittest.TestCase):
    """Ужать допуск легко; смысл в том, чтобы опечатки всё ещё принимались."""

    def test_dropped_letter_in_a_long_word_is_accepted(self):
        for word in ("necessary", "accommodation", "hyperlink"):
            typo = word[:len(word) // 2] + word[len(word) // 2 + 1:]
            with self.subTest(word=word):
                self.assertTrue(WT.accepts(word, typo, [word]))

    def test_case_and_spaces_do_not_matter(self):
        self.assertTrue(WT.accepts("Hardware", "  hardware  ", ["hardware"]))

    def test_most_typos_survive_on_the_shipped_dictionaries(self):
        """
        Цена правила — числом. Ужимать допуск до нуля везде было бы
        «безопасно» и бесполезно: проверка перестала бы отличаться от
        строгой, и мягкий режим потерял бы смысл.
        """
        words = _shipped_words()
        if len(words) < 50:
            self.skipTest("в этой поставке слишком мало слов")
        checked = accepted = 0
        for word in words:
            if len(word) < 4:
                continue
            typo = word[:len(word) // 2] + word[len(word) // 2 + 1:]
            checked += 1
            if WT.accepts(word, typo, words):
                accepted += 1
        self.assertGreater(accepted / checked, 0.85,
                           f"принято {accepted} из {checked}")


class SessionTests(unittest.TestCase):
    """Тренажёр считает допуск по словарю сессии — и не меняет его по ходу."""

    def _session(self):
        from exercises.english.generators import WordsSession
        return WordsSession(dict(NETWORK), tolerant=True)

    def test_session_uses_its_vocabulary(self):
        session = self._session()
        self.assertEqual(sorted(session._vocabulary()), sorted(NETWORK))

    def test_vocabulary_does_not_shrink_with_progress(self):
        """
        Допуск, посчитанный по «оставшимся» словам, рос бы к концу
        диктанта: соседи кончаются, окрестность разрежается. Один и тот
        же ответ принимался бы или отвергался в зависимости от того,
        когда его дали, — и объяснить это студенту было бы нечем.
        """
        session = self._session()
        before = sorted(session._vocabulary())
        session._remaining.pop(next(iter(session._remaining)))
        self.assertEqual(sorted(session._vocabulary()), before)


def _shipped_words() -> list[str]:
    from exercises.english.generators import (
        WordsTrainerGenerator, _read_json_lenient,
    )
    root = pathlib.Path(__file__).resolve().parent.parent
    found: set[str] = set()
    for path in sorted((root / "resources" / "words").glob("*.json")):
        try:
            data = _read_json_lenient(path)
            found |= {str(k).strip().lower()
                      for k in WordsTrainerGenerator._flatten_words(data)}
        except Exception:                       # noqa: BLE001
            continue
    return sorted(w for w in found if w.isalpha())


if __name__ == "__main__":
    unittest.main()
