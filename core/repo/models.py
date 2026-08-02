"""
Значения предметной области: dataclass'ы строк БД и константы.

Вынесены отдельно от доступа к данным, потому что их импортируют и те,
кто с БД не работает вовсе (роутеры, сериализация). Все frozen и без
зависимостей от UI и ORM — это значения, а не сущности сессии.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

# Роли пользователя (иерархия аддитивна: admin ⊃ teacher ⊃ student).
ROLES = ("student", "teacher", "admin")


@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    parent_name: str  # значение поля pra_subject

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "parent_name": self.parent_name,
        }


@dataclass(frozen=True)
class Partition:
    id: int
    subject_id: int
    name: str
    constracted: int          # 0=одиночный, 1=конструктор, 2=группа, 3=тест
    generation_params: dict   # распарсенный JSON или {}

    def to_dict(self) -> dict:
        # generation_params целенаправленно не отдаём в публичный API —
        # это «кишки» (конфиг физического конструктора, список task_id
        # группы и т.п.). Если он понадобится конкретному веб-эндпоинту,
        # пусть достаёт его отдельно через get_partition().
        return {
            "id": self.id,
            "subject_id": self.subject_id,
            "name": self.name,
            "constracted": self.constracted,
        }


# Какой view_kind использовать для каждого constracted:
#   0 — single  (одиночное задание, кнопка «Сгенерировать»)
#   1 — table   (конструктор физики — таблица накопленных заданий)
#   2 — table   (группа — таблица заданий из разных детей)
#   3 — test    (тест с вариантами)
_VIEW_KIND_BY_CONSTRACTED = {
    0: "single",
    1: "table",
    2: "table",
    3: "test",
}


@dataclass(frozen=True)
class Group:
    """Структурная группа. created_by — логин автора (NULL у seed'а из
    users."group"). Списки участников/преподавателей достаются отдельными
    методами Repository (не денормализуем в dataclass)."""
    id: int
    name: str
    created_by: Optional[str]
    created_at: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Assignment:
    """Выдача задания (партиции) группе как домашки. due_at — срок (epoch,
    None = без срока). Поля partition_name/subject_name/group_name
    заполняются в read-методах (join), в самой таблице их нет."""
    id: int
    partition_id: int
    group_id: int
    assigned_by: Optional[str]
    due_at: Optional[float]
    partition_name: str = ""
    subject_name: str = ""
    group_name: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "partition_id": self.partition_id,
            "group_id": self.group_id,
            "assigned_by": self.assigned_by,
            "due_at": self.due_at,
            "partition_name": self.partition_name,
            "subject_name": self.subject_name,
            "group_name": self.group_name,
        }


@dataclass(frozen=True)
class UserProfile:
    login: str
    fio: str
    group: str
    email: str
    about: str
    avatar_color: str
    created_at: float
    id: int = 0
    role: str = "student"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "login": self.login,
            "role": self.role,
            "fio": self.fio,
            "group": self.group,
            "email": self.email,
            "about": self.about,
            "avatar_color": self.avatar_color,
            "created_at": self.created_at,
        }
