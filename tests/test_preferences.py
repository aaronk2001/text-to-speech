from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtGui import QKeySequence

from tts_app.config import AppSettings
from tts_app.ui.preferences import PreferencesDialog, hotkey_to_sequence, sequence_to_hotkey


@pytest.mark.parametrize(
    "spec",
    ["ctrl+alt+s", "windows+f1", "ctrl+page up", "ctrl+plus", "shift+delete", "alt+space"],
)
def test_hotkey_spec_round_trips_through_qt(qapp: Any, spec: str) -> None:
    assert sequence_to_hotkey(hotkey_to_sequence(spec)) == spec


def test_ok_writes_settings(qtbot: Any) -> None:
    settings = AppSettings()
    dialog = PreferencesDialog(settings)
    qtbot.addWidget(dialog)
    dialog._hotkey.setKeySequence(QKeySequence("Ctrl+Shift+R"))
    dialog._preview_text.setText("Testing one two.")

    dialog.accept()

    assert settings.hotkey == "ctrl+shift+r"
    assert settings.preview_text == "Testing one two."
    assert dialog.result() == 1


def test_enabled_hotkey_needs_a_key(qtbot: Any) -> None:
    settings = AppSettings()
    dialog = PreferencesDialog(settings)
    qtbot.addWidget(dialog)
    dialog._hotkey.clear()

    dialog.accept()

    assert dialog.result() != 1
    assert settings.hotkey == "ctrl+alt+s"
    assert not dialog._error.isHidden()


def test_disabling_keeps_the_old_binding(qtbot: Any) -> None:
    settings = AppSettings(hotkey="ctrl+alt+r")
    dialog = PreferencesDialog(settings)
    qtbot.addWidget(dialog)
    dialog._hotkey_enabled.setChecked(False)
    dialog._hotkey.clear()

    dialog.accept()

    assert settings.hotkey_enabled is False
    assert settings.hotkey == "ctrl+alt+r"
