"""
Программа на C как модель — и ключ, проверенный компилятором.

Главный тест здесь запускает **gcc**. Это не педантизм: ожидаемый вывод в
этом генераторе написан руками на питоне параллельно тому, что печатает C,
и разойтись они могут молча. Так и оказалось — §2.6: у условных программ
ветка `else` в листинг не попадала, программа не печатала ничего, а ключ
обещал «Branch B: …». Никакой разбор кода этого не показал; показал
запуск.

Запуск:
    python -m unittest core.test_ccode_model
"""

from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.models.base import ModelConfigError  # noqa: E402
from core.models.opvs_ccode import KINDS, MODEL as CCODE  # noqa: E402

SEEDS = range(12)
HAS_GCC = shutil.which("gcc") is not None


def _instance(seed: int, **params):
    return CCODE.build(random.Random(seed), **({"mistakes": 5} | params))


def _compile_and_run(code: str):
    """(вывод, ошибка компиляции). Вывод None — не собралось."""
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "a.c")
        binary = os.path.join(folder, "a.out")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(code)
        built = subprocess.run(["gcc", "-O0", "-o", binary, source, "-lm"],
                               capture_output=True, text=True)
        if built.returncode:
            return None, built.stderr
        run = subprocess.run([binary], capture_output=True, text=True,
                             timeout=20)
        return run.stdout, ""


def _compiles(code: str) -> bool:
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "a.c")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write(code)
        return subprocess.run(["gcc", "-fsyntax-only", source],
                              capture_output=True).returncode == 0


@unittest.skipUnless(HAS_GCC, "нет gcc — ключ проверить нечем")
class CompilerTests(unittest.TestCase):
    """Единственный способ узнать, что печатает программа, — запустить её."""

    def test_the_program_prints_exactly_the_declared_output(self):
        for seed in SEEDS:
            instance = _instance(seed)
            actual, error = _compile_and_run(instance.values["code"])
            with self.subTest(seed=seed, kind=instance.values["kind"]):
                self.assertIsNotNone(actual, f"не собралось: {error}")
                self.assertEqual(actual.rstrip("\n"),
                                 instance.values["output"].rstrip("\n"))

    def test_every_kind_of_program_is_correct(self):
        for kind in KINDS:
            for seed in range(5):
                instance = _instance(seed, kind=kind)
                actual, error = _compile_and_run(instance.values["code"])
                with self.subTest(kind=kind, seed=seed):
                    self.assertIsNotNone(actual, f"не собралось: {error}")
                    self.assertEqual(actual.rstrip("\n"),
                                     instance.values["output"].rstrip("\n"))

    def test_both_branches_of_the_conditional_are_verified(self):
        """
        Прицельно по дефекту §2.6: ветка `else` в листинг не попадала, и
        программа не печатала ничего, пока ключ обещал «Branch B: …».
        Ловится это ТОЛЬКО на ложном условии, а оно редкое — 4 сида из
        сорока. На случайной выборке проверка проходила бы по совпадению,
        поэтому сиды обеих веток перечислены поимённо.
        """
        branches = set()
        for seed in (0, 1, 5, 11, 18):
            instance = _instance(seed, kind="conditional")
            expected = instance.values["output"]
            actual, error = _compile_and_run(instance.values["code"])
            branches.add("B" if "Branch B" in expected else "A")
            with self.subTest(seed=seed):
                self.assertIsNotNone(actual, f"не собралось: {error}")
                self.assertEqual(actual.rstrip("\n"), expected.rstrip("\n"))
        self.assertEqual(branches, {"A", "B"},
                         "проверены не обе ветки — тест ничего не сторожит")

    def test_broken_code_really_does_not_compile(self):
        """
        Задание «найдите синтаксические ошибки» держится на том, что они
        там есть. Код, который собирается, делает задание бессмысленным.
        """
        for seed in SEEDS:
            instance = _instance(seed)
            with self.subTest(seed=seed):
                self.assertFalse(_compiles(instance.values["broken"]))


