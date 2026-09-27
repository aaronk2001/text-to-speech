from __future__ import annotations

import shutil
import wave
from collections.abc import Iterator
from pathlib import Path

import pytest

from tts_app.audio.encode import OutputFormat, resolve_output
from tts_app.audio.export import export_speech
from tts_app.engines.base import SynthesisError, TTSEngine, Voice


@pytest.mark.parametrize(
    ("name", "selected_filter", "expected_name", "expected_fmt"),
    [
        ("talk.wav", "MP3 (*.mp3)", "talk.wav", OutputFormat.WAV),  # extension wins
        ("talk.MP3", "", "talk.MP3", OutputFormat.MP3),
        ("talk", "OGG (*.ogg)", "talk.ogg", OutputFormat.OGG),
        ("talk", "", "talk.wav", OutputFormat.WAV),
        ("notes.txt", "MP3 (*.mp3)", "notes.txt.mp3", OutputFormat.MP3),
    ],
)
def test_resolve_output(
    tmp_path: Path,
    name: str,
    selected_filter: str,
    expected_name: str,
    expected_fmt: OutputFormat,
) -> None:
    dest, fmt = resolve_output(tmp_path / name, selected_filter)
    assert dest == tmp_path / expected_name
    assert fmt == expected_fmt


class _RecordingEngine(TTSEngine):
    name = "rec"

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self._fail_on = fail_on

    def is_available(self) -> bool:
        return True

    def list_voices(self) -> list[Voice]:
        return [Voice(id="rec:1", engine="rec", name="rec", language="en")]

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        self.calls.append(text)
        if text == self._fail_on:
            raise SynthesisError("boom")
        yield len(self.calls).to_bytes(2, "little") * 100


def test_export_synthesizes_each_sentence_into_one_wav(tmp_path: Path) -> None:
    engine = _RecordingEngine()
    dest = tmp_path / "out.wav"

    export_speech(engine, engine.list_voices()[0], "First one. Second one.", dest, OutputFormat.WAV)

    assert engine.calls == ["First one.", "Second one."]
    with wave.open(str(dest), "rb") as wf:
        assert wf.getframerate() == 22050
        frames = wf.readframes(wf.getnframes())
    assert frames == b"\x01\x00" * 100 + b"\x02\x00" * 100


def test_export_checks_encoder_before_synthesizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    engine = _RecordingEngine()

    with pytest.raises(RuntimeError, match="ffmpeg required"):
        export_speech(engine, engine.list_voices()[0], "Hi.", tmp_path / "a.mp3", OutputFormat.MP3)

    assert engine.calls == []


def test_export_failure_removes_partial_file(tmp_path: Path) -> None:
    engine = _RecordingEngine(fail_on="Second one.")
    dest = tmp_path / "out.wav"

    with pytest.raises(SynthesisError):
        export_speech(
            engine, engine.list_voices()[0], "First one. Second one.", dest, OutputFormat.WAV
        )

    assert not dest.exists()
