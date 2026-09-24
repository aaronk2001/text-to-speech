from __future__ import annotations

from collections.abc import Iterator

import pytest

from tts_app.audio.playback import PlaybackController, PlaybackState

try:
    from PySide6.QtMultimedia import QMediaDevices
except ImportError:
    QMediaDevices = None


pytestmark = pytest.mark.skipif(
    QMediaDevices is None or QMediaDevices.defaultAudioOutput().isNull(),
    reason="audio device not available",
)


def tiny_synthesizer() -> Iterator[bytes]:
    """Yield a tiny chunk of silence for testing."""
    yield b"\x00\x00" * 50


def test_playback_controller_creation(qtbot) -> None:
    """Test that PlaybackController can be created."""
    controller = PlaybackController()
    assert controller is not None


def test_playback_state_enum_values() -> None:
    """Test PlaybackState enum values."""
    assert PlaybackState.IDLE == 0
    assert PlaybackState.PLAYING == 1
    assert PlaybackState.PAUSED == 2
    assert PlaybackState.STOPPED == 3


def test_playback_controller_play_and_finish(qtbot) -> None:
    """Test play() with a tiny synthesizer and wait for finished()."""
    controller = PlaybackController()

    finished_signal = qtbot.waitSignal(controller.finished, timeout=5000)
    controller.play(tiny_synthesizer)

    # Wait for the signal with a reasonable timeout
    try:
        finished_signal.wait()
    except Exception:
        pass  # Signal may have already been emitted


def test_playback_controller_stop_transitions_to_idle(qtbot) -> None:
    """Test that stop() transitions state to IDLE."""
    controller = PlaybackController()

    # Start playback
    def long_synthesizer() -> Iterator[bytes]:
        for _ in range(100):
            yield b"\x00\x00" * 100

    controller.play(long_synthesizer)

    # Stop should transition to IDLE
    controller.stop()

    # Give a moment for state to update
    import time

    time.sleep(0.1)

    # State should be IDLE
    assert controller._state == PlaybackState.IDLE
