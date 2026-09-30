from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class Wordmark(QWidget):
    GLYPH = 18
    GAP = 10

    def __init__(self, text: str = "TTS", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._font = QFont("Archivo", 14)
        self._font.setWeight(QFont.Weight.Bold)
        self._font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.6)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(28)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font)
        return QSize(self.GLYPH + self.GAP + fm.horizontalAdvance(self._text), 28)

    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        gx, gy = 0.0, (self.height() - self.GLYPH) / 2
        glyph_rect = QRectF(gx, gy, self.GLYPH, self.GLYPH)
        grad = QLinearGradient(gx, gy, gx + self.GLYPH, gy + self.GLYPH)
        grad.setColorAt(0.0, QColor("#60a5fa"))
        grad.setColorAt(0.55, QColor("#3b82f6"))
        grad.setColorAt(1.0, QColor("#8b5cf6"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(glyph_rect)

        # inner notch — turns a circle into a "play" silhouette without explicit emoji
        path = QPainterPath()
        cx = gx + self.GLYPH / 2 - 1
        cy = gy + self.GLYPH / 2
        path.moveTo(cx - 3, cy - 3.5)
        path.lineTo(cx + 4, cy)
        path.lineTo(cx - 3, cy + 3.5)
        path.closeSubpath()
        p.setBrush(QColor("#f8fafc"))
        p.drawPath(path)

        p.setFont(self._font)
        p.setPen(QColor("#f8fafc"))
        text_x = self.GLYPH + self.GAP
        fm = QFontMetrics(self._font)
        baseline = (self.height() + fm.ascent() - fm.descent()) / 2
        p.drawText(QPointF(text_x, baseline), self._text)


class StatusDot(QWidget):
    COLORS = {
        "idle":         "#475569",
        "synthesizing": "#f59e0b",
        "playing":      "#22c55e",
        "paused":       "#f59e0b",
        "error":        "#ef4444",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self.setFixedSize(16, 16)
        self.setToolTip("Idle")

    def set_state(self, state: str, tooltip: str | None = None) -> None:
        if state not in self.COLORS:
            state = "idle"
        self._state = state
        self.setToolTip(tooltip or state.capitalize())
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 8, 8
        color = QColor(self.COLORS[self._state])

        if self._state in ("playing", "synthesizing"):
            glow = QRadialGradient(cx, cy, 8)
            glow.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 110))
            glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(0, 0, 16, 16))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))


class HamburgerButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "icon")
        self.setFixedSize(36, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#8a8a8a") if not self.underMouse() else QColor("#ededed")
        pen = QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        for dy in (-4, 0, 4):
            p.drawLine(QPointF(cx - 6, cy + dy), QPointF(cx + 6, cy + dy))


class ErrorBanner(QWidget):
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout()
        row.setContentsMargins(14, 10, 10, 10)
        row.setSpacing(10)

        self._icon = QLabel("⚠")
        self._icon.setStyleSheet("color: #e5736b; font-size: 14px;")
        self._icon.setFixedWidth(18)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: #e8c4c0; font-size: 13px;")

        self._dismiss = QPushButton("✕")
        self._dismiss.setProperty("role", "icon")
        self._dismiss.setFixedSize(24, 24)
        self._dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss.clicked.connect(self._on_dismiss)

        row.addWidget(self._icon)
        row.addWidget(self._label, stretch=1)
        row.addWidget(self._dismiss)

        self.setLayout(row)
        self.setStyleSheet(
            "ErrorBanner { background-color: rgba(229,115,107,0.08);"
            " border: none; border-radius: 8px; }"
        )

    def show_error(self, message: str) -> None:
        self._label.setText(message)
        self.setVisible(True)

    def _on_dismiss(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()
