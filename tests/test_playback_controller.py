"""PlaybackController behaviour against a fake QAudioSink (no audio device needed)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from tts_app.audio.playback import BYTES_PER_SECOND, PlaybackController, PlaybackState
from tts_app.text.segment import segment_text

from .conftest import FakeSink


@pytest.fixture
def controller(qtbot: Any, fake_audio: type[FakeSink]) -> Iterator[PlaybackController]:
    c = PlaybackController()
    yield c
    c.shutdown()


def _pcm(seconds: float) -> bytes:
    return b"\x01\x00" * int(BYTES_PER_SECOND * seconds / 2)


def test_plays_to_completion(controller: PlaybackController, qtbot: Any) -> None:
    audio = _pcm(0.5)
    controller.play(lambda: iter([audio]))
    qtbot.waitUntil(lambda: controller._synthesis_done)
    sink = FakeSink.instances[-1]
    assert bytes(sink.written) == audio

    with qtbot.waitSignal(controller.finished, timeout=1000):
        sink.run_dry()
    assert controller.state() == PlaybackState.IDLE


def test_audio_queued_before_stop_is_dropped(
    controller: PlaybackController, qtbot: Any
) -> None:
    produced = threading.Event()

    def synth() -> Iterator[bytes]:
        for _ in range(200):
            yield _pcm(0.01)
            produced.set()
            time.sleep(0.002)

    controller.play(synth)
    assert produced.wait(2)
    time.sleep(0.05)  # chunks pile up in the event queue; this thread isn't draining it
    controller.stop()
    qtbot.wait(100)  # now deliver everything that was queued before stop()

    assert controller.state() == PlaybackState.IDLE
    assert FakeSink.instances == []  # nothing restarted the audio


def test_stop_does_not_wait_for_a_busy_engine(
    controller: PlaybackController, qtbot: Any
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def synth() -> Iterator[bytes]:
        entered.set()
        release.wait(5)
        yield _pcm(0.01)

    controller.play(synth)
    assert entered.wait(2)

    t0 = time.monotonic()
    controller.stop()
    assert time.monotonic() - t0 < 0.5
    assert controller.state() == PlaybackState.IDLE

    release.set()
    qtbot.waitUntil(lambda: not controller._retired, timeout=3000)


def test_restarts_never_synthesize_concurrently(
    controller: PlaybackController, qtbot: Any
) -> None:
    guard = threading.Lock()
    active = 0
    peak = 0

    def synth() -> Iterator[bytes]:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            for _ in range(20):
                time.sleep(0.005)
                yield _pcm(0.01)
        finally:
            with guard:
                active -= 1

    for _ in range(5):
        controller.play(synth)
        qtbot.wait(15)
    controller.stop()
    qtbot.waitUntil(lambda: not controller._retired, timeout=3000)

    assert peak == 1


def test_finishes_when_sink_ran_dry_before_synthesis_ended(
    controller: PlaybackController, qtbot: Any
) -> None:
    release = threading.Event()

    def synth() -> Iterator[bytes]:
        yield _pcm(0.2)
        release.wait(5)  # e.g. a trailing segment that produces no audio

    controller.play(synth)
    qtbot.waitUntil(lambda: controller.state() == PlaybackState.PLAYING)
    FakeSink.instances[-1].run_dry()
    assert controller.state() == PlaybackState.PLAYING  # synthesis still running

    with qtbot.waitSignal(controller.finished, timeout=2000):
        release.set()
    assert controller.state() == PlaybackState.IDLE


def test_underrun_with_audio_pending_does_not_finish(
    controller: PlaybackController, qtbot: Any
) -> None:
    FakeSink.free_bytes = 1000  # the device only takes a little at a time
    audio = _pcm(0.5)
    controller.play(lambda: iter([audio]))
    qtbot.waitUntil(lambda: controller._synthesis_done)
    sink = FakeSink.instances[-1]
    sink.free = 0
    assert 0 < len(sink.written) < len(audio)

    sink.run_dry()  # played what it had while the rest is still queued on our side
    assert controller.state() == PlaybackState.PLAYING

    sink.free = 10**9
    qtbot.waitUntil(lambda: len(sink.written) == len(audio))
    with qtbot.waitSignal(controller.finished, timeout=1000):
        sink.run_dry()


def test_segment_highlight_follows_playback_position(
    controller: PlaybackController, qtbot: Any
) -> None:
    text = "First one. Second one."
    highlights: list[str] = []
    controller.segment_changed.connect(lambda s, e: highlights.append(text[s:e]))

    controller.play_segments(segment_text(text), lambda seg: iter([_pcm(1.0)]))
    qtbot.waitUntil(lambda: controller._synthesis_done)

    # Both segments are synthesized, but only the first is being heard.
    assert highlights == ["First one."]

    FakeSink.instances[-1].processed_us = 1_500_000
    qtbot.waitUntil(lambda: len(highlights) == 2)
    assert highlights == ["First one.", "Second one."]


def test_synthesis_error_is_reported(controller: PlaybackController, qtbot: Any) -> None:
    def synth() -> Iterator[bytes]:
        raise RuntimeError("engine exploded")
        yield b""

    with qtbot.waitSignal(controller.error, timeout=2000) as blocker:
        controller.play(synth)
    assert "engine exploded" in blocker.args[0]
    assert controller.state() == PlaybackState.IDLE
