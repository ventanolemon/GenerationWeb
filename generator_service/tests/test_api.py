"""
Изолированный smoke-тест FastAPI-роутеров.

НЕ требует реальной БД, реального bootstrap'а и реальных доменных
модулей. Вместо них подсовываем фейковые Repository и Registry,
заполненные тремя генераторами: один статичный, один интерактивный
и один статичный с разными типами блоков (для проверки экспорта).

Это unit-тест на сам слой роутеров: проверяет, что они корректно
дёргают ядро, обрабатывают ошибки (404, 400) и возвращают валидный
JSON через to_dict().

Запуск:
    cd <корень монорепо>
    python -m generator_service.tests.test_api
"""

from __future__ import annotations
import io
import os
import sys
import traceback

# Делаем монорепо и пакет core импортируемыми независимо от того,
# откуда запущен тест. Корень монорепо — два уровня вверх от этого файла.
_HERE = os.path.dirname(os.path.abspath(__file__))
_MONOREPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _MONOREPO not in sys.path:
    sys.path.insert(0, _MONOREPO)
# А ещё ядро может лежать в core/core (как у нас на шаге 1 — папка core/
# содержит подпакет core/). Тогда в монорепо нужен дополнительный путь.
_CORE_NESTED = os.path.join(_MONOREPO, "core")
if os.path.isdir(os.path.join(_CORE_NESTED, "core")) and _CORE_NESTED not in sys.path:
    sys.path.insert(0, _CORE_NESTED)


from core import (  # noqa: E402
    Block,
    Capability,
    FormulaBlock,
    GeneratorRegistry,
    InteractiveTask,
    Partition,
    StaticTask,
    Subject,
    TaskGenerator,
    TextBlock,
    TurnResult,
)


# ────────────────────────────────────────────────────────────────────────────
# Fake-генераторы (живут только в этом тесте)
# ────────────────────────────────────────────────────────────────────────────

class _FakeStaticGen(TaskGenerator):
    name = "Fake static"
    partition_id = 100
    capabilities = Capability.STATIC | Capability.GROUPABLE | Capability.EXPORTABLE

    def generate(self) -> StaticTask:
        return StaticTask(
            statement=[TextBlock("2 + 2 = ?"), FormulaBlock("2 + 2")],
            answer=[TextBlock("4")],
            meta={},
        )


class _FakeInteractive(InteractiveTask):
    """Сессия из ровно двух ходов: после второго ответа is_finished == True."""

    def __init__(self):
        self._turn = 0
        self.meta = {}

    def initial_prompt(self) -> list[Block]:
        return [TextBlock("Скажи 'hello'")]

    def submit(self, user_input: str) -> TurnResult:
        self._turn += 1
        correct = user_input.strip().lower() == "hello"
        if self._turn >= 2:
            return TurnResult(
                correct=correct,
                feedback=[TextBlock("ok" if correct else "no")],
                next_prompt=None,
            )
        return TurnResult(
            correct=correct,
            feedback=[TextBlock("ok" if correct else "no")],
            next_prompt=[TextBlock("Теперь 'world'")],
        )

    def is_finished(self) -> bool:
        return self._turn >= 2


class _FakeInteractiveGen(TaskGenerator):
    name = "Fake interactive"
    partition_id = 200
    capabilities = Capability.INTERACTIVE

    def generate(self) -> InteractiveTask:
        return _FakeInteractive()


# ────────────────────────────────────────────────────────────────────────────
# Fake-репозиторий: реализует только методы, которые дёргают роутеры
# ────────────────────────────────────────────────────────────────────────────

class _FakeRepo:
    def __init__(self, subjects: list[Subject], partitions: list[Partition]):
        self._subjects = subjects
        self._partitions = partitions

    def list_subjects(self) -> list[Subject]:
        return list(self._subjects)

    def list_partitions_for_subject(self, subject_id: int) -> list[Partition]:
        return [p for p in self._partitions if p.subject_id == subject_id]

    def get_partition(self, partition_id: int):
        return next((p for p in self._partitions if p.id == partition_id), None)

    def view_kind_for(self, partition: Partition) -> str:
        return {0: "single", 1: "table", 2: "table", 3: "test"}.get(
            partition.constracted, "single"
        )


def _make_app():
    """Собирает FastAPI app с подменёнными repo/registry — без lifespan."""
    from fastapi import FastAPI

    from generator_service.routers import (
        export as export_router,
        generate as generate_router,
        interactive as interactive_router,
        meta as meta_router,
        subjects as subjects_router,
    )
    from generator_service.session_store import SessionStore

    app = FastAPI()
    app.include_router(subjects_router.router)
    app.include_router(generate_router.router)
    app.include_router(interactive_router.router)
    app.include_router(export_router.router)
    app.include_router(meta_router.router)

    subjects = [Subject(id=1, name="Math", parent_name="Math")]
    partitions = [
        Partition(id=100, subject_id=1, name="Static fake",
                  constracted=0, generation_params={}),
        Partition(id=200, subject_id=1, name="Interactive fake",
                  constracted=0, generation_params={}),
    ]
    registry = GeneratorRegistry()
    registry.register(_FakeStaticGen())
    registry.register(_FakeInteractiveGen())

    app.state.repo = _FakeRepo(subjects, partitions)
    app.state.registry = registry
    app.state.sessions = SessionStore()
    return app


