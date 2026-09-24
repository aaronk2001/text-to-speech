from __future__ import annotations

from collections.abc import Iterator

from tts_app.engines.base import TTSEngine, Voice
from tts_app.engines.registry import EngineRegistry


class _StubEngine(TTSEngine):
    def __init__(self, name: str, available: bool, voices: list[Voice]) -> None:
        self._name = name
        self._available = available
        self._voices = voices

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    def is_available(self) -> bool:
        return self._available

    def list_voices(self) -> list[Voice]:
        return list(self._voices)

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        yield b"\x00\x00"


def _v(engine: str, vid: str = "v1") -> Voice:
    return Voice(id=f"{engine}:{vid}", engine=engine, name=vid, language="en_US")


def test_all_returns_registered_engines() -> None:
    a = _StubEngine("a", True, [_v("a")])
    b = _StubEngine("b", False, [])
    reg = EngineRegistry([a, b])
    assert {e.name for e in reg.all()} == {"a", "b"}
    assert reg.get("a") is a
    assert reg.get("missing") is None


def test_available_filters_unavailable() -> None:
    a = _StubEngine("a", True, [_v("a")])
    b = _StubEngine("b", False, [])
    reg = EngineRegistry([a, b])
    assert reg.available() == [a]


def test_all_voices_aggregates_and_skips_failing_engine() -> None:
    class _Bad(_StubEngine):
        def list_voices(self) -> list[Voice]:
            raise RuntimeError("boom")

    a = _StubEngine("a", True, [_v("a", "1"), _v("a", "2")])
    bad = _Bad("bad", True, [])
    reg = EngineRegistry([a, bad])
    voices = reg.all_voices()
    assert {v.id for v in voices} == {"a:1", "a:2"}


def test_find_voice_locates_engine() -> None:
    a = _StubEngine("a", True, [_v("a", "x")])
    b = _StubEngine("b", True, [_v("b", "y")])
    reg = EngineRegistry([a, b])
    found = reg.find_voice("b:y")
    assert found is not None
    engine, voice = found
    assert engine is b and voice.id == "b:y"
    assert reg.find_voice("missing") is None


def test_fallback_chain_respects_preference_then_appends_others() -> None:
    a = _StubEngine("piper", True, [_v("piper")])
    b = _StubEngine("sapi", True, [_v("sapi")])
    c = _StubEngine("espeak", False, [])
    d = _StubEngine("extra", True, [_v("extra")])
    reg = EngineRegistry([d, a, b, c])
    chain = reg.fallback_chain(("piper", "sapi", "espeak"))
    assert [e.name for e in chain] == ["piper", "sapi", "extra"]


def test_pick_default_returns_first_available() -> None:
    a = _StubEngine("piper", False, [])
    b = _StubEngine("sapi", True, [_v("sapi")])
    reg = EngineRegistry([a, b])
    default = reg.pick_default(("piper", "sapi", "espeak"))
    assert default is b


def test_pick_default_none_when_nothing_available() -> None:
    a = _StubEngine("piper", False, [])
    reg = EngineRegistry([a])
    assert reg.pick_default() is None
