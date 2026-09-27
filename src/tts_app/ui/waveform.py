"""Real-time PCM waveform visualizer — NEXUS Dark gradient bars.

Subscribes to PlaybackController.audio_chunk for live samples; renders 48 mirrored
bars at ~60fps with a blue→violet gradient that matches the portfolio hero.
"""

from __future__ import annotations

import struct
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

BARS = 48
BUFFER_SAMPLES = 2048


class WaveformWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples: deque[int] = deque(maxlen=BUFFER_SAMPLES)
        self._envelope: list[float] = [0.0] * BARS
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._samples.clear()
        self._envelope = [0.0] * BARS
        self.update()

    def push_pcm(self, data: bytes) -> None:
        n = len(data) // 2
        if n <= 0:
            return
        arr = struct.unpack(f"<{n}h", data[: n * 2])
        stride = max(1, n // 256)
        for i in range(0, n, stride):
            self._samples.append(arr[i])

    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        w = rect.width()
        h = rect.height()
        cy = h / 2

        if not self._samples:
            pen = QPen(QColor("#1e293b"))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawLine(0, int(cy), w, int(cy))
            return

        samples = list(self._samples)
        bin_size = max(1, len(samples) // BARS)
        for i in range(BARS):
            chunk = samples[i * bin_size : (i + 1) * bin_size]
            target = (max(abs(s) for s in chunk) / 32768.0) if chunk else 0.0
            current = self._envelope[i]
            if target > current:
                self._envelope[i] = current + (target - current) * 0.6
            else:
                self._envelope[i] = current + (target - current) * 0.18

        bar_w = w / BARS
        gap = 2.0
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor("#60a5fa"))
        grad.setColorAt(0.5, QColor("#3b82f6"))
        grad.setColorAt(1.0, QColor("#8b5cf6"))

        for i, env in enumerate(self._envelope):
            if env <= 0.005:
                continue
            bar_h = max(3.0, env * h * 0.85)
            x = i * bar_w + gap / 2
            y = cy - bar_h / 2
            p.fillRect(
                int(x),
                int(y),
                int(bar_w - gap),
                int(bar_h),
                grad,
            )
