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

    if args.detail and differ:
        parts = ["# Диффы расходящихся узлов\n"]
        for name, pair in differ.items():
            parts.append(f"\n## `{name}` ({pair[0]['file']})\n\n```diff\n"
                         + "\n".join(_diff(*pair)) + "\n```\n")
        pathlib.Path(args.detail).write_text("\n".join(parts), encoding="utf-8")
        print(f"\nДиффы: {args.detail}")

    drifted = bool(only_dsk or only_srv or differ or files)
    print("\n" + ("ДРЕЙФ ЕСТЬ" if drifted else "Расхождений нет"))
    return 1 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
