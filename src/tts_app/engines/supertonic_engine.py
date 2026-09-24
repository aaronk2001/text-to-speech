from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import numpy as np
import platformdirs

from tts_app.engines.base import PCM_SAMPLE_RATE, TTSEngine, Voice

logger = logging.getLogger(__name__)

_VOICES: tuple[tuple[str, str], ...] = (
    ("F1", "female"),
    ("F2", "female"),
    ("F3", "female"),
    ("F4", "female"),
    ("F5", "female"),
    ("M1", "male"),
    ("M2", "male"),
    ("M3", "male"),
    ("M4", "male"),
    ("M5", "male"),
)


def get_supertonic_model_dir() -> Path:
    d = Path(platformdirs.user_data_dir("TTSApp", appauthor=False)) / "supertonic"
    d.mkdir(parents=True, exist_ok=True)
    # De-virtualize Microsoft Store Python's sandboxed AppData path so the
    # ONNX runtime (native) and Python agree on the model location.
    return Path(os.path.realpath(d))


class SupertonicEngine(TTSEngine):
    name: ClassVar[str] = "supertonic"

    def __init__(self) -> None:
        self._tts = None  # cached supertonic.TTS (loads ONNX once)
        self._status: str = "unknown"

    def _probe(self) -> None:
        if self._status != "unknown":
            return
        try:
            import supertonic  # noqa: F401

            self._status = "ready"
        except ImportError:
            self._status = "missing"

    def recheck(self) -> None:
        self._status = "unknown"
        self._probe()

    def is_available(self) -> bool:
        self._probe()
        return self._status == "ready"

    def install_hint(self) -> str | None:
        return "pip install supertonic"

    def list_voices(self) -> list[Voice]:
        return [
            Voice(
                id=f"supertonic:{name}",
                engine="supertonic",
                name=f"Supertonic {name}",
                language="en",
                gender=gender,
                quality=5,
            )
            for name, gender in _VOICES
        ]

    def _get_tts(self):
        if self._tts is not None:
            return self._tts
        from supertonic import TTS

        self._tts = TTS(
            model="supertonic-3",
            model_dir=str(get_supertonic_model_dir()),
            auto_download=True,
        )
        return self._tts

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        if not text.strip():
            return

        tts = self._get_tts()
        voice_name = voice.id.removeprefix("supertonic:")
        style = tts.get_voice_style(voice_name)

        # Supertonic's natural rate is ~1.05x; map the UI's 1.0 to that so the
        # default sounds neutral, then scale by the user's rate.
        speed = max(0.5, min(2.0, 1.05 * rate))
        wav, _ = tts.synthesize(text, style, speed=speed, lang="en")

        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        src_sr = int(getattr(tts, "sample_rate", 44100))
        audio = _resample_mono(audio, src_sr, PCM_SAMPLE_RATE)

        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak > 0:
            audio = audio / peak * 0.95 * max(0.0, min(volume, 1.0))
        pcm = (audio * 32767.0).clip(-32768, 32767).astype("<i2").tobytes()

        chunk = PCM_SAMPLE_RATE * 2
        for i in range(0, len(pcm), chunk):
            yield pcm[i:i + chunk]


def _resample_mono(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or audio.size == 0:
        return audio
    n_out = int(round(audio.size * dst_sr / src_sr))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
