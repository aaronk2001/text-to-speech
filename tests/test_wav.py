from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from tts_app.engines._wav import stream_wav_as_pcm
from tts_app.engines.base import PCM_SAMPLE_RATE, SynthesisError


def _write_wav(path: Path, frames: bytes, *, width: int, channels: int, rate: int) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setsampwidth(width)
        wf.setnchannels(channels)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return path


def _samples(pcm_chunks: list[bytes]) -> np.ndarray:
    return np.frombuffer(b"".join(pcm_chunks), dtype="<i2")


def test_native_format_passes_through_unchanged(tmp_path: Path) -> None:
    src = np.arange(-15000, 15000, 3, dtype="<i2").tobytes()
    path = _write_wav(tmp_path / "a.wav", src, width=2, channels=1, rate=PCM_SAMPLE_RATE)

    chunks = list(stream_wav_as_pcm(path))

    assert len(chunks) > 1  # streamed, not one blob
    assert b"".join(chunks) == src


def test_8bit_unsigned_silence_decodes_to_zero(tmp_path: Path) -> None:
    path = _write_wav(
        tmp_path / "a.wav", bytes([128]) * 100, width=1, channels=1, rate=PCM_SAMPLE_RATE
    )

    out = _samples(list(stream_wav_as_pcm(path)))

    assert out.size == 100
    assert np.all(out == 0)


def test_24bit_decodes_sign_and_scale(tmp_path: Path) -> None:
    values = [0, 0x3FFFFF, -0x400000, 0x7FFFFF, -0x800000]
    frames = b"".join(struct.pack("<i", v)[:3] for v in values)
    path = _write_wav(tmp_path / "a.wav", frames, width=3, channels=1, rate=PCM_SAMPLE_RATE)

    out = _samples(list(stream_wav_as_pcm(path)))

    assert out.tolist() == pytest.approx([0, 16383, -16384, 32767, -32767], abs=1)


def test_32bit_decodes(tmp_path: Path) -> None:
    frames = np.array([0, 2**30, -(2**30)], dtype="<i4").tobytes()
    path = _write_wav(tmp_path / "a.wav", frames, width=4, channels=1, rate=PCM_SAMPLE_RATE)

    out = _samples(list(stream_wav_as_pcm(path)))

    assert out.tolist() == pytest.approx([0, 16383, -16384], abs=1)


def test_stereo_is_averaged_to_mono(tmp_path: Path) -> None:
    # Frames: (L, R) = (8000, 8000), (8000, -8000), (-4000, 0)
    frames = np.array([8000, 8000, 8000, -8000, -4000, 0], dtype="<i2").tobytes()
    path = _write_wav(tmp_path / "a.wav", frames, width=2, channels=2, rate=PCM_SAMPLE_RATE)

    out = _samples(list(stream_wav_as_pcm(path)))

    assert out.tolist() == pytest.approx([8000, 0, -2000], abs=1)


def test_16khz_is_resampled_to_output_rate(tmp_path: Path) -> None:
    t = np.arange(16000) / 16000
    tone = (np.sin(2 * np.pi * 220 * t) * 10000).astype("<i2").tobytes()
    path = _write_wav(tmp_path / "a.wav", tone, width=2, channels=1, rate=16000)

    out = _samples(list(stream_wav_as_pcm(path)))

    # One second in, one second out.
    assert out.size == PCM_SAMPLE_RATE
    assert np.abs(out).max() == pytest.approx(10000, rel=0.02)


def test_invalid_wav_raises_synthesis_error(tmp_path: Path) -> None:
    path = tmp_path / "junk.wav"
    path.write_bytes(b"not a wav file at all")

    with pytest.raises(SynthesisError):
        list(stream_wav_as_pcm(path))
