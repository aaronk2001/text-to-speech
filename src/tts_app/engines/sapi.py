from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from tts_app.engines._wav import stream_wav_as_pcm
from tts_app.engines.base import SynthesisError, TTSEngine, Voice


def _import_pyttsx3() -> Any | None:
    try:
        import pyttsx3  # type: ignore[import-untyped]

        return pyttsx3
    except Exception:
        return None


def _lcid_to_lang(raw: object) -> str:
    """Best-effort SAPI language tag → 'en_US' style."""
    if isinstance(raw, list) and raw:
        s = raw[0]
    else:
        s = raw
    if isinstance(s, bytes):
        try:
            s = s.decode("utf-8", errors="replace")
        except Exception:
            s = str(s)
    s = str(s)
    s = s.replace("-", "_")
    return s or "und"


class SapiEngine(TTSEngine):
    name: ClassVar[str] = "sapi"

    def __init__(self) -> None:
        self._pyttsx3 = _import_pyttsx3()

    def is_available(self) -> bool:
        if self._pyttsx3 is None:
            return False
        try:
            engine = self._pyttsx3.init()
            engine.stop()
            return True
        except Exception:
            return False

    def list_voices(self) -> list[Voice]:
        if self._pyttsx3 is None:
            return []
        try:
            engine = self._pyttsx3.init()
            raw = engine.getProperty("voices") or []
        except Exception:
            return []
        voices: list[Voice] = []
        for v in raw:
            vid = getattr(v, "id", None) or ""
            vname = getattr(v, "name", None) or vid or "voice"
            gender = getattr(v, "gender", None)
            lang = _lcid_to_lang(getattr(v, "languages", None) or "und")
            voices.append(
                Voice(
                    id=f"sapi:{vid}",
                    engine=self.name,
                    name=str(vname),
                    language=str(lang),
                    gender=str(gender) if gender else None,
                    quality=2,
                )
            )
        return voices

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        if self._pyttsx3 is None:
            raise SynthesisError("pyttsx3 not installed")
        if voice.engine != self.name:
            raise SynthesisError(f"voice {voice.id} not a SAPI voice")
        sapi_id = voice.id.removeprefix("sapi:")
        try:
            engine = self._pyttsx3.init()
            engine.setProperty("voice", sapi_id)
            base_rate = int(engine.getProperty("rate") or 200)
            engine.setProperty("rate", max(50, int(base_rate * rate)))
            engine.setProperty("volume", max(0.0, min(1.0, volume)))
        except Exception as e:
            raise SynthesisError(f"sapi init failed: {e}") from e

        with tempfile.TemporaryDirectory(prefix="tts_sapi_") as td:
            out = Path(td) / "out.wav"
            try:
                engine.save_to_file(text, str(out))
                engine.runAndWait()
            except Exception as e:
                raise SynthesisError(f"sapi synthesize failed: {e}") from e
            if not out.exists() or out.stat().st_size == 0:
                raise SynthesisError("sapi produced no audio")
            yield from stream_wav_as_pcm(out)

    def install_hint(self) -> str | None:
        if self._pyttsx3 is None:
            return "Install pyttsx3:  pip install pyttsx3"
        return None
