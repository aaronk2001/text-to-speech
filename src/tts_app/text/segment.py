from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    text: str
    start: int
    end: int


_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def segment_text(text: str) -> list[Segment]:
    if not text:
        return []
    segments: list[Segment] = []
    cursor = 0
    for m in _BOUNDARY.finditer(text):
        end = m.start()
        chunk = text[cursor:end]
        if chunk.strip():
            segments.append(Segment(chunk, cursor, end))
        cursor = m.end()
    if cursor < len(text):
        chunk = text[cursor:]
        if chunk.strip():
            segments.append(Segment(chunk, cursor, len(text)))
    return segments
