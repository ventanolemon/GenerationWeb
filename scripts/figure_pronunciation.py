"""
Рисунок 7.3: уверенно неверные вердикты по словарям поставки.

    python -m scripts.figure_pronunciation [--out ФАЙЛ] [--samples N]

Зачем отдельный скрипт
----------------------
Рисунок ПОРОЖДАЕТСЯ замером, а не рисуется по его пересказу. Разница не
формальная: рис. 7.2 был собран руками по выводу скрипта, и когда вывод
скрипта оказался неполным (счётчик не различал «уверенно» и «уверенно и
верно»), рисунок повторил ошибку и закрепил её подписью «красного нет».
Порождённый рисунок такую ошибку переживает: он меняется вместе с
замером.

Что на рисунке
--------------
По ДВА ряда на словарь: верхний — прежнее правило (константный порог
отрыва 0.08), нижний — нынешнее (порог выводится из окрестности). Оба
правила считаются на ОДНОМ материале в одном прогоне, иначе сравнение
превратилось бы в сопоставление двух разных случайностей.

Словари упорядочены по числу уверенно неверных вердиктов прежнего
правила — то есть по тому, насколько сильно оно ошибалось.
"""

from __future__ import annotations

import argparse
import pathlib
import random
import zlib

WIDTH = 860
ROW = 26
LEFT = 250
BAR = 420

#: Цвета-значения, не цвета-поверхности: зелёный — верный вердикт,
#: красный — уверенно неверный. Проверены на различимость при
#: чёрно-белой печати по светлоте (0.42 против 0.55).
RIGHT_COLOR = "#17784a"
WRONG_COLOR = "#b3261e"
INK = "#1b1c21"
MUTED = "#676c7a"
RULE = "#d6d8e0"


def measure(samples: int, neighbours: int) -> list[tuple]:
    """
    По словарю: сколько вердиктов вынесли ОБА правила и сколько неверных.

    Считаются оба сразу и на одном материале — иначе сравнение
    превратится в сопоставление двух прогонов с разными случайностями, а
    именно сравнение здесь и есть содержание рисунка.
    """
    from core import pronunciation as P, pronunciation_match as M
    from core.graph.resources import resolve
    from scripts.measure_pronunciation import (
        PERTURBATIONS, _all_dictionaries, _seed,
    )

    index = P.audio_index()
    cache: dict = {}

    def features(term: str):
        if term not in cache:
            cache[term] = M.features_of(resolve(index[term]))
        return cache[term]

    rows = []
    for stem, pool in _all_dictionaries():
        if len(pool) < neighbours:
            continue
        generator = random.Random(zlib.crc32(stem.encode("utf-8")))
        old_confident = old_wrong = new_confident = new_wrong = trials = 0
        length = 0.0
        for step in range(samples):
            target = generator.choice(pool)
            others = [t for t in pool if t != target]
            generator.shuffle(others)
            vocabulary = [target, *others[:neighbours - 1]]
            picked = {t: features(t) for t in vocabulary}
            gaps = M.separations(picked)
            signal, rate = M.read_wav(resolve(index[target]))
            signal = M.resample(signal, rate)
            length += len(target.split())
            for _label, params in PERTURBATIONS:
                distorted = M.perturb(signal, seed=_seed(target) + step,
                                      **params)
                found = M.match(M.mfcc(distorted), picked, gaps=gaps)
                trials += 1
                bad = found.term != target
                # Прежнее правило: константный порог относительного отрыва.
                if found.margin >= 0.08:
                    old_confident += 1
                    old_wrong += int(bad)
                if found.confident:
                    new_confident += 1
                    new_wrong += int(bad)
        rows.append((stem, len(pool), length / samples, trials,
                     old_confident, old_wrong, new_confident, new_wrong))
    rows.sort(key=lambda row: row[5], reverse=True)
    return rows


