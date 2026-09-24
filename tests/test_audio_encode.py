from __future__ import annotations

import shutil
import tempfile
import wave
from pathlib import Path

import pytest

from tts_app.audio.encode import OutputFormat, encode_pcm_to_file, format_from_extension


def test_wav_encode_round_trip() -> None:
    """Test WAV encoding and reading back."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "test.wav"

        # Generate 1 second of silence at 22050 Hz
        num_frames = 22050
        silence_chunk = b"\x00\x00" * num_frames

        result = encode_pcm_to_file([silence_chunk], dest, OutputFormat.WAV)

        assert result == dest
        assert dest.exists()

        # Verify WAV structure
        with wave.open(str(dest), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == 22050
            assert wav.getnframes() == num_frames


def test_format_from_extension_lowercase() -> None:
    assert format_from_extension(Path("file.wav")) == OutputFormat.WAV
    assert format_from_extension(Path("file.mp3")) == OutputFormat.MP3
    assert format_from_extension(Path("file.ogg")) == OutputFormat.OGG


def test_format_from_extension_uppercase() -> None:
    assert format_from_extension(Path("file.WAV")) == OutputFormat.WAV
    assert format_from_extension(Path("file.MP3")) == OutputFormat.MP3
    assert format_from_extension(Path("file.OGG")) == OutputFormat.OGG


def test_format_from_extension_mixed_case() -> None:
    assert format_from_extension(Path("file.WaV")) == OutputFormat.WAV
    assert format_from_extension(Path("file.Mp3")) == OutputFormat.MP3


def test_format_from_extension_raises_on_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown audio format"):
        format_from_extension(Path("file.flac"))

    with pytest.raises(ValueError, match="Unknown audio format"):
        format_from_extension(Path("file.xyz"))


@pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not available"
)
def test_mp3_encode_requires_ffmpeg() -> None:
    """Smoke test that MP3 encoding works if ffmpeg is available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "test.mp3"
        silence_chunk = b"\x00\x00" * 22050

        try:
            import pydub  # noqa: F401
        except ImportError:
            pytest.skip("pydub not installed")

        result = encode_pcm_to_file([silence_chunk], dest, OutputFormat.MP3)
        assert result == dest
        assert dest.exists()


@pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="ffmpeg not available"
)
def test_ogg_encode_requires_ffmpeg() -> None:
    """Smoke test that OGG encoding works if ffmpeg is available."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "test.ogg"
        silence_chunk = b"\x00\x00" * 22050

        try:
            import pydub  # noqa: F401
        except ImportError:
            pytest.skip("pydub not installed")

        result = encode_pcm_to_file([silence_chunk], dest, OutputFormat.OGG)
        assert result == dest
        assert dest.exists()


def test_mp3_encode_raises_without_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that MP3 encoding raises RuntimeError if ffmpeg is missing."""
    monkeypatch.setattr(shutil, "which", lambda x: None)

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "test.mp3"
        silence_chunk = b"\x00\x00" * 22050

        with pytest.raises(RuntimeError, match="ffmpeg required"):
            encode_pcm_to_file([silence_chunk], dest, OutputFormat.MP3)
