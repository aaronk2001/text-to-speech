from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

from tts_app.audio.encode import OutputFormat, encode_pcm_to_file, ensure_encoder
from tts_app.engines.base import SYNTHESIS_LOCK, TTSEngine, Voice
from tts_app.text.segment import segment_text


class ExportCancelled(Exception):
    """Raised when export_speech's cancel event is set before it finishes."""


def export_speech(
    engine: TTSEngine,
    voice: Voice,
    text: str,
    dest: Path,
    fmt: OutputFormat,
    *,
    rate: float = 1.0,
    pitch: float = 1.0,
    volume: float = 1.0,
    cancel: threading.Event | None = None,
) -> Path:
    """Synthesize text sentence by sentence, as playback does, and encode it to dest.

    Runs on a worker thread. Writes to a temporary file first, so a failure
    leaves neither a partial file nor a damaged copy of an existing dest.
    Setting `cancel` stops it between sentences with ExportCancelled.
    """
    ensure_encoder(fmt)  # fail before spending minutes on synthesis

    def pcm() -> Iterator[bytes]:
        for seg in segment_text(text):
            if cancel is not None and cancel.is_set():
                raise ExportCancelled
            with SYNTHESIS_LOCK:
                chunks = list(
                    engine.synthesize(seg.text, voice, rate=rate, pitch=pitch, volume=volume)
                )
            yield from chunks

    part = dest.with_name(dest.name + ".part")
    try:
        encode_pcm_to_file(pcm(), part, fmt)
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dest
