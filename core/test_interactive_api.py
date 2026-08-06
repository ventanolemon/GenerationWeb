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
import re
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
from generator_service.routers import answers as answers_router  # noqa: E402
from generator_service.routers import generate as generate_router  # noqa: E402
from generator_service.routers import interactive as interactive_router  # noqa: E402
from generator_service.session_store import SessionStore  # noqa: E402

CHECKABLE_PARTITION = 1
PLAIN_PARTITION = 2
SLOTS_PARTITION = 3


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
        app.include_router(answers_router.router)
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
        # max_attempts=1: вопрос закрывается сразу, и ответ показывается.
        # С умолчанием режима (три попытки) первая ошибка вопрос не
        # закрывает — это разные ситуации, и обе проверяются.
        session_id = self.generate(
            CHECKABLE_PARTITION, interactive=True,
            max_attempts=1).json()["session_id"]
        body = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "1"}).json()
        self.assertFalse(body["correct"])
        shown = " ".join(b.get("content", "") for b in body["feedback"])
        self.assertIn("Правильный ответ", shown)

    def test_first_mistake_keeps_the_answer_hidden_by_default(self):
        # Умолчание свободной тренировки — три попытки: показывать ответ
        # после первой ошибки значило бы отменить остальные две.
        session_id = self.generate(
            CHECKABLE_PARTITION, interactive=True).json()["session_id"]
        body = self.client.post("/interactive/submit", json={
            "session_id": session_id, "user_input": "1"}).json()
        shown = " ".join(b.get("content", "") for b in body["feedback"])
        self.assertNotIn("Правильный ответ", shown)
        self.assertIn("Осталось попыток", shown)

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


class ScenarioEndpointTests(InteractiveApiTestBase):

    def attempts(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM attempts")]
        finally:
            conn.close()

    def play(self, **extra):
        """Открыть сессию и ответить верно один раз."""
        opened = self.generate(
            CHECKABLE_PARTITION, interactive=True, **extra).json()
        self.client.post("/interactive/submit", json={
            "session_id": opened["session_id"], "user_input": "9.8 м/с^2"})
        return opened

    def test_scenario_rides_in_the_response(self):
        data = self.generate(CHECKABLE_PARTITION, interactive=True).json()
        self.assertEqual(data["scenario"]["mode"], "practice_free")

    def test_free_practice_writes_no_attempts(self):
        # Не «нечего писать», а исполненный контракт режима.
        self.play(session_mode="practice_free")
        self.assertEqual(self.attempts(), [])

    def test_practice_writes_an_attempt(self):
        self.play(session_mode="practice")
        rows = self.attempts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_mode"], "practice")
        self.assertEqual(rows[0]["check_mode"], "soft")
        self.assertEqual(rows[0]["correct"], 1)

    def test_attempt_carries_partition_and_user(self):
        self.play(session_mode="practice")
        row = self.attempts()[0]
        self.assertEqual(row["partition_id"], CHECKABLE_PARTITION)
        self.assertEqual(row["user_id"], "ivanov")

    def test_repeated_submit_does_not_duplicate_the_attempt(self):
        opened = self.play(session_mode="practice")
        # Сессия уже закрыта и удалена из стора — повтор вернёт 404, но
        # даже если бы дошёл, ключ попытки детерминирован.
        self.client.post("/interactive/submit", json={
            "session_id": opened["session_id"], "user_input": "9.8 м/с^2"})
        self.assertEqual(len(self.attempts()), 1)

    def test_attempt_is_written_before_the_session_ends(self):
        # Сессию бросают чаще, чем доводят до конца: запись «в конце»
        # потеряла бы всё, на что студент успел ответить.
        opened = self.generate(
            CHECKABLE_PARTITION, interactive=True,
            session_mode="practice", max_attempts=2).json()
        self.client.post("/interactive/submit", json={
            "session_id": opened["session_id"], "user_input": "1"})
        self.client.post("/interactive/submit", json={
            "session_id": opened["session_id"], "user_input": "2"})
        rows = self.attempts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["correct"], 0)
        self.assertEqual(rows[0]["attempts_used"], 2)

    def test_unknown_mode_is_refused(self):
        response = self.generate(
            CHECKABLE_PARTITION, interactive=True, session_mode="телепатия")
        self.assertEqual(response.status_code, 400)

    def test_unimplemented_modes_are_refused_with_a_reason(self):
        # Пометить попытку зачётом, не обеспечив условий зачёта, — это
        # статистика, про которую потом нельзя сказать, что она означает.
        for mode in ("homework", "exam"):
            with self.subTest(mode=mode):
                response = self.generate(
                    CHECKABLE_PARTITION, interactive=True, session_mode=mode)
                self.assertEqual(response.status_code, 400)
                self.assertIn("не открыт", response.json()["error"]["message"])

    def test_max_attempts_overrides_the_mode_default(self):
        data = self.generate(
            CHECKABLE_PARTITION, interactive=True,
            session_mode="practice", max_attempts=5).json()
        self.assertEqual(
            data["scenario"]["settings"]["max_attempts"]["value"], 5)


