"""RvcEngine against a fake rvc-inferpy converter (torch isn't needed)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tts_app.engines import rvc_engine
from tts_app.engines.base import PCM_SAMPLE_RATE, TTSEngine, Voice
from tts_app.engines.rvc_engine import RvcEngine


class _Base(TTSEngine):
    name = "piper"

    def __init__(self) -> None:
        self.used: list[str] = []

    def is_available(self) -> bool:
        return True

    def list_voices(self) -> list[Voice]:
        return [
            Voice(id="piper:a.onnx", engine="piper", name="a", language="en"),
            Voice(id="piper:b.onnx", engine="piper", name="b", language="en"),
        ]

    def synthesize(self, text: str, voice: Voice, *args: Any, **kwargs: Any) -> Iterator[bytes]:
        self.used.append(voice.id)
        yield b"\x10\x00" * 2205


class _FakeVC:
    def __init__(self) -> None:
        self.loaded: list[str] = []

    def get_vc(self, pth: str, protect: float, _x: float) -> None:
        self.loaded.append(pth)


class _FakeConverter:
    def __init__(self, out_dir: Path) -> None:
        self.vc = _FakeVC()
        self.calls: list[dict[str, Any]] = []
        self._out_dir = out_dir

    def _run_inference(self, **kwargs: Any) -> tuple:
        self.calls.append(kwargs)
        self._out_dir.mkdir(exist_ok=True)
        out = self._out_dir / f"result{len(self.calls)}.wav"
        out.write_bytes(b"x")
        audio = (np.sin(np.arange(40000) / 20) * 16000).astype(np.int16)  # 1 s at 40 kHz
        return ("Success.", "Index not used.", [0, 0, 0]), (40000, audio), str(out)


@pytest.fixture
def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RvcEngine, _Base, _FakeConverter]:
    models = tmp_path / "models"
    (models / "singer").mkdir(parents=True)
    (models / "singer" / "singer.pth").write_bytes(b"pth")
    (models / "singer" / "added.index").write_bytes(b"idx")
    assets = tmp_path / "assets"
    assets.mkdir()
    monkeypatch.setattr(rvc_engine, "get_rvc_models_dir", lambda: models)
    monkeypatch.setattr(rvc_engine, "get_rvc_assets_dir", lambda: assets)

    base = _Base()
    engine = RvcEngine(base_engine=base)
    conv = _FakeConverter(tmp_path / "output")
    monkeypatch.setattr(engine, "_get_converter", lambda: conv)
    return engine, base, conv


def _voice() -> Voice:
    return Voice(id="rvc:singer", engine="rvc", name="Singer", language="any")


def test_converts_with_explicit_paths_and_no_chdir(
    setup: tuple[RvcEngine, _Base, _FakeConverter], tmp_path: Path
) -> None:
    engine, _, conv = setup
    cwd = os.getcwd()

    pcm = b"".join(engine.synthesize("Hello.", _voice(), pitch=1.5))

    assert os.getcwd() == cwd
    call = conv.calls[0]
    assert call["index_path"].endswith("added.index")
    assert call["f0_change"] == 6  # pitch 1.5 -> +6 semitones
    assert conv.vc.loaded == [str(tmp_path / "models" / "singer" / "singer.pth")]
    assert len(pcm) == PCM_SAMPLE_RATE * 2  # 1 s resampled from 40 kHz
    # Temp input and rvc-inferpy's own output file are cleaned up.
    assert list((tmp_path / "assets").iterdir()) == []
    assert not (tmp_path / "output").exists()


def test_model_is_loaded_once_across_sentences(
    setup: tuple[RvcEngine, _Base, _FakeConverter],
) -> None:
    engine, _, conv = setup
    for text in ("One.", "Two."):
        b"".join(engine.synthesize(text, _voice()))
    assert len(conv.vc.loaded) == 1 and len(conv.calls) == 2


def test_uses_the_configured_base_voice(setup: tuple[RvcEngine, _Base, _FakeConverter]) -> None:
    engine, base, _ = setup
    engine.set_base_voice("piper:b.onnx")
    b"".join(engine.synthesize("Hi.", _voice()))
    engine.set_base_voice("piper:gone.onnx")  # missing -> first voice
    b"".join(engine.synthesize("Hi.", _voice()))
    assert base.used == ["piper:b.onnx", "piper:a.onnx"]


def test_failed_conversion_raises(
    setup: tuple[RvcEngine, _Base, _FakeConverter], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, _, conv = setup
    monkeypatch.setattr(
        conv, "_run_inference", lambda **k: (("Traceback ...", None, []), (None, None), None)
    )
    with pytest.raises(RuntimeError, match="RVC conversion failed"):
        b"".join(engine.synthesize("Hi.", _voice()))
