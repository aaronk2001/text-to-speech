from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from tts_app.config import AppSettings
from tts_app.engines.base import Voice

# Qt portable key names -> names the `keyboard` package understands.
_QT_TO_KEYBOARD = {
    "meta": "windows",
    "pgup": "page up",
    "pgdown": "page down",
    "del": "delete",
    "ins": "insert",
    "return": "enter",
}
_KEYBOARD_TO_QT = {v: k for k, v in _QT_TO_KEYBOARD.items()}


def sequence_to_hotkey(seq: QKeySequence) -> str:
    """First chord of a QKeySequence as a `keyboard` spec, e.g. 'ctrl+alt+s'."""
    if seq.isEmpty():
        return ""
    # Multi-chord sequences print as "Ctrl+K, Ctrl+S"; only the first chord is used.
    text = seq.toString(QKeySequence.SequenceFormat.PortableText).split(", ")[0]
    # "Ctrl++" means Ctrl and the plus key; keep that last '+' as a key.
    parts = text[:-2].split("+") + ["plus"] if text.endswith("++") else text.split("+")
    return "+".join(_QT_TO_KEYBOARD.get(p.lower(), p.lower()) for p in parts if p)


def hotkey_to_sequence(spec: str) -> QKeySequence:
    names = []
    for part in (p.strip().lower() for p in spec.split("+")):
        if part:
            names.append("+" if part == "plus" else _KEYBOARD_TO_QT.get(part, part).title())
    return QKeySequence("+".join(names))


class PreferencesDialog(QDialog):
    """Edits the settings that have no other UI. Writes into `settings` on OK."""

    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        rvc_base_voices: list[Voice] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self._settings = settings

        self._hotkey_enabled = QCheckBox("Read the clipboard with a global hotkey")
        self._hotkey_enabled.setChecked(settings.hotkey_enabled)

        self._hotkey = QKeySequenceEdit(hotkey_to_sequence(settings.hotkey))
        self._hotkey.setMaximumSequenceLength(1)
        self._hotkey.setClearButtonEnabled(True)
        self._hotkey.setEnabled(settings.hotkey_enabled)
        self._hotkey_enabled.toggled.connect(self._hotkey.setEnabled)

        self._preview_text = QLineEdit(settings.preview_text)

        # Which voice RVC converts from; only offered when there's a choice to make.
        self._rvc_base: QComboBox | None = None
        if rvc_base_voices:
            self._rvc_base = QComboBox()
            self._rvc_base.addItem("First available", None)
            for v in rvc_base_voices:
                self._rvc_base.addItem(v.display, v.id)
            index = self._rvc_base.findData(settings.rvc_base_voice_id)
            self._rvc_base.setCurrentIndex(max(index, 0))

        self._error = QLabel()
        self._error.setProperty("role", "bodyMuted")
        self._error.setVisible(False)

        form = QFormLayout()
        form.addRow(self._hotkey_enabled)
        form.addRow("Hotkey", self._hotkey)
        form.addRow("Preview text", self._preview_text)
        if self._rvc_base is not None:
            form.addRow("RVC speaks from", self._rvc_base)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addWidget(buttons)

    def accept(self) -> None:
        enabled = self._hotkey_enabled.isChecked()
        spec = sequence_to_hotkey(self._hotkey.keySequence())
        if enabled and not spec:
            self._error.setText("Press a key combination for the hotkey, or turn it off.")
            self._error.setVisible(True)
            return
        self._settings.hotkey_enabled = enabled
        if spec:
            self._settings.hotkey = spec
        if self._rvc_base is not None:
            self._settings.rvc_base_voice_id = self._rvc_base.currentData()
        self._settings.preview_text = (
            self._preview_text.text().strip() or AppSettings().preview_text
        )
        super().accept()
