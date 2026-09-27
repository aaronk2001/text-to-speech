from __future__ import annotations

import logging
from typing import ClassVar

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from tts_app.audio.playback import PlaybackController, PlaybackState
from tts_app.config import load_settings, save_settings
from tts_app.engines.registry import EngineRegistry, build_default_engines
from tts_app.hotkey.global_hotkey import GlobalHotkey, format_hotkey
from tts_app.ui.icon import app_icon
from tts_app.ui.main_window import MainWindow
from tts_app.ui.motion import init_motion
from tts_app.ui.theme import apply_nexus_dark
from tts_app.ui.tray import TrayIcon

logger = logging.getLogger(__name__)


class _EngineProbeThread(QThread):
    completed = Signal()

    def __init__(self, registry: EngineRegistry, parent=None) -> None:
        super().__init__(parent)
        self._registry = registry

    def run(self) -> None:
        engine = self._registry.get("supertonic")
        if engine is not None and hasattr(engine, "recheck"):
            engine.recheck()
        self.completed.emit()


class App:
    _instance: ClassVar[App | None] = None

    def __init__(self, argv: list[str]) -> None:
        self._app = QApplication.instance() or QApplication(argv)
        self._app.setApplicationName("TTS App")
        self._app.setOrganizationName("TTSApp")
        self._app.setWindowIcon(app_icon())

        self._registry = EngineRegistry(build_default_engines())
        self._playback = PlaybackController()
        self._settings = load_settings()

        apply_nexus_dark(self._app)
        init_motion(self._settings)

        self._main_window: MainWindow | None = None
        self._local_server: QLocalServer | None = None
        self._probe: _EngineProbeThread | None = None
        self._hotkey: GlobalHotkey | None = None
        self._tray: TrayIcon | None = None
        self._tray_hint_shown = False

    def run(self) -> int:
        if not self._try_acquire_singleton():
            return 0

        self._main_window = MainWindow(
            self._registry, self._playback, self._settings
        )
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

        self._apply_hotkey(self._main_window)
        self._start_tray(self._main_window)
        self._apply_residency(self._main_window)
        self._main_window.hidden_to_tray.connect(self._on_hidden_to_tray)
        self._main_window.preferences_changed.connect(self._on_preferences_changed)
        self._app.aboutToQuit.connect(self._shutdown)

        self._probe = _EngineProbeThread(self._registry)
        self._probe.completed.connect(self._main_window.on_engines_probed)
        QTimer.singleShot(0, self._probe.start)

        if not self._settings.first_run_complete:
            self._settings.first_run_complete = True
            save_settings(self._settings)

        return self._app.exec()

    def _apply_hotkey(self, window: MainWindow) -> None:
        """(Re)register the global hotkey to match settings; None if it isn't running."""
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
        if not self._settings.hotkey_enabled:
            return
        hotkey = GlobalHotkey(self._settings.hotkey)
        if not hotkey.is_available():
            logger.warning("Global hotkey disabled: %s", hotkey.install_hint())
            return
        hotkey.triggered.connect(window.read_clipboard)
        hotkey.start()
        if hotkey.is_running():
            self._hotkey = hotkey

    def _start_tray(self, window: MainWindow) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = TrayIcon(
            parent=None,
            icon=app_icon(),
            on_show=window.show_and_raise,
            on_hide=window.hide,
            on_read_clipboard=window.read_clipboard,
            on_pause_resume=window.toggle_pause,
            on_quit=window.quit_app,
        )
        tray.update_playback_state(self._playback.state())
        self._playback.state_changed.connect(
            lambda state: tray.update_playback_state(PlaybackState(state))
        )
        tray.show()
        self._tray = tray

    def _apply_residency(self, window: MainWindow) -> None:
        """While the hotkey works, closing the window hides it to the tray instead."""
        if self._tray is not None:
            self._tray.set_hotkey(self._settings.hotkey if self._hotkey is not None else None)
        resident = self._tray is not None and self._hotkey is not None
        window.set_close_to_tray(resident)
        self._app.setQuitOnLastWindowClosed(not resident)

    def _on_preferences_changed(self) -> None:
        window = self._main_window
        if window is None:
            return
        self._apply_hotkey(window)
        self._apply_residency(window)
        if self._settings.hotkey_enabled and self._hotkey is None:
            QMessageBox.warning(
                window,
                "Hotkey",
                f"Couldn't register {format_hotkey(self._settings.hotkey)}. Another app may "
                "already use it, or the `keyboard` package isn't available.",
            )

    def _on_hidden_to_tray(self) -> None:
        if self._tray is None or self._tray_hint_shown:
            return
        self._tray_hint_shown = True
        self._tray.showMessage(
            "TTS is still running",
            f"Press {format_hotkey(self._settings.hotkey)} to read the clipboard. "
            "Right-click the tray icon to quit.",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def _shutdown(self) -> None:
        if self._hotkey is not None:
            self._hotkey.stop()
        if self._tray is not None:
            self._tray.hide()
        if self._main_window is not None:
            self._main_window.cancel_save()  # else a half-written .part is left behind
        self._playback.shutdown()
        if self._probe is not None:
            self._probe.wait(5000)  # a QThread destroyed while running aborts the process

    def _try_acquire_singleton(self) -> bool:
        QLocalServer.removeServer("TTSApp.singleton")
        self._local_server = QLocalServer()

        if self._local_server.listen("TTSApp.singleton"):
            def on_new_connection() -> None:
                conn = self._local_server.nextPendingConnection()
                if conn and self._main_window:
                    self._main_window.show_and_raise()
                if conn:
                    conn.disconnectFromServer()

            self._local_server.newConnection.connect(on_new_connection)
            return True

        socket = QLocalSocket()
        socket.connectToServer("TTSApp.singleton")
        if socket.waitForConnected(500):
            socket.write(b"show")
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer("TTSApp.singleton")
        return self._local_server.listen("TTSApp.singleton")

