from __future__ import annotations

import bisect
import contextlib
import functools
import logging
from collections.abc import Callable, Generator, Iterator
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QIODevice, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

from tts_app.engines.base import SYNTHESIS_LOCK

logger = logging.getLogger(__name__)

SAMPLE_RATE = 22050
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes (s16le)
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH


class PlaybackState(IntEnum):
    IDLE = 0
    SYNTHESIZING = 1
    PLAYING = 2
    PAUSED = 3
    STOPPED = 4


class _SynthWorker(QThread):
    # Every signal carries the run's generation: signals already queued when the
    # controller stops a run are still delivered, and must be told apart.
    chunk = Signal(int, bytes)
    segment_started = Signal(int, int, int)  # generation, start_char, end_char
    finished_ok = Signal(int)
    failed = Signal(int, str)

    def __init__(
        self,
        generation: int,
        synthesize_callable: Callable[[], Iterator[bytes]] | None = None,
        segments: list | None = None,
        segment_synth: Callable[[object], Iterator[bytes]] | None = None,
    ) -> None:
        super().__init__()
        self._generation = generation
        self._synthesize = synthesize_callable
        self._segments = segments
        self._segment_synth = segment_synth

    def run(self) -> None:
        gen = self._generation
        try:
            if self._segments is not None and self._segment_synth is not None:
                segment_synth = self._segment_synth
                for seg in self._segments:
                    if self.isInterruptionRequested():
                        return
                    self.segment_started.emit(gen, seg.start, seg.end)
                    if not self._drain(functools.partial(segment_synth, seg)):
                        return
            elif self._synthesize is not None:
                if not self._drain(self._synthesize):
                    return
            self.finished_ok.emit(gen)
        except Exception as e:
            logger.exception("synthesis worker failed")
            self.failed.emit(gen, str(e))

    def _drain(self, synthesize: Callable[[], Iterator[bytes]]) -> bool:
        """Emit every chunk of one synthesis call; False if interrupted."""
        # A stopped run may still be finishing its current segment; wait for it
        # rather than driving the engine from two threads.
        with SYNTHESIS_LOCK:
            if self.isInterruptionRequested():
                return False
            chunks = synthesize()
            try:
                for c in chunks:
                    if self.isInterruptionRequested():
                        return False
                    if c:
                        self.chunk.emit(self._generation, bytes(c))
            finally:
                # Run the engine's cleanup (temp files, subprocesses) under the lock too.
                if isinstance(chunks, Generator):
                    chunks.close()
        return True


