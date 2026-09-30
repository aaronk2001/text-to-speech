"""Graphite theme: flat monochrome dark with a single warm accent."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

TOKENS: dict[str, str] = {
    "bg":        "#121212",
    "bg_raised": "#1a1a1a",
    "bg_hover":  "#242424",
    "text":      "#ededed",
    "text_dim":  "#a3a3a3",
    "text_muted": "#6b6b6b",
    "accent":    "#e0a458",
}


def _load_embedded_fonts() -> None:
    fonts_dir = Path(__file__).resolve().parent.parent / "resources" / "fonts"
    if not fonts_dir.is_dir():
        return
    for ttf in fonts_dir.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(ttf))
    for otf in fonts_dir.glob("*.otf"):
        QFontDatabase.addApplicationFont(str(otf))


def apply_nexus_dark(app: QApplication) -> None:
    app.setStyle("Fusion")
    _load_embedded_fonts()

    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(TOKENS["bg"]))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(TOKENS["text"]))
    p.setColor(QPalette.ColorRole.Base,            QColor(TOKENS["bg"]))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(TOKENS["bg_raised"]))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(TOKENS["bg_hover"]))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(TOKENS["text"]))
    p.setColor(QPalette.ColorRole.Text,            QColor(TOKENS["text"]))
    p.setColor(QPalette.ColorRole.Button,          QColor(TOKENS["bg_raised"]))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(TOKENS["text"]))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(TOKENS["bg_hover"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#5c5c5c"))
    app.setPalette(p)

    qss_path = Path(__file__).resolve().parent / "styles.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
