#!/usr/bin/env python3
"""
Auto-generate IPA transcription drafts for the IT vocabulary corpus.

Pipeline:
  * Read all vocabularies (resources/words/*.json or --dict overrides).
  * For each unique term that does not have an inline `transcription` field
    in its JSON entry, attempt to derive an IPA transcription:
      - single English word → CMUdict (via nltk) → ARPAbet → IPA
      - multi-word / hyphenated → split, transcribe each piece, join
      - all-caps abbreviation (2..6 letters)   → letter-by-letter table
        with primary stress on the last letter, secondary on the first
        (matches the typical English «ay-dee-es-EL» pattern)
      - parenthetical expansion like "BIOS (Basic Input/Output System)"
        → transcribe just the head (BIOS), the expansion is a gloss
  * Write resources/transcriptions.json — { term: "/ɪpɑ/" } — consumed
    by the trainer at runtime.
  * Write tools/transcription_review.csv — term, ipa, method, confidence,
    needs_review, notes — for human review. The CSV is *not* used by the
    trainer; it just tells the reviewer where to focus first.

Quality note. Stress placement uses a single-consonant onset rule, which
is correct for most English words but can misplace the marker in complex
clusters (e.g. "extract" → ɪkstrˈækt instead of ɪkˈstrækt). This is a
draft — manual cleanup of marked rows in the CSV is the intended workflow.

Inline overrides. Any vocabulary entry that already carries a
`"transcription"` field is treated as the authoritative source: the
script does NOT overwrite it, and the runtime prefers it over the global
file. This is how reviewers pin a correct value next to its term.

Usage:
  python tools/generate_transcriptions.py
  python tools/generate_transcriptions.py --force      # regenerate all
  python tools/generate_transcriptions.py --dict resources/words/term_4_unit1_internet.json
  python tools/generate_transcriptions.py --output resources/transcriptions.json

One-time setup:
  pip install nltk
  python -c "import nltk; nltk.download('cmudict')"
"""

from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "resources" / "transcriptions.json"
DEFAULT_REVIEW = ROOT / "tools" / "transcription_review.csv"


# ---------- ARPAbet → IPA (общая американская конвенция) ----------

ARPABET_TO_IPA = {
    "AA": "ɑ",  "AE": "æ",  "AH": "ʌ",   # AH с ударением 0 заменяется на ə
    "AO": "ɔ",  "AW": "aʊ", "AY": "aɪ",
    "B":  "b",  "CH": "tʃ", "D":  "d",   "DH": "ð",
    "EH": "ɛ",  "ER": "ɜr",  # ɝ/ɚ — приближение, ɜr нагляднее
    "EY": "eɪ",
    "F":  "f",  "G":  "ɡ",   "HH": "h",
    "IH": "ɪ",  "IY": "iː",
    "JH": "dʒ", "K":  "k",   "L":  "l",   "M":  "m",
    "N":  "n",  "NG": "ŋ",
    "OW": "oʊ", "OY": "ɔɪ",
    "P":  "p",  "R":  "r",   # допустимое упрощение ɹ→r для читаемости
    "S":  "s",  "SH": "ʃ",
    "T":  "t",  "TH": "θ",
    "UH": "ʊ",  "UW": "uː",
    "V":  "v",  "W":  "w",   "Y":  "j",
    "Z":  "z",  "ZH": "ʒ",
}

VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
          "IH", "IY", "OW", "OY", "UH", "UW"}


# ---------- Letter table для аббревиатур ----------

LETTER_IPA = {
    "A": "eɪ",  "B": "biː", "C": "siː", "D": "diː", "E": "iː",
    "F": "ɛf",  "G": "dʒiː", "H": "eɪtʃ", "I": "aɪ", "J": "dʒeɪ",
    "K": "keɪ", "L": "ɛl",  "M": "ɛm",  "N": "ɛn",  "O": "oʊ",
    "P": "piː", "Q": "kjuː", "R": "ɑr",  "S": "ɛs",  "T": "tiː",
    "U": "juː", "V": "viː", "W": "ˈdʌbəljuː", "X": "ɛks",
    "Y": "waɪ", "Z": "ziː",
}


