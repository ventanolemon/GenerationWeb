"""
Проверка произношения: ближайший эталон в словаре, а не абсолютный порог.

Главное свойство здесь то же, что у допуска на опечатку, и формулируется
так же одной фразой:

    вердикт выносится сравнением с ОСТАЛЬНЫМИ словами словаря,
    а не сравнением с порогом.

Почему порог хуже: ему нужна калибровка под голос и микрофон, а правилу
ближайшего — нет, оно сравнивает внутри одной записи.

Отдельно закреплён отрицательный результат. Замысел был показать, что
порога, годного сразу для всех, не существует; на поставочных эталонах с
синтетическими искажениями это НЕ подтвердилось — порог разделял
(18.2 против 21.0). Тест `test_absolute_threshold_is_not_ruled_out_on_this_material`
закрепляет факт, а не желаемое.

Второе свойство, ради которого всё и делалось: правило умеет ОТКАЗАТЬСЯ
судить. Порог этого отказа СНАЧАЛА БЫЛ КОНСТАНТОЙ (отрыв ≥ 8%), и это
была та же ошибка, против которой написан модуль: замер по всем
четырнадцати словарям поставки дал 144 уверенно неверных вердикта из
1651, причём на 11 словарях из 14.

Порог заменён на выводимый из окрестности: отрыв меряется долей от
`separation` — расстояния между эталонами самого словаря. После замены
на том же протоколе: 832 вердикта, **0 неверных, 0 словарей с ошибками**;
цена — покрытие упало с 78.6% до 39.6%. Разбор в
`docs/thesis/07-chapter-results.md` §7.3.2.

Запуск:
    python -m unittest core.test_pronunciation_match
"""

from __future__ import annotations

import math
import pathlib
import unittest

import numpy as np

from core import pronunciation as P
from core import pronunciation_match as M
from core.graph.resources import resolve


def _shipped(limit: int = 8) -> dict[str, np.ndarray]:
    """Признаки нескольких поставочных эталонов."""
    index = P.audio_index()
    terms = sorted(index)[:limit]
    return M.reference_features(
        terms, lambda term: resolve(index[term]) if term in index else None)


def _signal(term: str) -> np.ndarray:
    signal, rate = M.read_wav(resolve(P.audio_index()[term]))
    return M.resample(signal, rate)


class SignalTests(unittest.TestCase):
    """Чтение и приведение звука."""

    def test_reads_shipped_wav(self):
        index = P.audio_index()
        if not index:
            self.skipTest("в этой поставке нет звука")
        signal, rate = M.read_wav(resolve(next(iter(index.values()))))
        self.assertGreater(signal.size, 0)
        self.assertGreater(rate, 0)
        self.assertLessEqual(float(np.max(np.abs(signal))), 1.0001)

    def test_resample_changes_length_proportionally(self):
        signal = np.sin(np.linspace(0, 50, 1000)).astype(np.float32)
        out = M.resample(signal, 22050, 11025)
        self.assertAlmostEqual(out.size / signal.size, 0.5, places=2)

    def test_trim_removes_leading_and_trailing_silence(self):
        core = np.ones(100, dtype=np.float32)
        padded = np.concatenate([np.zeros(500, dtype=np.float32), core,
                                 np.zeros(500, dtype=np.float32)])
        self.assertLess(M.trim_silence(padded).size, padded.size)
        self.assertGreaterEqual(M.trim_silence(padded).size, core.size - 2)


class FeatureTests(unittest.TestCase):
    """Признаки: что они обязаны игнорировать."""

    def test_shape_is_frames_by_cepstra(self):
        features = M.mfcc(np.sin(np.linspace(0, 400, 11025)).astype(np.float32))
        self.assertEqual(features.shape[1], M.CEPSTRA - 1)
        self.assertGreater(features.shape[0], 10)

    def test_gain_does_not_change_features(self):
        """
        Громкость записи к произношению отношения не имеет. Свойство
        обеспечено по построению — отброшен нулевой коэффициент (он и
        есть громкость) и вычтено среднее, — поэтому и проверяется как
        свойство, а не как удачный порог.

        Допуск 1e-3, а не ноль: признаки считаются в float32, и разница
        порядка 1e-4 остаётся от округления, а не от громкости.
        """
        signal = np.sin(np.linspace(0, 400, 11025)).astype(np.float32)
        quiet = M.mfcc(signal * 0.3)
        loud = M.mfcc(signal * 1.0)
        self.assertEqual(quiet.shape, loud.shape)
        np.testing.assert_allclose(quiet, loud, atol=1e-3)

    def test_empty_input_gives_empty_features(self):
        self.assertEqual(M.mfcc(np.zeros(0, dtype=np.float32)).shape[0], 0)


