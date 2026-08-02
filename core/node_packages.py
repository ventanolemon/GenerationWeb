"""
Пакеты узлов графа: реестр, установка на сервере, разрешение зависимостей.

Односторонний канал: пакеты приезжают С СЕРВЕРА, наружу с десктопов ничего
не публикуется. Это сознательный компромисс — он снимает вектор
«преподаватель отправил код, код доехал до других преподавателей», оставляя
удобство расширяемости.

Оставшуюся угрозу («скомпрометированный сервер → все десктопы») снимает не
односторонность, а ОБЩИЙ КОРЕНЬ ДОВЕРИЯ с обновлениями приложения
(`core/signing.py`): та же офлайновая подпись, тот же ключ, та же защита от
отката. Пакеты — не новый канал доставки кода, а тот же самый, только мельче
гранулярностью.

## Форма взята у пакетных менеджеров, открытость — нет

Определяющее свойство PyPI — публиковать может кто угодно, и именно оно
порождает тайпсквоттинг, угон аккаунтов и вредоносные обновления безобидных
пакетов. Здесь взята форма (пакеты, версии, установка, список доступного), а
публикация оставлена как у релизов: администратор плюс офлайновая подпись.

## Именование узлов

Узлы пакета обязаны быть с префиксом: `physics.projectile`. Встроенные
остаются без него. Это делает коллизии невозможными по построению — пакет
не может перехватить `formula` — и не требует миграции существующих графов.

## Кто решает, какой код исполняется на сервере

Администратор, а не автор графа. Набор пакетов сервера курируется явно
(`installed_packages`); граф с узлом из неустановленного пакета отвергается
на push'е с внятным сообщением, а не падает потом при генерации. Иначе
решение «что запускается на сервере» принимал бы тот, кто прислал граф, — то
есть дверь, закрытая односторонностью, приоткрывалась бы на шаг длиннее.

Отказ кладёт запрос в очередь `package_requests`: без неё отказ на push'е
превращается в переписку в чате.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from . import signing
from .repository import Repository
from .signing import SignatureError

__all__ = ["SignatureError", "PackageError", "MissingPackages",
           "canonical_manifest", "verify_signature", "publish",
           "yank", "describe", "catalog", "manifest_for_install",
           "install", "uninstall", "installed_node_types",
           "graph_node_types", "check_graph_requirements",
           "pending_requests", "SIGNED_FIELDS"]

# Состав подписанного манифеста пакета. node_types входит НАМЕРЕННО: иначе
# кто угодно мог бы заявить, что его пакет предоставляет `formula`, и
# перехватывать чужие графы.
SIGNED_FIELDS = ("name", "version", "sequence", "size_bytes", "sha256",
                 "api_version", "node_types")
# Версия API узлов, которую понимает этот сервер. Пакет, собранный под другую,
# не принимается: сигнатуры Node/Port/ExecContext — контракт, и молча
# исполнять код, рассчитанный на другой, значит получать падения в рантайме.
SUPPORTED_API_VERSIONS = ("1",)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class PackageError(ValueError):
    """Недопустимое по бизнес-правилам действие — роутер превращает в 400."""


class MissingPackages(PackageError):
    """Граф требует пакетов, которых на сервере нет. `packages` — каких."""

    def __init__(self, message: str, packages: list, unknown_types: list):
        super().__init__(message)
        self.packages = packages
        self.unknown_types = unknown_types


# ---------- Манифест ----------

def canonical_manifest(package: dict) -> bytes:
    """Байты манифеста пакета. `node_types` нормализуется сортировкой —
    подписывающий и проверяющий обязаны получить одно и то же."""
    payload = dict(package)
    payload["node_types"] = ",".join(sorted(package.get("node_types") or []))
    return signing.canonical_manifest(
        payload, SIGNED_FIELDS, int_fields=("sequence", "size_bytes"))


def verify_signature(package: dict, signature_b64: str,
                     public_key_b64: str) -> None:
    signing.verify(canonical_manifest(package), signature_b64, public_key_b64)


# ---------- Публикация (admin + офлайновая подпись) ----------

def publish(repo: Repository, *, name: str, version: str, sequence: int,
            url: str, size_bytes: int, sha256: str, signature: str,
            node_types: Iterable[str], public_key: str,
            api_version: str = "1", signing_key_id: str = "",
            summary: str = "", actor_login: str = "") -> dict:
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise PackageError(
            "Имя пакета: строчные латинские буквы, цифры и подчёркивание, "
            "2–31 символ.")
    if api_version not in SUPPORTED_API_VERSIONS:
        raise PackageError(
            f"api_version {api_version!r} не поддерживается этим сервером "
            f"(понимает {', '.join(SUPPORTED_API_VERSIONS)}).")
    if len(sha256 or "") != 64:
        raise PackageError("sha256 должен быть 64 hex-символа.")
    if not url.strip():
        raise PackageError("Нужен адрес артефакта.")

    types = sorted({str(t).strip() for t in node_types if str(t).strip()})
    if not types:
        raise PackageError("Пакет обязан объявить хотя бы один тип узла.")
    bad = [t for t in types if not t.startswith(f"{name}.")]
    if bad:
        # Без префикса пакет мог бы перехватить встроенный тип и незаметно
        # подменить поведение всех графов, которые его используют.
        raise PackageError(
            f"Типы узлов пакета обязаны начинаться с «{name}.»; не годятся: "
            f"{', '.join(bad)}.")

    with repo.transaction():
        if repo.get_node_package(name, version) is not None:
            raise PackageError(
                f"Пакет {name} {version} уже опубликован. Исправление — "
                f"новая версия, а не перевыпуск: перевыпуск подменяет уже "
                f"раздаваемое.")
        expected = repo.next_package_sequence(name)
        if int(sequence or 0) < expected:
            raise PackageError(
                f"sequence {sequence} не больше уже выпущенных: следующий "
                f"свободный — {expected}.")

        # Чужой пакет не должен объявлять типы, которые уже даёт другой:
        # два источника одного type_id — это неопределённость, какой код
        # исполнится.
        for other in repo.list_node_packages():
            if other["name"] == name:
                continue
            clash = set(types) & set(other["node_types"])
            if clash:
                raise PackageError(
                    f"Типы {', '.join(sorted(clash))} уже объявлены пакетом "
                    f"{other['name']}.")

        manifest = {"name": name, "version": version,
                    "sequence": int(sequence or 0),
                    "size_bytes": int(size_bytes or 0), "sha256": sha256,
                    "api_version": api_version, "node_types": types}
        verify_signature(manifest, signature, public_key)

        repo.add_node_package(
            **manifest, url=url.strip(), signature=signature,
            signing_key_id=signing_key_id.strip(), summary=summary.strip(),
            published_by=actor_login or None)
    return describe(repo, name, version)


def yank(repo: Repository, *, name: str, version: str) -> dict:
    if not repo.yank_node_package(name, version):
        raise PackageError(f"Действующий пакет {name} {version} не найден.")
    return describe(repo, name, version)


def describe(repo: Repository, name: str, version: str) -> dict:
    row = repo.get_node_package(name, version)
    if row is None:
        raise PackageError(f"Пакет {name} {version} не найден.")
    return row


def catalog(repo: Repository) -> dict:
    """Что вообще существует и что из этого стоит на сервере."""
    installed = {p["name"]: p["version"] for p in repo.installed_packages()}
    latest: dict[str, dict] = {}
    for pkg in repo.list_node_packages():
        latest.setdefault(pkg["name"], pkg)      # list_* уже по sequence DESC
    packages = []
    for name, pkg in sorted(latest.items()):
        packages.append({
            "name": name, "version": pkg["version"],
            "summary": pkg["summary"], "node_types": pkg["node_types"],
            "api_version": pkg["api_version"],
            "installed_version": installed.get(name),
            "installed": name in installed,
        })
    return {"packages": packages}


def manifest_for_install(repo: Repository, name: str,
                         version: Optional[str] = None) -> dict:
    """
    Что нужно клиенту для установки: манифест и подпись.

    Клиент обязан проверить подпись СВОИМ ключом до записи на диск и
    отвергнуть пакет, чей `sequence` не больше уже установленного, — сервер
    здесь источник данных, а не граница безопасности.
    """
    pkg = (repo.get_node_package(name, version) if version
           else repo.latest_node_package(name))
    if pkg is None or pkg["yanked_at"] is not None:
        raise PackageError(f"Действующий пакет {name} не найден.")
    return {
        "manifest": {f: pkg[f] for f in SIGNED_FIELDS},
        "signature": pkg["signature"],
        "signing_key_id": pkg["signing_key_id"],
        "url": pkg["url"],
        "summary": pkg["summary"],
    }


# ---------- Набор сервера (курирует администратор) ----------

def install(repo: Repository, *, name: str, version: Optional[str] = None,
            actor_login: str = "") -> dict:
    """
    Разрешить пакет на сервере. Отметка в БД, а не распаковка: физическую
    выкладку файлов делает деплой, здесь фиксируется РЕШЕНИЕ администратора,
    от которого зависит приём графов.
    """
    pkg = (repo.get_node_package(name, version) if version
           else repo.latest_node_package(name))
    if pkg is None:
        raise PackageError(f"Пакет {name} не найден в реестре.")
    if pkg["yanked_at"] is not None:
        raise PackageError(f"Пакет {name} {pkg['version']} отозван.")
    with repo.transaction():
        repo.set_installed_package(name, pkg["version"], actor_login or None)
        repo.resolve_package_requests(name)
    return {"installed": name, "version": pkg["version"],
            "node_types": pkg["node_types"]}


def uninstall(repo: Repository, *, name: str) -> dict:
    if not repo.remove_installed_package(name):
        raise PackageError(f"Пакет {name} на сервере не установлен.")
    return {"uninstalled": name}


def installed_node_types(repo: Repository) -> set[str]:
    """Типы узлов, которые сервер готов исполнять сверх встроенных."""
    types: set[str] = set()
    for entry in repo.installed_packages():
        pkg = repo.get_node_package(entry["name"], entry["version"])
        if pkg is not None:
            types.update(pkg["node_types"])
    return types


# ---------- Разрешение зависимостей графа ----------

def graph_node_types(generation_params) -> set[str]:
    """
    Типы узлов, использованные в графе.

    Читаем из сохранённого графа (`{"nodes": [{"id", "type", "params"}]}`), а
    не из деклараций клиента: декларация неизбежно расходится с содержимым, а
    здесь источник истины один — сам граф.
    """
    if not isinstance(generation_params, dict):
        return set()
    nodes = generation_params.get("nodes")
    if not isinstance(nodes, list):
        return set()
    return {str(n.get("type", "")).strip() for n in nodes
            if isinstance(n, dict) and str(n.get("type", "")).strip()}


def check_graph_requirements(repo: Repository, generation_params,
                             known_types: Iterable[str],
                             requested_by: str = "") -> None:
    """
    Проверить, что сервер способен исполнить этот граф. Бросает
    MissingPackages.

    Зовётся на push'е, а не при генерации: отвергнуть на входе с внятным
    «нужен пакет X» честнее, чем принять граф и падать на нём потом у всех,
    кто его откроет, — включая стороннего интегратора через публичный API.
    """
    used = graph_node_types(generation_params)
    if not used:
        return
    available = set(known_types) | installed_node_types(repo)
    missing = sorted(used - available)
    if not missing:
        return

    # Для недостающего типа ищем, какой пакет его даёт: сообщение «нужен
    # пакет physics» действеннее, чем «неизвестный узел physics.projectile».
    provider: dict[str, str] = {}
    for pkg in repo.list_node_packages():
        for node_type in pkg["node_types"]:
            provider.setdefault(node_type, pkg["name"])

    packages = sorted({provider[t] for t in missing if t in provider})
    unknown = [t for t in missing if t not in provider]

    if packages and requested_by:
        with repo.transaction():
            for name in packages:
                repo.request_package(
                    name, requested_by,
                    reason="нужен для узлов: " + ", ".join(
                        t for t in missing if provider.get(t) == name))

    parts = []
    if packages:
        parts.append("на сервере не установлены пакеты: "
                     + ", ".join(packages)
                     + " — запрос администратору отправлен")
    if unknown:
        parts.append("неизвестные типы узлов: " + ", ".join(unknown))
    raise MissingPackages("Граф не принят: " + "; ".join(parts) + ".",
                          packages, unknown)


def pending_requests(repo: Repository) -> dict:
    """Чего людям не хватает — очередь для администратора."""
    return {"requests": repo.list_package_requests(pending_only=True)}
