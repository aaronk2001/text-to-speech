from __future__ import annotations

import logging
from typing import ClassVar

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

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

        self._start_hotkey(self._main_window)
        self._start_tray(self._main_window)
        self._app.aboutToQuit.connect(self._shutdown)

        self._probe = _EngineProbeThread(self._registry)
        self._probe.completed.connect(self._main_window.on_engines_probed)
        QTimer.singleShot(0, self._probe.start)

        if not self._settings.first_run_complete:
            self._settings.first_run_complete = True
            save_settings(self._settings)

        return self._app.exec()

    def _start_hotkey(self, window: MainWindow) -> None:
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
            hotkey=self._settings.hotkey if self._hotkey is not None else None,
        )
        tray.update_playback_state(self._playback.state())
        self._playback.state_changed.connect(
            lambda state: tray.update_playback_state(PlaybackState(state))
        )
        tray.show()
        self._tray = tray

        if self._hotkey is not None:
            # Keep running after the window is closed so the hotkey still works.
            window.set_close_to_tray(True)
            window.hidden_to_tray.connect(self._on_hidden_to_tray)
            self._app.setQuitOnLastWindowClosed(False)

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

