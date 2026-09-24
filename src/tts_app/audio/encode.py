from __future__ import annotations

import shutil
import wave
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path


class OutputFormat(StrEnum):
    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"


def format_from_extension(path: Path) -> OutputFormat:
    ext = path.suffix.lower().lstrip(".")
    try:
        return OutputFormat(ext)
    except ValueError:
        raise ValueError(f"Unknown audio format: .{ext}") from None


def encode_pcm_to_file(
    pcm_chunks: Iterable[bytes], dest: Path, fmt: OutputFormat
) -> Path:
    if fmt == OutputFormat.WAV:
        return _encode_wav(pcm_chunks, dest)
    elif fmt in (OutputFormat.MP3, OutputFormat.OGG):
        return _encode_with_pydub(pcm_chunks, dest, fmt)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _encode_wav(pcm_chunks: Iterable[bytes], dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        for chunk in pcm_chunks:
            wav.writeframes(chunk)
    return dest


def _encode_with_pydub(
    pcm_chunks: Iterable[bytes], dest: Path, fmt: OutputFormat
) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg required for MP3/OGG; install or bundle in assets/bin"
        )

    try:
        from pydub import AudioSegment
    except ImportError:
        raise RuntimeError(
            "pydub not installed; required for MP3/OGG encoding"
        ) from None

    dest.parent.mkdir(parents=True, exist_ok=True)

    raw_bytes = b"".join(pcm_chunks)
    audio = AudioSegment(
        data=raw_bytes, sample_width=2, frame_rate=22050, channels=1
    )
    audio.export(str(dest), format=str(fmt))
    return dest
