from __future__ import annotations

import wave
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from tts_app.engines.base import PCM_SAMPLE_RATE, SynthesisError

_CHUNK_FRAMES = 2048


def stream_wav_as_pcm(path: Path) -> Iterator[bytes]:
    """Read a WAV file and yield s16le mono chunks at PCM_SAMPLE_RATE."""
    try:
        with wave.open(str(path), "rb") as wf:
            sw = wf.getsampwidth()
            ch = wf.getnchannels()
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except wave.Error as e:
        raise SynthesisError(f"invalid wav: {e}") from e

    if sw == 2 and ch == 1 and sr == PCM_SAMPLE_RATE:
        pcm = raw
    else:
        audio = pcm_to_float(raw, sw)
        if ch > 1:
            audio = audio.reshape(-1, ch).mean(axis=1)
        pcm = float_to_pcm16(resample_mono(audio, sr, PCM_SAMPLE_RATE))

    step = _CHUNK_FRAMES * 2
    for i in range(0, len(pcm), step):
        yield pcm[i:i + step]


def pcm_to_float(raw: bytes, sample_width: int) -> np.ndarray:
    """Decode little-endian integer PCM (8/16/24/32-bit) to float32 in [-1, 1]."""
    if sample_width == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        return v.astype(np.float32) / 8388608.0
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    raise SynthesisError(f"unsupported sample width {sample_width}")


def float_to_pcm16(audio: np.ndarray) -> bytes:
    return (audio * 32767.0).clip(-32768, 32767).astype("<i2").tobytes()


def resample_mono(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or audio.size == 0:
        return audio
    n_out = int(round(audio.size * dst_sr / src_sr))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
