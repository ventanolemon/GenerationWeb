"""
Расхождение движка между сервером (GenerationWeb) и десктопом (Generator).

    python -m scripts.core_drift [путь-к-Generator] [--detail ФАЙЛ]

Сравнение по УЗЛАМ через AST, а не по строкам файлов. Это не педантизм:
узлы переставляют внутри модулей и переносят между ними, и построчный diff
на таком материале выдаёт сотни строк шума, в которых тонет единственное,
что важно, — «этот узел исполняется по-разному по разные стороны синка».
Единица сравнения здесь — класс узла, опознанный по `type_id`, потому что
именно `type_id` едет в графе по проводу.

Код выхода: 0 — расхождений нет, 1 — есть. Годится как гейт в CI, когда он
появится: дрейф движка должен быть громким событием, а не открытием через
полгода.

Зачем это вообще: графы синхронизируются между десктопом и сервером
(`generation_parametrs` в offline_sync_protocol.md), а исполняются по обе
стороны. Узел, которого нет на сервере, роняет `/generate` и `/v1/tasks`;
узел с разным кодом даёт РАЗНОЕ задание, ничего об этом не сообщая.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DESKTOP = _HERE.parent / "Generator"

# Файлы, где расхождение ОЖИДАЕМО и не является дрейфом: серверные адаптации
# (ленивые Qt-импорты ради headless, to_dict() для JSON, снимок состояния
# сессии) и слой доступа к БД, который у сторон разный по построению.
EXPECTED = {
    "repository.py", "blocks.py", "dynamic_blocks.py", "content.py",
    "task.py", "__init__.py",
}

# Каталоги, которые обе стороны ИСПОЛНЯЮТ: движок графа и модели. Здесь
# файл, существующий только с одной стороны, — уже расхождение, даже если
# его содержимое сравнивать не с чем. Для модели это громкий случай:
# граф, собранный на десктопе вокруг модели, которой нет на сервере,
# уронит /generate — а сравнение «файл против файла» такую пропажу молча
# пропускает, потому что сравнивать нечего.
#
# По остальному ядру такой проверки нет намеренно: стороны законно
# разные (у сервера слой БД и API, у десктопа клиенты и Qt), и список
# «только с одной стороны» там состоит из полусотни ожидаемых имён,
# в которых настоящее расхождение утонет.
SHARED_DIRS = ("graph", "models")

# Модули ядра, которые живут ТОЛЬКО на сервере: слой API, доступ к БД,
# подписи, изоляция исполнения. Список нужен не для порядка, а для
# проверки в обратную сторону: файл отсюда, ОКАЗАВШИЙСЯ на десктопе, —
# это ошибка зеркалирования, а не новая возможность.
#
# Случай не гипотетический: при переносе правок сюда однажды уехали
# `content_authz.py`, `sync_api.py` и два серверных теста. Прежняя
# проверка их не увидела — она сравнивает файл с файлом, а сравнивать
# было не с чем. Теперь увидит.
#
# Список устаревает громко: если серверный модуль законно становится
# общим, проверка падает и его убирают отсюда осознанно. Это та же
# дисциплина, что у EXPECTED.
#
# Так и случилось с `export_api.py`: раскладка ответов в документе —
# понятие предметной области, а не деталь веб-службы, и её потребителей
# трое (служба и два бэкенда десктопа). Модуль убран отсюда осознанно и
# теперь зеркалится.
SERVER_ONLY = {
    "admin_api.py", "analytics_api.py", "api_clients.py",
    "assignments_api.py", "auth_sessions.py", "content_api.py",
    "content_authz.py", "grants_api.py",
    "graph/isolation.py", "graph/worker.py", "graph_api.py",
    "graph_probe.py", "groups_api.py", "migrations.py", "node_packages.py",
    "organizations_api.py", "passwords.py", "public_api.py", "signing.py",
    "signing_keys.py", "subjects_api.py", "sync_api.py", "updates.py",
}


def node_classes(core: pathlib.Path) -> dict[str, dict]:
    """type_id → {file, src} по каталогу узлов."""
    out: dict[str, dict] = {}
    nodes_dir = core / "graph" / "nodes"
    if not nodes_dir.exists():
        return out
    for path in sorted(nodes_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for stmt in cls.body:
                if (isinstance(stmt, ast.Assign)
                        and any(getattr(t, "id", None) == "type_id"
                                for t in stmt.targets)
                        and isinstance(stmt.value, ast.Constant)):
                    out[stmt.value.value] = {
                        "file": path.name,
                        "src": ast.get_source_segment(text, cls) or "",
                    }
    return out


def shared_gaps(server_core: pathlib.Path,
                desktop_core: pathlib.Path) -> list[str]:
    """Файлы общих каталогов, существующие лишь с одной стороны."""

    def listing(root: pathlib.Path) -> set[str]:
        out: set[str] = set()
        for name in SHARED_DIRS:
            base = root / name
            if not base.exists():
                continue
            for path in base.rglob("*.py"):
                rel = path.relative_to(root)
                if rel.name.startswith("test_"):
                    continue
                out.add(rel.as_posix())
        return out

    srv, dsk = listing(server_core), listing(desktop_core)
    out = [f"{rel} — только на сервере" for rel in sorted(srv - dsk)
           if rel not in SERVER_ONLY]
    out += [f"{rel} — только на десктопе" for rel in sorted(dsk - srv)]
    out += [f"{rel} — серверный модуль, а лежит и на десктопе"
            for rel in sorted(SERVER_ONLY & _all_desktop(desktop_core))]
    return out


def _all_desktop(desktop_core: pathlib.Path) -> set[str]:
    """Все файлы десктопного ядра, включая тесты."""
    return {path.relative_to(desktop_core).as_posix()
            for path in desktop_core.rglob("*.py")}


def stray_tests(desktop_core: pathlib.Path) -> list[str]:
    """
    Серверные тесты, уехавшие на десктоп.

    Проверка механическая, а не по списку: тест серверный, если он
    импортирует то, чего на десктопе нет, — модуль из SERVER_ONLY или
    сам `generator_service`. Список таких тестов вести не надо, он
    выводится.

    Нужно это потому, что ошибка повторяется: правку переносят пачкой
    файлов, и вместе с общими уезжают серверные. За одну сессию так
    случилось дважды — `content_authz.py` с двумя тестами, затем
    `test_subject_grants.py`. Оба раза прежняя проверка молчала: она
    сравнивает файл с файлом, а сравнивать было не с чем.
    """
    forbidden = {name.rsplit("/", 1)[-1].removesuffix(".py")
                 for name in SERVER_ONLY} | {"generator_service"}
    out: list[str] = []
    for path in sorted(desktop_core.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
                names.update(a.name.split(".")[-1] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")
                names.update(module)
                names.update(a.name for a in node.names)
        hit = sorted(names & forbidden)
        if hit:
            rel = path.relative_to(desktop_core).as_posix()
            out.append(f"{rel} — серверный тест на десктопе "
                       f"(импортирует {', '.join(hit)})")
    return out


def _norm(src: str) -> list[str]:
    """Хвостовые пробелы и пустые строки — не расхождение."""
    return [ln.rstrip() for ln in src.splitlines() if ln.strip()]


def _diff(a: dict, b: dict) -> list[str]:
    return list(difflib.unified_diff(
        _norm(a["src"]), _norm(b["src"]),
        fromfile=f"сервер/{a['file']}", tofile=f"десктоп/{b['file']}",
        lineterm="", n=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("desktop", nargs="?", default=str(DEFAULT_DESKTOP),
                    help="корень репозитория Generator")
    ap.add_argument("--detail", help="куда выгрузить диффы спорных узлов")
    args = ap.parse_args()

    server_core = _HERE / "core"
    desktop_core = pathlib.Path(args.desktop) / "core"
    if not desktop_core.exists():
        print(f"Не найден {desktop_core}", file=sys.stderr)
        return 2

    srv, dsk = node_classes(server_core), node_classes(desktop_core)
    only_dsk = sorted(set(dsk) - set(srv))
    only_srv = sorted(set(srv) - set(dsk))
    differ = {k: (srv[k], dsk[k]) for k in sorted(set(srv) & set(dsk))
              if _norm(srv[k]["src"]) != _norm(dsk[k]["src"])}

    # Чистое добавление на десктопе (в диффе нет удалений) — это отставание
    # сервера, а не конфликт: решать нечего, надо подтянуть.
    additive, mutual = [], []
    for name, pair in differ.items():
        removed = [ln for ln in _diff(*pair)
                   if ln.startswith("-") and not ln.startswith("---")]
        (mutual if removed else additive).append(name)

    print(f"Узлы: сервер {len(srv)}, десктоп {len(dsk)}, "
          f"идентичны {len(set(srv) & set(dsk)) - len(differ)}")
    if only_dsk:
        print(f"\nТолько на десктопе ({len(only_dsk)}) — сервер такой граф "
              f"не исполнит:\n  " + ", ".join(only_dsk))
    if only_srv:
        print(f"\nТолько на сервере ({len(only_srv)}):\n  " + ", ".join(only_srv))
    if additive:
        print(f"\nСервер отстал, конфликта нет ({len(additive)}):\n  "
              + ", ".join(sorted(additive)))
    if mutual:
        print(f"\nВзаимное расхождение — смотреть глазами ({len(mutual)}):\n  "
              + ", ".join(sorted(mutual)))

    files = []
    for path in sorted(server_core.rglob("*.py")):
        rel = path.relative_to(server_core)
        if rel.name.startswith("test_") or "repo" in rel.parts:
            continue
        other = desktop_core / rel
        if not other.exists() or rel.name in EXPECTED:
            continue
        if _norm(path.read_text()) != _norm(other.read_text()):
            files.append(str(rel))
    if files:
        print(f"\nФайлы движка с расхождением ({len(files)}):\n  "
              + "\n  ".join(files))

    missing = shared_gaps(server_core, desktop_core) + stray_tests(desktop_core)
    if missing:
        print(f"\nФайлы не на своих сторонах ({len(missing)}):\n  "
              + "\n  ".join(missing))

    if args.detail and differ:
        parts = ["# Диффы расходящихся узлов\n"]
        for name, pair in differ.items():
            parts.append(f"\n## `{name}` ({pair[0]['file']})\n\n```diff\n"
                         + "\n".join(_diff(*pair)) + "\n```\n")
        pathlib.Path(args.detail).write_text("\n".join(parts), encoding="utf-8")
        print(f"\nДиффы: {args.detail}")

    drifted = bool(only_dsk or only_srv or differ or files or missing)
    print("\n" + ("ДРЕЙФ ЕСТЬ" if drifted else "Расхождений нет"))
    return 1 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
