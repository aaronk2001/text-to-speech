from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest

from tts_app.engines.base import (
    PCM_SAMPLE_RATE,
    EngineUnavailable,
    SynthesisError,
    TTSEngine,
    Voice,
)


def test_voice_display_with_gender() -> None:
    v = Voice(id="x", engine="e", name="lessac", language="en_US", gender="M", quality=4)
    assert v.display == "lessac — en_US (M)"


def test_voice_display_without_gender() -> None:
    v = Voice(id="x", engine="e", name="lessac", language="en_US")
    assert v.display == "lessac — en_US"


def test_voice_is_hashable_and_frozen() -> None:
    v = Voice(id="x", engine="e", name="n", language="en_US")
    assert hash(v)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.name = "other"  # type: ignore[misc]


def test_pcm_sample_rate_is_22050() -> None:
    assert PCM_SAMPLE_RATE == 22050


def test_cannot_instantiate_abstract_engine() -> None:
    with pytest.raises(TypeError):
        TTSEngine()  # type: ignore[abstract]


class _FakeEngine(TTSEngine):
    name = "fake"

    def is_available(self) -> bool:
        return True

    def list_voices(self) -> list[Voice]:
        return [Voice(id="fake-1", engine="fake", name="fake", language="en_US")]

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        yield b"\x00\x00" * 100


def test_concrete_subclass_satisfies_contract() -> None:
    e = _FakeEngine()
    assert e.is_available()
    voices = e.list_voices()
    assert len(voices) == 1 and voices[0].engine == "fake"
    chunks = list(e.synthesize("hello", voices[0]))
    assert chunks and all(isinstance(c, bytes) for c in chunks)
    assert e.install_hint() is None


def test_engine_errors_are_runtime_errors() -> None:
    assert issubclass(EngineUnavailable, RuntimeError)
    assert issubclass(SynthesisError, RuntimeError)
