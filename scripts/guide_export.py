"""
Выгрузка базы знаний для веб-клиента.

    python -m scripts.guide_export

Разбор формата живёт в `core/guide.py` и только там: два разбора одного
формата расходятся молча. Здесь — только запись готового.

Файл лежит в исходниках фронтенда и попадает в сборку обычным импортом.
Так база знаний открывается у гостя и без сети: инструкция, за которой
надо сходить на сервер, бесполезна ровно тогда, когда сервер недоступен.
"""

from __future__ import annotations

import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.guide import EXPORT_FILE, to_json          # noqa: E402


def main() -> int:
    EXPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json()
    EXPORT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"{EXPORT_FILE.relative_to(_ROOT)}: "
          f"страниц {len(payload['pages'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
