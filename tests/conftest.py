"""Shared fakes: an in-memory QAudioSink so playback runs without a sound card."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtMultimedia import QAudio

from tts_app.audio import playback


class _FakeSignal:
    def __init__(self) -> None:
        self._slots: list[Any] = []

    def connect(self, slot: Any) -> None:
        self._slots.append(slot)

    def emit(self, *args: Any) -> None:
        for slot in list(self._slots):
            slot(*args)


class _FakeIO:
    def __init__(self, sink: FakeSink) -> None:
        self._sink = sink

    def write(self, data: bytes) -> int:
        self._sink.written.extend(data)
        if self._sink.state() != QAudio.State.SuspendedState:  # a paused device stays paused
            self._sink.set_state(QAudio.State.ActiveState)
        return len(data)


class FakeSink:
    """Records writes; each test decides when the 'device' has played everything."""

    instances: list[FakeSink] = []
    free_bytes = 10**9

    def __init__(self, device: Any, fmt: Any) -> None:
        self.stateChanged = _FakeSignal()
        self.written = bytearray()
        self.free = FakeSink.free_bytes
        self.processed_us = 0
        self._state = QAudio.State.StoppedState
        FakeSink.instances.append(self)

    def setBufferSize(self, n: int) -> None:
        pass

    def start(self) -> _FakeIO:
        self.set_state(QAudio.State.IdleState)  # push mode starts out idle
        return _FakeIO(self)

    def bytesFree(self) -> int:
        return self.free

    def processedUSecs(self) -> int:
        return self.processed_us

    def state(self) -> QAudio.State:
        return self._state

    def suspend(self) -> None:
        self.set_state(QAudio.State.SuspendedState)

    def resume(self) -> None:
        self.set_state(QAudio.State.ActiveState)

    def stop(self) -> None:
        self.set_state(QAudio.State.StoppedState)

    def set_state(self, state: QAudio.State) -> None:
        if state != self._state:
            self._state = state
            self.stateChanged.emit(state)

    def run_dry(self) -> None:
        """Everything written so far has been played."""
        self.set_state(QAudio.State.IdleState)


class _FakeDevice:
    def isNull(self) -> bool:
        return False


class _FakeMediaDevices:
    @staticmethod
    def defaultAudioOutput() -> _FakeDevice:
        return _FakeDevice()


@pytest.fixture
def fake_audio(monkeypatch: pytest.MonkeyPatch) -> type[FakeSink]:
    """Route PlaybackController output into FakeSink instances."""
    monkeypatch.setattr(FakeSink, "instances", [])
    monkeypatch.setattr(FakeSink, "free_bytes", 10**9)
    monkeypatch.setattr(playback, "QAudioSink", FakeSink)
    monkeypatch.setattr(playback, "QMediaDevices", _FakeMediaDevices)
    return FakeSink
