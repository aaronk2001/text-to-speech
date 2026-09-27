from __future__ import annotations

from PySide6.QtCore import Property, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSlider, QWidget

from tts_app.ui.motion import should_animate


class TransportProgressSlider(QSlider):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("progressSlider")
        self._phase = 0.0
        self._sweeping = False
        self.setMinimumHeight(20)

        self._anim = QPropertyAnimation(self, b"phase", self)
        self._anim.setDuration(2200)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)

    def get_phase(self) -> float:
        return self._phase

    def set_phase(self, value: float) -> None:
        self._phase = value
        self.update()

    phase = Property(float, get_phase, set_phase)

    def start_sweep(self) -> None:
        if not should_animate():
            self.stop_sweep()
            return
        if not self._sweeping:
            self._sweeping = True
            self._anim.start()
            self.update()

    def stop_sweep(self) -> None:
        self._sweeping = False
        self._anim.stop()
        self._phase = 0.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        w = rect.width()
        h = rect.height()

        groove_h = 6
        groove_y = (h - groove_h) / 2
        groove_rect = QRectF(0.0, groove_y, float(w), float(groove_h))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(groove_rect, 3, 3)

        span = max(1, self.maximum() - self.minimum())
        ratio = (self.value() - self.minimum()) / span
        fill_w = float(w) * ratio

        if fill_w > 0:
            fill_rect = QRectF(0.0, groove_y, fill_w, float(groove_h))
            if self._sweeping:
                grad = QLinearGradient(0.0, 0.0, float(w), 0.0)
                phase = self._phase
                lo = max(0.0, phase - 0.18)
                hi = min(1.0, phase + 0.18)
                grad.setColorAt(0.0, QColor("#3b82f6"))
                if lo > 0.0:
                    grad.setColorAt(lo, QColor("#3b82f6"))
                grad.setColorAt(phase, QColor("#8b5cf6"))
                if hi < 1.0:
                    grad.setColorAt(hi, QColor("#3b82f6"))
                grad.setColorAt(1.0, QColor("#3b82f6"))
                p.setBrush(grad)
            else:
                p.setBrush(QColor("#3b82f6"))

            p.save()
            p.setClipRect(fill_rect)
            p.drawRoundedRect(QRectF(0.0, groove_y, float(w), float(groove_h)), 3, 3)
            p.restore()

        if span > 0:
            handle_size = 14.0
            handle_x = fill_w - handle_size / 2
            handle_x = max(0.0, min(handle_x, float(w) - handle_size))
            handle_y = (h - handle_size) / 2
            p.setBrush(QColor("#f8fafc"))
            p.setPen(QPen(QColor("#3b82f6"), 2))
            p.drawEllipse(QRectF(handle_x, handle_y, handle_size, handle_size))
