"""
Основание Repository: файл БД, схема, соединение и транзакции.

Здесь всё, что не относится ни к одному домену, но нужно всем: создание
и проверка файла, прогон миграций, соединение по потоку и вложенная
транзакция. Доменные методы живут в миксинах рядом.
"""

from __future__ import annotations
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..migrations import run_migrations


class RepositoryBase:
    """Файл БД, схема, соединение, транзакции."""
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        # Соединение и глубина вложенности транзакции — по потоку.
        self._local = threading.local()
        self._init_db()

    def _init_db(self) -> None:
        """Создаёт файл БД и все таблицы, если они отсутствуют.
        Повреждённый файл отводится в резервную копию и создаётся заново."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists() and not self._is_healthy():
            # Раньше здесь был unlink() — данные пользователя удалялись
            # безвозвратно, в том числе если открыть файл помешала
            # временная причина (права, блокировка другим процессом).
            # Отводим в сторону: восстановить можно, а старт не блокируем.
            import logging
            backup = self.db_path.with_name(
                f"{self.db_path.name}.bak-{int(time.time())}")
            self.db_path.rename(backup)
            logging.getLogger(__name__).warning(
                "БД %s повреждена; сохранена как %s, создаётся новая.",
                self.db_path, backup,
            )
        self._create_schema()

    def _is_healthy(self) -> bool:
        """
        Проходит ли файл PRAGMA integrity_check.

        Важно читать результат, а не только ловить исключение: повреждение
        внутри читаемого файла integrity_check возвращает строками, ничего
        не выбрасывая, — прежняя проверка такие БД считала здоровыми.
        """
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                rows = conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError:
            return False        # файл не открывается как БД
        return len(rows) == 1 and rows[0][0] == "ok"

    def _create_schema(self) -> None:
        """Создать таблицы и прогнать миграции. Идемпотентно."""
        with sqlite3.connect(str(self.db_path)) as conn:
            # WAL: на файле работают три процесса (веб-сервис, десктоп,
            # contour_service). В журнале по умолчанию (delete) читатель и
            # писатель блокируют друг друга — с WAL читатели не ждут писателя.
            # Режим хранится в самом файле: достаточно выставить один раз.
            # На сетевых ФС WAL не поддерживается — тогда остаёмся на delete.
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                pass
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS Subjects (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_name  TEXT    NOT NULL DEFAULT '',
                    pra_subject   TEXT    NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS Partitions (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_id           INTEGER NOT NULL DEFAULT 0,
                    partition_name       TEXT    NOT NULL DEFAULT '',
                    constracted          INTEGER NOT NULL DEFAULT 0,
                    generation_parametrs TEXT    NOT NULL DEFAULT ''
                );
            """)
            conn.commit()
            # Версионированные миграции: RBAC, владение, sync-колонки, таблицы
            # контура. Идемпотентно — на уже мигрированной БД это no-op.
            run_migrations(conn)

    # ---------- Соединение и транзакции ----------
    #
    # Соединение живёт по одному на ПОТОК и переиспользуется, а не заводится
    # на каждый вызов метода. Два повода: sqlite3.Connection не переносится
    # между потоками (а sync-роуты FastAPI работают в пуле потоков), и
    # открытие соединения на операцию — это работа, которую на Postgres
    # придётся заменить пулом в любом случае; здесь та же форма заранее.

    def _thread_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path))
            # foreign_keys — настройка соединения, а не файла: без неё SQLite
            # разбирает объявленные REFERENCES, но не проверяет их, и в БД
            # копятся висячие ссылки. Ставим на каждом соединении.
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Транзакция вокруг набора операций. ПУБЛИЧНАЯ и ВЛОЖЕННАЯ.

        Публичная — потому что многошаговые операции живут не здесь, а слоем
        выше (`grants_api.set_teacher_grants` проверяет пользователя, потом
        предметы, потом пишет). Раньше такой код брал приватное `_connect()`
        с `# noqa`, то есть атомарности у него не было вовсе: между проверкой
        и записью могло произойти что угодно. Теперь он берёт транзакцию явно.

        Вложенная — потому что иначе публичность бесполезна: внешний вызов
        открывает транзакцию и внутри дёргает обычные методы Repository,
        каждый из которых тоже её открывает. Вложенный вызов ПРИСОЕДИНЯЕТСЯ к
        уже открытой, фиксация одна — на самом внешнем уровне. Без этого
        первый же вложенный commit фиксировал бы половину чужой работы.

        SAVEPOINT'ы намеренно не заводятся: частичный откат внутренней
        операции никому здесь не нужен, а стоил бы отдельной семантики
        отката, которую пришлось бы объяснять на каждом вызове.
        """
        conn = self._thread_connection()
        depth = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        try:
            yield conn
        except BaseException:
            if depth == 0:
                conn.rollback()
            raise
        else:
            if depth == 0:
                conn.commit()
        finally:
            self._local.depth = depth

    # Историческое имя. Осталось внутренним синонимом transaction(): на него
    # опираются 74 метода этого класса, и переименовывать их разом — шум в
    # диффе без выигрыша. Новый код (и всё, что вне Repository) берёт
    # transaction().
    _connect = transaction

    def close(self) -> None:
        """Закрыть соединение текущего потока. Нужно там, где файл БД потом
        удаляют или переоткрывают (тесты, обслуживание)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
            self._local.depth = 0
