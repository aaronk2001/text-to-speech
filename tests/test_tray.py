from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from tts_app.ui.tray import TrayIcon
from tts_app.audio.playback import PlaybackState


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_tray_icon_constructs(qapp):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("System tray not available")

    icon_path = Path(__file__).parent / "fixtures" / "test_icon.png"
    icon_path.parent.mkdir(exist_ok=True)
    icon_path.touch()

    callbacks = {
        "show": MagicMock(),
        "hide": MagicMock(),
        "read_clipboard": MagicMock(),
        "pause_resume": MagicMock(),
        "quit": MagicMock(),
    }

    tray = TrayIcon(
        parent=None,
        icon=icon_path,
        on_show=callbacks["show"],
        on_hide=callbacks["hide"],
        on_read_clipboard=callbacks["read_clipboard"],
        on_pause_resume=callbacks["pause_resume"],
        on_quit=callbacks["quit"],
    )

    assert tray is not None


def test_tray_update_playback_state_playing(qapp):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("System tray not available")

    icon_path = Path(__file__).parent / "fixtures" / "test_icon.png"
    icon_path.parent.mkdir(exist_ok=True)
    icon_path.touch()

    tray = TrayIcon(
        parent=None,
        icon=icon_path,
        on_show=MagicMock(),
        on_hide=MagicMock(),
        on_read_clipboard=MagicMock(),
        on_pause_resume=MagicMock(),
        on_quit=MagicMock(),
    )

    tray.update_playback_state(PlaybackState.PLAYING)
    assert tray._pause_action.text() == "Pause"
    assert tray._pause_action.isEnabled()


def test_tray_update_playback_state_paused(qapp):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("System tray not available")

    icon_path = Path(__file__).parent / "fixtures" / "test_icon.png"
    icon_path.parent.mkdir(exist_ok=True)
    icon_path.touch()

    tray = TrayIcon(
        parent=None,
        icon=icon_path,
        on_show=MagicMock(),
        on_hide=MagicMock(),
        on_read_clipboard=MagicMock(),
        on_pause_resume=MagicMock(),
        on_quit=MagicMock(),
    )

    tray.update_playback_state(PlaybackState.PAUSED)
    assert tray._pause_action.text() == "Resume"
    assert tray._pause_action.isEnabled()


def test_tray_update_playback_state_idle(qapp):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("System tray not available")

    icon_path = Path(__file__).parent / "fixtures" / "test_icon.png"
    icon_path.parent.mkdir(exist_ok=True)
    icon_path.touch()

    tray = TrayIcon(
        parent=None,
        icon=icon_path,
        on_show=MagicMock(),
        on_hide=MagicMock(),
        on_read_clipboard=MagicMock(),
        on_pause_resume=MagicMock(),
        on_quit=MagicMock(),
    )

    tray.update_playback_state(PlaybackState.IDLE)
    assert not tray._pause_action.isEnabled()
