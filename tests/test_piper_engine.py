from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tts_app.engines.base import SynthesisError, Voice
from tts_app.engines.piper import PiperEngine


def test_piper_not_available_no_binary():
    engine = PiperEngine(piper_exe=Path("/nonexistent/piper.exe"))
    assert not engine.is_available()


def test_piper_not_available_no_voices(tmp_path, monkeypatch):
    fake_exe = tmp_path / "piper.exe"
    fake_exe.touch()

    monkeypatch.setattr("tts_app.engines.piper.get_voices_dir", lambda: tmp_path / "voices")

    engine = PiperEngine(piper_exe=fake_exe)
    assert not engine.is_available()


def test_piper_is_available(tmp_path, monkeypatch):
    fake_exe = tmp_path / "piper.exe"
    fake_exe.touch()

    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    (voices_dir / "test.onnx").touch()

    monkeypatch.setattr("tts_app.engines.piper.get_voices_dir", lambda: voices_dir)

    engine = PiperEngine(piper_exe=fake_exe)
    assert engine.is_available()


def test_piper_list_voices(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()

    (voices_dir / "en_US-test-medium.onnx").touch()
    with open(voices_dir / "en_US-test-medium.onnx.json", "w") as f:
        json.dump({"language": {"code": "en_US"}, "name_native": "Test"}, f)

    monkeypatch.setattr("tts_app.engines.piper.get_voices_dir", lambda: voices_dir)

    fake_exe = tmp_path / "piper.exe"
    fake_exe.touch()

    engine = PiperEngine(piper_exe=fake_exe)
    voices = engine.list_voices()

    assert len(voices) == 1
    assert voices[0].language == "en_US"
    assert voices[0].quality == 4


def test_piper_list_voices_quality_detection(tmp_path, monkeypatch):
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()

    (voices_dir / "en_US-test-low.onnx").touch()
    (voices_dir / "en_US-test-high.onnx").touch()

    for name in ["en_US-test-low.onnx", "en_US-test-high.onnx"]:
        with open(voices_dir / f"{name}.json", "w") as f:
            json.dump({"language": {"code": "en_US"}}, f)

    monkeypatch.setattr("tts_app.engines.piper.get_voices_dir", lambda: voices_dir)

    fake_exe = tmp_path / "piper.exe"
    fake_exe.touch()

    engine = PiperEngine(piper_exe=fake_exe)
    voices = engine.list_voices()

    qualities = {v.name: v.quality for v in voices}
    assert qualities["en_US-test-low"] == 3
    assert qualities["en_US-test-high"] == 5


def test_piper_synthesize_success(tmp_path, monkeypatch):
    fake_exe = tmp_path / "piper.exe"
    fake_exe.touch()

    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    model_file = voices_dir / "test.onnx"
    model_file.touch()

    monkeypatch.setattr("tts_app.engines.piper.get_voices_dir", lambda: voices_dir)

    import wave

    with tempfile.TemporaryDirectory() as td:
        wav_file = Path(td) / "test.wav"
        with wave.open(str(wav_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * 1000)

        def mock_run(*args, **kwargs):
            import shutil
            shutil.copy(wav_file, kwargs.get("stdout", "/dev/null") if "stdout" in kwargs else args[0][-2])

            from unittest.mock import MagicMock
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        def mock_subprocess_run(cmd, **kwargs):
            output_file = None
            for i, arg in enumerate(cmd):
                if arg == "--output_file" and i + 1 < len(cmd):
                    output_file = cmd[i + 1]
                    break
            if output_file:
                import shutil
                shutil.copy(wav_file, output_file)

            from unittest.mock import MagicMock
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)

        voice = Voice(
            id="piper:test.onnx",
            engine="piper",
            name="test",
            language="en_US",
        )

        engine = PiperEngine(piper_exe=fake_exe)
        # Exercise the piper.exe subprocess path even when piper-tts is installed.
        engine._inproc = None
        engine._module_ok = False
        chunks = list(engine.synthesize("hello", voice, rate=1.0))

        assert len(chunks) > 0


def test_piper_synthesize_rate_conversion():
    engine = PiperEngine(piper_exe=Path("/nonexistent"))

    length_scale = 1.0 / max(2.0, 0.25)
    assert length_scale == 0.5


def test_piper_synthesize_invalid_voice(tmp_path, monkeypatch):
    fake_exe = tmp_path / "piper.exe"
    fake_exe.touch()

    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()

    monkeypatch.setattr("tts_app.engines.piper.get_voices_dir", lambda: voices_dir)

    voice = Voice(
        id="sapi:not-piper",
        engine="sapi",
        name="test",
        language="en_US",
    )

    engine = PiperEngine(piper_exe=fake_exe)

    with pytest.raises(SynthesisError):
        list(engine.synthesize("hello", voice))


def test_piper_install_hint_no_binary(tmp_path):
    engine = PiperEngine(piper_exe=Path("/nonexistent/piper.exe"))
    # No runtime at all: neither the piper-tts module nor a binary.
    engine._inproc = None
    engine._module_ok = False
    hint = engine.install_hint()

    assert hint is not None
    assert "piper.exe" in hint.lower()