# Аббревиатуры, которые произносятся как слова, а не побуквенно. CMUdict
# их не содержит, побуквенная форма для них неверна. Считаются «medium
# confidence», т.к. в IT-узусе встречаются варианты (SQL ≈ «sequel» или
# «S-Q-L»). Расширяется по мере вычитки.
KNOWN_WORD_ACRONYMS: dict[str, str] = {
    "CAPTCHA": "ˈkæp.tʃə",
    "WYSIWYG": "ˈwɪz.iː.wɪɡ",
    "BIOS":    "ˈbaɪ.ɒs",
    "GUI":     "ˈɡuː.iː",
    "ASCII":   "ˈæs.kiː",
    "JSON":    "ˈdʒeɪ.sən",
    "JPEG":    "ˈdʒeɪ.pɛɡ",
    "GIF":     "ɡɪf",
    "MIDI":    "ˈmɪd.iː",
    "SQL":     "ˈsiː.kwəl",
}


@dataclass
class Entry:
    """Одна запись в выходных таблицах."""
    term: str
    ipa: str | None = None
    method: str = ""          # cmudict / abbrev / multi / inline / failed
    confidence: str = "low"   # high / medium / low
    needs_review: bool = True
    notes: str = ""


# ---------- ARPAbet → IPA с расстановкой ударения ----------

def _is_vowel(phoneme: str) -> bool:
    return phoneme.rstrip("012") in VOWELS


def _stress_digit(phoneme: str) -> str | None:
    return phoneme[-1] if phoneme[-1].isdigit() else None


def _onset_position(phones: list[str], vowel_idx: int) -> int:
    """
    Позиция, перед которой ставить маркер ударения для гласной phones[vowel_idx].

    Правило одинарного-согласного onset: единственная согласная перед
    гласной идёт в onset слога. Если согласных больше — в начало слова всё,
    в середине только последняя (упрощённое MOP). Это «достаточно правильно»
    для черновика; редактор поправит сложные кластеры (str-, spl-).
    """
    j = vowel_idx
    while j > 0 and not _is_vowel(phones[j - 1]):
        j -= 1
    # Если кластер из ≥2 согласных и до него есть гласная (т.е. это не
    # инициальный кластер слова) — оставляем onset из одной согласной.
    if vowel_idx - j > 1 and j > 0:
        j = vowel_idx - 1
    return j


def arpabet_to_ipa(phones: list[str]) -> str:
    """Перевод последовательности ARPAbet (с цифрами ударения) в IPA-строку."""
    if not phones:
        return ""
    # Где ставить ˈ / ˌ перед какой позицией исходного списка фонем.
    inserts: dict[int, str] = {}
    for i, p in enumerate(phones):
        if not _is_vowel(p):
            continue
        d = _stress_digit(p)
        if d == "1":
            inserts[_onset_position(phones, i)] = "ˈ"
        elif d == "2":
            inserts[_onset_position(phones, i)] = "ˌ"

    out: list[str] = []
    for i, p in enumerate(phones):
        if i in inserts:
            out.append(inserts[i])
        clean = p.rstrip("012")
        if clean == "AH" and _stress_digit(p) == "0":
            out.append("ə")   # ударение 0 у AH — это шва
        elif clean == "ER" and _stress_digit(p) == "0":
            out.append("ər")
        else:
            out.append(ARPABET_TO_IPA.get(clean, clean.lower()))
    return "".join(out)


# ---------- Классификация и транскрибирование терминов ----------

# Скобочное расширение вида «BIOS (Basic Input/Output System)» — это
# глосса, головной токен (BIOS) важен; в скобках — расшифровка.
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")


def _strip_parens(term: str) -> str:
    return _PAREN_RE.sub("", term).strip()


def _split_words(term: str) -> list[str]:
    """Разбить multiword/дефисное на отдельные «слова»."""
    return [w for w in re.split(r"[\s\-/]+", term) if w]


def _is_abbrev(token: str) -> bool:
    """Похоже ли на аббревиатуру: все буквы заглавные, длина 2..8."""
    if not token or not (2 <= len(token) <= 8):
        return False
    return token.isupper() and token.isalpha()


def _abbrev_to_ipa(token: str) -> str:
    """
    Побуквенное произнесение аббревиатуры. Первая буква — secondary
    stress, последняя — primary; на средние — без маркера. Совпадает с
    типичным английским «ay-dee-es-EL» для ADSL.
    """
    letters = list(token)
    parts = []
    for i, ch in enumerate(letters):
        ipa = LETTER_IPA.get(ch.upper())
        if ipa is None:
            return ""  # неподдерживаемый символ
        if i == 0 and len(letters) > 1:
            parts.append("ˌ" + ipa)
        elif i == len(letters) - 1 and len(letters) > 1:
            parts.append("ˈ" + ipa)
        else:
            parts.append(ipa)
    return " ".join(parts)


def transcribe_word(word: str, cmu) -> tuple[str | None, str]:
    """
    Транскрипция одного «слова» (без пробелов и дефисов).
    Возвращает (ipa | None, method).
    """
    key = word.lower()
    pron = cmu.get(key)
    if pron:
        # CMUdict часто даёт несколько вариантов произношения; берём первый.
        return arpabet_to_ipa(pron[0]), "cmudict"
    return None, "missing"