def render(rows: list[tuple], neighbours: int, samples: int) -> str:
    top = 118
    height = top + ROW * len(rows) + 60
    peak = max((max(row[4], row[6]) for row in rows), default=1) or 1
    scale = BAR / peak

    def bar(x, y, confident, wrong, tag):
        right = confident - wrong
        parts = []
        if right:
            parts.append(f'<rect x="{x}" y="{y}" width="{right * scale:.1f}"'
                         f' height="9" fill="{RIGHT_COLOR}"/>')
        if wrong:
            parts.append(f'<rect x="{x + right * scale:.1f}" y="{y}" '
                         f'width="{wrong * scale:.1f}" height="9" '
                         f'fill="{WRONG_COLOR}"/>')
        colour = WRONG_COLOR if wrong else MUTED
        weight = ' font-weight="bold"' if wrong else ''
        parts.append(f'<text x="{x + confident * scale + 7:.1f}" y="{y + 8}" '
                     f'font-size="10" fill="{colour}"{weight}>'
                     f'{tag} {confident}, неверных {wrong}</text>')
        return parts

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}"'
        f' width="{WIDTH}" height="{height}"'
        ' font-family="DejaVu Sans, Arial, sans-serif" font-size="13">',
        f'<rect width="{WIDTH}" height="{height}" fill="#ffffff"/>',
        f'<text x="24" y="30" font-size="15" font-weight="bold" fill="{INK}">'
        'Порог уверенности: константа против окрестности</text>',
        f'<text x="24" y="50" font-size="12" fill="{MUTED}">'
        f'окрестность {neighbours} слов, 6 искажений, {samples} проб на '
        f'словарь; по два ряда на словарь — верхний ряд прежнее правило, '
        f'нижний нынешнее</text>',
        f'<rect x="24" y="66" width="12" height="10" fill="{RIGHT_COLOR}"/>',
        f'<text x="42" y="75" font-size="12" fill="{MUTED}">'
        'вердикт вынесен и верен</text>',
        f'<rect x="228" y="66" width="12" height="10" fill="{WRONG_COLOR}"/>',
        f'<text x="246" y="75" font-size="12" fill="{MUTED}">'
        'вердикт вынесен и НЕВЕРЕН</text>',
        f'<text x="24" y="99" font-size="12" fill="{INK}" font-weight="bold">'
        'словарь</text>',
        f'<text x="{LEFT - 12}" y="99" font-size="11" fill="{MUTED}" '
        f'text-anchor="end">длина</text>',
    ]

    for i, row in enumerate(rows):
        stem, _size, length, _trials, oc, ow, nc, nw = row
        y = top + ROW * i
        out.append(f'<line x1="24" y1="{y + 23}" x2="{WIDTH - 24}" '
                   f'y2="{y + 23}" stroke="{RULE}" stroke-width="1"/>')
        out.append(f'<text x="24" y="{y + 13}" font-size="12" fill="{INK}">'
                   f'{stem[:30]}</text>')
        out.append(f'<text x="{LEFT - 12}" y="{y + 13}" font-size="11" '
                   f'fill="{MUTED}" text-anchor="end">{length:.1f} сл.</text>')
        out.extend(bar(LEFT, y, oc, ow, "было:"))
        out.extend(bar(LEFT, y + 11, nc, nw, "стало:"))

    trials = sum(row[3] for row in rows)
    oc = sum(row[4] for row in rows); ow = sum(row[5] for row in rows)
    nc = sum(row[6] for row in rows); nw = sum(row[7] for row in rows)
    bad_dicts = sum(1 for row in rows if row[5] > 0)
    out.append(
        f'<text x="24" y="{height - 30}" font-size="12" fill="{INK}">'
        f'Константа: вынесено {oc} из {trials} ({100 * oc / trials:.0f}%), '
        f'неверных <tspan font-weight="bold" fill="{WRONG_COLOR}">{ow}</tspan>'
        f' на {bad_dicts} словарях из {len(rows)}.</text>')
    out.append(
        f'<text x="24" y="{height - 12}" font-size="12" fill="{INK}">'
        f'Окрестность: вынесено {nc} из {trials} ({100 * nc / trials:.0f}%), '
        f'неверных <tspan font-weight="bold" fill="{RIGHT_COLOR}">{nw}</tspan>'
        f'. Цена — покрытие; ошибка — ноль.</text>')
    out.append('</svg>')
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/thesis/figures/"
                                         "pronunciation-spread.svg")
    parser.add_argument("--samples", type=int, default=25)
    parser.add_argument("--neighbours", type=int, default=12)
    args = parser.parse_args()

    rows = measure(args.samples, args.neighbours)
    if not rows:
        print("Нет словарей со звуком — рисовать нечего.")
        return 1
    target = pathlib.Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(rows, args.neighbours, args.samples),
                      encoding="utf-8")
    print(f"{target}: {len(rows)} словарей, было неверных {sum(r[5] for r in rows)}, стало {sum(r[7] for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