class DistanceTests(unittest.TestCase):

    def test_distance_to_itself_is_zero(self):
        """
        Строго нулём оно не будет: матрица расстояний считается через
        `a² + b² − 2ab`, и на близких к нулю величинах float32 даёт
        остаток порядка 1e-3. Проверяется поэтому малость, а не нуль.
        """
        features = M.mfcc(np.sin(np.linspace(0, 400, 5000)).astype(np.float32))
        self.assertLess(M.dtw_distance(features, features), 1e-2)

    def test_symmetric(self):
        a = M.mfcc(np.sin(np.linspace(0, 400, 5000)).astype(np.float32))
        b = M.mfcc(np.sin(np.linspace(0, 700, 5000)).astype(np.float32))
        self.assertAlmostEqual(M.dtw_distance(a, b), M.dtw_distance(b, a),
                               places=6)

    def test_tempo_change_costs_less_than_a_different_word(self):
        """
        Ради этого и нужно выравнивание по времени: то же слово, сказанное
        быстрее, обязано быть ближе, чем другое слово.

        Проверяется на НАСТОЯЩЕЙ речи, а не на синусоидах. Первая
        редакция теста брала чистые тоны и падала: у стационарного тона
        признаки почти постоянны во времени, а вычитание среднего
        обнуляет ровно то, чем два тона и различаются. Материал теста
        должен быть того же рода, что и материал задачи.
        """
        index = P.audio_index()
        if len(index) < 2:
            self.skipTest("в поставке нет звука")
        terms = sorted(index)[:2]
        reference = M.mfcc(_signal(terms[0]))
        faster = M.mfcc(M.perturb(_signal(terms[0]), speed=1.2))
        other = M.mfcc(_signal(terms[1]))
        self.assertLess(M.dtw_distance(reference, faster),
                        M.dtw_distance(reference, other))

    def test_empty_side_gives_infinity(self):
        features = M.mfcc(np.sin(np.linspace(0, 400, 5000)).astype(np.float32))
        empty = np.zeros((0, M.CEPSTRA - 1), dtype=np.float32)
        self.assertEqual(M.dtw_distance(features, empty), float("inf"))


