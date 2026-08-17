#!/usr/bin/env python3
"""
Pre-render pronunciation audio for the IT vocabulary corpus (build-time).

Walks all vocab JSONs, synthesises one WAV per unique term via a TTS backend
(default espeak-ng, fully offline), downsamples to a compact mono rate, and
writes them to resources/audio/ together with an index.json manifest that
maps term → relative wav filename. The trainer reads only the manifest +
WAV files at runtime; it never touches the TTS engine.

Pronunciation text. The literal term is not always what should be spoken:
  * parenthetical glosses are stripped: "BIOS (Basic ...)" → "BIOS"
  * "/" becomes a space so "TCP/IP" is spelled out, not read as "slash"
  * an inline "speak_as" field in the vocab entry overrides everything
  * a small SPEAK_AS_OVERRIDES table fixes known offenders (DDoS, SQL...)

Filenames. Terms contain "/", spaces and parentheses, so files are named by
a short stable hash of the term; the manifest keeps the human mapping.

Usage:
  python tools/generate_audio.py                     # all dicts, espeak
  python tools/generate_audio.py --rate 16000        # target sample rate
  python tools/generate_audio.py --backend espeak --force
  python tools/generate_audio.py --dict resources/words/term_4_unit1_internet.json

Setup (espeak):  apt-get install espeak-ng
"""

from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from tts_backends import make_backend, TTSBackendError  # noqa: E402

DEFAULT_AUDIO_DIR = ROOT / "resources" / "audio"


# Аббревиатуры/термины, которые espeak произносит неверно, если подать как
# есть. Значение — то, что реально надо «сказать». Расширяется по мере нужды.
SPEAK_AS_OVERRIDES: dict[str, str] = {
    "DDoS attack": "dee dos attack",
    "DDoS attack (Distributed Denial of Service)": "dee dos attack",
    "DoS attack": "doss attack",
    "SQL": "sequel",
    "GIF": "gif",
    "GUI": "gooey",
    "JSON": "jason",
    "WYSIWYG": "wizzywig",
    "SQLite": "sequel light",
    "NoSQL": "no sequel",
}


_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")


def speak_text(term: str, inline_speak_as: str | None) -> str:
    """
    Во что превратить термин перед подачей в TTS.
    Приоритет: inline speak_as → таблица overrides → нормализация термина.
    """
    if inline_speak_as:
        return inline_speak_as
    if term in SPEAK_AS_OVERRIDES:
        return SPEAK_AS_OVERRIDES[term]
    text = _PAREN_RE.sub(" ", term)        # убрать скобочную расшифровку
    text = text.replace("/", " ")          # слэш → пауза, а не «slash»
    text = re.sub(r"\s+", " ", text).strip()
    return text or term


def term_filename(term: str) -> str:
    """Стабильное имя файла из хэша термина (термины содержат / и пробелы)."""
    h = hashlib.sha1(term.encode("utf-8")).hexdigest()[:16]
    return f"{h}.wav"


def downsample_wav(path: Path, target_rate: int, trim: bool = True) -> None:
    """
    Пост-обработка WAV на месте: привести к mono, обрезать тишину в начале
    и конце (espeak добавляет заметные паузы), понизить частоту до
    target_rate. Используется stdlib audioop — это build-time скрипт.
    Если audioop недоступен (Python 3.13+) — тихо пропускаем.
    """
    try:
        import audioop  # noqa: PLC0415  (deprecated в 3.13, но это dev-tool)
    except Exception:
        return
    try:
        with wave.open(str(path), "rb") as r:
            frames = r.readframes(r.getnframes())
            sampwidth, nchannels, rate = (
                r.getsampwidth(), r.getnchannels(), r.getframerate()
            )
        if nchannels > 1:
            frames = audioop.tomono(frames, sampwidth, 0.5, 0.5)
            nchannels = 1
        if trim:
            frames = _trim_silence(frames, sampwidth, rate)
        if rate > target_rate:
            frames, _ = audioop.ratecv(
                frames, sampwidth, nchannels, rate, target_rate, None
            )
            rate = target_rate
        with wave.open(str(path), "wb") as w:
            w.setnchannels(nchannels)
            w.setsampwidth(sampwidth)
            w.setframerate(rate)
            w.writeframes(frames)
    except Exception as e:
        print(f"  [warn] postprocess {path.name}: {e}", file=sys.stderr)