class PlaybackController(QObject):
    state_changed = Signal(int)
    error = Signal(str)
    finished = Signal()
    position_changed = Signal(int, int)  # current_ms, total_ms
    audio_chunk = Signal(bytes)  # raw PCM s16le for visualizers
    synthesizing = Signal()  # emitted at the start of play(), before any chunk arrives
    segment_changed = Signal(int, int)  # start_char, end_char of segment now playing

    def __init__(self) -> None:
        super().__init__()
        self._state = PlaybackState.IDLE
        self._sink: QAudioSink | None = None
        self._sink_io: QIODevice | None = None
        self._worker: _SynthWorker | None = None
        # Stopped workers still unwinding. Kept referenced until they exit:
        # destroying a running QThread aborts the process.
        self._retired: list[_SynthWorker] = []
        self._generation = 0
        # Everything synthesized so far in this run, kept so playback can seek.
        # The sink was opened at _base_bytes and has been fed up to _write_pos.
        self._audio = bytearray()
        self._base_bytes = 0
        self._write_pos = 0
        self._synthesis_done = False
        self._first_chunk_seen = False
        # True once the sink has played everything written to it so far.
        self._sink_drained = False
        # (stream byte offset, start_char, end_char) for each synthesized segment
        self._segment_marks: list[tuple[int, int, int]] = []
        self._current_mark = -1

        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._format = fmt
        self._output_device = QMediaDevices.defaultAudioOutput()
        if self._output_device.isNull():
            logger.warning("No default audio output device")

        self._position_timer = QTimer(self)
        self._position_timer.setInterval(100)
        self._position_timer.timeout.connect(self._emit_position)

        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(20)
        self._pump_timer.timeout.connect(self._pump)

    def state(self) -> PlaybackState:
        return self._state

    @property
    def duration_ms(self) -> int:
        return _bytes_to_ms(len(self._audio))

    @property
    def position_ms(self) -> int:
        if self._sink is None:
            return 0
        return _bytes_to_ms(self._base_bytes) + int(self._sink.processedUSecs() / 1000)

    def can_seek(self) -> bool:
        return self._sink is not None and self._state in (
            PlaybackState.PLAYING,
            PlaybackState.PAUSED,
        )

    def seek(self, position_ms: int) -> None:
        """Jump within the audio synthesized so far (clamped to what exists)."""
        if not self.can_seek():
            return
        target = int(position_ms) * BYTES_PER_SECOND // 1000
        target = max(0, min(target, len(self._audio)))
        target -= target % (CHANNELS * SAMPLE_WIDTH)
        # A push-mode sink can't rewind, so replace it with one starting at target.
        self._open_sink(target, suspended=self._state == PlaybackState.PAUSED)
        self._current_mark = -1
        self._emit_position()
        if target >= len(self._audio) and self._synthesis_done:
            self._sink_drained = True  # sought to the very end: nothing left to play
            self._maybe_finish()
            return
        self._pump()

    def skip(self, delta_ms: int) -> None:
        if self.can_seek():
            self.seek(self.position_ms + delta_ms)

    def play(self, synthesize_callable: Callable[[], Iterator[bytes]]) -> None:
        self._start(synthesize_callable=synthesize_callable)

    def play_segments(
        self,
        segments: list,
        segment_synth: Callable[[object], Iterator[bytes]],
    ) -> None:
        self._start(segments=segments, segment_synth=segment_synth)

    def _start(self, **worker_args: Any) -> None:
        self.stop()
        if self._output_device.isNull():
            self.error.emit("No audio output device available")
            return

        self._set_state(PlaybackState.SYNTHESIZING)
        self.synthesizing.emit()

        worker = _SynthWorker(self._generation, **worker_args)
        worker.chunk.connect(self._on_chunk)
        worker.segment_started.connect(self._on_segment_started)
        worker.finished_ok.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker = worker
        worker.start()

    def pause(self) -> None:
        if self._sink is not None and self._state == PlaybackState.PLAYING:
            self._sink.suspend()
            self._position_timer.stop()
            self._set_state(PlaybackState.PAUSED)

    def resume(self) -> None:
        if self._sink is not None and self._state == PlaybackState.PAUSED:
            self._sink.resume()
            self._position_timer.start()
            self._set_state(PlaybackState.PLAYING)

    def stop(self) -> None:
        # Invalidate whatever the current worker has already queued.
        self._generation += 1
        self._retire_worker()
        self._position_timer.stop()
        self._pump_timer.stop()
        if self._sink is not None:
            with contextlib.suppress(Exception):
                self._sink.stop()
            self._sink = None
        self._sink_io = None
        self._audio = bytearray()
        self._base_bytes = 0
        self._write_pos = 0
        self._synthesis_done = False
        self._first_chunk_seen = False
        self._segment_marks.clear()
        self._current_mark = -1
        if self._state != PlaybackState.IDLE:
            self._set_state(PlaybackState.IDLE)
        self.position_changed.emit(0, 0)

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Stop playback and wait for synthesis threads to exit. Call before quitting."""
        self.stop()
        for worker in self._retired:
            if not worker.wait(timeout_ms):
                logger.warning("synthesis thread still running at shutdown")
        self._reap_workers()

    def _retire_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.requestInterruption()
            worker.finished.connect(self._reap_workers)
            self._retired.append(worker)
        self._reap_workers()

    @Slot()
    def _reap_workers(self) -> None:
        self._retired = [w for w in self._retired if not w.isFinished()]

    def _set_state(self, s: PlaybackState) -> None:
        self._state = s
        self.state_changed.emit(int(s))

    @Slot()
    def _emit_position(self) -> None:
        position = self.position_ms
        self.position_changed.emit(position, self.duration_ms)
        self._sync_segment(position)

    def _sync_segment(self, position_ms: int) -> None:
        """Emit segment_changed once playback reaches the next segment's audio."""
        played = position_ms * BYTES_PER_SECOND // 1000
        offsets = [offset for offset, _, _ in self._segment_marks]
        mark = bisect.bisect_right(offsets, played) - 1
        if mark >= 0 and mark != self._current_mark:
            self._current_mark = mark
            _, start, end = self._segment_marks[mark]
            self.segment_changed.emit(start, end)

    @Slot(int, int, int)
    def _on_segment_started(self, generation: int, start: int, end: int) -> None:
        if generation != self._generation:
            return
        # Chunks arrive in order, so this segment's audio begins at the current end
        # of the stream. Highlighting waits until playback actually gets there.
        self._segment_marks.append((len(self._audio), start, end))

    @Slot(int, bytes)
    def _on_chunk(self, generation: int, c: bytes) -> None:
        if generation != self._generation:
            return
        self.audio_chunk.emit(c)
        self._audio.extend(c)

        if not self._first_chunk_seen:
            self._first_chunk_seen = True
            self._open_sink(0)
            self._emit_position()
            self._set_state(PlaybackState.PLAYING)

        self._pump()

    def _open_sink(self, offset: int, suspended: bool = False) -> None:
        """(Re)create the push sink, starting playback at byte `offset` of the stream."""
        if self._sink is not None:
            with contextlib.suppress(Exception):
                self._sink.stop()
        self._sink = QAudioSink(self._output_device, self._format)
        # 1s buffer: enough to hide synth bursts, small enough to keep latency low
        self._sink.setBufferSize(BYTES_PER_SECOND)
        self._sink.stateChanged.connect(self._on_sink_state_changed)
        self._base_bytes = offset
        self._write_pos = offset
        self._sink_drained = False
        self._sink_io = self._sink.start()
        if suspended:
            self._sink.suspend()
        else:
            self._position_timer.start()
        self._pump_timer.start()

    @Slot()
    def _pump(self) -> None:
        """Drain pending PCM into the sink as buffer space frees up.

        QAudioSink push-mode silently drops bytes written beyond bytesFree(),
        so we have to pace writes ourselves.
        """
        if self._sink is None or self._sink_io is None:
            return
        pending = len(self._audio) - self._write_pos
        if pending > 0:
            free = self._sink.bytesFree()
            if free > 0:
                n = min(free, pending)
                start = self._write_pos
                try:
                    written = self._sink_io.write(bytes(self._audio[start:start + n]))
                except Exception as e:
                    logger.warning("sink write failed: %s", e)
                    return
                if written > 0:
                    self._write_pos += written
                    self._sink_drained = False

        if self._synthesis_done and self._write_pos >= len(self._audio):
            # Last bytes have been handed to the sink; wait for IdleState to fire finished.
            # Stop polling — _on_sink_state_changed handles the rest.
            self._pump_timer.stop()

    @Slot(int)
    def _on_worker_finished(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._synthesis_done = True
        if not self._first_chunk_seen:
            self._set_state(PlaybackState.IDLE)
            self.finished.emit()
            return
        # The sink may already have run dry while the last segment was being
        # synthesized, in which case no further IdleState is coming.
        self._maybe_finish()

    @Slot(int, str)
    def _on_worker_failed(self, generation: int, msg: str) -> None:
        if generation != self._generation:
            return
        self.error.emit(f"Synthesis error: {msg}")
        self.stop()

    @Slot(QAudio.State)
    def _on_sink_state_changed(self, state: QAudio.State) -> None:
        if state != QAudio.State.IdleState or self._sink is None:
            return
        if self._sink.state() != QAudio.State.IdleState:
            return  # stale: more audio was written after this was queued
        self._sink_drained = True
        self._maybe_finish()

    def _maybe_finish(self) -> None:
        if self._state not in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            return
        # Idle with audio still pending is an underrun, not the end.
        pending = len(self._audio) - self._write_pos
        if not (self._synthesis_done and self._sink_drained and pending <= 0):
            return
        self._position_timer.stop()
        self._pump_timer.stop()
        if self._sink is not None:
            # Stop but keep the reference: this can run inside the sink's own
            # stateChanged emission, where deleting it would crash.
            with contextlib.suppress(Exception):
                self._sink.stop()
        total = self.duration_ms
        self.position_changed.emit(total, total)
        self._set_state(PlaybackState.IDLE)
        self.finished.emit()


def _bytes_to_ms(n: int) -> int:
    return int(n / BYTES_PER_SECOND * 1000)
