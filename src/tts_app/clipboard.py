from __future__ import annotations

from PySide6.QtWidgets import QApplication


def read_clipboard_text(app: QApplication) -> str:
    text = app.clipboard().text()
    return text.strip() if text else ""