if __name__ == "__main__":
    unittest.main()


class SlotsPartitionTestBase(InteractiveApiTestBase):
    """Раздел с несколькими полями ответа — путь виджета `slot_fields`."""

    def setUp(self):
        super().setUp()
        from core.answers import ExpressionSpec, SlotsSpec

        spec = SlotsSpec(slots=(
            ("v", NumberSpec(value=10.0, unit="м/с")),
            ("y", ExpressionSpec(value="x**2 - 1", symbols=("x",))),
        ))

        class _SlotsGenerator(TaskGenerator):
            name = "Со слотами"
            partition_id = SLOTS_PARTITION
            capabilities = CHECKABLE_DEFAULT

            def generate(self) -> StaticTask:
                return StaticTask(
                    statement=[TextBlock("Найдите скорость и многочлен.")],
                    answer=[TextBlock("v = 10 м/с, y = x^2-1")],
                    answer_spec=spec)

        self.spec = spec
        registry = self.client.app.state.registry
        registry._items[SLOTS_PARTITION] = _SlotsGenerator()


class InputFieldsRideWithTheSessionTests(InteractiveApiTestBase):
    """
    Виджет говорит, ЧЕМ рисовать; поля — сколько их и что подписать.
    Без второго набор слотов на экране не собрать.
    """

    def test_single_field_for_a_number(self):
        data = self.generate(CHECKABLE_PARTITION, interactive=True).json()
        self.assertEqual(len(data["fields"]), 1)
        self.assertEqual(data["fields"][0]["kind"], "number")
        self.assertEqual(data["fields"][0]["hint"], "м/с^2")

    def test_specification_does_not_ride_with_the_session(self):
        """
        Сессию проходит СТУДЕНТ. Спецификация содержит ответ, и её в этом
        ответе быть не должно — в отличие от статического задания, где
        ответ и так показан.
        """
        data = self.generate(CHECKABLE_PARTITION, interactive=True).json()
        self.assertNotIn("answer_spec", data)
        self.assertNotIn("answer", data)
        self.assertNotIn("9.8", str(data))