class MistakeBookkeepingTests(unittest.TestCase):
    def test_log_matches_the_lines_that_actually_changed(self):
        """
        Ключ обязан указывать на строки, где код ДЕЙСТВИТЕЛЬНО другой.
        Расхождение здесь означало бы, что студент ищет ошибку там, где
        её нет, — и находит «свою», которой в ключе не окажется.
        """
        for seed in SEEDS:
            instance = _instance(seed)
            before = instance.values["code"].split("\n")
            after = instance.values["broken"].split("\n")
            changed = sorted(
                i + 1 for i in range(max(len(before), len(after)))
                if _at(before, i) != _at(after, i))
            with self.subTest(seed=seed):
                self.assertEqual(changed, instance.values["lines"])

    def test_one_mistake_per_line(self):
        """
        Инвариант модели, которого у генератора не было: замер показал
        43% прогонов, где две правки ложились в одну строку. Тогда «5
        ошибок» и «5 строк с ошибками» — разные числа, и задание «укажите
        номера строк» становится неформулируемым.
        """
        for seed in SEEDS:
            values = _instance(seed).values
            with self.subTest(seed=seed):
                self.assertEqual(len(set(values["lines"])),
                                 len(values["lines"]))
                self.assertEqual(len(values["lines"]),
                                 values["mistake_count"])
                self.assertEqual(len(values["mistakes"]),
                                 values["mistake_count"])

    def test_lines_are_sorted_and_inside_the_listing(self):
        for seed in SEEDS:
            values = _instance(seed).values
            total = len(values["broken"].split("\n"))
            with self.subTest(seed=seed):
                self.assertEqual(values["lines"], sorted(values["lines"]))
                self.assertTrue(all(1 <= n <= total for n in values["lines"]),
                                values["lines"])

    def test_descriptions_follow_the_same_order(self):
        for seed in SEEDS:
            values = _instance(seed).values
            numbers = [int(text.split(":", 1)[0].split()[1])
                       for text in values["mistakes"]]
            with self.subTest(seed=seed):
                self.assertEqual(numbers, values["lines"])

    def test_requested_count_is_honoured(self):
        for count in (1, 3, 7):
            with self.subTest(count=count):
                self.assertEqual(_instance(2, mistakes=count).values[
                    "mistake_count"], count)


