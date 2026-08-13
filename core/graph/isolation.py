"""
Клиентская сторона изоляции исполнения графов.

План, §9: исполнение графов — отдельный рабочий процесс без доступа к БД,
получающий данные на вход и отдающий результат. Здесь живёт вызывающая
половина: запуск процессов, протокол, таймаут и переработка.

Что это закрывает
-----------------
  * доступ к БД — у процесса нет ни соединения, ни импорта репозитория;
  * бесконечный цикл — жёсткий таймаут со снятием процесса;
  * утечку памяти — предел адресного пространства плюс переработка после
    N запросов;
  * падение — умирает рабочий процесс, а не сервис.

Чего это НЕ закрывает
---------------------
Это изоляция, а не песочница. Процесс запускается тем же пользователем и
видит файловую систему: злонамеренный пакет узлов прочитает файл БД, если
знает путь. Настоящее ограничение прав — дело развёртывания (отдельный
пользователь, контейнер, seccomp), и подменять его обещанием в коде нельзя.
Здесь снимается ровно та угроза, которая описана в §9: случайно плохой
граф больше не уносит с собой процесс и соединение.

Почему процесс постоянный
-------------------------
Замер на этом коде: прогон графа — 0.08 мс, старт интерпретатора с
импортом ядра графа — около 400 мс. Процесс на запрос сделал бы
изоляцию дороже самой работы в пять тысяч раз. Поэтому процесс живёт, а
от накопления утечек защищает переработка по счётчику запросов.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from typing import Optional

DEFAULT_TIMEOUT = float(os.environ.get("GRAPH_WORKER_TIMEOUT", "10"))
DEFAULT_MEMORY_MB = int(os.environ.get("GRAPH_WORKER_MEMORY_MB", "512"))
DEFAULT_MAX_REQUESTS = int(os.environ.get("GRAPH_WORKER_MAX_REQUESTS", "500"))

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def isolation_enabled() -> bool:
    """
    Включена ли изоляция.

    Читается на каждый вызов, а не в момент импорта: развёртывание должно
    иметь возможность выключить изоляцию, не пересобирая образ, а тесты —
    сравнить оба пути в одном прогоне.
    """
    return os.environ.get("GRAPH_ISOLATION", "1").strip().lower() not in (
        "0", "false", "no", "off")


class WorkerError(RuntimeError):
    """Рабочий процесс не смог обслужить запрос."""


class WorkerTimeout(WorkerError):
    """Граф не уложился в отведённое время и был снят."""


class _Worker:
    """Один рабочий процесс с построчным JSON-протоколом."""

    def __init__(self, *, memory_mb: int):
        self._memory_mb = memory_mb
        self._process: Optional[subprocess.Popen] = None
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self.served = 0

    # ---------- Жизненный цикл ----------

    def start(self) -> None:
        env = dict(os.environ)
        env["GRAPH_WORKER_MEMORY_MB"] = str(self._memory_mb)
        # PYTHONPATH, а не надежда на cwd: сервис запускают из разных мест,
        # и «работает у меня» здесь означало бы падение на развёртывании.
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (_ROOT + os.pathsep + existing) if existing else _ROOT
        self._process = subprocess.Popen(
            [sys.executable, "-m", "core.graph.worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=_ROOT, env=env, text=True, bufsize=1,
        )
        self._lines = queue.Queue()
        self._reader = threading.Thread(
            target=self._pump, args=(self._process.stdout,), daemon=True)
        self._reader.start()
        self.served = 0

    def _pump(self, stream) -> None:
        """Читать вывод в очередь: readline() без таймаута заблокировал бы
        вызывающего навсегда, а снять его было бы нечем."""
        try:
            for line in stream:
                self._lines.put(line)
        except Exception:                          # noqa: BLE001
            pass
        finally:
            self._lines.put(None)                  # процесс закрыл вывод

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except Exception:                      # noqa: BLE001
                pass
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:                          # noqa: BLE001
            try:
                process.kill()
            except Exception:                      # noqa: BLE001
                pass

    # ---------- Обмен ----------

    def request(self, payload: dict, timeout: float) -> dict:
        if not self.alive:
            self.start()
        assert self._process is not None and self._process.stdin is not None

        try:
            self._process.stdin.write(json.dumps(payload, ensure_ascii=False)
                                      + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            self.stop()
            raise WorkerError(f"рабочий процесс не принял запрос: {exc}") from exc

        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            # Снимаем, а не ждём: процесс висит в бесконечном цикле, и
            # вернуть его к жизни нечем. Следующий запрос поднимет новый.
            self.stop()
            raise WorkerTimeout(
                f"граф не уложился в {timeout:g} с и был снят")

        if line is None:
            self.stop()
            raise WorkerError("рабочий процесс завершился, не ответив")

        self.served += 1
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            self.stop()
            raise WorkerError(f"неразборный ответ процесса: {exc}") from exc


class IsolatedGraphRunner:
    """
    Пул рабочих процессов.

    Размер по умолчанию — один: прогон графа занимает сотые доли
    миллисекунды, поэтому очередь из одного процесса не становится узким
    местом раньше, чем всё остальное. Размер оставлен настраиваемым,
    чтобы это можно было проверить, а не предполагать.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        memory_mb: int = DEFAULT_MEMORY_MB,
        max_requests: int = DEFAULT_MAX_REQUESTS,
    ):
        self.timeout = timeout
        self.max_requests = max_requests
        self._worker = _Worker(memory_mb=memory_mb)
        self._lock = threading.Lock()

    def run(self, spec: dict, *, seed: Optional[int] = None,
            timeout: Optional[float] = None) -> dict:
        """
        Исполнить граф в изолированном процессе.

        Возвращает ответ рабочего процесса как есть: `{ok: True, task: {...}}`
        либо `{ok: False, kind, error}`. Исключение поднимается только на
        отказ самого процесса — таймаут, смерть, поломка протокола: это
        разные вещи, и путать их с ошибкой в графе нельзя.
        """
        payload = {"spec": spec, "seed": seed}
        with self._lock:
            if self._worker.served >= self.max_requests:
                # Переработка по счётчику: постоянный процесс копит утечки
                # чужого кода, а перезапуск стоит сотни миллисекунд раз в
                # сотни запросов.
                self._worker.stop()
            return self._worker.request(payload,
                                        timeout or self.timeout)

    def preview(self, spec: dict, seeds=None, max_seeds: int = 8,
                timeout: Optional[float] = None) -> dict:
        """Предпросмотр на нескольких сидах одним запросом."""
        payload = {"op": "preview", "spec": spec, "seeds": seeds,
                   "max_seeds": max_seeds}
        with self._lock:
            if self._worker.served >= self.max_requests:
                self._worker.stop()
            return self._worker.request(payload, timeout or self.timeout)

    def close(self) -> None:
        with self._lock:
            self._worker.stop()

    def __enter__(self) -> "IsolatedGraphRunner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