def transcribe_term(term: str, cmu) -> Entry:
    """
    Транскрипция произвольного термина. Возвращает Entry со всеми полями,
    в т.ч. method/confidence/notes для CSV.
    """
    head = _strip_parens(term)
    notes_parts: list[str] = []
    if head != term:
        notes_parts.append("отсечена скобочная расшифровка")

    if not head:
        return Entry(term=term, method="failed",
                     confidence="low", notes="пустой head")

    # Случай: целая аббревиатура (одно слово целиком из заглавных).
    if _is_abbrev(head):
        # Сначала — словесные акронимы (CAPTCHA, WYSIWYG): они произносятся
        # как слово, побуквенная форма для них неверна.
        if head in KNOWN_WORD_ACRONYMS:
            return Entry(
                term=term, ipa=f"/{KNOWN_WORD_ACRONYMS[head]}/",
                method="word-acronym", confidence="medium",
                needs_review=True,
                notes="; ".join(notes_parts +
                                ["словесный акроним; вариант из таблицы — "
                                 "проверить локальный узус"]),
            )
        ipa = _abbrev_to_ipa(head)
        if ipa:
            return Entry(
                term=term, ipa=f"/{ipa}/", method="abbrev",
                confidence="medium",
                needs_review=True,  # CAPTCHA/BIOS/SQL читаются как слова
                notes="; ".join(notes_parts +
                                ["проверить: может произноситься как слово, "
                                 "а не побуквенно"]),
            )

    pieces = _split_words(head)
    if not pieces:
        return Entry(term=term, method="failed",
                     confidence="low", notes="не удалось разбить на слова")

    # Транскрибируем каждую часть; смешанные стратегии (слово + аббревиатура)
    out_parts: list[str] = []
    methods: list[str] = []
    missing: list[str] = []
    for piece in pieces:
        if _is_abbrev(piece):
            if piece in KNOWN_WORD_ACRONYMS:
                out_parts.append(KNOWN_WORD_ACRONYMS[piece])
                methods.append("word-acronym")
                continue
            ipa = _abbrev_to_ipa(piece)
            if ipa:
                out_parts.append(ipa)
                methods.append("abbrev")
                continue
        ipa, m = transcribe_word(piece, cmu)
        if ipa is not None:
            out_parts.append(ipa)
            methods.append(m)
        else:
            missing.append(piece)
            out_parts.append(f"<{piece}>")  # placeholder для черновика
            methods.append("missing")

    method = "multi" if len(pieces) > 1 else methods[0]
    # Confidence: high если всё нашлось в CMUdict; medium если есть abbrev;
    # low если есть missing.
    if missing:
        confidence = "low"
        needs_review = True
        notes_parts.append(f"не нашли в CMUdict: {', '.join(missing)}")
    elif "abbrev" in methods:
        confidence = "medium"
        needs_review = True
        notes_parts.append("в составе есть аббревиатура")
    else:
        confidence = "high"
        needs_review = False

    ipa_str = " ".join(out_parts)
    return Entry(
        term=term, ipa=f"/{ipa_str}/", method=method,
        confidence=confidence, needs_review=needs_review,
        notes="; ".join(notes_parts),
    )


# ---------- Сбор терминов из словарей ----------

def collect_terms(paths: list[Path]) -> dict[str, str | None]:
    """
    Пройти по vocab-словарям, собрать {term: inline_transcription}.
    inline_transcription = None если поле отсутствует.

    Файлы предложений (sentences) пропускаются: у них нет терминов.
    """
    out: dict[str, str | None] = {}
    for p in paths:
        try:
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[skip] {p}: {e}", file=sys.stderr)
            continue

        def _add(term: str, trans: str | None) -> None:
            if not isinstance(term, str) or not term:
                return
            # Inline побеждает: если у нас уже есть значение из другого
            # файла, не перетираем непустым None.
            prev = out.get(term)
            if trans:
                out[term] = trans
            elif prev is None and term not in out:
                out[term] = None

        if isinstance(data, dict):
            if "vocabulary" in data and isinstance(data["vocabulary"], list):
                for e in data["vocabulary"]:
                    if isinstance(e, dict):
                        _add(e.get("term", ""), e.get("transcription"))
            elif "units" in data and isinstance(data["units"], list):
                for unit in data["units"]:
                    if isinstance(unit, dict):
                        for e in unit.get("vocabulary", []) or []:
                            if isinstance(e, dict):
                                _add(e.get("term", ""),
                                     e.get("transcription"))
            else:
                # старый плоский формат {word: translation} — без транскрипций
                for k, v in data.items():
                    if isinstance(v, str):
                        _add(k, None)
        elif isinstance(data, list):
            # Старые форматы или sentences. Игнорируем sentences (есть template).
            if data and isinstance(data[0], dict) and "template" in data[0]:
                continue
            for e in data:
                if isinstance(e, dict) and "section" in e:
                    for k, v in e.get("section", {}).items():
                        if isinstance(v, str):
                            _add(k, None)
    return out


