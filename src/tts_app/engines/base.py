from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar


class EngineUnavailable(RuntimeError):
    """Raised when an engine's prerequisites (binary/lib/voice) are missing."""


class SynthesisError(RuntimeError):
    """Raised when synthesis fails mid-stream."""


@dataclass(frozen=True)
class Voice:
    id: str
    engine: str
    name: str
    language: str
    gender: str | None = None
    quality: int = 3  # 1..5

    @property
    def display(self) -> str:
        suffix = f" ({self.gender})" if self.gender else ""
        return f"{self.name} — {self.language}{suffix}"


# Uniform PCM format produced by every engine adapter. Audio layer assumes this.
PCM_SAMPLE_RATE = 22050
PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH_BYTES = 2  # s16le

# Engines wrap native runtimes (SAPI/COM, ONNX sessions) that aren't safe to drive
# from two threads at once. Hold this around any synthesis done off the UI thread.
SYNTHESIS_LOCK = threading.Lock()


class TTSEngine(ABC):
    name: ClassVar[str] = ""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this engine can synthesize right now."""

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """Return all voices currently usable by this engine."""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        """Yield PCM s16le mono chunks at PCM_SAMPLE_RATE. May raise SynthesisError."""

    def install_hint(self) -> str | None:
        """Human-readable instructions when is_available() is False."""
        return None
