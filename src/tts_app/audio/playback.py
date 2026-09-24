from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from enum import IntEnum

from PySide6.QtCore import QIODevice, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

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
    chunk = Signal(bytes)
    segment_started = Signal(int, int)  # start_char, end_char
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        synthesize_callable: Callable[[], Iterator[bytes]] | None = None,
        segments: list | None = None,
        segment_synth: Callable[[object], Iterator[bytes]] | None = None,
    ) -> None:
        super().__init__()
        self._synthesize = synthesize_callable
        self._segments = segments
        self._segment_synth = segment_synth

    def run(self) -> None:
        try:
            if self._segments is not None and self._segment_synth is not None:
                for seg in self._segments:
                    if self.isInterruptionRequested():
                        return
                    self.segment_started.emit(seg.start, seg.end)
                    for c in self._segment_synth(seg):
                        if self.isInterruptionRequested():
                            return
                        if c:
                            self.chunk.emit(bytes(c))
            else:
                for c in self._synthesize():
                    if self.isInterruptionRequested():
                        return
                    if c:
                        self.chunk.emit(bytes(c))
            self.finished_ok.emit()
        except Exception as e:
            logger.exception("synthesis worker failed")
            self.failed.emit(str(e))


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
        self._total_bytes = 0
        self._synthesis_done = False
        self._first_chunk_seen = False
        self._pending = bytearray()

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
        return int(self._total_bytes / BYTES_PER_SECOND * 1000)

    @property
    def position_ms(self) -> int:
        if self._sink is None:
            return 0
        return int(self._sink.processedUSecs() / 1000)

    def seek(self, position_ms: int) -> None:
        # Push-mode streaming sink does not support arbitrary seek.
        return

    def skip(self, delta_ms: int) -> None:
        return

    def play(self, synthesize_callable: Callable[[], Iterator[bytes]]) -> None:
        if self._state in (PlaybackState.PLAYING, PlaybackState.PAUSED, PlaybackState.SYNTHESIZING):
            self.stop()
        if self._output_device.isNull():
            self.error.emit("No audio output device available")
            return

        self._total_bytes = 0
        self._synthesis_done = False
        self._first_chunk_seen = False
        self._set_state(PlaybackState.SYNTHESIZING)
        self.synthesizing.emit()

        self._worker = _SynthWorker(synthesize_callable)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def play_segments(
        self,
        segments: list,
        segment_synth: Callable[[object], Iterator[bytes]],
    ) -> None:
        if self._state in (PlaybackState.PLAYING, PlaybackState.PAUSED, PlaybackState.SYNTHESIZING):
            self.stop()
        if self._output_device.isNull():
            self.error.emit("No audio output device available")
            return

        self._total_bytes = 0
        self._synthesis_done = False
        self._first_chunk_seen = False
        self._set_state(PlaybackState.SYNTHESIZING)
        self.synthesizing.emit()

        self._worker = _SynthWorker(segments=segments, segment_synth=segment_synth)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.segment_started.connect(self.segment_changed)
        self._worker.finished_ok.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

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
        self._position_timer.stop()
        self._pump_timer.stop()
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait(2000)
            self._worker = None
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
            self._sink = None
        self._sink_io = None
        self._pending.clear()
        self._total_bytes = 0
        self._first_chunk_seen = False
        if self._state != PlaybackState.IDLE:
            self._set_state(PlaybackState.IDLE)
        self.position_changed.emit(0, 0)

    def _set_state(self, s: PlaybackState) -> None:
        self._state = s
        self.state_changed.emit(int(s))

    @Slot()
    def _emit_position(self) -> None:
        self.position_changed.emit(self.position_ms, self.duration_ms)

    @Slot(bytes)
    def _on_chunk(self, c: bytes) -> None:
        self.audio_chunk.emit(c)
        self._total_bytes += len(c)

        if not self._first_chunk_seen:
            self._first_chunk_seen = True
            self._start_push_sink()
            self._set_state(PlaybackState.PLAYING)

        self._pending.extend(c)
        self._pump()

    def _start_push_sink(self) -> None:
        self._sink = QAudioSink(self._output_device, self._format)
        # 1s buffer: enough to hide synth bursts, small enough to keep latency low
        self._sink.setBufferSize(BYTES_PER_SECOND)
        self._sink.stateChanged.connect(self._on_sink_state_changed)
        self._sink_io = self._sink.start()
        self._pump_timer.start()
        self._position_timer.start()
        self._emit_position()

    @Slot()
    def _pump(self) -> None:
        """Drain pending PCM into the sink as buffer space frees up.

        QAudioSink push-mode silently drops bytes written beyond bytesFree(),
        so we have to pace writes ourselves.
        """
        if self._sink is None or self._sink_io is None:
            return
        if self._pending:
            free = self._sink.bytesFree()
            if free > 0:
                n = min(free, len(self._pending))
                try:
                    self._sink_io.write(bytes(self._pending[:n]))
                except Exception as e:
                    logger.warning("sink write failed: %s", e)
                    return
                del self._pending[:n]

        if self._synthesis_done and not self._pending:
            # Last bytes have been handed to the sink; wait for IdleState to fire finished.
            # Stop polling — _on_sink_state_changed handles the rest.
            self._pump_timer.stop()

    @Slot()
    def _on_worker_finished(self) -> None:
        self._synthesis_done = True
        if not self._first_chunk_seen:
            self._set_state(PlaybackState.IDLE)
            self.finished.emit()

    @Slot(str)
    def _on_worker_failed(self, msg: str) -> None:
        self.error.emit(f"Synthesis error: {msg}")
        self.stop()

    @Slot(QAudio.State)
    def _on_sink_state_changed(self, state: QAudio.State) -> None:
        if state == QAudio.State.IdleState and self._synthesis_done:
            self._position_timer.stop()
            if self._sink is not None:
                try:
                    self._sink.stop()
                except Exception:
                    pass
            self._set_state(PlaybackState.IDLE)
            self.finished.emit()
