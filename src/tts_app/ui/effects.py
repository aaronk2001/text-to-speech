"""Micro-animation helpers — hover glow + opacity pulse.

Mirrors the .btn-accent:hover { box-shadow: var(--shadow-glow) } pattern from
aaron-portfolio-site/app/globals.css using QGraphicsDropShadowEffect with an
animated blur radius (Qt has no QSS box-shadow).
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QWidget

from tts_app.ui.motion import should_animate


class HoverGlow(QObject):
    def __init__(
        self,
        widget: QWidget,
        color: str = "#3b82f6",
        max_radius: int = 28,
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._effect = QGraphicsDropShadowEffect(widget)
        self._effect.setColor(QColor(color))
        self._effect.setOffset(0, 0)
        self._effect.setBlurRadius(0)
        widget.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"blurRadius", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._max = max_radius

        widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        et = event.type()
        if et == QEvent.Type.Enter:
            if not should_animate():
                return False
            self._anim.stop()
            self._anim.setStartValue(self._effect.blurRadius())
            self._anim.setEndValue(self._max)
            self._anim.start()
        elif et == QEvent.Type.Leave:
            self._anim.stop()
            self._anim.setStartValue(self._effect.blurRadius())
            self._anim.setEndValue(0)
            self._anim.start()
        return False


class OpacityPulse(QObject):
    """Looping opacity oscillation — used for the playing-status indicator."""

    def __init__(
        self,
        widget: QWidget,
        period_ms: int = 1400,
        floor: float = 0.45,
    ) -> None:
        super().__init__(widget)
        self._effect = QGraphicsOpacityEffect(widget)
        self._effect.setOpacity(1.0)
        widget.setGraphicsEffect(self._effect)

        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(period_ms)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, floor)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    def start(self) -> None:
        if not should_animate():
            self._effect.setOpacity(1.0)
            return
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        self._effect.setOpacity(1.0)
