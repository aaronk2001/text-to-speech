from __future__ import annotations

import sys
from typing import ClassVar

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from tts_app.audio.playback import PlaybackController
from tts_app.config import load_settings, save_settings
from tts_app.engines.registry import EngineRegistry, build_default_engines
from tts_app.ui.main_window import MainWindow
from tts_app.ui.motion import init_motion
from tts_app.ui.theme import apply_nexus_dark


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

        self._registry = EngineRegistry(build_default_engines())
        self._playback = PlaybackController()
        self._settings = load_settings()

        apply_nexus_dark(self._app)
        init_motion(self._settings)

        self._main_window: MainWindow | None = None
        self._local_server: QLocalServer | None = None
        self._probe: _EngineProbeThread | None = None

    def run(self) -> int:
        if not self._try_acquire_singleton():
            return 0

        self._main_window = MainWindow(
            self._registry, self._playback, self._settings
        )
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

        self._probe = _EngineProbeThread(self._registry)
        self._probe.completed.connect(self._main_window.on_engines_probed)
        QTimer.singleShot(0, self._probe.start)

        if not self._settings.first_run_complete:
            self._settings.first_run_complete = True
            save_settings(self._settings)

        return self._app.exec()

    def _try_acquire_singleton(self) -> bool:
        QLocalServer.removeServer("TTSApp.singleton")
        self._local_server = QLocalServer()

        if self._local_server.listen("TTSApp.singleton"):
            def on_new_connection() -> None:
                conn = self._local_server.nextPendingConnection()
                if conn and self._main_window:
                    self._main_window.raise_()
                    self._main_window.activateWindow()
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

