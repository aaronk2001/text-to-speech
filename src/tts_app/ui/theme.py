"""NEXUS Dark theme — Qt port of aaron-portfolio-site/globals.css + forge/tokens.css.

Tokens kept verbatim so the TTS app reads as part of the same design family:
- Surfaces:  #020617 / #0a0f1a / #111827 / #1e293b / #334155
- Text:      #f8fafc / #cbd5e1 / #94a3b8 / #475569
- Accent:    #3b82f6 (electric blue) — hover #60a5fa
- Glass:     rgba(255,255,255,0.03) bg / rgba(255,255,255,0.08) border (Qt has
             no backdrop-filter; we approximate with flat surface + hairline border)
- Radii:     6 / 10 / 16 / 24
- Type:      Archivo (heads) / Space Grotesk (body) / JetBrains Mono (data)
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

TOKENS: dict[str, str] = {
    "bg_void":      "#020617",
    "bg_canvas":    "#0a0f1a",
    "bg_surface":   "#111827",
    "bg_elevated":  "#1e293b",
    "bg_overlay":   "#334155",

    "text_primary":   "#f8fafc",
    "text_secondary": "#cbd5e1",
    "text_tertiary":  "#94a3b8",
    "text_muted":     "#475569",

    "accent":         "#3b82f6",
    "accent_hover":   "#60a5fa",
    "accent_glow":    "rgba(59,130,246,0.4)",
    "accent_muted":   "rgba(59,130,246,0.15)",

    "green":  "#22c55e",
    "red":    "#ef4444",
    "yellow": "#f59e0b",
    "purple": "#8b5cf6",
    "cyan":   "#06b6d4",

    "glass_bg":           "rgba(255,255,255,0.03)",
    "glass_bg_hover":     "rgba(255,255,255,0.06)",
    "glass_border":       "rgba(255,255,255,0.08)",
    "glass_border_hover": "rgba(255,255,255,0.12)",

    "radius_sm": "6px",
    "radius_md": "10px",
    "radius_lg": "16px",
    "radius_xl": "24px",
}

FONT_HEADING = "Archivo, 'Space Grotesk', sans-serif"
FONT_BODY    = "'Space Grotesk', -apple-system, sans-serif"
FONT_MONO    = "'JetBrains Mono', 'Cascadia Code', Consolas, monospace"


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
    p.setColor(QPalette.ColorRole.Window,         QColor(TOKENS["bg_void"]))
    p.setColor(QPalette.ColorRole.WindowText,     QColor(TOKENS["text_secondary"]))
    p.setColor(QPalette.ColorRole.Base,           QColor(TOKENS["bg_canvas"]))
    p.setColor(QPalette.ColorRole.AlternateBase,  QColor(TOKENS["bg_surface"]))
    p.setColor(QPalette.ColorRole.ToolTipBase,    QColor(TOKENS["bg_elevated"]))
    p.setColor(QPalette.ColorRole.ToolTipText,    QColor(TOKENS["text_primary"]))
    p.setColor(QPalette.ColorRole.Text,           QColor(TOKENS["text_primary"]))
    p.setColor(QPalette.ColorRole.Button,         QColor(TOKENS["bg_surface"]))
    p.setColor(QPalette.ColorRole.ButtonText,     QColor(TOKENS["text_primary"]))
    p.setColor(QPalette.ColorRole.Highlight,      QColor(TOKENS["accent"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(TOKENS["text_muted"]))
    app.setPalette(p)

    qss_path = Path(__file__).resolve().parent / "styles.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
