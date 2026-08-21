"""
Ответ голосом: `VoiceSpec` и задание на произношение.

Что здесь закрепляется
----------------------
Правило приёма уже проверено само по себе
(`core/test_pronunciation_match.py`). Здесь проверяется, что оно
действительно СТАЛО заданием: спецификация, виджет, генератор, окрестность
и — главное — поведение на границе, где система НЕ ЗНАЕТ ответа.

Главное свойство, ради которого всё делалось, формулируется одной фразой:

    отказ проверить — не «неверно».

Сказать студенту «неверно» там, где не расслышали, значит соврать о его
ответе. Поэтому у отказа отдельный код (`Reason.UNCERTAIN`), и тесты
различают именно коды, а не только «принято / не принято».

Чего здесь НЕТ и почему
-----------------------
Живых записей людей. Их у нас нет, и делать вид, что есть, нельзя:
проверка идёт на поставочных эталонах с синтетическими искажениями
(`perturb` — темп, шум, громкость). Это НИЖНЯЯ граница: правило, не
пережившее искусственного искажения, не переживёт и настоящего.
Обратное отсюда не следует, и в тексте диплома это сказано прямо.

Запуск:
    python -m unittest core.test_voice_answer
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
import wave

import numpy as np

from core import pronunciation as P
from core import pronunciation_match as M
from core.answers import (
    INLINE_LIMIT_BYTES, INLINE_PREFIX,
    AnswerSpec, CheckMode, Reason, VoiceSpec, normalize,
)
from core.graph.resources import resolve
from core.widgets import registry, resolve_widget


def _terms_with_audio(limit: int) -> list[str]:
    """Несколько поставочных терминов, у которых есть эталон."""
    return sorted(P.audio_index())[:limit]


def _reference(term: str) -> pathlib.Path:
    return resolve(P.audio_of(term))


def _write(signal: np.ndarray, rate: int = M.TARGET_RATE) -> pathlib.Path:
    """Сохранить сигнал во временный WAV — то, что отдаёт запись с микрофона."""
    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    handle.close()
    path = pathlib.Path(handle.name)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(
            np.clip(signal * 32767.0, -32768, 32767).astype(np.int16).tobytes())
    return path


class VoiceSpecBasicsTests(unittest.TestCase):
    """Спецификация как спецификация: вид, виджет, сериализация."""

    def setUp(self):
        self.terms = _terms_with_audio(6)
        self.spec = VoiceSpec(term=self.terms[0],
                              vocabulary=tuple(self.terms),
                              transcription="/test/")

    def test_the_kind_is_registered(self):
        self.assertEqual(VoiceSpec.kind, "voice")
        restored = AnswerSpec.from_dict(self.spec.to_dict())
        self.assertEqual(restored, self.spec)

    def test_the_only_widget_that_serves_it_is_the_recorder(self):
        served = [w.name for w in registry.for_spec(self.spec)]
        self.assertEqual(served, ["voice_recorder"])
        self.assertEqual(resolve_widget(self.spec).name, "voice_recorder")

    def test_a_text_widget_does_not_serve_a_voice_answer(self):
        # Совместимость — свойство ПАРЫ. Поле ввода физически не может
        # принять произнесённое слово, и реестр обязан это знать.
        text_input = registry.get("text_input")
        self.assertFalse(text_input.serves(self.spec))

    def test_the_field_carries_no_answer(self):
        # То же требование, что у остальных видов: описание поля едет
        # отвечающему, а спецификация — нет.
        field = self.spec.input_fields()[0]
        self.assertEqual(field.kind, "voice")
        self.assertNotIn(self.spec.term, field.to_dict().get("hint", ""))

    def test_an_empty_answer_is_empty_not_wrong(self):
        verdict = self.spec.check("")
        self.assertEqual(verdict.reason, Reason.EMPTY)

    def test_a_missing_file_is_not_a_wrong_answer(self):
        verdict = self.spec.check("/нет/такого/файла.wav")
        self.assertEqual(verdict.reason, Reason.UNPARSED)

    def test_a_file_that_is_not_wav_is_refused_before_reading(self):
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        handle.write(b"not audio at all")
        handle.close()
        self.addCleanup(pathlib.Path(handle.name).unlink)
        self.assertEqual(self.spec.check(handle.name).reason, Reason.UNPARSED)

    def test_the_verdict_does_not_carry_the_local_path(self):
        """
        В попытку и в журнал уезжает `normalized_input`. Домашний каталог
        проверяющего к ответу отношения не имеет, и класть его туда
        незачем — тем более что путь у записи временный.
        """
        signal, rate = M.read_wav(_reference(self.terms[0]))
        path = _write(M.resample(signal, rate))
        self.addCleanup(path.unlink)
        verdict = self.spec.check(str(path))
        self.assertEqual(verdict.normalized_input, path.name)
        self.assertNotIn(str(path.parent), verdict.normalized_input)


class NeighbourhoodRuleTests(unittest.TestCase):
    """Правило приёма: ближайший эталон в СЛОВАРЕ."""

    @classmethod
    def setUpClass(cls):
        cls.terms = _terms_with_audio(6)

    def _spec(self, term: str, **kwargs) -> VoiceSpec:
        return VoiceSpec(term=term, vocabulary=tuple(self.terms), **kwargs)

    def test_the_reference_of_the_word_is_accepted(self):
        spec = self._spec(self.terms[0])
        self.assertTrue(spec.check(P.audio_of(self.terms[0])).accepted)

    def test_a_resource_identifier_is_accepted_as_the_answer(self):
        """
        Переносимая форма ответа. Путь верен на одной машине,
        идентификатор — на любой, где есть поставка.
        """
        spec = self._spec(self.terms[0])
        self.assertTrue(P.audio_of(self.terms[0]).startswith("res:"))
        self.assertTrue(spec.check(P.audio_of(self.terms[0])).accepted)

    def test_the_reference_of_another_word_is_a_mismatch(self):
        """
        Не отказ, а именно «неверно»: система расслышала — и услышала
        другое слово. Эти два исхода обязаны различаться.
        """
        spec = self._spec(self.terms[0])
        verdict = spec.check(P.audio_of(self.terms[1]))
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.MISMATCH)
        self.assertIn(self.terms[1], verdict.detail)

    def test_a_distorted_recording_is_still_accepted(self):
        """
        Главное практическое свойство: чужой голос и чужой микрофон
        сдвигают все расстояния разом, а порядок близости — нет.
        Искажения синтетические, и это нижняя граница, а не доказательство
        работы на живых записях.
        """
        accepted = 0
        for term in self.terms:
            signal, rate = M.read_wav(_reference(term))
            signal = M.resample(signal, rate)
            noisy = M.perturb(signal, speed=1.12, noise=0.03, gain=0.7, seed=3)
            path = _write(noisy)
            self.addCleanup(path.unlink)
            if self._spec(term).check(str(path)).accepted:
                accepted += 1
        self.assertEqual(accepted, len(self.terms),
                         "искажение темпа, шума и громкости не должно "
                         "менять, на что слово похоже больше всего")

    def test_silence_is_not_a_wrong_answer(self):
        path = _write(np.zeros(M.TARGET_RATE // 2, dtype=np.float32))
        self.addCleanup(path.unlink)
        verdict = self._spec(self.terms[0]).check(str(path))
        self.assertFalse(verdict.accepted)
        self.assertIn(verdict.reason, (Reason.EMPTY, Reason.UNCERTAIN))
        self.assertNotEqual(verdict.reason, Reason.MISMATCH)

    def test_without_references_it_refuses_instead_of_failing_the_student(self):
        """
        Установка без каталога звуков — поломка поставки, а не ответ
        студента. Вердикт обязан говорить «не с чем сравнить», а не
        «неверно»: иначе разбираться будут с произношением, а не с
        поставкой.
        """
        spec = VoiceSpec(term="нет-такого-слова",
                         vocabulary=("и-такого-нет",))
        signal, rate = M.read_wav(_reference(self.terms[0]))
        path = _write(M.resample(signal, rate))
        self.addCleanup(path.unlink)
        verdict = spec.check(str(path))
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.UNCERTAIN)


class InlineRecordingTests(unittest.TestCase):
    """
    Третья форма ответа: САМА ЗАПИСЬ, а не адрес.

    Ради чего она и существует
    --------------------------
    Первые две формы — путь и поставочный идентификатор — годятся, пока
    записывает и проверяет одна машина. У веба это не так: путь,
    присланный по сети, называл бы файл на ЧУЖОЙ машине, и принимать
    такое нельзя ни при каких условиях. Значит, браузер обязан прислать
    не имя, а содержимое.

    Проверяется поэтому не «работает ли base64», а то, что встроенная
    запись проходит РОВНО ТОТ ЖЕ путь, что файл: то же правило
    окрестности, тот же отказ на тишине, те же коды вердикта. Разойдись
    они — и одно и то же произношение получало бы разный ответ на разных
    клиентах, причём молча.

    И отдельно — что чужие байты не роняют проверку. Со встроенной формой
    в разбор впервые попадает то, что пришло по сети: не WAV, обрезанный
    WAV, мегабайт мусора. Каждый из этих случаев обязан быть вердиктом, а
    не отказом сервиса.
    """

    @classmethod
    def setUpClass(cls):
        cls.terms = _terms_with_audio(6)

    def _spec(self, term: str, **kwargs) -> VoiceSpec:
        return VoiceSpec(term=term, vocabulary=tuple(self.terms), **kwargs)

    @staticmethod
    def _inline(raw: bytes) -> str:
        import base64
        return INLINE_PREFIX + base64.b64encode(raw).decode("ascii")

    def _inline_reference(self, term: str) -> str:
        return self._inline(_reference(term).read_bytes())

    def test_the_reference_sent_as_data_is_accepted(self):
        term = self.terms[0]
        self.assertTrue(self._spec(term).check(self._inline_reference(term))
                        .accepted)

    def test_it_agrees_with_the_very_same_file(self):
        """
        Главное свойство: форма передачи на вердикт не влияет. Иначе
        студент получал бы разный ответ в браузере и в приложении.
        """
        for term in self.terms[:3]:
            with self.subTest(term=term):
                spec = self._spec(term)
                by_path = spec.check(str(_reference(term)))
                by_data = spec.check(self._inline_reference(term))
                self.assertEqual((by_path.accepted, by_path.reason),
                                 (by_data.accepted, by_data.reason))

    def test_another_word_sent_as_data_is_a_mismatch(self):
        verdict = self._spec(self.terms[0]).check(
            self._inline_reference(self.terms[1]))
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.MISMATCH)

    def test_silence_sent_as_data_is_not_a_wrong_answer(self):
        path = _write(np.zeros(M.TARGET_RATE // 2, dtype=np.float32))
        self.addCleanup(path.unlink)
        verdict = self._spec(self.terms[0]).check(
            self._inline(path.read_bytes()))
        self.assertFalse(verdict.accepted)
        self.assertIn(verdict.reason, (Reason.EMPTY, Reason.UNCERTAIN))

    def test_the_verdict_does_not_carry_the_recording(self):
        """
        `normalized_input` уезжает в попытку и в журнал. Положить туда
        мегабайт base64 значило бы завести хранение голоса случайно —
        мимо объёма, квот и согласия на запись. Поле обязано остаться
        коротким.
        """
        verdict = self._spec(self.terms[0]).check(
            self._inline_reference(self.terms[0]))
        self.assertLess(len(verdict.normalized_input), 60)
        self.assertNotIn("base64", verdict.normalized_input)

    def test_bytes_that_are_not_wav_give_a_verdict_not_a_crash(self):
        verdict = self._spec(self.terms[0]).check(
            self._inline("это совсем не звук".encode("utf-8")))
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.UNPARSED)

    def test_a_truncated_wav_gives_a_verdict_not_a_crash(self):
        raw = _reference(self.terms[0]).read_bytes()
        verdict = self._spec(self.terms[0]).check(self._inline(raw[:40]))
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.UNPARSED)

    def test_broken_base64_is_refused(self):
        verdict = self._spec(self.terms[0]).check(INLINE_PREFIX + "!!!!не64!!!")
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.UNPARSED)

    def test_an_oversized_recording_is_refused_without_decoding_it(self):
        """
        Поле ответа — не загрузка файла. Предел стоит на РАСКОДИРОВАННОМ
        размере, а проверяется по длине строки: раскодировать гигабайт
        ради того, чтобы его отвергнуть, незачем.
        """
        huge = INLINE_PREFIX + "A" * (INLINE_LIMIT_BYTES * 2)
        verdict = self._spec(self.terms[0]).check(huge)
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.UNPARSED)

    def test_an_empty_payload_is_refused(self):
        verdict = self._spec(self.terms[0]).check(INLINE_PREFIX)
        self.assertFalse(verdict.accepted)
        self.assertNotEqual(verdict.reason, Reason.EXACT)

    def test_the_recording_is_not_written_anywhere(self):
        """
        Запись не хранится — это записано в `VoiceSpec` и должно
        оставаться правдой. Проверяется тем, что после проверки во
        временном каталоге не прибавилось ни одного WAV.
        """
        import tempfile as tf

        before = set(pathlib.Path(tf.gettempdir()).glob("*.wav"))
        self._spec(self.terms[0]).check(self._inline_reference(self.terms[0]))
        after = set(pathlib.Path(tf.gettempdir()).glob("*.wav"))
        self.assertEqual(after - before, set())


class RefusalIsNotRejectionTests(unittest.TestCase):
    """Строгий режим отказывается судить, а не судит наугад."""

    @classmethod
    def setUpClass(cls):
        cls.terms = _terms_with_audio(6)

    def test_strict_refuses_on_a_single_word_vocabulary(self):
        """
        Словарь из ОДНОГО слова: разделения нет по построению, значит нет
        и свидетельства. Мягкий режим засчитает — первое место есть;
        строгий откажется, и это не придирчивость, а честность: выбирать
        не из чего.

        Прежнее правило считало такой вердикт бесконечно уверенным:
        отсутствие соперника принималось за бесспорную победу.
        """
        term = self.terms[0]
        spec_soft = VoiceSpec(term=term, vocabulary=(term,))
        spec_strict = VoiceSpec(term=term, vocabulary=(term,),
                                mode=CheckMode.STRICT)
        signal, rate = M.read_wav(_reference(term))
        path = _write(M.resample(signal, rate))
        self.addCleanup(path.unlink)

        self.assertTrue(spec_soft.check(str(path)).accepted)
        verdict = spec_strict.check(str(path))
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.reason, Reason.UNCERTAIN)

    def test_the_threshold_comes_from_the_vocabulary_not_a_constant(self):
        """
        Главное свойство исправления: масштаб уверенности приносит САМ
        СЛОВАРЬ.

        Проверяется тем, что мера безразмерна: умножение всех признаков
        на константу меняет все расстояния и не меняет ни доли, ни
        вердикта. Абсолютный порог этого не умел — его пришлось бы
        калибровать под голос и микрофон.
        """
        spec = VoiceSpec(term=self.terms[0], vocabulary=tuple(self.terms))
        references, gaps = spec._references()
        recording = M.features_of(_reference(self.terms[0]))
        plain = M.match(recording, references, gaps=gaps)

        scaled = {t: f * 4.0 for t, f in references.items()}
        loud = M.match(recording * 4.0, scaled, gaps=M.separations(scaled))

        self.assertEqual(plain.term, loud.term)
        self.assertEqual(plain.confident, loud.confident)
        self.assertAlmostEqual(plain.share, loud.share, places=4)
        self.assertGreater(loud.distance, plain.distance * 2)

    def test_an_uncertain_verdict_is_not_a_mismatch(self):
        """
        Различие кодов — единственное, по чему клиент отличает «вы сказали
        не то» от «я не расслышал». Слить их в один код значило бы
        показать студенту «неверно» на ровном месте.
        """
        self.assertNotEqual(Reason.UNCERTAIN, Reason.MISMATCH)
        self.assertEqual(Reason.UNCERTAIN.value, "uncertain")

    def test_a_refusal_is_still_not_accepted(self):
        """
        Отказ не означает «зачтём на всякий случай». Не расслышали —
        значит не зачли; вердикт остаётся отрицательным, меняется только
        его объяснение.
        """
        spec = VoiceSpec(term="нет-эталона", vocabulary=("и-тут-нет",))
        signal, rate = M.read_wav(_reference(self.terms[0]))
        path = _write(M.resample(signal, rate))
        self.addCleanup(path.unlink)
        verdict = spec.check(str(path))
        self.assertEqual(verdict.reason, Reason.UNCERTAIN)
        self.assertFalse(verdict.accepted)


class PreviewTests(unittest.TestCase):
    """«Предпросмотр не врёт» — тот же инвариант, что у остальных видов."""

    @classmethod
    def setUpClass(cls):
        cls.terms = _terms_with_audio(5)

    def test_the_promised_example_really_passes(self):
        for mode in (CheckMode.SOFT, CheckMode.STRICT):
            spec = VoiceSpec(term=self.terms[0], vocabulary=tuple(self.terms),
                             mode=mode)
            for example in spec.accepted_examples():
                with self.subTest(mode=mode, example=example):
                    self.assertTrue(spec.check(example, mode=mode).accepted)

    def test_a_word_without_a_reference_promises_nothing(self):
        spec = VoiceSpec(term="слова-такого-нет", vocabulary=("и-такого",))
        self.assertEqual(spec.accepted_examples(), [])

    def test_there_is_no_test_form_of_a_voice_answer(self):
        """
        Выбор из вариантов здесь не собирается: произношение нельзя
        предъявить четырьмя строчками. Пустой список честнее, чем тест,
        в котором верный ответ виден по написанию.
        """
        spec = VoiceSpec(term=self.terms[0], vocabulary=tuple(self.terms))
        self.assertEqual(spec.distractors(3), [])
        self.assertEqual(spec.options(4), [])


class DisplayTests(unittest.TestCase):
    """Показ выводится из данных — то же правило, что у остальных."""

    def test_the_answer_card_shows_the_word_and_offers_the_reference(self):
        term = _terms_with_audio(1)[0]
        spec = VoiceSpec(term=term, vocabulary=(term,), transcription="/ipa/")
        kinds = [type(b).__name__ for b in spec.display_blocks()]
        self.assertIn("TextBlock", kinds)
        self.assertIn("AudioBlock", kinds)

    def test_a_word_without_sound_still_shows_a_card(self):
        spec = VoiceSpec(term="безголосое", vocabulary=("безголосое",))
        blocks = spec.display_blocks()
        self.assertEqual([type(b).__name__ for b in blocks], ["TextBlock"])


class GeneratorTests(unittest.TestCase):
    """Раздел «произнесите вслух»."""

    @classmethod
    def setUpClass(cls):
        from exercises.english.generators import PronunciationGenerator
        cls.cls = PronunciationGenerator
        cls.path = cls._first_dictionary_with_audio()

    @staticmethod
    def _first_dictionary_with_audio() -> pathlib.Path:
        from exercises.english.generators import PronunciationGenerator
        for path in sorted(pathlib.Path("resources/words").glob("*.json")):
            if PronunciationGenerator("x", path)._load():
                return path
        raise unittest.SkipTest("нет словаря с готовым звуком")

    def _generator(self):
        return self.cls(name="Произношение", words_path=self.path,
                        partition_id=3_000_001)

    def test_the_task_is_checkable_and_still_exportable(self):
        from core import Capability
        generator = self._generator()
        self.assertIn(Capability.CHECKABLE, generator.capabilities)
        # Печатная форма остаётся: список слов для чтения вслух — законная
        # выдача, и отнимать её ради автопроверки незачем.
        self.assertIn(Capability.EXPORTABLE, generator.capabilities)

    def test_every_word_in_the_neighbourhood_has_a_reference(self):
        """
        Слово без эталона не участвует ни как цель, ни как сосед: правило
        сравнивает запись с эталонами, и слово без эталона в сравнении
        просто отсутствует, молча уменьшая окрестность.
        """
        spec = self._generator().generate().answer_spec
        for term in spec.vocabulary:
            with self.subTest(term=term):
                self.assertIsNotNone(P.audio_of(term))

    def test_the_target_is_inside_its_own_neighbourhood(self):
        spec = self._generator().generate().answer_spec
        self.assertIn(spec.term, spec.vocabulary)

    def test_the_neighbourhood_is_bounded(self):
        """
        Не весь словарь: правило считает DTW до КАЖДОГО эталона, и на
        двухстах словах это двести выравниваний на один ответ.
        """
        spec = self._generator().generate().answer_spec
        self.assertLessEqual(len(spec.vocabulary), self.cls.NEIGHBOURS)
        self.assertGreater(len(spec.vocabulary), 1)

    def test_the_statement_offers_the_reference(self):
        """
        Эталон в УСЛОВИИ, а не в разборе: здесь спрашивают произношение, и
        услышать образец до попытки — это и есть упражнение. В словарном
        диктанте та же кнопка стоит в разборе, потому что там она выдала
        бы ответ.
        """
        task = self._generator().generate()
        self.assertIn("AudioBlock",
                      [type(b).__name__ for b in task.statement])

    def test_it_refuses_rather_than_guesses_by_default(self):
        spec = self._generator().generate().answer_spec
        self.assertEqual(spec.mode, CheckMode.STRICT)

    def test_the_generated_task_survives_a_round_trip(self):
        """
        Задание уезжает в JSON — в снимок сессии и на клиент. Спецификация
        обязана пережить это без потерь, иначе восстановленная сессия
        проверяла бы другое.
        """
        from core.task import StaticTask
        task = self._generator().generate()
        restored = StaticTask.from_dict(task.to_dict())
        self.assertEqual(restored.answer_spec, task.answer_spec)

    def test_a_dictionary_without_sound_says_so_instead_of_failing(self):
        empty = tempfile.NamedTemporaryFile(suffix=".json", delete=False,
                                            mode="w", encoding="utf-8")
        empty.write('{"vocabulary": [{"term": "щукщ", "translation": "х"}]}')
        empty.close()
        self.addCleanup(pathlib.Path(empty.name).unlink)
        task = self.cls("Пусто", pathlib.Path(empty.name)).generate()
        self.assertIsNone(task.answer_spec)
        self.assertTrue(task.statement)


class SessionTests(unittest.TestCase):
    """Проверяемое задание, поданное как сессия «решать»."""

    @classmethod
    def setUpClass(cls):
        from exercises.english.generators import PronunciationGenerator
        cls.generator = PronunciationGenerator(
            name="Произношение",
            words_path=GeneratorTests._first_dictionary_with_audio(),
            partition_id=3_000_001)

    def test_the_session_asks_for_the_recorder(self):
        from core.interactive import SolvingGenerator
        session = SolvingGenerator(self.generator).generate()
        self.assertEqual(session.current().widget_name(), "voice_recorder")

    def test_the_reference_closes_the_question(self):
        from core.interactive import SolvingGenerator
        session = SolvingGenerator(self.generator).generate()
        term = session.current().spec.term
        result = session.submit(P.audio_of(term))
        self.assertTrue(result.correct)
        self.assertTrue(session.is_finished())

    def test_the_attempt_describes_the_outcome_and_not_the_recording(self):
        """
        Запись не хранится: поле попытки текстовое, а двоичное хранилище —
        отдельная работа. Клиент, которому нечего положить в попытку,
        спрашивает сессию, и та отвечает тем, что и так знает.
        """
        from core.interactive import SolvingGenerator
        session = SolvingGenerator(self.generator).generate()
        term = session.current().spec.term
        session.submit(P.audio_of(term))
        payload = session.attempt_payload()
        self.assertEqual(payload["term"], term)
        self.assertEqual(payload["kind"], "voice")
        self.assertTrue(payload["accepted"])
        self.assertNotIn("input", payload)
        self.assertNotIn(".wav", repr(payload))

    def test_an_empty_session_describes_nothing(self):
        from core.interactive import SolvingGenerator
        session = SolvingGenerator(self.generator).generate()
        self.assertEqual(session.attempt_payload(), {})


class AudioLookupTests(unittest.TestCase):
    """Адресация звука по термину, включая запасной путь."""

    def test_a_term_written_without_its_gloss_still_finds_its_sound(self):
        """
        В одном словаре сокращение записано «BIOS», в другом — «BIOS
        (Basic Input/Output System)». Манифест адресует термин
        посимвольно и считал их разными словами: звук терялся при том,
        что файл есть.

        Подмена законна по построению материала: `tools/generate_audio.py`
        снимает скобочное пояснение ПЕРЕД синтезом, поэтому в файле
        произнесено ровно сокращение (проверено длительностью: 0.57 с).
        """
        index = P.audio_index()
        glossed = [t for t in index if "(" in t]
        if not glossed:
            self.skipTest("в поставке нет терминов с пояснением")
        full = glossed[0]
        short = full.split("(", 1)[0].strip()
        self.assertNotIn(short, index, "случай выродился: короткая форма "
                                       "есть в манифесте сама по себе")
        self.assertEqual(P.audio_of(short), index[full])

    def test_an_unknown_term_still_has_no_sound(self):
        """Запасной путь не должен превращаться в «найдётся что-нибудь»."""
        self.assertIsNone(P.audio_of("заведомо-несуществующий-термин"))
        self.assertIsNone(P.audio_of(""))

    def test_the_fallback_does_not_shadow_an_exact_match(self):
        term = next(iter(P.audio_index()))
        self.assertEqual(P.audio_of(term), P.audio_index()[term])


class PartitionBandTests(unittest.TestCase):
    """Номер раздела выводится из имени, и полоса своя."""

    def test_three_sections_of_one_dictionary_never_collide(self):
        from core import partition_ids as ids
        stem = "unit3_hardware"
        numbers = {ids.english_words_id(stem),
                   ids.english_transcription_id(stem),
                   ids.english_pronunciation_id(stem)}
        self.assertEqual(len(numbers), 3)
        self.assertIn(ids.english_pronunciation_id(stem),
                      ids.ENGLISH_PRONUNCIATION)

    def test_the_band_is_reserved_on_both_installs(self):
        """
        Полоса объявлена обеими сторонами, хотя разделы в ней заводит пока
        только десктоп. Иначе `next_dynamic_id` на сервере выдал бы
        пользовательскому разделу номер, занятый на десктопе кодом, — тот
        самый дефект расхождения установок, ради которого модуль написан.
        """
        from core import partition_ids as ids
        self.assertIn(ids.ENGLISH_PRONUNCIATION, ids.RESERVED)
        self.assertTrue(ids.is_reserved(ids.ENGLISH_PRONUNCIATION.start))
        following = ids.next_dynamic_id([ids.ENGLISH_PRONUNCIATION.start - 1])
        self.assertFalse(ids.is_reserved(following))


class DtwSpeedTests(unittest.TestCase):
    """
    Ускорение выравнивания не должно менять его результат.

    Считается по антидиагоналям вместо построчного обхода — ради скорости
    (замер: 3.65 с на ответ в задании на произношение). Рекуррента при
    этом не тронута, и здесь это утверждение проверяется, а не
    декларируется.
    """

    @staticmethod
    def _row_by_row(a: np.ndarray, b: np.ndarray) -> float:
        """Прежняя реализация — эталон сравнения."""
        if a.shape[0] == 0 or b.shape[0] == 0:
            return float("inf")
        cost = np.sqrt(np.maximum(
            ((a ** 2).sum(axis=1)[:, None] + (b ** 2).sum(axis=1)[None, :]
             - 2.0 * a @ b.T), 0.0))
        rows, cols = cost.shape
        acc = np.full((rows + 1, cols + 1), np.inf, dtype=np.float64)
        acc[0, 0] = 0.0
        for i in range(1, rows + 1):
            previous, current = acc[i - 1], acc[i]
            line = cost[i - 1]
            for j in range(1, cols + 1):
                current[j] = line[j - 1] + min(previous[j], current[j - 1],
                                               previous[j - 1])
        return float(acc[rows, cols] / (rows + cols))

    def test_the_value_is_the_same_as_before(self):
        generator = np.random.default_rng(20260818)
        for _ in range(40):
            rows = int(generator.integers(1, 25))
            cols = int(generator.integers(1, 25))
            a = generator.normal(size=(rows, 4)).astype(np.float32)
            b = generator.normal(size=(cols, 4)).astype(np.float32)
            with self.subTest(rows=rows, cols=cols):
                self.assertAlmostEqual(M.dtw_distance(a, b),
                                       self._row_by_row(a, b), places=9)

    def test_it_holds_on_real_references(self):
        terms = _terms_with_audio(4)
        features = [M.features_of(_reference(t)) for t in terms]
        for a in features:
            for b in features:
                self.assertAlmostEqual(M.dtw_distance(a, b),
                                       self._row_by_row(a, b), places=9)


class ItIsReachableAtAllTests(unittest.TestCase):
    """
    Раздел заводится при старте — иначе упражнения просто нет.

    Класс дефекта, ради которого проверка написана: генератор
    `PronunciationGenerator` существовал, тестами покрывался и НЕ БЫЛ
    подключён к `bootstrap` на сервере. Разделы «Английский: …
    (произношение)» заводил только десктоп; на вебе упражнение было
    недостижимо, и ни один тест этого не видел — все они брали генератор
    напрямую, минуя реестр.

    Это тот же класс, что «Смотреть/Решать» и число вариантов: **два
    клиента расходятся молча**. Поэтому проверяется не генератор, а то,
    что до него можно ДОЙТИ — через реестр, собранный обычным путём.
    """

    @classmethod
    def setUpClass(cls):
        import shutil

        import bootstrap
        from const import DB_TEMPLATE, WORDS_DIR
        from core import Repository
        from core.tmpdb import temp_path

        if not pathlib.Path(DB_TEMPLATE).exists():
            raise unittest.SkipTest("базы нет в этой сборке")
        # На КОПИИ: поставку прогон не трогает (docs/handbook/06 §7).
        copy = temp_path()
        shutil.copyfile(DB_TEMPLATE, copy)
        cls.repo = Repository(copy)
        bootstrap.sync_database(cls.repo, WORDS_DIR)
        cls.registry = bootstrap.build_registry(cls.repo, WORDS_DIR)
        cls.words_dir = WORDS_DIR

    @staticmethod
    def _has_audio(path: pathlib.Path) -> bool:
        """
        Есть ли в словаре хоть один термин с эталоном.

        Считается ЗДЕСЬ, а не берётся из `bootstrap`, намеренно. Проверка
        должна падать словами «раздела нет», а не «нет такой функции»:
        первое называет дефект, второе — только его признак, и на старом
        коде вся эта группа падала бы `AttributeError`, ничего не сказав
        про недостижимое упражнение.
        """
        from core import pronunciation
        from exercises.english.generators import (
            WordsTrainerGenerator, _read_json_lenient,
        )
        try:
            words = WordsTrainerGenerator._flatten_words(
                _read_json_lenient(path))
        except Exception:                       # noqa: BLE001
            return False
        return any(pronunciation.audio_of(term) for term in words)

    def _dictionaries_with_audio(self) -> list[pathlib.Path]:
        from exercises.english.generators import _detect_kind
        return [p for p in sorted(self.words_dir.glob("*.json"))
                if _detect_kind(p) == "words" and self._has_audio(p)]

    def test_a_dictionary_with_sound_gets_its_partition(self):
        from core import partition_ids

        wanted = self._dictionaries_with_audio()
        if not wanted:
            self.skipTest("в поставке нет словарей со звуком")
        known = {p.id for p in self.repo.list_partitions_for_subject(2)}
        missing = [p.stem for p in wanted
                   if partition_ids.english_pronunciation_id(p.stem)
                   not in known]
        self.assertEqual(missing, [])

    def test_the_partition_has_a_generator_behind_it(self):
        """
        Раздел без генератора хуже отсутствующего: он стоит в списке
        наравне с рабочими, а клик по нему даёт отказ.
        """
        from core import partition_ids

        wanted = self._dictionaries_with_audio()
        if not wanted:
            self.skipTest("в поставке нет словарей со звуком")
        unserved = [p.stem for p in wanted
                    if not self.registry.has(
                        partition_ids.english_pronunciation_id(p.stem))]
        self.assertEqual(unserved, [])

    def test_a_dictionary_without_sound_gets_no_partition(self):
        """
        Обратная сторона: раздел, который на первом же клике скажет
        «здесь ничего нет», заводить нельзя.
        """
        from core import partition_ids
        from exercises.english.generators import _detect_kind

        silent = [p for p in sorted(self.words_dir.glob("*.json"))
                  if _detect_kind(p) == "words" and not self._has_audio(p)]
        if not silent:
            self.skipTest("все словари поставки со звуком")
        known = {p.id for p in self.repo.list_partitions_for_subject(2)}
        extra = [p.stem for p in silent
                 if partition_ids.english_pronunciation_id(p.stem) in known]
        self.assertEqual(extra, [])

    def test_the_task_it_serves_asks_for_the_recorder(self):
        from core import partition_ids

        wanted = self._dictionaries_with_audio()
        if not wanted:
            self.skipTest("в поставке нет словарей со звуком")
        pid = partition_ids.english_pronunciation_id(wanted[0].stem)
        task = self.registry.get(pid).generate()
        self.assertEqual(task.answer_spec.preferred_widget, "voice_recorder")


if __name__ == "__main__":
    unittest.main()
