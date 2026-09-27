from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap


def app_icon() -> QIcon:
    """The wordmark glyph (gradient disc with a play notch), drawn at icon sizes."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, size - 1, size - 1)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor("#60a5fa"))
        grad.setColorAt(0.55, QColor("#3b82f6"))
        grad.setColorAt(1.0, QColor("#8b5cf6"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(rect)

        # Same proportions as Wordmark: 18px disc, notch spans 7x7 around centre.
        u = size / 18
        cx = size / 2 - u
        cy = size / 2
        notch = QPainterPath()
        notch.moveTo(cx - 3 * u, cy - 3.5 * u)
        notch.lineTo(cx + 4 * u, cy)
        notch.lineTo(cx - 3 * u, cy + 3.5 * u)
        notch.closeSubpath()
        p.setBrush(QColor("#f8fafc"))
        p.drawPath(notch)

        p.end()
        icon.addPixmap(pm)
    return icon