class SlotFieldsTests(SlotsPartitionTestBase):

    def test_one_field_per_slot_with_names(self):
        data = self.generate(SLOTS_PARTITION, interactive=True).json()
        self.assertEqual([f["name"] for f in data["fields"]], ["v", "y"])
        self.assertEqual(data["widget"], "slot_fields")

    def test_answer_by_fields(self):
        started = self.generate(SLOTS_PARTITION, interactive=True).json()
        result = self.client.post("/interactive/submit", json={
            "session_id": started["session_id"],
            "values": {"v": "10 м/с", "y": "x^2-1"},
        }).json()
        self.assertTrue(result["correct"])

    def test_user_input_is_optional_when_values_are_sent(self):
        """Клиент с раздельными полями строки не собирает вовсе."""
        started = self.generate(SLOTS_PARTITION, interactive=True).json()
        response = self.client.post("/interactive/submit", json={
            "session_id": started["session_id"],
            "values": {"v": "нет", "y": "нет"},
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["correct"])

    def test_string_path_still_works(self):
        """Старый путь не сломан: строка по-прежнему принимается."""
        started = self.generate(SLOTS_PARTITION, interactive=True).json()
        result = self.client.post("/interactive/submit", json={
            "session_id": started["session_id"],
            "user_input": "v=10 м/с; y=x^2-1",
        }).json()
        self.assertTrue(result["correct"])


class AnswerPreviewTests(InteractiveApiTestBase):
    """
    «Что примут» — материал преподавателя, отдельным запросом.

    Отдельным, потому что для выражения он стоит около 200 мс: платить
    их на каждой генерации ради подсказки, которую смотрят раз при
    настройке, незачем.
    """

    def preview(self, spec, **extra):
        body = {"spec": spec}
        body.update(extra)
        return self.client.post("/answers/preview", json=body)

    def test_examples_are_returned(self):
        spec = NumberSpec(value=9.8, unit="м/с^2",
                          tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1))
        data = self.preview(spec.to_dict()).json()
        self.assertIn("9.8 м/с^2", data["examples"])
        self.assertEqual(data["mode"], "soft")
        self.assertEqual(data["tolerance"], "±0.1")

    def test_every_example_is_actually_accepted(self):
        """
        Инвариант §5: предпросмотр не врёт. Проверяем не доверием к
        реализации, а прогоном каждого показанного примера.
        """
        spec = NumberSpec(value=9.8, unit="м/с^2",
                          tolerance=Tolerance(ToleranceKind.ABSOLUTE, 0.1))
        for example in self.preview(spec.to_dict()).json()["examples"]:
            self.assertTrue(spec.check(example).accepted, example)

    def test_mode_can_be_asked_for_explicitly(self):
        """
        Тумблер строгости меняет СПИСОК принимаемых ответов, и увидеть
        разницу нужно ДО переключения.
        """
        from core.answers import ExpressionSpec
        spec = ExpressionSpec(value="x**2 - 1", symbols=("x",))
        soft = self.preview(spec.to_dict(), mode="soft").json()
        strict = self.preview(spec.to_dict(), mode="strict").json()
        self.assertEqual(strict["mode"], "strict")
        self.assertLess(len(strict["examples"]), len(soft["examples"]))

    def test_fields_ride_with_the_preview(self):
        spec = NumberSpec(value=1.0, unit="кг")
        self.assertEqual(self.preview(spec.to_dict()).json()["fields"],
                         [{"kind": "number", "hint": "кг"}])

    def test_unknown_kind_is_refused(self):
        self.assertEqual(self.preview({"kind": "колбаса"}).status_code, 400)

    def test_unknown_mode_is_refused(self):
        spec = NumberSpec(value=1.0)
        self.assertEqual(
            self.preview(spec.to_dict(), mode="полустрогий").status_code, 400)


