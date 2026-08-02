"""
Предметы и разделы: чтение, запись, владение и видимость.

Владение (owner_user_id) лежит здесь, а не рядом с пользователями:
это свойство КОНТЕНТА, и все предикаты видимости считаются по
предметам. Партиции своего владельца не имеют — он выводится из
предмета, одна точка истины (см. rbac_and_data_model.md §3).
"""

from __future__ import annotations
import json
import sqlite3
import time
from typing import List, Optional

from .models import Partition, Subject, _VIEW_KIND_BY_CONSTRACTED


class ContentMixin:
    """Предметы, разделы, владение и видимость."""
    # ---------- Subjects ----------

    def list_subjects(self) -> List[Subject]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects"
            ).fetchall()
        return [Subject(r[0], r[1], r[2]) for r in rows]

    def get_subject_by_name(self, name: str) -> Optional[Subject]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects "
                "WHERE subject_name = ?",
                (name,),
            ).fetchone()
        return Subject(*row) if row else None

    # ---------- Partitions ----------

    def list_partitions_for_subject(self, subject_id: int) -> List[Partition]:
        # Tombstones (deleted_at) скрыты: для приложения удалённый раздел
        # не существует, строка живёт только ради offline-sync.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE subject_id = ? AND deleted_at IS NULL "
                "ORDER BY id",
                (subject_id,),
            ).fetchall()
        return [self._row_to_partition(r) for r in rows]

    def get_partition(self, partition_id: int) -> Optional[Partition]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE id = ? AND deleted_at IS NULL",
                (partition_id,),
            ).fetchone()
        return self._row_to_partition(row) if row else None

    def view_kind_for(self, partition: Partition) -> str:
        """Какое представление подобрать разделу."""
        return _VIEW_KIND_BY_CONSTRACTED.get(partition.constracted, "single")

    @staticmethod
    def _row_to_partition(row) -> Partition:
        params: dict = {}
        raw = row[4]
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    params = parsed
                else:
                    params = {"data": parsed}
            except json.JSONDecodeError:
                params = {"raw": raw}
        return Partition(
            id=row[0],
            subject_id=row[1],
            name=row[2],
            constracted=row[3],
            generation_params=params,
        )

    # ---------- Запись разделов ----------

    @staticmethod
    def next_row_version(conn: sqlite3.Connection, table: str) -> int:
        """
        Следующий row_version — глобально монотонный per-таблица (НЕ по-строчный
        +1): курсор sync = «максимальный полученный row_version на тип сущности»
        (offline_sync_protocol.md §4), поэтому версии обязаны быть уникальны в
        пределах таблицы. SQLite сериализует писателей — гонки MAX+1 нет;
        на Postgres это станет sequence.
        """
        row = conn.execute(
            f"SELECT COALESCE(MAX(row_version), 0) + 1 FROM {table}"
        ).fetchone()
        return int(row[0])

    def ensure_subject(
        self, subject_id: int, name: str, parent_name: str | None = None
    ) -> int:
        """
        Гарантировать наличие предмета. Если subject_id уже занят, просто
        возвращаем его. Если в БД есть запись с таким же name — используем её id.
        Иначе — вставляем новую с подобранным id (или указанным, если свободен).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM Subjects WHERE id = ?", (subject_id,)
            ).fetchone()
            if row:
                return row[0]
            row = conn.execute(
                "SELECT id FROM Subjects WHERE subject_name = ?", (name,)
            ).fetchone()
            if row:
                return row[0]
            parent = parent_name if parent_name is not None else name
            ver = self.next_row_version(conn, "Subjects")
            now = time.time()
            try:
                conn.execute(
                    "INSERT INTO Subjects (id, subject_name, pra_subject, "
                    " row_version, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (subject_id, name, parent, ver, now),
                )
                return subject_id
            except sqlite3.IntegrityError:
                cur = conn.execute(
                    "INSERT INTO Subjects (subject_name, pra_subject, "
                    " row_version, updated_at) VALUES (?, ?, ?, ?)",
                    (name, parent, ver, now),
                )
                return cur.lastrowid

    def ensure_code_partition(
        self,
        partition_id: int,
        subject_id: int,
        name: str,
    ) -> None:
        """
        Гарантировать наличие записи раздела для code-only генератора
        (constracted=0, без generation_params).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, partition_name, subject_id, constracted "
                "FROM Partitions WHERE id = ?", (partition_id,)
            ).fetchone()
            if row is None:
                try:
                    conn.execute(
                        "INSERT INTO Partitions "
                        "(id, subject_id, partition_name, constracted, "
                        " generation_parametrs, row_version, updated_at) "
                        "VALUES (?, ?, ?, 0, '', ?, ?)",
                        (partition_id, subject_id, name,
                         self.next_row_version(conn, "Partitions"), time.time()),
                    )
                except sqlite3.IntegrityError:
                    pass
                return
            if row[3] == 0 and (row[1] != name or row[2] != subject_id):
                conn.execute(
                    "UPDATE Partitions SET partition_name = ?, subject_id = ?, "
                    "row_version = ?, updated_at = ? WHERE id = ?",
                    (name, subject_id,
                     self.next_row_version(conn, "Partitions"), time.time(),
                     partition_id),
                )

    def upsert_partition(
        self,
        subject_id: int,
        name: str,
        constracted: int,
        generation_params: dict | list | str,
    ) -> int:
        if isinstance(generation_params, (dict, list)):
            raw = json.dumps(generation_params, ensure_ascii=False)
        else:
            raw = str(generation_params)

        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id FROM Partitions WHERE subject_id = ? AND partition_name = ?",
                (subject_id, name),
            )
            existing = cur.fetchone()
            now = time.time()
            ver = self.next_row_version(conn, "Partitions")
            if existing:
                pid = existing[0]
                # Новый row_version + updated_at — основа offline-sync;
                # deleted_at сбрасывается: пересоздание раздела под старым
                # именем воскрешает tombstone-строку.
                conn.execute(
                    "UPDATE Partitions SET constracted = ?, generation_parametrs = ?, "
                    "row_version = ?, updated_at = ?, deleted_at = NULL WHERE id = ?",
                    (constracted, raw, ver, now, pid),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO Partitions "
                    "(subject_id, partition_name, constracted, generation_parametrs, "
                    " row_version, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (subject_id, name, constracted, raw, ver, now),
                )
                pid = cur.lastrowid
        return pid

    def delete_partition(self, partition_id: int) -> None:
        """Tombstone, не физическое удаление: офлайн-клиент узнаёт об
        удалении только по строке с deleted_at и новым row_version
        (offline_sync_protocol.md §2)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE Partitions SET deleted_at = ?, updated_at = ?, "
                "row_version = ? WHERE id = ? AND deleted_at IS NULL",
                (time.time(), time.time(),
                 self.next_row_version(conn, "Partitions"), partition_id),
            )

    # ---------- Карта constracted → kind редактора ----------

    EDITOR_KIND_BY_CONSTRACTED = {
        1: "fisic",
        2: "group",
        3: "test",
    }

    def editor_kind_for(self, partition: Partition) -> str | None:
        return self.EDITOR_KIND_BY_CONSTRACTED.get(partition.constracted)

    # ---------- Владение контентом и видимость (RBAC) ----------
    #
    # Право enforcement'а по договору живёт в web_layer (см.
    # docs/architecture/rbac_and_data_model.md). Эти методы — детерминированные
    # предикаты над схемой, которыми web_layer и будущий contour_service
    # пользуются; сам сервис ролей не «решает», он их вычисляет.

    def subject_owner(self, subject_id: int) -> Optional[str]:
        """owner_user_id предмета (логин-строка); None — системный/встроенный."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT owner_user_id FROM Subjects WHERE id = ?", (subject_id,)
            ).fetchone()
        return row[0] if row else None

    def create_subject(
        self, name: str, parent_name: str, owner_user_id: Optional[str] = None
    ) -> int:
        """Создать предмет с владельцем-логином (None = системный). id."""
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO Subjects "
                "(subject_name, pra_subject, owner_user_id, row_version, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, parent_name, owner_user_id,
                 self.next_row_version(conn, "Subjects"), now),
            )
            return cur.lastrowid

    def set_subject_owner(self, subject_id: int,
                          owner_user_id: Optional[str]) -> bool:
        """
        Перенести предмет между хранилищами: `None` — общее, логин — личное.

        Владелец — это и есть «где лежит предмет» (rbac_and_data_model.md §3),
        отдельной сущности «хранилище» нет и не нужно. Партиции переезжают
        вместе с предметом сами: своего владельца у них нет, права выводятся
        из предмета — одна точка истины.

        Обязателен новый `row_version`: смена владельца меняет строку, которую
        синк реплицирует (`owner_user_id` уезжает в pull), и без версии
        десктопы никогда не узнают о переезде. Того же требует и клиентская
        логика — по `owner_user_id` десктоп отличает встроенный предмет от
        авторского и решает, можно ли его подчищать при пересборке скоупа.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE Subjects SET owner_user_id = ?, row_version = ?, "
                "updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (owner_user_id, self.next_row_version(conn, "Subjects"),
                 time.time(), subject_id),
            )
            return cur.rowcount > 0

    def subjects_with_owner(self) -> List[dict]:
        """Предметы вместе с владельцем и числом разделов — админский обзор
        «что где лежит». Отдельный метод, потому что Subject.to_dict()
        владельца не отдаёт: наружу он не нужен, а админу нужен именно он."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT s.id, s.subject_name, s.pra_subject, s.owner_user_id, "
                "       COUNT(p.id) "
                "FROM Subjects s "
                "LEFT JOIN Partitions p "
                "  ON p.subject_id = s.id AND p.deleted_at IS NULL "
                "WHERE s.deleted_at IS NULL "
                "GROUP BY s.id, s.subject_name, s.pra_subject, s.owner_user_id "
                "ORDER BY s.id"
            ).fetchall()
        return [{"id": r[0], "name": r[1], "parent_name": r[2],
                 "owner": r[3], "partition_count": int(r[4] or 0)}
                for r in rows]

    def visible_subject_ids(self, user_id: Optional[str], role: str) -> List[int]:
        """
        Какие предметы видит пользователь: admin — все; остальные — системные
        (owner IS NULL) плюс свои. Удалённые (deleted_at) исключены.
        """
        with self._connect() as conn:
            if role == "admin":
                rows = conn.execute(
                    "SELECT id FROM Subjects WHERE deleted_at IS NULL ORDER BY id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM Subjects "
                    "WHERE deleted_at IS NULL "
                    "  AND (owner_user_id IS NULL OR owner_user_id = ?) "
                    "ORDER BY id",
                    (user_id,),
                ).fetchall()
        return [r[0] for r in rows]

    def owned_subject_ids(self, user_id: Optional[str]) -> List[int]:
        """Предметы, которыми пользователь ВЛАДЕЕТ (owner_user_id = логин).
        Встроенные (owner IS NULL) сюда не входят — у них владельца нет."""
        if not user_id:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM Subjects "
                "WHERE deleted_at IS NULL AND owner_user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def can_edit_subject(self, user_id: Optional[str], role: str,
                         subject_id: int) -> bool:
        """
        Кто может редактировать предмет: admin — всегда; teacher — только свои;
        системные предметы (owner IS NULL) — только admin; student — никогда.
        """
        if role == "admin":
            return True
        if role != "teacher":
            return False
        owner = self.subject_owner(subject_id)
        return owner is not None and owner == user_id