class NeighbourhoodRuleTests(unittest.TestCase):
    """То, ради чего модуль написан."""

    def setUp(self):
        self.references = _shipped()
        if len(self.references) < 4:
            self.skipTest("в поставке слишком мало звука")

    def test_every_reference_identifies_itself(self):
        self.assertEqual(M.vocabulary_confusions(self.references), [])

    def test_tempo_change_is_still_recognized(self):
        """Другой темп — тот же говорящий: слово обязано остаться тем же."""
        for term in list(self.references)[:4]:
            with self.subTest(term=term):
                distorted = M.mfcc(M.perturb(_signal(term), speed=1.2))
                self.assertTrue(M.accepts(term, distorted, self.references))

    def test_wrong_word_is_rejected(self):
        terms = list(self.references)
        recording = M.mfcc(_signal(terms[0]))
        self.assertFalse(M.accepts(terms[1], recording, self.references))

    def test_verdict_is_refused_when_the_lead_is_thin(self):
        """
        Вторая половина правила: при слабом отрыве вердикт не выносится.
        Ошибиться уверенно хуже, чем отказаться судить, — особенно на
        зачёте.
        """
        terms = list(self.references)
        noisy = M.mfcc(M.perturb(_signal(terms[0]), noise=0.6, seed=1))
        found = M.match(noisy, self.references)
        self.assertIsNotNone(found)
        if found.confident:
            self.skipTest("на этой поставке шум не размыл отрыв")
        self.assertFalse(M.accepts(terms[0], noisy, self.references,
                                   require_confident=True))

    def test_a_single_word_vocabulary_is_never_confident(self):
        """
        Словарь из одного слова: соперника нет, разделения нет, значит
        нет и свидетельства. Прежнее правило считало такой вердикт
        БЕСКОНЕЧНО уверенным — отсутствие соперника принималось за
        бесспорную победу.
        """
        term = next(iter(self.references))
        alone = {term: self.references[term]}
        found = M.match(M.mfcc(_signal(term)), alone)
        self.assertEqual(found.term, term)
        self.assertFalse(found.confident)
        self.assertEqual(found.share, 0.0)
        self.assertFalse(M.accepts(term, M.mfcc(_signal(term)), alone,
                                   require_confident=True))
        # Без требования уверенности — принимается: первое место есть.
        self.assertTrue(M.accepts(term, M.mfcc(_signal(term)), alone))

    def test_a_perfect_recording_takes_all_of_the_separation(self):
        """
        Смысл величины `share`: доля ДОСТИЖИМОГО разделения.

        Запись, совпавшая с эталоном, стоит от своего слова на нуле, а от
        ближайшего чужого — ровно на `separation`. Значит доля равна
        единице, и это верхняя граница, а не совпадение.
        """
        term = next(iter(self.references))
        found = M.match(self.references[term], self.references)
        self.assertEqual(found.term, term)
        self.assertAlmostEqual(found.share, 1.0, places=2)
        self.assertTrue(found.confident)

    def test_separation_is_computed_from_references_alone(self):
        """
        Масштаб уверенности не должен зависеть от записи — иначе он снова
        начнёт зависеть от голоса и микрофона, то есть потребует
        калибровки. Проверяется буквально: величина считается функцией,
        которой запись не передают.
        """
        gaps = M.separations(self.references)
        self.assertEqual(set(gaps), set(self.references))
        for term, value in gaps.items():
            with self.subTest(term=term):
                self.assertGreater(value, 0.0)
                self.assertTrue(math.isfinite(value))
        # То же значение, что кладётся в вердикт.
        term = next(iter(self.references))
        found = M.match(M.mfcc(_signal(term)), self.references)
        self.assertAlmostEqual(found.separation, gaps[found.term], places=9)

    def test_precomputed_separations_change_nothing(self):
        """
        Готовые межэталонные расстояния — только про скорость. Вердикт с
        ними обязан совпадать с вердиктом без них, иначе кэш начинает
        менять результат.
        """
        gaps = M.separations(self.references)
        for term in list(self.references)[:3]:
            recording = M.mfcc(M.perturb(_signal(term), speed=1.1, seed=2))
            with self.subTest(term=term):
                self.assertEqual(
                    M.match(recording, self.references).confident,
                    M.match(recording, self.references, gaps=gaps).confident)

    def test_the_threshold_is_not_a_distance(self):
        """
        Главное свойство новой меры: она БЕЗРАЗМЕРНА.

        Умножение всех признаков на константу меняет все расстояния — и
        не должно менять ни доли, ни вердикта. Именно этого не умел
        прежний абсолютный порог, и именно поэтому его приходилось бы
        калибровать под голос и микрофон.
        """
        scaled = {t: f * 3.0 for t, f in self.references.items()}
        term = next(iter(self.references))
        plain = M.match(M.mfcc(_signal(term)), self.references)
        loud = M.match(M.mfcc(_signal(term)) * 3.0, scaled)
        self.assertEqual(plain.term, loud.term)
        # Не до последнего знака: DTW накапливает погрешность на
        # умноженных признаках. Проверяется свойство, а не арифметика.
        self.assertAlmostEqual(plain.share, loud.share, places=4)
        self.assertGreater(loud.distance, plain.distance)

    def test_absolute_threshold_is_not_ruled_out_on_this_material(self):
        """
        Честная запись отрицательного результата.

        Замысел был показать, что абсолютного порога, годного сразу для
        всех слов, не существует: наибольшее расстояние «своё к своему
        после искажения» превысило бы наименьшее «чужое к чужому». На
        поставочных эталонах с синтетическими искажениями **это не так** —
        замер: 18.2 против 21.0, то есть порог бы разделил.

        Причина в материале: искажения темпом и шумом мягче, чем смена
        живого диктора. Утверждение «порог не переносится между
        дикторами» известно из литературы, но НАШИМИ данными не
        подтверждено, и опираться на него в работе нельзя.

        Правило ближайшего остаётся предпочтительным по другой причине,
        и она проверяема: порогу нужна калибровка под голос и микрофон, а
        правилу ближайшего — нет, оно сравнивает внутри одной записи.

        Тест закрепляет ФАКТ, а не желаемое: если на новом материале
        (живые записи) разделимость исчезнет, он упадёт, и это будет
        сигналом обновить формулировку.
        """
        own: list[float] = []
        alien: list[float] = []
        terms = list(self.references)[:5]
        for term in terms:
            distorted = M.mfcc(M.perturb(_signal(term), speed=1.15,
                                         noise=0.05, seed=7))
            own.append(M.dtw_distance(distorted, self.references[term]))
            for other in terms:
                if other != term:
                    alien.append(M.dtw_distance(self.references[term],
                                                self.references[other]))
        self.assertLess(max(own), min(alien),
                        "разделимость пропала — обновить формулировку в "
                        "docs/thesis и в докстроке core/pronunciation_match")

    def test_single_word_vocabulary_gives_no_lead(self):
        """
        В словаре из одного слова сравнивать не с чем, и правило это
        показывает: отрыв бесконечен, но соседа нет. Вызывающий обязан
        учитывать, что уверенность здесь ничего не означает.
        """
        term = list(self.references)[0]
        found = M.match(M.mfcc(_signal(term)), {term: self.references[term]})
        self.assertIsNotNone(found)
        self.assertIsNone(found.runner_up)


class ResourceTests(unittest.TestCase):

    def test_missing_reference_is_skipped_not_fatal(self):
        refs = M.reference_features(["нет такого слова"], lambda term: None)
        self.assertEqual(refs, {})

    def test_match_without_references_returns_none(self):
        features = M.mfcc(np.sin(np.linspace(0, 400, 5000)).astype(np.float32))
        self.assertIsNone(M.match(features, {}))


if __name__ == "__main__":
    unittest.main()
