from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from tts_app.audio.playback import PlaybackState

logger = logging.getLogger(__name__)


class TrayIcon(QSystemTrayIcon):
    def __init__(
        self,
        parent: QWidget | None,
        icon_path: Path,
        on_show: Callable[[], None],
        on_hide: Callable[[], None],
        on_read_clipboard: Callable[[], None],
        on_pause_resume: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(parent)

        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray is not available on this platform")
            self._available = False
            return

        self._available = True
        self._on_show = on_show
        self._on_hide = on_hide
        self._on_read_clipboard = on_read_clipboard
        self._on_pause_resume = on_pause_resume
        self._on_quit = on_quit

        self.setIcon(QIcon(str(icon_path)))

        menu = QMenu(parent)

        self._toggle_action = menu.addAction("Show / Hide")
        self._toggle_action.triggered.connect(self._on_toggle)

        menu.addAction("Read clipboard now (Ctrl+Alt+S)").triggered.connect(
            on_read_clipboard
        )

        self._pause_action = menu.addAction("Pause")
        self._pause_action.triggered.connect(on_pause_resume)

        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(on_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_toggle(self) -> None:
        self._on_show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show()

    def update_playback_state(self, state: PlaybackState) -> None:
        if not self._available:
            return
        if state == PlaybackState.PLAYING:
            self._pause_action.setText("Pause")
            self._pause_action.setEnabled(True)
        elif state == PlaybackState.PAUSED:
            self._pause_action.setText("Resume")
            self._pause_action.setEnabled(True)
        else:
            self._pause_action.setText("Pause")
            self._pause_action.setEnabled(False)
