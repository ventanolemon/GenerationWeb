"""
Учебный процесс: группы, привязка преподавателей, домашние задания.
"""

from __future__ import annotations
import time
from typing import List, Optional

from .models import Assignment, Group


class TeachingMixin:
    """Группы, membership, назначения и их прогресс."""
    # ---------- Группы и назначения ----------
    #
    # Идентификатор участника/преподавателя/автора группы — логин-строка
    # (канонический id, единый со всей системой). Структурная группа
    # (`groups`+`group_members`) — источник истины членства; свободный
    # `users."group"` остаётся самоописанием студента и синхронизируется с
    # членством при регистрации (create_user) и seed'ом миграции 003.

    def create_group(self, name: str, created_by: Optional[str] = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO groups (name, created_by, created_at) VALUES (?, ?, ?)",
                (name, created_by, time.time()),
            )
            return cur.lastrowid

    def get_group(self, group_id: int) -> Optional[Group]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, created_by, created_at FROM groups WHERE id = ?",
                (group_id,),
            ).fetchone()
        return Group(row[0], row[1], row[2], row[3] or 0.0) if row else None

    def group_by_name(self, name: str) -> Optional[Group]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, created_by, created_at FROM groups "
                "WHERE name = ?",
                (name,),
            ).fetchone()
        return Group(row[0], row[1], row[2], row[3] or 0.0) if row else None

    def list_groups(self) -> List[Group]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, created_by, created_at FROM groups "
                "ORDER BY name"
            ).fetchall()
        return [Group(r[0], r[1], r[2], r[3] or 0.0) for r in rows]

    def add_group_member(self, group_id: int, login: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO group_members (group_id, user_id) "
                "VALUES (?, ?)",
                (group_id, login),
            )

    def remove_group_member(self, group_id: int, login: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM group_members WHERE group_id = ? AND user_id = ?",
                (group_id, login),
            )

    def list_group_members(self, group_id: int) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user_id FROM group_members WHERE group_id = ? "
                "ORDER BY user_id",
                (group_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def assign_teacher_to_group(self, teacher_login: str, group_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO teacher_groups (teacher_id, group_id) "
                "VALUES (?, ?)",
                (teacher_login, group_id),
            )

    def unassign_teacher_from_group(
        self, teacher_login: str, group_id: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM teacher_groups WHERE teacher_id = ? AND group_id = ?",
                (teacher_login, group_id),
            )

    def group_teachers(self, group_id: int) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT teacher_id FROM teacher_groups WHERE group_id = ? "
                "ORDER BY teacher_id",
                (group_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def teacher_group_ids(self, teacher_login: str) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT group_id FROM teacher_groups WHERE teacher_id = ? "
                "ORDER BY group_id",
                (teacher_login,),
            ).fetchall()
        return [r[0] for r in rows]

    def user_group_ids(self, login: str) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT group_id FROM group_members WHERE user_id = ? "
                "ORDER BY group_id",
                (login,),
            ).fetchall()
        return [r[0] for r in rows]

    # ---------- Домашки (assignments: партиция → группа) ----------
    #
    # Выдающий (assigned_by) — логин-строка. Пара (partition_id, group_id)
    # уникальна по смыслу: повторная выдача той же задачи той же группе
    # обновляет срок, а не плодит дубли. Право enforcement'а (кто кому что
    # может выдать) живёт в assignments_api над visible_subject_ids /
    # teacher_group_ids — Repository лишь пишет/читает.

    _ASSIGN_COLS = ("a.id, a.partition_id, a.group_id, a.assigned_by, "
                    "a.due_at, p.partition_name, s.subject_name, g.name")

    @staticmethod
    def _row_to_assignment(row) -> "Assignment":
        return Assignment(
            id=row[0], partition_id=row[1], group_id=row[2],
            assigned_by=row[3], due_at=row[4],
            partition_name=row[5] or "", subject_name=row[6] or "",
            group_name=row[7] or "",
        )

    def create_assignment(
        self, partition_id: int, group_id: int,
        assigned_by: Optional[str], due_at: Optional[float] = None,
    ) -> int:
        """Выдать задание группе (или обновить срок существующей выдачи).
        Возвращает id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM assignments "
                "WHERE partition_id = ? AND group_id = ?",
                (partition_id, group_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE assignments SET due_at = ?, assigned_by = ? "
                    "WHERE id = ?",
                    (due_at, assigned_by, row[0]),
                )
                return row[0]
            cur = conn.execute(
                "INSERT INTO assignments "
                "(partition_id, group_id, assigned_by, due_at) "
                "VALUES (?, ?, ?, ?)",
                (partition_id, group_id, assigned_by, due_at),
            )
            return cur.lastrowid

    def get_assignment(self, assignment_id: int) -> Optional[Assignment]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._ASSIGN_COLS} FROM assignments a "
                "LEFT JOIN Partitions p ON p.id = a.partition_id "
                "LEFT JOIN Subjects s ON s.id = p.subject_id "
                "LEFT JOIN groups g ON g.id = a.group_id "
                "WHERE a.id = ?",
                (assignment_id,),
            ).fetchone()
        return self._row_to_assignment(row) if row else None

    def list_assignments_for_teacher(self, teacher_login: str) -> List[Assignment]:
        """Выданные этим преподавателем (assigned_by = логин)."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._ASSIGN_COLS} FROM assignments a "
                "LEFT JOIN Partitions p ON p.id = a.partition_id "
                "LEFT JOIN Subjects s ON s.id = p.subject_id "
                "LEFT JOIN groups g ON g.id = a.group_id "
                "WHERE a.assigned_by = ? "
                "ORDER BY a.due_at IS NULL, a.due_at, a.id",
                (teacher_login,),
            ).fetchall()
        return [self._row_to_assignment(r) for r in rows]

    def list_assignments_for_student(self, login: str) -> List[Assignment]:
        """Домашки студента: выдачи на группы, в которых он состоит. Скрываем
        задания удалённых партиций (deleted_at) — решать нечего."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {self._ASSIGN_COLS} FROM assignments a "
                "JOIN group_members gm ON gm.group_id = a.group_id "
                "JOIN Partitions p ON p.id = a.partition_id "
                "LEFT JOIN Subjects s ON s.id = p.subject_id "
                "LEFT JOIN groups g ON g.id = a.group_id "
                "WHERE gm.user_id = ? AND p.deleted_at IS NULL "
                "ORDER BY a.due_at IS NULL, a.due_at, a.id",
                (login,),
            ).fetchall()
        return [self._row_to_assignment(r) for r in rows]

    def delete_assignment(self, assignment_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM assignments WHERE id = ?",
                         (assignment_id,))

    # --- Учёт выполнения (без assignment_id на попытке) ---
    #
    # «Сдал» = участник группы имеет ВЕРНУЮ попытку по выданной партиции.
    # Это доменно-верный сигнал (решил ли студент задачу) и не требует
    # прокидывать assignment_id через UI решения; связывание
    # attempts.assignment_id с конкретной выдачей — отдельный будущий шаг.

    def assignment_completion_counts(
        self, partition_id: int, group_id: int
    ) -> tuple[int, int]:
        """(участников в группе, из них решивших верно эту партицию)."""
        with self._connect() as conn:
            members = conn.execute(
                "SELECT COUNT(*) FROM group_members WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
            solved = conn.execute(
                "SELECT COUNT(DISTINCT gm.user_id) "
                "FROM group_members gm "
                "JOIN attempts a ON a.user_id = gm.user_id "
                "  AND a.partition_id = ? AND a.correct = 1 "
                "WHERE gm.group_id = ?",
                (partition_id, group_id),
            ).fetchone()[0]
        return int(members), int(solved)

    def assignment_progress(self, assignment_id: int) -> Optional[dict]:
        """Пофамильный прогресс по выдаче: каждый участник группы + сколько
        попыток и решена ли задача верно. None — выдача не найдена."""
        assignment = self.get_assignment(assignment_id)
        if assignment is None:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT u.login, u.FIO, '
                '       COUNT(a.client_uuid) AS attempts, '
                '       MAX(CASE WHEN a.correct = 1 THEN 1 ELSE 0 END) AS solved, '
                '       MAX(a.created_at) AS last_at '
                'FROM group_members gm '
                'JOIN users u ON u.login = gm.user_id '
                'LEFT JOIN attempts a '
                '  ON a.user_id = gm.user_id AND a.partition_id = ? '
                'WHERE gm.group_id = ? '
                'GROUP BY u.login, u.FIO '
                'ORDER BY u.login',
                (assignment.partition_id, assignment.group_id),
            ).fetchall()
        students = [
            {"login": r[0], "fio": r[1] or "", "attempts": int(r[2] or 0),
             "solved": bool(r[3]), "last_at": r[4]}
            for r in rows
        ]
        solved = sum(1 for s in students if s["solved"])
        attempted = sum(1 for s in students if s["attempts"] > 0)
        return {
            "assignment": assignment.to_dict(),
            "students": students,
            "summary": {"members": len(students), "attempted": attempted,
                        "solved": solved},
        }