# ────────────────────────────────────────────────────────────────────────────
# Тесты
# ────────────────────────────────────────────────────────────────────────────

def test_subjects_list():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.get("/subjects")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["id"] == 1
    assert data[0]["name"] == "Math"
    print("✓ GET /subjects")


def test_partitions_list():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.get("/subjects/1/partitions")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    by_id = {p["id"]: p for p in data}
    assert set(by_id.keys()) == {100, 200}
    assert all(p["has_generator"] for p in data)
    assert all("view_kind" in p for p in data)
    # is_interactive: статичный fake — False, интерактивный fake — True.
    # Это контракт для фронта, чтобы выбрать view ещё до /generate.
    assert by_id[100]["is_interactive"] is False
    assert by_id[200]["is_interactive"] is True
    print("✓ GET /subjects/1/partitions (с is_interactive)")


def test_partitions_unknown_subject():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.get("/subjects/9999/partitions")
    assert r.status_code == 404, f"ожидался 404, получено {r.status_code}"
    print("✓ GET /subjects/9999/partitions → 404")


def test_generate_static():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.post("/generate", json={"partition_id": 100})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["type"] == "static"
    assert data["partition_id"] == 100
    assert len(data["statement"]) == 2
    assert data["statement"][0]["type"] == "text"
    assert data["statement"][1]["type"] == "formula"
    assert "image_b64" in data["statement"][1]
    assert data["answer"][0]["content"] == "4"
    print(f"✓ POST /generate (static) — JSON {len(r.text)} байт")


def test_generate_unknown_partition():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.post("/generate", json={"partition_id": 9999})
    assert r.status_code == 404
    print("✓ POST /generate → 404 для несуществующего partition_id")


def test_generate_bad_request():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    # partition_id обязан быть > 0
    r = client.post("/generate", json={"partition_id": 0})
    assert r.status_code == 422
    print("✓ POST /generate → 422 для невалидного запроса")


def test_interactive_full_flow():
    """Полный цикл: создание сессии, два хода, авто-удаление по завершении."""
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())

    # 1. Создаём сессию
    r = client.post("/generate", json={"partition_id": 200})
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "interactive"
    sid = data["session_id"]
    assert sid
    assert data["prompt"][0]["content"] == "Скажи 'hello'"

    # 2. Первый ход
    r = client.post("/interactive/submit",
                    json={"session_id": sid, "user_input": "hello"})
    assert r.status_code == 200
    d = r.json()
    assert d["correct"] is True
    assert d["is_finished"] is False
    assert d["next_prompt"] is not None

    # 3. Второй ход — сессия завершается
    r = client.post("/interactive/submit",
                    json={"session_id": sid, "user_input": "world"})
    assert r.status_code == 200
    d = r.json()
    assert d["is_finished"] is True
    assert d["next_prompt"] is None

    # 4. После завершения сессия должна быть удалена
    r = client.post("/interactive/submit",
                    json={"session_id": sid, "user_input": "anything"})
    assert r.status_code == 404
    print("✓ /interactive: полный цикл из 2 ходов + авто-удаление")


def test_interactive_unknown_session():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.post("/interactive/submit",
                    json={"session_id": "no-such-session", "user_input": "x"})
    assert r.status_code == 404
    print("✓ POST /interactive/submit → 404 для несуществующей сессии")


def test_export_static():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.post("/export", json={"partition_id": 100, "count": 2})
    assert r.status_code == 200, r.text
    assert "wordprocessingml" in r.headers["content-type"]
    body = r.content
    # .docx — это zip-файл, начинается на PK
    assert body[:2] == b"PK", "ответ должен быть валидным .docx (zip-архив)"
    assert len(body) > 1000, "пустой docx подозрителен"
    print(f"✓ POST /export → .docx {len(body)} байт")


def test_export_interactive_fails():
    """Интерактивные задачи нельзя экспортировать в Word."""
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.post("/export", json={"partition_id": 200, "count": 1})
    assert r.status_code == 400
    print("✓ POST /export → 400 для интерактивного раздела")


def test_health():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    print("✓ GET /health")


def test_session_stats():
    from fastapi.testclient import TestClient
    client = TestClient(_make_app())
    # Создадим пару сессий
    client.post("/generate", json={"partition_id": 200})
    client.post("/generate", json={"partition_id": 200})
    r = client.get("/interactive/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["alive"] == 2
    print(f"✓ GET /interactive/stats → alive={d['alive']}")


# ────────────────────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────────────────────

TESTS = [
    test_subjects_list,
    test_partitions_list,
    test_partitions_unknown_subject,
    test_generate_static,
    test_generate_unknown_partition,
    test_generate_bad_request,
    test_interactive_full_flow,
    test_interactive_unknown_session,
    test_export_static,
    test_export_interactive_fails,
    test_health,
    test_session_stats,
]


def main():
    print("─" * 60)
    print(" Smoke-тест generator_service")
    print("─" * 60)
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            passed += 1
        except Exception:
            print(f"✗ {t.__name__} провалился:")
            traceback.print_exc()
            failed += 1
    print("─" * 60)
    print(f" Итог: {passed} пройдено, {failed} провалено")
    print("─" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
