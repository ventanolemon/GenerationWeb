"""
Repository — слой доступа к БД, собранный из доменных миксинов.

Был один класс на 1520 строк и восемь доменов в нём. Разрезан по
доменам, а НЕ по таблицам: границы проведены там, где проходят границы
смысла (контент, люди, учебный процесс, доступ, состояние выполнения).

Композиция миксинами, а не отдельными объектами (`repo.subjects.list()`):
публичная поверхность обязана была остаться прежней — на неё опираются
все роутеры и 226 тестов, и менять её заодно с перекладыванием файлов
значило бы смешать механическую правку с содержательной. Миксины
разделяют один `self`, поэтому вызовы между доменами продолжают работать
как раньше.

Порядок наследования значения не имеет — имена методов не пересекаются;
`RepositoryBase` стоит последним как основание.
"""

from __future__ import annotations

from .access import AccessMixin
from .base import RepositoryBase
from .content import ContentMixin
from .organizations import OrganizationsMixin
from .models import (ROLES, Assignment, Group, Partition, Subject,
                     UserProfile, _VIEW_KIND_BY_CONSTRACTED)
from .runtime import RuntimeMixin
from .teaching import TeachingMixin
from .users import UsersMixin


class Repository(ContentMixin, UsersMixin, TeachingMixin, AccessMixin,
                 OrganizationsMixin, RuntimeMixin, RepositoryBase):
    """Единая точка доступа к БД. Домены — в соседних модулях."""


__all__ = [
    "Repository", "ROLES",
    "Subject", "Partition", "Group", "Assignment", "UserProfile",
    "_VIEW_KIND_BY_CONSTRACTED",
]
