from __future__ import annotations

import sys
from typing import Literal

from PySide6.QtCore import QObject, Signal

from tts_app.config import AppSettings

ReducedMotion = Literal["auto", "on", "off"]


class _Policy(QObject):
    changed = Signal(bool)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self._settings = settings

    def should_animate(self) -> bool:
        pref = self._settings.reduced_motion
        if pref == "on":
            return False
        if pref == "off":
            return True
        return not _os_prefers_reduced_motion()

    def set_preference(self, value: ReducedMotion) -> None:
        self._settings.reduced_motion = value
        self.changed.emit(self.should_animate())


def _os_prefers_reduced_motion() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        enabled = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
        return enabled.value == 0
    except Exception:
        return False


_policy: _Policy | None = None


def init_motion(settings: AppSettings) -> _Policy:
    global _policy
    _policy = _Policy(settings)
    return _policy


def policy() -> _Policy | None:
    return _policy


def should_animate() -> bool:
    return _policy.should_animate() if _policy is not None else True
