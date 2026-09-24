from __future__ import annotations

from collections.abc import Iterable

from tts_app.engines.base import TTSEngine, Voice
from tts_app.engines.piper import PiperEngine
from tts_app.engines.sapi import SapiEngine
from tts_app.engines.supertonic_engine import SupertonicEngine

_DEFAULT_PREFERENCE = ("supertonic", "piper", "sapi")


def build_default_engines() -> list[TTSEngine]:
    supertonic = SupertonicEngine()
    piper = PiperEngine()
    sapi = SapiEngine()
    return [supertonic, piper, sapi]


class EngineRegistry:
    def __init__(self, engines: Iterable[TTSEngine] | None = None) -> None:
        self._engines: dict[str, TTSEngine] = {}
        for e in engines if engines is not None else build_default_engines():
            self._engines[e.name] = e

    def all(self) -> list[TTSEngine]:
        return list(self._engines.values())

    def get(self, name: str) -> TTSEngine | None:
        return self._engines.get(name)

    def available(self) -> list[TTSEngine]:
        return [e for e in self._engines.values() if e.is_available()]

    def all_voices(self) -> list[Voice]:
        out: list[Voice] = []
        for e in self.available():
            try:
                out.extend(e.list_voices())
            except Exception:
                continue
        return out

    def find_voice(self, voice_id: str) -> tuple[TTSEngine, Voice] | None:
        for e in self.available():
            for v in e.list_voices():
                if v.id == voice_id:
                    return e, v
        return None

    def fallback_chain(
        self, preference: Iterable[str] = _DEFAULT_PREFERENCE
    ) -> list[TTSEngine]:
        ordered: list[TTSEngine] = []
        seen: set[str] = set()
        for name in preference:
            engine = self._engines.get(name)
            if engine is not None and engine.is_available():
                ordered.append(engine)
                seen.add(name)
        for engine in self._engines.values():
            if engine.name not in seen and engine.is_available():
                ordered.append(engine)
        return ordered

    def pick_default(
        self, preference: Iterable[str] = _DEFAULT_PREFERENCE
    ) -> TTSEngine | None:
        chain = self.fallback_chain(preference)
        return chain[0] if chain else None
