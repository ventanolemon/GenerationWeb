"""
Рабочий процесс исполнения графов.

План, §9. Сегодня `generator_service` исполняет произвольные графы в том же
процессе, где держит соединение с БД. Граф — пользовательский контент, то
есть исполнение кода, написанного автором задания; с пакетами узлов это
буквально сторонний Python. Один плохой граф — бесконечный цикл, утечка,
пакет с сюрпризом — получает и процесс, и базу.

Этот модуль запускается как отдельный процесс (`python -m core.graph.worker`)
и не импортирует ни репозиторий, ни сервис. Общение — построчный JSON через
stdin/stdout.

Почему отдельный процесс, а не поток
------------------------------------
Поток не изолирует ничего: у него та же память, те же дескрипторы, то же
соединение с БД, и снять его по таймауту нельзя — в Python нет способа
прервать чужой поток. Процесс снимается сигналом, и его память уходит с
ним.

Почему НЕ fork
--------------
Форк унаследовал бы соединение с БД и всю кучу родителя — ровно то, от
чего изолируемся. Процесс поднимается свежим интерпретатором, поэтому
дескрипторов родителя у него нет вовсе.

Почему постоянный, а не по процессу на запрос
---------------------------------------------
Замер: сам прогон графа — сотые доли миллисекунды, старт интерпретатора с
импортом ядра графа — сотни миллисекунд. Процесс на запрос сделал бы
генерацию на три порядка дороже исполнения. Поэтому процесс живёт и
обслуживает запросы подряд, а от накопления утечек защищает переработка
после N запросов — это делает клиентская сторона (`core.graph.isolation`).
"""

from __future__ import annotations

import json
import os
import sys


def _limit_memory(megabytes: int) -> None:
    """
    Ограничить адресное пространство процесса.

    Мягкий отказ: на платформах без `resource` (Windows) ограничения не
    будет, и это лучше, чем отказаться работать. Изоляция от БД —
    основная ценность — сохраняется в любом случае.
    """
    if megabytes <= 0:
        return
    try:
        import resource
    except ImportError:
        return
    limit = megabytes * 1024 * 1024
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        ceiling = limit if hard == resource.RLIM_INFINITY else min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, hard))
    except (ValueError, OSError):
        return


def _handle(request: dict) -> dict:
    """Исполнить один граф. Любая ошибка — ответ, а не падение процесса."""
    from .errors import GraphError, GraphValidationError, internal_error_text
    from .executor import GraphExecutor
    from .spec import GraphSpec

    spec_dict = dict(request.get("spec") or {})
    seed = request.get("seed")
    if seed is not None:
        # Сид кладётся в meta, а не в аргумент: исполнитель читает его
        # оттуда, и второй путь передачи разошёлся бы с первым.
        meta = dict(spec_dict.get("meta") or {})
        meta["seed"] = seed
        spec_dict["meta"] = meta

    try:
        executor = GraphExecutor(GraphSpec.parse(spec_dict))
    except GraphValidationError as exc:
        return {"ok": False, "kind": "validation", "error": str(exc)}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "kind": "internal",
                "error": internal_error_text(exc)}

    try:
        task = executor.run()
    except GraphValidationError as exc:
        return {"ok": False, "kind": "validation", "error": str(exc)}
    except GraphError as exc:
        return {"ok": False, "kind": "runtime", "error": str(exc)}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "kind": "runtime",
                "error": internal_error_text(exc)}

    to_dict = getattr(task, "to_dict", None)
    if to_dict is None:
        # Интерактивное задание держит ссылки на хранилища и генератор —
        # через границу процесса оно не проходит по своей природе, а не
        # из-за недоделки. Честный отказ лучше урезанной копии.
        return {"ok": False, "kind": "not_serializable",
                "error": (f"Задание типа {type(task).__name__} не пересекает "
                          f"границу процесса: оно держит состояние сессии.")}
    try:
        return {"ok": True, "task": to_dict()}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "kind": "serialization",
                "error": internal_error_text(exc)}


def _preview(request: dict) -> dict:
    """
    Предпросмотр графа на нескольких сидах.

    Отдельная операция, а не N обычных запросов: предпросмотр гоняет
    один и тот же граф с разными сидами, и пересобирать исполнитель на
    каждый сид значило бы платить валидацией за каждый прогон.

    Считает `core.graph_probe` — тот же код, что и при выключенной
    изоляции. Двух реализаций предпросмотра быть не должно.
    """
    from .. import graph_probe
    from .errors import internal_error_text
    try:
        return graph_probe.preview_runs(
            dict(request.get("spec") or {}),
            request.get("seeds"),
            int(request.get("max_seeds", 8)))
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "errors": [internal_error_text(exc)],
                "runs": []}


def main() -> int:
    _limit_memory(int(os.environ.get("GRAPH_WORKER_MEMORY_MB", "0") or 0))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"ok": False, "kind": "protocol", "error": str(exc)}
        else:
            try:
                op = request.get("op") if isinstance(request, dict) else None
                if op == "ping":
                    response = {"ok": True, "pong": True}
                elif op == "preview":
                    response = _preview(request)
                else:
                    response = _handle(request)
            except Exception as exc:               # noqa: BLE001
                # Ни один запрос не имеет права убить процесс: иначе
                # достаточно одного кривого поля, чтобы вызывающий получил
                # «процесс завершился, не ответив» вместо внятной ошибки.
                from .errors import internal_error_text
                response = {"ok": False, "kind": "internal",
                            "error": internal_error_text(exc)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    # Запуск как `python -m core.graph.worker` из корня монорепо; путь
    # добавляется и явно, чтобы процесс поднимался при любом cwd.
    _ROOT = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    raise SystemExit(main())