class ParamTests(unittest.TestCase):
    def test_kind_is_honoured(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(_instance(0, kind=kind).values["kind"], kind)

    def test_any_kind_gives_all_three_eventually(self):
        seen = {_instance(seed).values["kind"] for seed in range(30)}
        self.assertEqual(seen, set(KINDS))

    def test_unknown_kind_is_a_config_error(self):
        with self.assertRaises(ModelConfigError):
            _instance(0, kind="рекурсивный")

    def test_absurd_count_is_a_config_error(self):
        for count in (0, 99):
            with self.subTest(count=count), self.assertRaises(ModelConfigError):
                _instance(0, mistakes=count)


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_gives_the_same_program(self):
        self.assertEqual(_instance(7).values["broken"],
                         _instance(7).values["broken"])

    def test_global_random_is_left_alone(self):
        # Исполнитель графа сеет глобальный random один раз на попытку;
        # сбить его посреди исполнения значит изменить соседние узлы.
        random.seed(99)
        expected = [random.random() for _ in range(3)]
        random.seed(99)
        _instance(4)
        self.assertEqual([random.random() for _ in range(3)], expected)

    def test_different_seeds_give_different_programs(self):
        seen = {_instance(seed).values["broken"] for seed in range(15)}
        self.assertGreater(len(seen), 10)


class OutputEquivalenceTests(unittest.TestCase):
    def test_trailing_whitespace_is_forgiven(self):
        instance = _instance(1)
        text = instance.values["output"]
        self.assertTrue(instance.equivalent("output", text + "\n\n  "))
        self.assertTrue(instance.equivalent(
            "output", "\n".join(line + "   " for line in text.split("\n"))))

    def test_line_order_matters(self):
        # Цикл печатает четыре строки — на однострочном выводе условной
        # программы эта проверка прошла бы по совпадению.
        instance = _instance(1, kind="loop")
        rows = instance.values["output"].split("\n")
        self.assertGreater(len(rows), 1)
        self.assertFalse(instance.equivalent(
            "output", "\n".join(reversed(rows))))

    def test_joining_the_lines_is_a_different_answer(self):
        instance = _instance(1, kind="loop")
        joined = instance.values["output"].replace("\n", " ")
        self.assertFalse(instance.equivalent("output", joined))


class OutputSpecTests(unittest.TestCase):
    """
    Вид ответа «вывод программы».

    Строковый слот сюда не годится по двум причинам, и обе молчаливые:
    общая нормализация схлопывает переводы строк, а допуск на опечатку
    принял бы `sum=86` вместо `sum=85`.
    """

    VALUE = "Loop results:\nsum=85\nproduct=0.047"

    def _spec(self):
        from core.answers import OutputSpec

        return OutputSpec(value=self.VALUE)

    def test_exact_answer_is_accepted(self):
        self.assertTrue(self._spec().check(self.VALUE).accepted)

    def test_trailing_space_is_forgiven(self):
        self.assertTrue(self._spec().check(self.VALUE + "  \n\n").accepted)

    def test_one_character_off_is_refused(self):
        self.assertFalse(self._spec().check(
            self.VALUE.replace("85", "86")).accepted)

    def test_one_line_answer_is_refused(self):
        self.assertFalse(self._spec().check(
            self.VALUE.replace("\n", " ")).accepted)

    def test_empty_is_reported_as_empty(self):
        from core.answers import Reason

        self.assertIs(self._spec().check("   ").reason, Reason.EMPTY)

    def test_examples_are_accepted(self):
        spec = self._spec()
        examples = spec.accepted_examples()
        self.assertTrue(examples)
        for text in examples:
            self.assertTrue(spec.check(text).accepted)

    def test_shown_as_a_listing(self):
        # Абзац схлопнул бы пробелы и перенёс бы строки по ширине окна.
        block = self._spec().display_blocks()[0]
        self.assertEqual(type(block).__name__, "CodeBlock")

    def test_widget_is_multiline(self):
        from core.widgets import widgets_for

        self.assertIn("text_area", [w.name for w in widgets_for(self._spec())])

    def test_survives_serialisation(self):
        from core.answers import AnswerSpec

        spec = self._spec()
        self.assertEqual(AnswerSpec.from_dict(spec.to_dict()), spec)


class CodeBlockNodeTests(unittest.TestCase):
    """
    Узла для листинга в языке не было — показать код из графа было нечем.
    """

    def test_registered(self):
        from core.graph.nodes import DEFAULT_REGISTRY

        self.assertTrue(DEFAULT_REGISTRY.has("code_block"))

    def test_keeps_indentation(self):
        from core.graph.node import ExecContext
        from core.graph.nodes import DEFAULT_REGISTRY

        node = DEFAULT_REGISTRY.create("code_block", "b", {"language": "c"})
        block = node.compute({"text": "int main() {\n    return 0;\n}"},
                             ExecContext(rng=random.Random(0)))["out"]
        self.assertIn("    return 0;", block.render_plain())
        self.assertEqual(block.language, "c")


class CCodeTaskTests(unittest.TestCase):
    """Задания целиком: одна модель, две разводки, обе проверяемы."""

    @staticmethod
    def _graph(shown: str, answer_port: str, statement: str, slot: str,
               kind: str = "loop"):
        # Вид программы закреплён: у условной вывод в одну строку, и
        # проверка «слитый в строку ответ не принимается» на ней ничего
        # бы не проверяла — прошла бы по совпадению.
        return {"nodes": [
            {"id": "m", "type": "model_opvs_ccode",
             "params": {"mistakes": 5, "kind": kind}},
            {"id": "b", "type": "code_block", "params": {"language": "c"}},
            {"id": "t", "type": "task",
             "params": {"statement": statement, "slots": [slot]}},
        ], "edges": [
            {"from": shown, "to": "b:text"},
            {"from": "b:out", "to": "t:blocks"},
            {"from": answer_port, "to": "t:ответ"},
        ]}

    def _run(self, *args):
        from core.graph.executor import GraphExecutor
        from core.graph.spec import GraphSpec

        return GraphExecutor(GraphSpec.parse(self._graph(*args))).run()

    def test_find_the_broken_lines(self):
        from core.interactive import session_from_task

        task = self._run("m:broken", "m:lines",
                         "В каких строках изменён код?", "ответ:number:много")
        self.assertTrue(task.is_checkable)
        self.assertEqual(len(task.answer_spec.input_fields()), 5)
        example = task.answer_spec.accepted_examples()[0]
        self.assertTrue(session_from_task(task).submit(example).correct)

    def test_what_does_the_program_print(self):
        from core.interactive import session_from_task

        task = self._run("m:code", "m:output",
                         "Что напечатает программа?", "ответ:output")
        self.assertEqual(task.answer_spec.kind, "output")
        example = task.answer_spec.accepted_examples()[0]
        self.assertTrue(session_from_task(task).submit(example).correct)
        self.assertFalse(session_from_task(task).submit(
            example.replace("\n", " ")).correct)

    def test_the_listing_reaches_the_statement(self):
        task = self._run("m:broken", "m:lines", "Найдите ошибки.",
                         "ответ:number:много")
        shown = "".join(block.render_plain() for block in task.statement)
        self.assertIn("int main()", shown)

    def test_two_wirings_give_two_different_tasks(self):
        first = self._run("m:broken", "m:lines", "Строки?",
                          "ответ:number:много")
        second = self._run("m:code", "m:output", "Вывод?", "ответ:output")
        self.assertNotEqual(first.answer_spec.kind, second.answer_spec.kind)


def _at(rows, index):
    return rows[index] if index < len(rows) else None


if __name__ == "__main__":
    unittest.main()
