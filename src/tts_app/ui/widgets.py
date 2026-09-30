from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

ENGINE_LABELS = {"sapi": "Windows", "piper": "Piper", "supertonic": "Supertonic", "rvc": "RVC"}


def engine_label(name: str) -> str:
    return ENGINE_LABELS.get(name, name.title())


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
