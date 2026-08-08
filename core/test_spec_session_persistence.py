"""
Переезд общей интерактивной сессии между процессами (этап 2).

`core.test_session_persistence` уже проверяет этот путь для тренажёра слов.
Там задание пересобирается детерминированно: словарь лежит в БД, и снимка
одного прогресса достаточно.

Здесь случай принципиально другой и более опасный. Вопрос породил генератор
со случайными параметрами, поэтому пересборка в другом процессе даёт
ДРУГОЕ задание. Если бы снимок нёс только прогресс, студент после переезда
увидел бы чужое условие и свой ответ на него не узнал.

Проверяется именно это: сессия, поднятая вторым стором из БД, продолжает
тот же вопрос, а не свежесгенерированный.

Запуск: python -m unittest core.test_spec_session_persistence  (из корня монорепо)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)

from core.answers import NumberSpec, Tolerance, ToleranceKind  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.interactive import Question, SpecSession, session_from_task  # noqa: E402
from core.repository import Repository  # noqa: E402
from core.task import StaticTask  # noqa: E402
from generator_service.session_store import SessionStore  # noqa: E402


def a_task(value: float, text: str) -> StaticTask:
    """Статическое задание со спецификацией — то, что отдаёт генератор."""
    return StaticTask(
        statement=[TextBlock(text)],
        answer=[TextBlock(str(value))],
        answer_spec=NumberSpec(
            value=value, tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.05)),
    )


class SpecSessionAcrossProcessesTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(os.path.join(self._tmp.name, "db.sqlite"))
        # Каждый вызов «генератора» даёт НОВОЕ случайное задание — как в
        # жизни. Счётчик делает расхождение наблюдаемым.
        self._calls = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _factory(self, partition_id, user_id=None):
        self._calls += 1
        return session_from_task(
            a_task(float(self._calls), f"вопрос номер {self._calls}"))

    def _store(self):
        return SessionStore(1800, repo=self.repo, task_factory=self._factory)

    def test_second_process_continues_the_same_question(self):
        first = self._store()
        session = SpecSession([
            Question([TextBlock("первый")], NumberSpec(value=1.0)),
            Question([TextBlock("второй")], NumberSpec(value=2.0)),
        ])
        sid = first.create(session, partition_id=42, user_id="ivanov")
        session.submit("1")
        first.save(sid)

        revived = self._store().get(sid)

        self.assertIsNotNone(revived, "сессия должна подняться из БД")
        self.assertEqual(
            [b.render_plain() for b in revived.initial_prompt()], ["второй"],
            "после переезда должен продолжиться ТОТ ЖЕ вопрос")
        self.assertEqual(revived.score, (1, 2))

    def test_regenerated_task_does_not_leak_into_the_session(self):
        first = self._store()
        session = SpecSession([Question([TextBlock("исходный вопрос")],
                                        NumberSpec(value=7.0))])
        sid = first.create(session, partition_id=42)
        first.save(sid)

        revived = self._store().get(sid)

        self.assertGreater(self._calls, 0, "фабрика обязана была отработать")
        shown = [b.render_plain() for b in revived.initial_prompt()]
        self.assertEqual(shown, ["исходный вопрос"])
        self.assertNotIn("вопрос номер", shown[0],
                         "в сессию просочилось пересобранное задание")
        # И ответ проверяется по исходной спецификации, а не по новой.
        self.assertTrue(revived.submit("7").correct)

    def test_answer_still_checks_after_the_move(self):
        first = self._store()
        session = session_from_task(a_task(9.8, "ускорение?"))
        sid = first.create(session, partition_id=42)
        first.save(sid)

        revived = self._store().get(sid)
        result = revived.submit("9.81")

        self.assertTrue(result.correct, "допуск обязан пережить переезд")
        self.assertTrue(revived.is_finished())

    def test_finished_session_survives_as_finished(self):
        first = self._store()
        session = session_from_task(a_task(3.0, "три?"))
        sid = first.create(session, partition_id=42)
        session.submit("3")
        first.save(sid)

        revived = self._store().get(sid)
        self.assertTrue(revived.is_finished())
        self.assertEqual(revived.score, (1, 1))


if __name__ == "__main__":
    unittest.main()
