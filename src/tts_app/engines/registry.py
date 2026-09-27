from __future__ import annotations

import logging
from collections.abc import Iterable

from tts_app.engines.base import TTSEngine, Voice
from tts_app.engines.piper import PiperEngine
from tts_app.engines.sapi import SapiEngine
from tts_app.engines.supertonic_engine import SupertonicEngine

logger = logging.getLogger(__name__)

_DEFAULT_PREFERENCE = ("supertonic", "piper", "sapi")


def build_default_engines() -> list[TTSEngine]:
    supertonic = SupertonicEngine()
    piper = PiperEngine()
    sapi = SapiEngine()
    return [supertonic, piper, sapi]


class EngineRegistry:
    """Engines plus a cache of which are usable and their voices.

    Availability checks can be slow (SAPI spins up COM, Piper may start a
    subprocess), so results are cached until refresh() — call it after anything
    that can change them, such as installing a voice or a background probe.
    """

    def __init__(self, engines: Iterable[TTSEngine] | None = None) -> None:
        self._engines: dict[str, TTSEngine] = {}
        for e in engines if engines is not None else build_default_engines():
            self._engines[e.name] = e
        self._available: list[TTSEngine] | None = None
        self._voices: dict[str, list[Voice]] = {}

    def refresh(self) -> None:
        self._available = None
        self._voices.clear()

    @staticmethod
    def _check(engine: TTSEngine) -> bool:
        try:
            return engine.is_available()
        except Exception:
            logger.exception("availability check failed for %s", engine.name)
            return False

    def all(self) -> list[TTSEngine]:
        return list(self._engines.values())

    def get(self, name: str) -> TTSEngine | None:
        return self._engines.get(name)

    def available(self) -> list[TTSEngine]:
        if self._available is None:
            self._available = [e for e in self._engines.values() if self._check(e)]
        return list(self._available)

    def voices(self, engine: TTSEngine) -> list[Voice]:
        if engine.name not in self._voices:
            try:
                self._voices[engine.name] = engine.list_voices()
            except Exception:
                logger.exception("listing voices failed for %s", engine.name)
                self._voices[engine.name] = []
        return list(self._voices[engine.name])

    def all_voices(self) -> list[Voice]:
        return [v for e in self.available() for v in self.voices(e)]

    def find_voice(self, voice_id: str) -> tuple[TTSEngine, Voice] | None:
        for e in self.available():
            for v in self.voices(e):
                if v.id == voice_id:
                    return e, v
        return None

    def fallback_chain(
        self, preference: Iterable[str] = _DEFAULT_PREFERENCE
    ) -> list[TTSEngine]:
        available = self.available()
        by_name = {e.name: e for e in available}
        ordered = [by_name[name] for name in dict.fromkeys(preference) if name in by_name]
        ordered += [e for e in available if e not in ordered]
        return ordered

    def pick_default(
        self, preference: Iterable[str] = _DEFAULT_PREFERENCE
    ) -> TTSEngine | None:
        chain = self.fallback_chain(preference)
        return chain[0] if chain else None
