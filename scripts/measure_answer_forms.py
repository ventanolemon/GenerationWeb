"""
Замер: сколько верных записей ответа отвергает строковое сравнение.

    python -m scripts.measure_answer_forms [--variants N] [--json ФАЙЛ]

Зачем этот замер
----------------
Проблема Pr.02 диплома («проверка отвергает верный ответ, записанный в
другой форме») до сих пор стояла как «требует замера». Замерить её на
попытках студентов нельзя: накопленные попытки — демонстрационные, поле
введённого текста в них пустое.

Но само свойство от студентов не зависит. Это свойство СИСТЕМЫ (MOP), а
не процесса (MOE): вопрос «сколько допустимых записей одного и того же
ответа отвергнет строковое сравнение» решается на самих спецификациях
ответа, без единого живого студента.

Как устроен замер
-----------------
1. Собирается реестр генераторов — все, что есть в поставке.
2. Каждый порождает N вариантов; у варианта берётся спецификация ответа.
3. У спецификации запрашивается `accepted_examples()` — перечень
   записей, которые она САМА признаёт верными (каждая проверена её же
   `check`, инвариант «предпросмотр не врёт»).
4. Первая запись объявляется эталоном — это то, что наивная система
   хранила бы строкой «правильный ответ».
5. Остальные записи прогоняются через три проверки:

   * **строгое равенство строк** — `ответ == эталон`;
   * **нормализованное равенство** — с приведением регистра, схлопыванием
     пробелов и заменой запятой на точку (аккуратная наивная реализация);
   * **предметная проверка** — сама спецификация.

Считается доля отвергнутых. Третья проверка обязана давать ноль по
построению — она в замере как контроль: если она отвергла хоть одну
запись, сломан инвариант `accepted_examples`, и об этом надо знать.

Чего замер НЕ показывает
------------------------
Он меряет допустимые формы, ЗАЛОЖЕННЫЕ в спецификацию, а не формы,
которые реально пишут студенты. Распределение реальных ответов может
быть смещено к одной записи, и тогда наблюдаемая частота споров окажется
ниже. Замер даёт верхнюю оценку: сколько верных записей строковое
сравнение способно отвергнуть.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import warnings
from collections import Counter, defaultdict


def _normalize(text: str) -> str:
    """Аккуратная наивная нормализация: регистр, пробелы, разделитель."""
    out = str(text).strip().lower().replace(",", ".")
    return re.sub(r"\s+", " ", out)


def _collect(variants: int) -> list[dict]:
    """Прогнать все генераторы и собрать записи по каждой спецификации."""
    from core import Repository
    import bootstrap
    from const import DB_PATH, WORDS_DIR

    # Работаем с КОПИЕЙ поставочной БД: Repository при открытии заводит
    # служебные таблицы и переводит журнал, то есть МЕНЯЕТ ресурс
    # поставки. Замер не имеет права оставлять следов в том, что уезжает
    # пользователю.
    copy = tempfile.mktemp(suffix=".db")
    shutil.copyfile(DB_PATH, copy)
    repo = Repository(copy)
    registry = bootstrap.build_registry(repo, WORDS_DIR)

    rows: list[dict] = []
    for partition_id in sorted(registry.all_ids()):
        for _ in range(variants):
            try:
                task = registry.get(partition_id).generate()
            except Exception:                       # noqa: BLE001
                break
            spec = getattr(task, "answer_spec", None)
            if spec is None:
                break
            try:
                examples = spec.accepted_examples()
            except Exception:                       # noqa: BLE001
                continue
            if len(examples) < 2:
                # Одна допустимая запись — отвергать нечего, но случай
                # засчитывается: он показывает, у скольких заданий
                # вариативности записи нет вовсе.
                rows.append({"partition": partition_id,
                             "spec": type(spec).__name__,
                             "forms": len(examples),
                             "strict_rejected": 0,
                             "normalized_rejected": 0,
                             "domain_rejected": 0})
                continue

            canonical, rest = examples[0], examples[1:]
            strict = sum(1 for form in rest if form != canonical)
            normalized = sum(1 for form in rest
                             if _normalize(form) != _normalize(canonical))
            domain = sum(1 for form in rest
                         if not spec.check(form).accepted)
            rows.append({"partition": partition_id,
                         "spec": type(spec).__name__,
                         "forms": len(examples),
                         "strict_rejected": strict,
                         "normalized_rejected": normalized,
                         "domain_rejected": domain})
    if os.path.exists(copy):
        os.unlink(copy)
    return rows


def _report(rows: list[dict]) -> dict:
    total_forms = sum(r["forms"] - 1 for r in rows if r["forms"] >= 1)
    strict = sum(r["strict_rejected"] for r in rows)
    normalized = sum(r["normalized_rejected"] for r in rows)
    domain = sum(r["domain_rejected"] for r in rows)

    by_spec: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        c = by_spec[r["spec"]]
        c["variants"] += 1
        c["forms"] += max(0, r["forms"] - 1)
        c["strict"] += r["strict_rejected"]
        c["normalized"] += r["normalized_rejected"]
        c["domain"] += r["domain_rejected"]

    single = sum(1 for r in rows if r["forms"] <= 1)

    print(f"Вариантов со спецификацией ответа: {len(rows)}")
    print(f"Из них с единственной допустимой записью: {single} "
          f"({single / len(rows):.1%})" if rows else "")
    print(f"Всего альтернативных верных записей: {total_forms}")
    print()
    print(f"{'Проверка':32} {'отвергнуто':>11} {'доля':>8}")
    for name, value in (("строгое равенство строк", strict),
                        ("нормализованное равенство", normalized),
                        ("предметная проверка", domain)):
        share = value / total_forms if total_forms else 0.0
        print(f"{name:32} {value:11} {share:8.1%}")
    print()
    print(f"{'Вид спецификации':22} {'вариантов':>10} {'записей':>8} "
          f"{'строго':>8} {'норм.':>8} {'предм.':>8}")
    for name in sorted(by_spec):
        c = by_spec[name]
        print(f"{name:22} {c['variants']:10} {c['forms']:8} "
              f"{c['strict']:8} {c['normalized']:8} {c['domain']:8}")

    if domain:
        print("\nВНИМАНИЕ: предметная проверка отвергла собственные примеры — "
              "нарушен инвариант accepted_examples.")

    return {"variants": len(rows), "alternative_forms": total_forms,
            "rejected_strict": strict, "rejected_normalized": normalized,
            "rejected_domain": domain,
            "single_form_variants": single,
            "by_spec": {k: dict(v) for k, v in by_spec.items()}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variants", type=int, default=20,
                        help="сколько вариантов брать у каждого генератора")
    parser.add_argument("--json", help="куда сложить результат в JSON")
    args = parser.parse_args()

    warnings.simplefilter("ignore")
    rows = _collect(args.variants)
    if not rows:
        print("Ни одного варианта со спецификацией ответа не собрано.")
        return 1
    summary = _report(rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"summary": summary, "rows": rows}, handle,
                      ensure_ascii=False, indent=1)
        print(f"\nJSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
