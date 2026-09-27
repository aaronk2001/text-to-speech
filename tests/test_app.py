"""App wiring: hotkey and tray follow the settings, including after Preferences."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tts_app import app as app_module
from tts_app.config import AppSettings
from tts_app.hotkey import global_hotkey
from tts_app.ui import main_window
from tts_app.ui.main_window import MainWindow

from .conftest import FakeSink
from .test_main_window import _ToneEngine


class _Keyboard:
    def __init__(self) -> None:
        self.bound: list[str] = []
        self.fail_on: set[str] = set()

    def add_hotkey(self, spec: str, callback: Any, **kwargs: Any) -> str:
        if spec in self.fail_on:
            raise ValueError(f"can't bind {spec}")
        self.bound.append(spec)
        return spec

    def remove_hotkey(self, handle: str) -> None:
        self.bound.remove(handle)


class _Tray:
    """Stand-in for TrayIcon; the real system tray isn't available headless."""

    def __init__(self, **kwargs: Any) -> None:
        self.hotkey: str | None = None

    def set_hotkey(self, hotkey: str | None) -> None:
        self.hotkey = hotkey

    def update_playback_state(self, state: Any) -> None:
        pass

    def show(self) -> None:
        pass

    def hide(self) -> None:
        pass


@pytest.fixture
def keyboard(monkeypatch: pytest.MonkeyPatch) -> _Keyboard:
    kb = _Keyboard()
    monkeypatch.setattr(global_hotkey, "_try_import_keyboard", lambda: kb)
    return kb


@pytest.fixture
def app(
    qtbot: Any,
    fake_audio: type[FakeSink],
    keyboard: _Keyboard,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[app_module.App]:
    monkeypatch.setattr(app_module, "build_default_engines", lambda: [_ToneEngine()])
    monkeypatch.setattr(app_module, "load_settings", AppSettings)
    monkeypatch.setattr(main_window, "save_settings", lambda _settings: None)
    monkeypatch.setattr(app_module, "TrayIcon", _Tray)
    monkeypatch.setattr(
        app_module.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True)
    )
    a = app_module.App([])
    window = MainWindow(a._registry, a._playback, a._settings)
    qtbot.addWidget(window)
    a._main_window = window
    a._apply_hotkey(window)
    a._start_tray(window)
    a._apply_residency(window)
    yield a
    a._shutdown()
    a._app.setQuitOnLastWindowClosed(True)


def test_startup_binds_hotkey_and_stays_resident(app: app_module.App, keyboard: _Keyboard) -> None:
    assert keyboard.bound == ["ctrl+alt+s"]
    assert app._tray.hotkey == "ctrl+alt+s"
    assert app._main_window._close_to_tray


def test_changing_the_hotkey_rebinds_live(app: app_module.App, keyboard: _Keyboard) -> None:
    app._settings.hotkey = "ctrl+shift+r"
    app._on_preferences_changed()

    assert keyboard.bound == ["ctrl+shift+r"]
    assert app._tray.hotkey == "ctrl+shift+r"


def test_disabling_the_hotkey_stops_close_to_tray(
    app: app_module.App, keyboard: _Keyboard
) -> None:
    app._settings.hotkey_enabled = False
    app._on_preferences_changed()

    assert keyboard.bound == []
    assert app._tray.hotkey is None
    assert not app._main_window._close_to_tray


def test_unbindable_hotkey_warns(
    app: app_module.App, keyboard: _Keyboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        app_module.QMessageBox, "warning", staticmethod(lambda *a: warnings.append(a[2]))
    )
    keyboard.fail_on.add("ctrl+q")
    app._settings.hotkey = "ctrl+q"
    app._on_preferences_changed()

    assert keyboard.bound == []
    assert warnings and "Ctrl+Q" in warnings[0]
    assert not app._main_window._close_to_tray