# ---------- Запись результатов ----------

def write_transcriptions(entries: list[Entry], path: Path) -> None:
    """
    Карта термин → IPA для рантайма. Записи с placeholder-ом «<word>»
    (т.е. с непереведённым куском) пропускаются — иначе пользователь
    увидел бы в фидбэке /<crawler>/, что хуже, чем ничего.
    """
    out: dict[str, str] = {
        e.term: e.ipa for e in entries
        if e.ipa and "<" not in e.ipa
    }
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def write_review(entries: list[Entry], path: Path) -> None:
    """Side-file для ручной вычитки."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["term", "ipa", "method", "confidence",
                    "needs_review", "notes"])
        # Сортируем «требующие внимания» в начало
        ordered = sorted(
            entries,
            key=lambda e: (
                not e.needs_review, e.confidence != "low",
                e.confidence != "medium", e.term.lower(),
            ),
        )
        for e in ordered:
            w.writerow([
                e.term, e.ipa or "", e.method, e.confidence,
                "yes" if e.needs_review else "no", e.notes,
            ])


# ---------- CLI ----------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Сгенерировать черновик IPA-транскрипций для словаря.",
    )
    p.add_argument("--dict", dest="dicts", type=Path, action="append",
                   default=None,
                   help="Конкретный JSON-словарь. Можно несколько раз. "
                        "По умолчанию — все resources/words/*.json.")
    p.add_argument("--output", type=Path, default=DEFAULT_OUT,
                   help="Куда писать карту term→IPA для рантайма.")
    p.add_argument("--review", type=Path, default=DEFAULT_REVIEW,
                   help="Куда писать CSV для ручной вычитки.")
    p.add_argument("--force", action="store_true",
                   help="Перегенерировать даже те термины, для которых уже "
                        "есть IPA в --output (по умолчанию они переносятся "
                        "как есть и помечаются method=cached).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        import nltk
        from nltk.corpus import cmudict
        cmu = cmudict.dict()
    except Exception as e:
        print("Не удалось загрузить CMUdict через nltk.\n"
              "Установка:  pip install nltk\n"
              "Загрузка:   python -c \"import nltk; nltk.download('cmudict')\"\n"
              f"Ошибка: {e}", file=sys.stderr)
        return 2

    if args.dicts:
        paths = list(args.dicts)
    else:
        paths = sorted((ROOT / "resources" / "words").glob("*.json"))

    inline = collect_terms(paths)
    print(f"Терминов всего: {len(inline)}")
    print(f"  с inline-транскрипцией в JSON: "
          f"{sum(1 for v in inline.values() if v)}")

    # Существующий выход — для re-use без --force.
    existing: dict[str, str] = {}
    if args.output.exists() and not args.force:
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    entries: list[Entry] = []
    for term, inline_ipa in sorted(inline.items()):
        if inline_ipa:
            entries.append(Entry(
                term=term, ipa=inline_ipa, method="inline",
                confidence="high", needs_review=False,
                notes="закреплено вручную в vocab JSON",
            ))
            continue
        if not args.force and term in existing:
            entries.append(Entry(
                term=term, ipa=existing[term], method="cached",
                confidence="medium", needs_review=False,
                notes="перенесено из предыдущей генерации; "
                      "запустите с --force, чтобы перегенерировать",
            ))
            continue
        entries.append(transcribe_term(term, cmu))

    # Сводка
    from collections import Counter
    methods = Counter(e.method for e in entries)
    confs = Counter(e.confidence for e in entries)
    needs = sum(1 for e in entries if e.needs_review)
    print("По методам:", dict(methods))
    print("По уверенности:", dict(confs))
    print(f"Требуют вычитки: {needs}")

    write_transcriptions(entries, args.output)
    write_review(entries, args.review)
    written = sum(1 for e in entries if e.ipa and "<" not in e.ipa)
    print(f"\n→ {args.output}  ({written} строк, "
          f"{len(entries) - written} пропущено с placeholder-ом)")
    print(f"→ {args.review}  (все {len(entries)} записей)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