def _trim_silence(frames: bytes, sampwidth: int, rate: int,
                  threshold: int = 350, pad_ms: int = 40) -> bytes:
    """
    Обрезать тихие участки в начале/конце по порогу амплитуды, оставив
    небольшой отступ pad_ms, чтобы слово не «щёлкало». Работает на 16-бит
    PCM (то, что выдаёт espeak). При иной разрядности — возвращает как есть.
    """
    if sampwidth != 2:
        return frames
    import struct
    n = len(frames) // 2
    if n == 0:
        return frames
    samples = struct.unpack(f"<{n}h", frames)
    lo = 0
    while lo < n and abs(samples[lo]) < threshold:
        lo += 1
    hi = n
    while hi > lo and abs(samples[hi - 1]) < threshold:
        hi -= 1
    if lo >= hi:
        return frames  # всё ниже порога — не трогаем
    pad = int(rate * pad_ms / 1000)
    lo = max(0, lo - pad)
    hi = min(n, hi + pad)
    return frames[lo * 2:hi * 2]


# ---------- Сбор терминов (term → inline speak_as) ----------

def collect_terms(paths: list[Path]) -> dict[str, str | None]:
    """{term: inline_speak_as|None} по всем словарям. Sentences пропускаются."""
    out: dict[str, str | None] = {}

    def _add(term, speak_as):
        if isinstance(term, str) and term:
            if speak_as or term not in out:
                out[term] = speak_as if isinstance(speak_as, str) else out.get(term)

    for p in paths:
        try:
            with p.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[skip] {p}: {e}", file=sys.stderr)
            continue

        def _walk_vocab(vocab):
            for e in vocab or []:
                if isinstance(e, dict) and "term" in e:
                    _add(e.get("term"), e.get("speak_as"))

        if isinstance(data, dict):
            if isinstance(data.get("vocabulary"), list):
                _walk_vocab(data["vocabulary"])
            elif isinstance(data.get("units"), list):
                for unit in data["units"]:
                    if isinstance(unit, dict):
                        _walk_vocab(unit.get("vocabulary"))
            else:
                for k, v in data.items():       # старый плоский формат
                    if isinstance(v, str):
                        _add(k, None)
        elif isinstance(data, list):
            if data and isinstance(data[0], dict) and "template" in data[0]:
                continue                         # sentences — без терминов
            for e in data:
                if isinstance(e, dict) and "section" in e:
                    for k, v in e["section"].items():
                        if isinstance(v, str):
                            _add(k, None)
    return out


# ---------- CLI ----------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Пре-рендер аудио произношения терминов (build-time).")
    p.add_argument("--dict", dest="dicts", type=Path, action="append",
                   default=None, help="Конкретный словарь (можно несколько). "
                   "По умолчанию — все resources/words/*.json.")
    p.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR,
                   help="Каталог для WAV и index.json.")
    p.add_argument("--backend", default="espeak",
                   help="TTS-бэкенд: espeak | piper | online.")
    p.add_argument("--rate", type=int, default=11025,
                   help="Целевая частота дискретизации (Гц). По умолчанию 11025.")
    p.add_argument("--force", action="store_true",
                   help="Перегенерировать даже существующие файлы.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        backend = make_backend(args.backend)
    except TTSBackendError as e:
        print(e, file=sys.stderr)
        return 2
    if not backend.is_available():
        print(f"Бэкенд {args.backend!r} недоступен в этом окружении.\n"
              "espeak:  apt-get install espeak-ng", file=sys.stderr)
        return 2

    paths = args.dicts or sorted((ROOT / "resources" / "words").glob("*.json"))
    terms = collect_terms(paths)
    print(f"Терминов: {len(terms)} | бэкенд: {backend.name} | "
          f"частота: {args.rate}Hz | каталог: {args.audio_dir}")

    args.audio_dir.mkdir(parents=True, exist_ok=True)
    index_path = args.audio_dir / "index.json"
    index: dict[str, str] = {}
    if index_path.exists() and not args.force:
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}

    made, reused, failed = 0, 0, 0
    total_bytes = 0
    for term, inline in sorted(terms.items()):
        fname = term_filename(term)
        out = args.audio_dir / fname
        if out.exists() and not args.force:
            index[term] = fname
            reused += 1
            total_bytes += out.stat().st_size
            continue
        spoken = speak_text(term, inline)
        try:
            backend.synth(spoken, out)
            downsample_wav(out, args.rate)
            index[term] = fname
            made += 1
            total_bytes += out.stat().st_size
        except TTSBackendError as e:
            print(f"  [fail] {term!r}: {e}", file=sys.stderr)
            failed += 1

    # Манифест: только реально существующие файлы, отсортированы для стабильного diff
    index = {t: f for t, f in sorted(index.items())
             if (args.audio_dir / f).exists()}
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    mb = total_bytes / (1024 * 1024)
    print(f"\nСоздано: {made} | переиспользовано: {reused} | "
          f"ошибок: {failed}")
    print(f"Всего в манифесте: {len(index)} | объём аудио: {mb:.1f} МБ")
    print(f"→ {index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
