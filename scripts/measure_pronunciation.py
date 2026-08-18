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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--words", type=int, default=20,
                        help="сколько слов словаря брать")
    parser.add_argument("--json", help="куда сложить результат")
    args = parser.parse_args()

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

    for label, params in PERTURBATIONS:
        right = 0
        confident = 0
        current: list[float] = []
        for term in references:
            signal, rate = M.read_wav(resolve(index[term]))
            signal = M.resample(signal, rate)
            distorted = M.perturb(signal, seed=abs(hash(term)) % 10_000,
                                  **params)
            found = M.match(M.mfcc(distorted), references)
            ok = found is not None and found.term == term
            right += int(ok)
            if found is not None:
                current.append(found.margin if np.isfinite(found.margin) else 0.0)
                confident += int(ok and found.confident)
            rows.append({"perturbation": label, "term": term,
                         "recognized": None if found is None else found.term,
                         "correct": ok,
                         "margin": None if found is None else (
                             found.margin if np.isfinite(found.margin) else None)})
        totals[label] = right
        margins[label] = current
        share = right / len(references)
        conf_share = confident / len(references)
        print(f"  {label:22} опознано {right:3}/{len(references)} "
              f"({share:5.1%})   уверенно {conf_share:5.1%}   "
              f"медианный отрыв {statistics.median(current):.3f}")

    overall_right = sum(totals.values())
    overall_total = len(PERTURBATIONS) * len(references)
    print(f"\nИТОГО: {overall_right}/{overall_total} "
          f"({overall_right / overall_total:.1%})")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"words": len(references),
                       "perturbations": [p[0] for p in PERTURBATIONS],
                       "correct": dict(totals),
                       "total_per_perturbation": len(references),
                       "rows": rows}, handle, ensure_ascii=False, indent=1)
        print(f"JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
