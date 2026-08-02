"""
Точка импорта слоя доступа к БД.

Реализация переехала в пакет `core/repo/` и разрезана по доменам —
один класс на 1520 строк перестал быть слоем доступа и стал свалкой.
Модуль сохранён как имя, по которому слой импортируют роутеры, сервисы
и тесты: менять полсотни импортов заодно с перекладыванием файлов
значило бы смешать механическую правку с содержательной.

Куда что уехало:
  core/repo/base.py      файл БД, схема, соединение, транзакции
  core/repo/models.py    dataclass'ы строк и константы
  core/repo/content.py   предметы, разделы, владение и видимость
  core/repo/users.py     учётные записи, профили, роли
  core/repo/teaching.py  группы, преподаватели, домашние задания
  core/repo/access.py    выдачи предметов, ключи приложений, квоты
  core/repo/runtime.py   интерактивные сессии, статистика слов
"""

from __future__ import annotations

from .repo import (ROLES, Assignment, Group, Partition, Repository,
                   Subject, UserProfile, _VIEW_KIND_BY_CONSTRACTED)

__all__ = [
    "Repository", "ROLES",
    "Subject", "Partition", "Group", "Assignment", "UserProfile",
    "_VIEW_KIND_BY_CONSTRACTED",
]
