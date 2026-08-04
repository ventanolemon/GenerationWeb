"""
Сервисный путь общей интерактивной сессии (этап 2).

Проверяет проводку, а не доменную логику: что `POST /generate` умеет
открыть сессию над статическим заданием со спецификацией, что ходы идут
через существующий `POST /interactive/submit` без отдельного эндпоинта, и
— главное — что прикрепление спецификации к генератору НЕ меняет поведение
уже работающих вызовов.

Приложение собирается из роутеров, а не импортом `generator_service.main`:
тот тянет bootstrap и exercises со словарями. Так же устроен
`core.test_api_contract`.

Запуск: python -m unittest core.test_interactive_api  (из корня монорепо)
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

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core.answers import NumberSpec, Tolerance, ToleranceKind  # noqa: E402
from core.blocks import TextBlock  # noqa: E402
from core.generator import CHECKABLE_DEFAULT, STATIC_DEFAULT, TaskGenerator  # noqa: E402
from core.repository import Repository  # noqa: E402
from core.task import StaticTask  # noqa: E402
from generator_service import errors  # noqa: E402
from generator_service.routers import generate as generate_router  # noqa: E402
from generator_service.routers import interactive as interactive_router  # noqa: E402
from generator_service.session_store import SessionStore  # noqa: E402

CHECKABLE_PARTITION = 1
PLAIN_PARTITION = 2


class _CheckableGenerator(TaskGenerator):
    name = "Проверяемый"
    partition_id = CHECKABLE_PARTITION
    capabilities = CHECKABLE_DEFAULT

    def generate(self) -> StaticTask:
        return StaticTask(
            statement=[TextBlock("Ускорение свободного падения?")],
            answer=[TextBlock("9.8 м/с^2")],
            answer_spec=NumberSpec(
                value=9.8, unit="м/с^2",
                tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1)),
        )


class _PlainGenerator(TaskGenerator):
    name = "Обычный"
    partition_id = PLAIN_PARTITION
    capabilities = STATIC_DEFAULT

    def generate(self) -> StaticTask:
        return StaticTask(statement=[TextBlock("условие")],
                          answer=[TextBlock("ответ")])


class _Registry:
    def __init__(self):
        self._items = {
            CHECKABLE_PARTITION: _CheckableGenerator(),
            PLAIN_PARTITION: _PlainGenerator(),
        }

    def has(self, partition_id) -> bool:
        return partition_id in self._items

    def get(self, partition_id, params=None):
        return self._items[partition_id]


class InteractiveApiTestBase(unittest.TestCase):

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)

        app = FastAPI()
        errors.install(app)
        app.include_router(generate_router.router)
        app.include_router(interactive_router.router)
        app.state.repo = self.repo
        app.state.registry = _Registry()
        app.state.sessions = SessionStore(1800)
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def generate(self, partition_id, **extra):
        body = {"partition_id": partition_id, "user_id": "ivanov"}
        body.update(extra)
        return self.client.post("/generate", json=body)


class DefaultBehaviourUnchangedTests(InteractiveApiTestBase):
    """
    Прикрепление спецификации не должно менять то, что уже работает.

    Иначе «обогатить ответ» стало бы ломающим изменением, и обогащать
    существующие разделы стало бы страшно.
    """

    def test_checkable_partition_still_returns_static_by_default(self):
        data = self.generate(CHECKABLE_PARTITION).json()
        self.assertEqual(data["type"], "static")
        self.assertIn("statement", data)
        self.assertIn("answer", data)

    def test_static_answer_is_still_rendered_blocks(self):
        data = self.generate(CHECKABLE_PARTITION).json()
        self.assertEqual(data["answer"][0]["type"], "text")

    def test_spec_and_widgets_ride_along(self):
        data = self.generate(CHECKABLE_PARTITION).json()
        self.assertTrue(data["is_checkable"])
        self.assertEqual(data["answer_spec"]["kind"], "number")
        self.assertIn("text_input", [w["name"] for w in data["widgets"]])

    def test_plain_partition_is_untouched(self):
        data = self.generate(PLAIN_PARTITION).json()
        self.assertFalse(data["is_checkable"])
        self.assertNotIn("answer_spec", data)


class InteractiveOptInTests(InteractiveApiTestBase):

    def test_interactive_flag_opens_a_session(self):
        data = self.generate(CHECKABLE_PARTITION, interactive=True).json()
        self.assertEqual(data["type"], "interactive")
        self.assertTrue(data["session_id"])
        self.assertEqual(data["prompt"][0]["content"],
                         "Ускорение свободного падения?")

    def test_widget_is_reported(self):
        data = self.generate(CHECKABLE_PARTITION, interactive=True).json()
        self.assertEqual(data["widget"], "text_input")

    def test_plain_partition_ignores_the_flag(self):
        # Проверять нечем — значит статика, а не пустая сессия.
        data = self.generate(PLAIN_PARTITION, interactive=True).json()
        self.assertEqual(data["type"], "static")

    def test_submit_goes_through_the_existing_endpoint(self):
        session_id = self.generate(
            CHECKABLE_PARTITION, interactive=True).json()["session_id"]
        answer = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "9.85 м/с^2"})
        body = answer.json()
        self.assertTrue(body["correct"])
        self.assertTrue(body["is_finished"])

    def test_wrong_answer_reveals_the_expected_one(self):
        session_id = self.generate(
            CHECKABLE_PARTITION, interactive=True).json()["session_id"]
        body = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "1"}).json()
        self.assertFalse(body["correct"])
        shown = " ".join(b.get("content", "") for b in body["feedback"])
        self.assertIn("Правильный ответ", shown)

    def test_attempts_are_honoured(self):
        session_id = self.generate(
            CHECKABLE_PARTITION, interactive=True,
            max_attempts=2).json()["session_id"]
        first = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "1"}).json()
        self.assertFalse(first["is_finished"], "должна остаться вторая попытка")
        second = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "9.8 м/с^2"}).json()
        self.assertTrue(second["correct"])
        self.assertTrue(second["is_finished"])

    def test_finished_session_is_dropped_from_the_store(self):
        session_id = self.generate(
            CHECKABLE_PARTITION, interactive=True).json()["session_id"]
        self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "9.8 м/с^2"})
        again = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "9.8 м/с^2"})
        self.assertEqual(again.status_code, 404)


if __name__ == "__main__":
    unittest.main()
