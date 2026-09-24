from __future__ import annotations

import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from tts_app.engines import sapi as sapi_mod
from tts_app.engines.base import SynthesisError, Voice


def _write_silent_wav(path: Path, frames: int = 1024, rate: int = 22050) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack("<" + "h" * frames, *([0] * frames)))


class _FakePyttsx3Engine:
    def __init__(self) -> None:
        self.props: dict[str, object] = {"rate": 200, "volume": 1.0}
        self.saved: tuple[str, str] | None = None

    def setProperty(self, k: str, v: object) -> None:
        self.props[k] = v

    def getProperty(self, k: str) -> object:
        if k == "voices":
            return [
                SimpleNamespace(
                    id="HKLM\\...\\TTS_MS_EN-US_DAVID_11.0",
                    name="Microsoft David",
                    languages=["en-US"],
                    gender="Male",
                ),
                SimpleNamespace(
                    id="HKLM\\...\\TTS_MS_EN-US_ZIRA_11.0",
                    name="Microsoft Zira",
                    languages=[b"en-US"],
                    gender="Female",
                ),
            ]
        return self.props.get(k)

    def save_to_file(self, text: str, path: str) -> None:
        self.saved = (text, path)
        _write_silent_wav(Path(path))

    def runAndWait(self) -> None:  # noqa: N802
        return None

    def stop(self) -> None:
        return None


@pytest.fixture
def fake_pyttsx3(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    fake_engine = _FakePyttsx3Engine()
    fake_module = SimpleNamespace(init=lambda *a, **kw: fake_engine)
    monkeypatch.setattr(sapi_mod, "_import_pyttsx3", lambda: fake_module)
    return fake_engine  # type: ignore[return-value]


def test_unavailable_when_pyttsx3_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sapi_mod, "_import_pyttsx3", lambda: None)
    e = sapi_mod.SapiEngine()
    assert e.is_available() is False
    assert e.list_voices() == []
    assert "pyttsx3" in (e.install_hint() or "")


def test_available_and_lists_voices(fake_pyttsx3: _FakePyttsx3Engine) -> None:
    e = sapi_mod.SapiEngine()
    assert e.is_available() is True
    voices = e.list_voices()
    assert len(voices) == 2
    assert all(v.engine == "sapi" for v in voices)
    assert voices[0].name == "Microsoft David"
    assert voices[0].language == "en_US"
    assert voices[0].gender == "Male"
    assert voices[1].language == "en_US"  # bytes-decoded


def test_synthesize_returns_pcm_bytes(fake_pyttsx3: _FakePyttsx3Engine) -> None:
    e = sapi_mod.SapiEngine()
    voice = Voice(id="sapi:HKLM\\X", engine="sapi", name="X", language="en_US")
    chunks = list(e.synthesize("hello world", voice, rate=1.5, volume=0.8))
    assert chunks
    assert all(isinstance(c, bytes) for c in chunks)
    assert fake_pyttsx3.saved is not None and fake_pyttsx3.saved[0] == "hello world"
    assert fake_pyttsx3.props["rate"] == 300  # 200 * 1.5
    assert fake_pyttsx3.props["volume"] == pytest.approx(0.8)


def test_synthesize_rejects_wrong_engine_voice(fake_pyttsx3: _FakePyttsx3Engine) -> None:
    e = sapi_mod.SapiEngine()
    voice = Voice(id="piper:x", engine="piper", name="x", language="en_US")
    with pytest.raises(SynthesisError):
        list(e.synthesize("hi", voice))
