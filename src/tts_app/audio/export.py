from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from tts_app.audio.encode import OutputFormat, encode_pcm_to_file, ensure_encoder
from tts_app.engines.base import SYNTHESIS_LOCK, TTSEngine, Voice
from tts_app.text.segment import segment_text


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
) -> Path:
    """Synthesize text sentence by sentence, as playback does, and encode it to dest.

    Runs on a worker thread; a partially written file is removed on failure.
    """
    ensure_encoder(fmt)  # fail before spending minutes on synthesis

    def pcm() -> Iterator[bytes]:
        for seg in segment_text(text):
            with SYNTHESIS_LOCK:
                chunks = list(
                    engine.synthesize(seg.text, voice, rate=rate, pitch=pitch, volume=volume)
                )
            yield from chunks

    try:
        return encode_pcm_to_file(pcm(), dest, fmt)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
