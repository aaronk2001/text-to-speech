from __future__ import annotations

import audioop
import wave
from collections.abc import Iterator
from pathlib import Path

from tts_app.engines.base import (
    PCM_CHANNELS,
    PCM_SAMPLE_RATE,
    PCM_SAMPLE_WIDTH_BYTES,
    SynthesisError,
)

_CHUNK_FRAMES = 2048


def stream_wav_as_pcm(path: Path) -> Iterator[bytes]:
    """Read a WAV file and yield s16le mono chunks at PCM_SAMPLE_RATE."""
    try:
        with wave.open(str(path), "rb") as wf:
            sw = wf.getsampwidth()
            ch = wf.getnchannels()
            sr = wf.getframerate()
            state: object = None
            while True:
                frames = wf.readframes(_CHUNK_FRAMES)
                if not frames:
                    return
                if sw != PCM_SAMPLE_WIDTH_BYTES:
                    frames = audioop.lin2lin(frames, sw, PCM_SAMPLE_WIDTH_BYTES)
                if ch == 2 and PCM_CHANNELS == 1:
                    frames = audioop.tomono(frames, PCM_SAMPLE_WIDTH_BYTES, 1.0, 1.0)
                elif ch != PCM_CHANNELS:
                    raise SynthesisError(f"unsupported channel count {ch}")
                if sr != PCM_SAMPLE_RATE:
                    frames, state = audioop.ratecv(
                        frames,
                        PCM_SAMPLE_WIDTH_BYTES,
                        PCM_CHANNELS,
                        sr,
                        PCM_SAMPLE_RATE,
                        state,  # type: ignore[arg-type]
                    )
                yield frames
    except wave.Error as e:
        raise SynthesisError(f"invalid wav: {e}") from e
