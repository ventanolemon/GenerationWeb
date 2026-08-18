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
По одному ряду на словарь: сколько уверенных вердиктов вынесено и
сколько из них НЕВЕРНЫХ. Словари упорядочены по средней длине термина —
именно она объясняет разброс, и порядок делает это видимым без слов.
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
    """(имя, слов, средняя длина, уверенных, из них неверных) по словарям."""
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

    _label, params = PERTURBATIONS[-1]
    rows = []
    for stem, pool in _all_dictionaries():
        if len(pool) < neighbours:
            continue
        generator = random.Random(zlib.crc32(stem.encode("utf-8")))
        confident = wrong = 0
        length = 0.0
        for _ in range(samples):
            target = generator.choice(pool)
            others = [t for t in pool if t != target]
            generator.shuffle(others)
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
        rows.append((stem, len(pool), length / samples, confident, wrong))
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows


def render(rows: list[tuple], neighbours: int, samples: int) -> str:
    top = 96
    height = top + ROW * len(rows) + 56
    peak = max((row[3] for row in rows), default=1) or 1
    scale = BAR / peak

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}"'
        f' width="{WIDTH}" height="{height}"'
        ' font-family="DejaVu Sans, Arial, sans-serif" font-size="13">',
        f'<rect width="{WIDTH}" height="{height}" fill="#ffffff"/>',
        f'<text x="24" y="30" font-size="15" font-weight="bold" fill="{INK}">'
        'Уверенно неверные вердикты по словарям поставки</text>',
        f'<text x="24" y="50" font-size="12" fill="{MUTED}">'
        f'окрестность {neighbours} слов, искажение «темп ×1,15 + шум 8%», '
        f'{samples} проб на словарь; словари по убыванию длины термина</text>',
        f'<rect x="{LEFT}" y="64" width="12" height="12" fill="{RIGHT_COLOR}"/>',
        f'<text x="{LEFT + 18}" y="74" font-size="12" fill="{MUTED}">'
        'вердикт вынесен и верен</text>',
        f'<rect x="{LEFT + 190}" y="64" width="12" height="12" fill="{WRONG_COLOR}"/>',
        f'<text x="{LEFT + 208}" y="74" font-size="12" fill="{MUTED}">'
        'вердикт вынесен и НЕВЕРЕН</text>',
    ]

    for i, (stem, size, length, confident, wrong) in enumerate(rows):
        y = top + ROW * i
        right = confident - wrong
        out.append(f'<line x1="{LEFT}" y1="{y + 18}" x2="{WIDTH - 24}" '
                   f'y2="{y + 18}" stroke="{RULE}" stroke-width="1"/>')
        out.append(f'<text x="24" y="{y + 14}" font-size="12" fill="{INK}">'
                   f'{stem[:30]}</text>')
        out.append(f'<text x="{LEFT - 12}" y="{y + 14}" font-size="11" '
                   f'fill="{MUTED}" text-anchor="end">{length:.1f} сл.</text>')
        if right:
            out.append(f'<rect x="{LEFT}" y="{y + 3}" width="{right * scale:.1f}"'
                       f' height="13" fill="{RIGHT_COLOR}"/>')
        if wrong:
            out.append(f'<rect x="{LEFT + right * scale:.1f}" y="{y + 3}" '
                       f'width="{wrong * scale:.1f}" height="13" '
                       f'fill="{WRONG_COLOR}"/>')
        if wrong:
            out.append(f'<text x="{LEFT + confident * scale + 8:.1f}" '
                       f'y="{y + 14}" font-size="11" fill="{WRONG_COLOR}" '
                       f'font-weight="bold">{wrong} из {confident}</text>')
        else:
            out.append(f'<text x="{LEFT + confident * scale + 8:.1f}" '
                       f'y="{y + 14}" font-size="11" fill="{MUTED}">'
                       f'0 из {confident}</text>')

    total = sum(row[3] for row in rows)
    bad = sum(row[4] for row in rows)
    clean = sum(1 for row in rows if row[4] == 0)
    out.append(f'<text x="24" y="{height - 26}" font-size="12" fill="{INK}">'
               f'Всего вердиктов вынесено {total}, из них неверных '
               f'<tspan font-weight="bold" fill="{WRONG_COLOR}">{bad}</tspan>'
               f' ({100 * bad / max(1, total):.0f}%). '
               f'Словарей без неверных вердиктов: {clean} из {len(rows)}.</text>')
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
    bad = sum(row[4] for row in rows)
    total = sum(row[3] for row in rows)
    print(f"{target}: {len(rows)} словарей, {total} вердиктов, {bad} неверных")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