class RefusalsAreRelayableTests(InteractiveApiTestBase):
    """
    Контракт, на который опирается веб-слой: отказ приходит с ОСМЫСЛЕННЫМ
    кодом и телом-конвертом, а не голой пятисоткой.

    Тест здесь потому, что релей на C# в этом окружении не компилируется и
    не запускается: единственное, что можно закрепить автоматически, —
    форма ответа, которую он пересылает. Если она изменится, релей начнёт
    отдавать 500 там, где сервис объяснил причину, и узнать об этом будет
    неоткуда.
    """

    def test_out_of_range_attempts_is_422_not_500(self):
        response = self.generate(CHECKABLE_PARTITION, interactive=True,
                                 max_attempts=99)
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())

    def test_unopened_mode_is_400_with_a_reason(self):
        response = self.generate(CHECKABLE_PARTITION, interactive=True,
                                 session_mode="exam")
        self.assertEqual(response.status_code, 400)
        self.assertIn("выдач", response.json()["error"]["message"])

    def test_broken_spec_preview_is_400_with_a_reason(self):
        response = self.client.post("/answers/preview",
                                    json={"spec": {"kind": "нет такого"}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class EndToEndOnAGraphTests(unittest.TestCase):
    """
    Сквозной путь на одном задании, целиком.

    Раздел-граф → генерация → сессия → поля ввода → верный ответ. Именно
    этот путь до сих пор нигде не проходил целиком: спецификацию ответа
    не производил ни один генератор, кроме нового финального узла Июля, а
    витрина объявляла граф непроверяемым независимо от его содержимого.

    Тест намеренно берёт `EXAMPLE_GRAPH` — тот самый пример по умолчанию,
    который видит новичок, — а не выдуманный минимальный граф: если
    сломается он, сломается первое, что откроет пользователь.
    """

    def setUp(self):
        from exercises.graph.generators import (EXAMPLE_GRAPH,
                                                GraphConstructorGenerator)
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.repo = Repository(self.db_path)

        generator = GraphConstructorGenerator(7, "Путь", EXAMPLE_GRAPH)

        class _GraphRegistry:
            def has(self, partition_id):
                return partition_id == 7

            def get(self, partition_id, params=None):
                return generator

        app = FastAPI()
        errors.install(app)
        app.include_router(generate_router.router)
        app.include_router(interactive_router.router)
        app.state.repo = self.repo
        app.state.registry = _GraphRegistry()
        app.state.sessions = SessionStore(1800)
        self.generator = generator
        self.client = TestClient(app)

    def tearDown(self):
        from core.graph.isolation import shutdown_shared
        shutdown_shared()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_the_showcase_calls_it_checkable(self):
        """
        Витрина отвечает ДО генерации — по ней фронт выбирает экран.
        Пока она говорила «не интерактивный», проверяемый граф уводил
        студента на показ ответа.
        """
        from core.generator import Capability
        self.assertIn(Capability.CHECKABLE, self.generator.capabilities)

    def test_session_opens_with_fields(self):
        data = self.client.post("/generate", json={
            "partition_id": 7, "user_id": "ivanov", "interactive": True,
        }).json()
        self.assertEqual(data["type"], "interactive")
        self.assertEqual(data["widget"], "text_input")
        self.assertEqual(data["fields"], [{"kind": "number", "hint": "м"}])

    def test_correct_answer_is_accepted(self):
        started = self.client.post("/generate", json={
            "partition_id": 7, "user_id": "ivanov", "interactive": True,
        }).json()
        # Ответ считаем из условия, как считал бы студент: «Пройдено N м
        # за M с» — путь равен произведению.
        text = started["prompt"][0]["content"]
        numbers = [int(n) for n in re.findall(r"\d+", text)]
        answer = numbers[0] * numbers[1]

        result = self.client.post("/interactive/submit", json={
            "session_id": started["session_id"],
            "values": {"": f"{answer} м"},
        }).json()
        self.assertTrue(result["correct"])

    def test_wrong_answer_is_refused(self):
        started = self.client.post("/generate", json={
            "partition_id": 7, "user_id": "ivanov", "interactive": True,
        }).json()
        result = self.client.post("/interactive/submit", json={
            "session_id": started["session_id"],
            "values": {"": "0 м"},
        }).json()
        self.assertFalse(result["correct"])

    def test_teacher_sees_what_will_be_accepted(self):
        """Вторая половина пути: тот же граф глазами преподавателя."""
        app = self.client.app
        app.include_router(answers_router.router)
        static = self.client.post("/generate", json={"partition_id": 7}).json()
        self.assertTrue(static["is_checkable"])

        preview = self.client.post("/answers/preview", json={
            "spec": static["answer_spec"]}).json()
        self.assertTrue(preview["examples"])
        # И показанный ответ, и обещанные примеры сделаны из одной
        # спецификации — совпадение здесь не удача, а следствие.
        shown = static["answer"][0]["content"]
        self.assertIn(shown.split("= ")[-1], preview["examples"])
