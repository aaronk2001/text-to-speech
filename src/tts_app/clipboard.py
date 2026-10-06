from __future__ import annotations

from PySide6.QtWidgets import QApplication

from tts_app.text.tables import tsv_to_speech


def read_clipboard_text(app: QApplication) -> str:
    text = app.clipboard().text()
    return tsv_to_speech(text).strip() if text else ""