_shared: Optional[IsolatedGraphRunner] = None
_shared_lock = threading.Lock()


def shared_runner() -> IsolatedGraphRunner:
    """Пул на процесс сервиса. Поднимается лениво, при первом графе."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = IsolatedGraphRunner()
        return _shared


def shutdown_shared() -> None:
    """Снять общий пул — при остановке сервиса и между тестами."""
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.close()
            _shared = None


def run_graph(spec: dict, *, seed: Optional[int] = None,
              runner: Optional[IsolatedGraphRunner] = None):
    """
    Исполнить граф и вернуть готовое задание.

    Если изоляция выключена, граф исполняется в текущем процессе. Это не
    «то же самое»: при выключенной изоляции плохой граф снова получает и
    процесс, и базу. Переключатель существует ради развёртываний, где
    отдельный процесс невозможен, и ради сравнения обоих путей в тестах —
    не как равноценная альтернатива.
    """
    if not isolation_enabled():
        from .executor import GraphExecutor
        from .spec import GraphSpec
        spec_dict = dict(spec)
        if seed is not None:
            meta = dict(spec_dict.get("meta") or {})
            meta["seed"] = seed
            spec_dict["meta"] = meta
        return GraphExecutor(GraphSpec.parse(spec_dict)).run()

    from ..task import StaticTask
    response = (runner or shared_runner()).run(spec, seed=seed)
    if not response.get("ok"):
        raise WorkerError(response.get("error") or "граф не исполнился")
    return StaticTask.from_dict(response["task"])


def preview_graph_runs(spec: dict, seeds=None, max_seeds: int = 8,
                       runner: Optional[IsolatedGraphRunner] = None) -> dict:
    """
    Предпросмотр графа. Самый опасный путь: сюда приходят НЕСОХРАНЁННЫЕ
    графы прямо из редактора, то есть произвольное содержимое.
    """
    if not isolation_enabled():
        from .. import graph_probe
        return graph_probe.preview_runs(spec, seeds, max_seeds)
    return (runner or shared_runner()).preview(spec, seeds, max_seeds)


__all__ = [
    "IsolatedGraphRunner", "WorkerError", "WorkerTimeout",
    "isolation_enabled", "run_graph", "preview_graph_runs",
    "shared_runner", "shutdown_shared",
    "DEFAULT_TIMEOUT", "DEFAULT_MEMORY_MB", "DEFAULT_MAX_REQUESTS",
]
