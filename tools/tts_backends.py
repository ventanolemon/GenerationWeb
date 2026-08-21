"""
TTS-бэкенды для пре-рендера произношения терминов (build-time).

Этот модуль используется ТОЛЬКО скриптом tools/generate_audio.py при сборке
аудио. Рантайм приложения его не импортирует: тренажёр проигрывает уже
готовые WAV-файлы и о TTS-движке ничего не знает.

Архитектура — сменный бэкенд за общим интерфейсом TTSBackend, чтобы выбор
движка (espeak-ng сейчас, piper/онлайн позже) не затрагивал ни скрипт
генерации, ни рантайм. Добавить движок = реализовать synth() в новом
классе и зарегистрировать его в BACKENDS.

Сейчас реализован EspeakBackend (FOSS, offline). Заготовки PiperBackend и
OnlineBackend намеренно поднимают NotImplementedError с инструкцией — это
точки расширения, а не мёртвый код.
"""

from __future__ import annotations
import shutil
import subprocess
import wave
from abc import ABC, abstractmethod
from pathlib import Path


class TTSBackendError(RuntimeError):
    """Бэкенд недоступен или синтез не удался."""


class TTSBackend(ABC):
    """
    Контракт TTS-движка. Один метод synth(text) → WAV-файл на диске.

    Реализации обязаны писать mono PCM WAV (любая частота — скрипт сам
    приведёт к целевой). Формат WAV выбран намеренно: QMediaPlayer
    проигрывает его без системных кодеков, в отличие от mp3/ogg.
    """

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Готов ли движок к работе (есть бинарник/модель/ключ)."""

    @abstractmethod
    def synth(self, text: str, out_path: Path) -> None:
        """Синтезировать text в WAV-файл out_path. Бросает при ошибке."""


class EspeakBackend(TTSBackend):
    """
    espeak-ng — лёгкий FOSS-синтезатор, работает полностью offline.
    Качество роботизированное, но разборчивое; нулевая настройка.

    Установка (Debian/Ubuntu):  apt-get install espeak-ng
    """

    name = "espeak"

    def __init__(self, voice: str = "en-us", speed: int = 150,
                 pitch: int = 50):
        self.voice = voice
        self.speed = speed      # слов в минуту; 150 — спокойный темп
        self.pitch = pitch
        self._bin = shutil.which("espeak-ng") or shutil.which("espeak")

    def is_available(self) -> bool:
        return self._bin is not None

    def synth(self, text: str, out_path: Path) -> None:
        if self._bin is None:
            raise TTSBackendError(
                "espeak-ng не найден в PATH. Установите: apt-get install espeak-ng"
            )
        cmd = [
            self._bin, "-v", self.voice,
            "-s", str(self.speed), "-p", str(self.pitch),
            "-w", str(out_path), text,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise TTSBackendError(f"espeak-ng не справился с {text!r}: {e}") from e
        # Санити-проверка: WAV должен открыться и быть непустым
        try:
            with wave.open(str(out_path), "rb") as w:
                if w.getnframes() == 0:
                    raise TTSBackendError(f"espeak-ng выдал пустой WAV для {text!r}")
        except wave.Error as e:
            raise TTSBackendError(f"espeak-ng выдал битый WAV для {text!r}: {e}") from e


class PiperBackend(TTSBackend):
    """
    Заготовка под piper (нейросетевой offline TTS, заметно живее espeak).

    Чтобы включить:
      pip install piper-tts
      # скачать голос, напр. en_US-lessac-medium.onnx (+ .json) с
      # https://huggingface.co/rhasspy/piper-voices
    и реализовать synth() через piper.PiperVoice.load(...).synthesize(...).

    Не реализовано: голосовая модель тянется из сети, которая в CI/песочнице
    может быть закрыта. Реализуется на машине пользователя.
    """

    name = "piper"

    def __init__(self, model_path: Path | None = None):
        self.model_path = model_path

    def is_available(self) -> bool:
        return False

    def synth(self, text: str, out_path: Path) -> None:
        raise NotImplementedError(
            "PiperBackend — точка расширения. Установите piper-tts, скачайте "
            "голосовую модель и реализуйте synth(). См. docstring."
        )


class OnlineBackend(TTSBackend):
    """
    Заготовка под облачный TTS (gTTS/Azure/ElevenLabs) на этапе сборки.

    Лучшее качество, но нужен доступ в сеть/ключ при генерации (разово —
    рантайм всё равно offline на готовых файлах). Большинство облачных TTS
    отдают mp3 — потребуется конверсия в WAV (ffmpeg) перед записью.

    Не реализовано намеренно: зависит от выбранного провайдера и ключа.
    """

    name = "online"

    def is_available(self) -> bool:
        return False

    def synth(self, text: str, out_path: Path) -> None:
        raise NotImplementedError(
            "OnlineBackend — точка расширения под gTTS/Azure/ElevenLabs. "
            "Реализуйте synth() под выбранного провайдера."
        )


# Реестр движков по имени — используется CLI скрипта генерации.
BACKENDS: dict[str, type[TTSBackend]] = {
    "espeak": EspeakBackend,
    "piper": PiperBackend,
    "online": OnlineBackend,
}


def make_backend(name: str) -> TTSBackend:
    """Создать бэкенд по имени. KeyError → понятное сообщение."""
    cls = BACKENDS.get(name)
    if cls is None:
        raise TTSBackendError(
            f"Неизвестный TTS-бэкенд {name!r}. Доступны: {', '.join(BACKENDS)}"
        )
    return cls()
