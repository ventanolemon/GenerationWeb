"""
Замер: различает ли правило «ближайший эталон в словаре» слова словаря.

    python -m scripts.measure_pronunciation [--words N] [--json ФАЙЛ]

Что проверяется
---------------
Правило проверки произношения (`core/pronunciation_match.py`) устроено
так же, как правило допуска на опечатку: принимается не «похоже на
эталон больше порога», а «эталон целевого слова ближе всех остальных
слов словаря». Абсолютный порог здесь не работает измеримо: расстояние
между дикторами больше расстояния между словами.

Замер отвечает на вопрос, от которого зависит применимость правила:
**остаётся ли целевое слово ближайшим, когда запись отличается от
эталона.**

Как устроен замер
-----------------
Живых записей людей нет. Вместо них эталон искажается тремя способами,
которые заведомо различают дикторов и микрофоны:

* **темп** — тот же голос быстрее или медленнее;
* **шум** — другой микрофон и другое помещение;
* **громкость** — другое расстояние до микрофона.

Для каждого искажённого образца ищется ближайший эталон словаря. Если это
эталон исходного слова — опознание верное.

Два счётчика, которые нельзя путать
-----------------------------------
Правило умеет ОТКАЗАТЬСЯ от вердикта, поэтому исходов не два, а три:
вердикт верный, вердикт неверный, вердикта нет. Считать надо все три —
и отдельно **уверенно неверные**, потому что именно они дороги: студенту
говорят «неверно» там, где система ошиблась сама.

Здесь была ошибка замера, стоившая неверного вывода в отчёте. Счётчик
уверенных вердиктов был написан как `confident += int(ok and confident)`,
то есть считал уверенные И ВЕРНЫЕ. Доля «верных среди вынесенных»
получалась 100% ПО ПОСТРОЕНИЮ: уверенно неверный вердикт этот счётчик
увидеть не мог в принципе. Теперь считаются отдельно `уверенно` и
`уверенно неверно`, и второе выводится всегда, даже когда оно ноль.

Материал: один словарь или вся поставка
---------------------------------------
`--dictionary` берёт слова ОДНОГО словаря — это окрестность, в которой
правило работает у студента. Но результат на одном словаре нельзя
переносить на механизм: словари разные. `--all` прогоняет выборку
окрестностей по ВСЕМ словарям поставки и показывает разброс между ними —
без этого легко замерить самый удобный материал и обобщить.

Чего замер НЕ показывает
------------------------
Искажения синтетические, эталоны порождены одним синтезатором. Это
**нижняя граница**: правило, не пережившее искусственного искажения, не
переживёт и живого. Обратное неверно — успех здесь не означает работы на
записях людей, и утверждать это нельзя до эксперимента с живыми
голосами. Замер отвечает на вопрос «стоит ли строить дальше», а не «уже
работает».
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import zlib
from collections import Counter

import numpy as np


#: Искажения: (имя, параметры). Подобраны как заведомо различающие
#: дикторов, а не как предел устойчивости.
PERTURBATIONS = (
    ("темп ×0.85", {"speed": 0.85}),
    ("темп ×1.20", {"speed": 1.20}),
    ("шум 5%", {"noise": 0.05}),
    ("шум 15%", {"noise": 0.15}),
    ("громкость ×0.5", {"gain": 0.5}),
    ("темп ×1.15 + шум 8%", {"speed": 1.15, "noise": 0.08}),
)


def _seed(term: str) -> int:
    """
    Зерно искажения — воспроизводимое между запусками.

    Было `abs(hash(term)) % 10_000`, а `hash()` в Python рандомизируется
    от запуска к запуску: два прогона на одном материале давали разные
    числа (замерено: 86 и 87 уверенных вердиктов). Замер, который нельзя
    повторить, нельзя и проверить. Та же причина, по которой номер
    раздела считается crc32, а не `hash()` — см. `core/partition_ids.py`.
    """
    return zlib.crc32(term.encode("utf-8")) % 10_000


def _dictionary_terms(limit: int) -> list[str]:
    """
    Слова одного учебного словаря — именно та окрестность, в которой
    правило и работает: студент отвечает внутри словаря занятия, а не
    внутри всей поставки.
    """
    import pathlib

    from core import pronunciation as P
    from exercises.english.generators import (
        WordsTrainerGenerator, _detect_kind, _read_json_lenient,
    )

    root = pathlib.Path(__file__).resolve().parent.parent
    index = P.audio_index()
    best: list[str] = []
    for path in sorted((root / "resources" / "words").glob("*.json")):
        if _detect_kind(path) != "words":
            continue
        try:
            words = WordsTrainerGenerator._flatten_words(
                _read_json_lenient(path))
        except Exception:                       # noqa: BLE001
            continue
        covered = [w for w in words if w in index]
        if len(covered) > len(best):
            best = covered
        if len(best) >= limit:
            break
    return sorted(best)[:limit]


def _all_dictionaries() -> list[tuple[str, list[str]]]:
    """Все словари поставки: `(имя, слова со звуком)`."""
    import pathlib

    from core import pronunciation as P
    from exercises.english.generators import (
        WordsTrainerGenerator, _detect_kind, _read_json_lenient,
    )

    root = pathlib.Path(__file__).resolve().parent.parent
    index = P.audio_index()
    out: list[tuple[str, list[str]]] = []
    for path in sorted((root / "resources" / "words").glob("*.json")):
        if _detect_kind(path) != "words":
            continue
        try:
            words = WordsTrainerGenerator._flatten_words(
                _read_json_lenient(path))
        except Exception:                       # noqa: BLE001
            continue
        covered = [w for w in words if w in index]
        if covered:
            out.append((path.stem, covered))
    return out


def _across_all(neighbours: int, samples: int) -> int:
    """
    Разброс МЕЖДУ словарями при той окрестности, что берёт задание.

    Существует потому, что замер по одному словарю ввёл в заблуждение:
    отчёт утверждал «ни одного уверенно неверного вердикта», а замерен
    был `complete_abbreveations` — словарь с самыми длинными терминами
    поставки (3.5 слова в среднем). Длинные многословные термины
    выравнивание различает уверенно; односложные — нет, и на них
    уверенно неверные вердикты появляются.

    Вывод, который отсюда следует, касается не только произношения:
    материал замера надо выбирать не тем, что попалось первым.
    """
    import random

    from core import pronunciation as P, pronunciation_match as M
    from core.graph.resources import resolve

    index = P.audio_index()
    cache: dict[str, object] = {}

    def features(term: str):
        if term not in cache:
            cache[term] = M.features_of(resolve(index[term]))
        return cache[term]

    # Искажение берётся одно и самое трудное из набора: разброс между
    # словарями виден там, где правилу тяжело, а не там, где всё верно.
    label, params = PERTURBATIONS[-1]
    print(f"Разброс по словарям, окрестность {neighbours} слов, "
          f"искажение «{label}», {samples} проб на словарь\n")
    print(f"{'словарь':38}{'слов':>6}{'ср. длина':>11}"
          f"{'уверенно':>10}{'НЕВЕРНО':>9}")

    rows = []
    for stem, pool in _all_dictionaries():
        if len(pool) < neighbours:
            continue
        rng = random.Random(zlib.crc32(stem.encode("utf-8")))
        confident = wrong = 0
        length = 0.0
        for _ in range(samples):
            target = rng.choice(pool)
            others = [t for t in pool if t != target]
            rng.shuffle(others)
            vocabulary = [target, *others[:neighbours - 1]]
            signal, rate = M.read_wav(resolve(index[target]))
            distorted = M.perturb(M.resample(signal, rate),
                                  seed=_seed(target), **params)
            found = M.match(M.mfcc(distorted),
                            {t: features(t) for t in vocabulary})
            length += len(target.split())
            if found is not None and found.confident:
                confident += 1
                wrong += int(found.term != target)
        rows.append((wrong, confident, stem, len(pool), length / samples))

    if not rows:
        print("Нет словаря, где хватило бы слов со звуком.")
        return 1

    rows.sort(reverse=True)
    for wrong, confident, stem, size, length in rows:
        print(f"  {stem[:36]:36}{size:>6}{length:>11.1f}"
              f"{confident:>10}{wrong:>9}")

    confident_total = sum(r[1] for r in rows)
    wrong_total = sum(r[0] for r in rows)
    print(f"\nВердикт вынесен: {confident_total}, из них НЕВЕРНЫХ: "
          f"{wrong_total}"
          + (f" ({wrong_total / confident_total:.1%})"
             if confident_total else ""))
    clean = [r[2] for r in rows if r[0] == 0]
    print(f"Словарей без уверенно неверных вердиктов: "
          f"{len(clean)} из {len(rows)}")
    print("\nСвойство «система не ошибается уверенно» ЗАВИСИТ ОТ МАТЕРИАЛА "
          "и\nмеханизму не принадлежит. Отчёты обязаны называть словарь.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, default=20,
                        help="сколько слов словаря брать")
    parser.add_argument("--all", action="store_true",
                        help="разброс по ВСЕМ словарям поставки")
    parser.add_argument("--neighbours", type=int, default=12,
                        help="размер окрестности для --all (как в задании)")
    parser.add_argument("--samples", type=int, default=25,
                        help="проб на словарь для --all")
    parser.add_argument("--json", help="куда сложить результат")
    args = parser.parse_args()

    if args.all:
        return _across_all(args.neighbours, args.samples)

    from core import pronunciation as P, pronunciation_match as M
    from core.graph.resources import resolve

    index = P.audio_index()
    if not index:
        print("В этой поставке нет звука — замерять нечего.")
        return 1

    terms = _dictionary_terms(args.words)
    if len(terms) < 4:
        print("Слишком мало слов со звуком.")
        return 1

    references = M.reference_features(
        terms, lambda term: resolve(index[term]) if term in index else None)
    print(f"Словарь: {len(references)} слов со звуком\n")

    confusions = M.vocabulary_confusions(references)
    print(f"Эталон опознаёт сам себя: "
          f"{len(references) - len(confusions)} из {len(references)}")

    rows = []
    totals: Counter = Counter()
    margins: dict[str, list[float]] = {}

    confident_total = wrong_confident_total = 0
    print(f"\n{'искажение':24}{'опознано':>12}{'уверенно':>10}"
          f"{'уверенно НЕВЕРНО':>19}{'медианный отрыв':>17}")

    for label, params in PERTURBATIONS:
        right = 0
        confident = 0
        wrong_confident = 0
        current: list[float] = []
        for term in references:
            signal, rate = M.read_wav(resolve(index[term]))
            signal = M.resample(signal, rate)
            distorted = M.perturb(signal, seed=_seed(term), **params)
            found = M.match(M.mfcc(distorted), references)
            ok = found is not None and found.term == term
            right += int(ok)
            if found is not None:
                current.append(found.margin if np.isfinite(found.margin) else 0.0)
                # Уверенность — свойство ВЕРДИКТА, а не его правильности.
                # Складывать их в один счётчик значит сделать долю
                # «верных среди вынесенных» равной 100% по построению.
                if found.confident:
                    confident += 1
                    wrong_confident += int(not ok)
            rows.append({"perturbation": label, "term": term,
                         "recognized": None if found is None else found.term,
                         "correct": ok,
                         "confident": bool(found is not None and found.confident),
                         "margin": None if found is None else (
                             found.margin if np.isfinite(found.margin) else None)})
        totals[label] = right
        margins[label] = current
        confident_total += confident
        wrong_confident_total += wrong_confident
        print(f"  {label:22}{right:>7}/{len(references):<4}{confident:>10}"
              f"{wrong_confident:>19}{statistics.median(current):>17.3f}")

    overall_right = sum(totals.values())
    overall_total = len(PERTURBATIONS) * len(references)
    print(f"\nОпознано верно: {overall_right}/{overall_total} "
          f"({overall_right / overall_total:.1%})")
    print(f"Вердикт вынесен: {confident_total}, "
          f"из них НЕВЕРНЫХ: {wrong_confident_total}"
          + (f" ({wrong_confident_total / confident_total:.1%})"
             if confident_total else ""))
    if wrong_confident_total == 0:
        print("Уверенно неверных вердиктов нет — НА ЭТОМ материале.\n"
              "Обобщать на механизм нельзя: словари разные, "
              "прогоните `--all`.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"words": len(references),
                       "perturbations": [p[0] for p in PERTURBATIONS],
                       "correct": dict(totals),
                       "confident": confident_total,
                       "wrong_confident": wrong_confident_total,
                       "total_per_perturbation": len(references),
                       "rows": rows}, handle, ensure_ascii=False, indent=1)
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
