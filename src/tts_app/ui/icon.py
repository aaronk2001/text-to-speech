from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap


def app_icon() -> QIcon:
    """An off-white disc with a dark play notch, drawn at icon sizes."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, size - 1, size - 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ededed"))
        p.drawEllipse(rect)

        # Laid out on an 18-unit grid: the notch spans 7x7 around the centre.
        u = size / 18
        cx = size / 2 - u
        cy = size / 2
        notch = QPainterPath()
        notch.moveTo(cx - 3 * u, cy - 3.5 * u)
        notch.lineTo(cx + 4 * u, cy)
        notch.lineTo(cx - 3 * u, cy + 3.5 * u)
        notch.closeSubpath()
        p.setBrush(QColor("#121212"))
        p.drawPath(notch)

        p.end()
        icon.addPixmap(pm)
    return icon
