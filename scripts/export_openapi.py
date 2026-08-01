"""
Выгрузка OpenAPI-описания generator_service в файл.

    python -m scripts.export_openapi [путь]        # по умолчанию openapi.json

Зачем отдельной командой, а не закоммиченным файлом: описание порождается
из кода (FastAPI собирает его из сигнатур и моделей), и закоммиченная копия
разошлась бы с реальностью на первой же правке роутера. Актуальность
контракта стережёт `core/test_api_contract.py`, а этот скрипт нужен, чтобы
отдать описание наружу — в генератор клиентов, в Swagger UI или в ревью
диффом двух выгрузок.

Приложение не поднимается целиком: `app.openapi()` читает маршруты, ему не
нужны ни БД, ни реестр генераторов. Поэтому команда работает где угодно,
включая CI без окружения.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

_MONOREPO = Path(__file__).resolve().parent.parent
if str(_MONOREPO) not in sys.path:
    sys.path.insert(0, str(_MONOREPO))


def main() -> int:
    from generator_service.main import app

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    spec = app.openapi()
    target.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths = len(spec.get("paths", {}))
    print(f"OpenAPI {spec['openapi']}: {paths} маршрутов → {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
