from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)


def _try_import_keyboard() -> Any | None:
    try:
        import keyboard  # type: ignore[import-untyped]

        return keyboard
    except Exception as e:
        logger.warning("keyboard library not available: %s", e)
        return None


class GlobalHotkey(QObject):
    triggered = Signal()

    def __init__(self, spec: str, keyboard_module: Any | None = None) -> None:
        super().__init__()
        self._spec = spec
        self._keyboard = keyboard_module if keyboard_module is not None else _try_import_keyboard()
        self._handle: object | None = None
        self._running = False

    def is_available(self) -> bool:
        return self._keyboard is not None

    def install_hint(self) -> str | None:
        if self._keyboard is None:
            return "Install the `keyboard` package: pip install keyboard"
        return None

    def start(self) -> None:
        if self._keyboard is None or self._running:
            return
        try:
            self._handle = self._keyboard.add_hotkey(self._spec, self._fire, suppress=False)
            self._running = True
        except Exception as e:
            logger.error("Failed to register hotkey %s: %s", self._spec, e)

    def stop(self) -> None:
        if self._keyboard is None or not self._running:
            return
        try:
            if self._handle is not None:
                self._keyboard.remove_hotkey(self._handle)
        except Exception as e:
            logger.error("Failed to unregister hotkey: %s", e)
        finally:
            self._handle = None
            self._running = False

    def change_binding(self, spec: str) -> None:
        was_running = self._running
        self.stop()
        self._spec = spec
        if was_running:
            self.start()

    @Slot()
    def _fire(self) -> None:
        self.triggered.emit()
