from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tts_app.audio.encode import resolve_output
from tts_app.audio.export import ExportCancelled, export_speech
from tts_app.audio.playback import PlaybackController, PlaybackState
from tts_app.clipboard import read_clipboard_text
from tts_app.config import AppSettings, save_settings
from tts_app.engines.base import TTSEngine, Voice
from tts_app.engines.registry import EngineRegistry
from tts_app.text.segment import Segment, segment_text
from tts_app.ui.motion import ReducedMotion, should_animate
from tts_app.ui.motion import policy as motion_policy
from tts_app.ui.preferences import PreferencesDialog
from tts_app.ui.rvc_card_grid import RvcCardGrid
from tts_app.ui.transport_progress import TransportProgressSlider
from tts_app.ui.voice_browser import VoiceBrowser
from tts_app.ui.voice_picker import VoicePicker
from tts_app.ui.waveform import WaveformWidget
from tts_app.ui.widgets import ErrorBanner, HamburgerButton, engine_label

logger = logging.getLogger(__name__)


def _qapp() -> QApplication:
    return cast(QApplication, QApplication.instance())


def _hairline() -> QFrame:
    line = QFrame()
    line.setProperty("role", "hairline")
    return line


def _button(text: str, role: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("role", role)
    return btn


class MainWindow(QMainWindow):
    hidden_to_tray = Signal()
    preferences_changed = Signal()

    # Emitted from the save worker thread; delivered on the UI thread.
    _save_finished = Signal(str)
    _save_failed = Signal(str)

    # Created by _add_param() via setattr.
    _rate_slider: QSlider
    _pitch_slider: QSlider
    _volume_slider: QSlider
    _rate_label: QLabel
    _pitch_label: QLabel
    _volume_label: QLabel

    def __init__(
        self,
        registry: EngineRegistry,
        playback: PlaybackController,
        settings: AppSettings,
    ) -> None:
        super().__init__()
        self._registry = registry
        self._playback = playback
        self._settings = settings

        self.setWindowTitle("TTS")
        self.setMinimumSize(760, 640)
        self.resize(920, 760)

        self._current_engine: TTSEngine | None = None
        self._current_voice: Voice | None = None
        self._engines_probed = False
        self._engine_buttons: dict[str, QPushButton] = {}
        self._close_to_tray = False
        self._quitting = False
        self._save_thread: threading.Thread | None = None
        self._save_cancel = threading.Event()

        self._setup_ui()
        self._setup_status_bar()
        self._connect_signals()
        self._load_settings()

    def _setup_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(32, 20, 32, 12)
        layout.setSpacing(0)

        layout.addLayout(self._create_topbar())
        layout.addSpacing(12)
        self._error_banner = ErrorBanner()
        layout.addWidget(self._error_banner)
        layout.addLayout(self._create_text_section(), stretch=1)
        layout.addSpacing(16)
        layout.addWidget(_hairline())
        layout.addSpacing(18)
        layout.addWidget(self._create_voice_section())
        layout.addSpacing(22)
        layout.addLayout(self._create_transport_section())

        central.setLayout(layout)
        self.setCentralWidget(central)

    def _create_topbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        wordmark = QLabel("TTS")
        wordmark.setProperty("role", "wordmark")
        self._state_label = QLabel("")
        self._state_label.setProperty("role", "status")

        row.addWidget(wordmark)
        row.addSpacing(10)
        row.addWidget(self._state_label)
        row.addStretch()

        self._add_voice_btn = _button("Get voices", "ghost")
        self._add_voice_btn.clicked.connect(self._on_browse_voices)

        self._settings_btn = HamburgerButton()
        self._settings_btn.setToolTip("Menu")
        self._settings_btn.setMenu(self._build_settings_menu())

        row.addWidget(self._add_voice_btn)
        row.addWidget(self._settings_btn)
        return row

    def _build_settings_menu(self) -> QMenu:
        menu = QMenu(self)

        motion_menu = QMenu("Reduced Motion", menu)
        self._motion_actions: dict[str, QAction] = {}
        options: tuple[tuple[str, ReducedMotion], ...] = (
            ("Follow OS", "auto"),
            ("Always On", "on"),
            ("Always Off", "off"),
        )
        for label, value in options:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, v=value: self._set_reduced_motion(v))
            motion_menu.addAction(act)
            self._motion_actions[value] = act
        self._motion_actions[self._settings.reduced_motion].setChecked(True)
        menu.addMenu(motion_menu)

        rvc_action = QAction("RVC voice models…", self)
        rvc_action.triggered.connect(self._on_rvc_voices)
        menu.addAction(rvc_action)

        prefs = QAction("Preferences…", self)
        prefs.triggered.connect(self._on_preferences)
        menu.addAction(prefs)

        about = QAction("About TTS", self)
        about.triggered.connect(self._on_about)
        menu.addAction(about)

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        return menu

    def _set_reduced_motion(self, value: ReducedMotion) -> None:
        p = motion_policy()
        if p is not None:
            p.set_preference(value)
        else:
            self._settings.reduced_motion = value
        save_settings(self._settings)
        for v, act in self._motion_actions.items():
            act.setChecked(v == value)

    def _create_text_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("Paste something to read aloud, or open a text file.")
        self._text_edit.setFrameShape(QFrame.Shape.NoFrame)
        self._text_edit.document().setDocumentMargin(0)
        self._text_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._text_edit, stretch=1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(2)
        open_btn = _button("Open file", "ghost")
        clear_btn = _button("Clear", "ghost")
        actions.addStretch()
        actions.addWidget(open_btn)
        actions.addWidget(clear_btn)
        layout.addLayout(actions)

        open_btn.clicked.connect(self._on_open_file)
        clear_btn.clicked.connect(self._text_edit.clear)

        return layout

    def _create_voice_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        voice_row = QHBoxLayout()
        voice_row.setContentsMargins(0, 0, 0, 0)
        voice_row.setSpacing(4)

        self._engine_group = QButtonGroup(self)
        self._engine_group.setExclusive(True)
        self._engine_pill_row = QHBoxLayout()
        self._engine_pill_row.setContentsMargins(0, 0, 0, 0)
        self._engine_pill_row.setSpacing(2)
        voice_row.addLayout(self._engine_pill_row)

        voice_row.addSpacing(12)
        self._voice_picker = VoicePicker()
        voice_row.addWidget(self._voice_picker, stretch=1)

        preview_btn = _button("Preview", "ghost")
        preview_btn.clicked.connect(self._on_preview)
        voice_row.addWidget(preview_btn)
        layout.addLayout(voice_row)

        params = QGridLayout()
        params.setContentsMargins(0, 0, 0, 0)
        params.setHorizontalSpacing(32)
        params.setVerticalSpacing(6)
        for col, (name, lo, hi, attr) in enumerate(
            (("Speed", 25, 300, "rate"), ("Pitch", 50, 200, "pitch"), ("Volume", 0, 100, "volume"))
        ):
            self._add_param(params, col, name, lo, hi, 100, attr)
            params.setColumnStretch(col, 1)
        layout.addLayout(params)

        section.setLayout(layout)
        self._voice_card_opacity = QGraphicsOpacityEffect(section)
        self._voice_card_opacity.setOpacity(1.0)
        section.setGraphicsEffect(self._voice_card_opacity)
        self._engine_xfade_anim: QPropertyAnimation | None = None
        return section

    def _add_param(
        self,
        grid: QGridLayout,
        col: int,
        name: str,
        minimum: int,
        maximum: int,
        initial: int,
        attr: str,
    ) -> None:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        label = QLabel(name)
        label.setProperty("role", "bodyMuted")

        value = QLabel()
        value.setProperty("role", "paramValue")

        reset = _button("↺", "paramReset")
        reset.setToolTip("Reset")
        reset.setFixedSize(18, 18)
        size_policy = reset.sizePolicy()
        size_policy.setRetainSizeWhenHidden(True)
        reset.setSizePolicy(size_policy)
        reset.setVisible(False)

        header.addWidget(label)
        header.addStretch()
        header.addWidget(reset)
        header.addWidget(value)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(initial)

        reset.clicked.connect(lambda _checked=False, s=slider, d=initial: s.setValue(d))
        slider.valueChanged.connect(lambda val: reset.setVisible(val != initial))

        grid.addLayout(header, 0, col)
        grid.addWidget(slider, 1, col)

        setattr(self, f"_{attr}_slider", slider)
        setattr(self, f"_{attr}_label", value)

    def _create_transport_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._waveform = WaveformWidget()
        layout.addWidget(self._waveform)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self._time_elapsed_label = QLabel("0:00")
        self._time_elapsed_label.setProperty("role", "timecode")
        self._time_total_label = QLabel("0:00")
        self._time_total_label.setProperty("role", "timecode")
        self._progress_slider = TransportProgressSlider()
        self._progress_slider.setMinimum(0)
        self._progress_slider.setMaximum(0)
        self._progress_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        progress_row.addWidget(self._time_elapsed_label)
        progress_row.addWidget(self._progress_slider, stretch=1)
        progress_row.addWidget(self._time_total_label)
        layout.addLayout(progress_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._rewind_btn = _button("−10", "transport")
        self._rewind_btn.setToolTip("Back 10 seconds")
        self._play_btn = _button("Play", "play")
        self._forward_btn = _button("+10", "transport")
        self._forward_btn.setToolTip("Forward 10 seconds")
        self._stop_btn = _button("Stop", "transport")
        self._stop_btn.setMinimumWidth(56)
        self._save_btn = _button("Save audio", "ghost")

        # Balance the Save button so Play sits in the true centre.
        balance = QWidget()
        balance.setFixedWidth(
            self._save_btn.sizeHint().width() + self._stop_btn.minimumWidth() + 12
        )
        btn_row.addWidget(balance)
        btn_row.addStretch()
        btn_row.addWidget(self._rewind_btn)
        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._forward_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._stop_btn)
        btn_row.addSpacing(6)
        btn_row.addWidget(self._save_btn)
        layout.addSpacing(4)
        layout.addLayout(btn_row)

        self._play_btn.clicked.connect(self._on_play)
        self._stop_btn.clicked.connect(self._on_stop)
        self._save_btn.clicked.connect(self._on_save)
        self._rewind_btn.clicked.connect(self._on_rewind)
        self._forward_btn.clicked.connect(self._on_forward)
        self._rewind_btn.setEnabled(False)  # enabled while there's audio to seek in
        self._forward_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_slider.sliderReleased.connect(self._on_seek_released)

        return layout

    def _refresh_engine_pills(self) -> None:
        for btn in list(self._engine_buttons.values()):
            self._engine_group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._engine_buttons.clear()

        while self._engine_pill_row.count():
            item = self._engine_pill_row.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

        for engine in self._registry.available():
            btn = _button(engine_label(engine.name), "enginePill")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, e=engine: self._select_engine(e))
            self._engine_group.addButton(btn)
            self._engine_buttons[engine.name] = btn
            self._engine_pill_row.addWidget(btn)

        if self._current_engine and self._current_engine.name in self._engine_buttons:
            self._engine_buttons[self._current_engine.name].setChecked(True)

    def _select_engine(self, engine: TTSEngine) -> None:
        if engine is self._current_engine:
            return
        if should_animate():
            self._engine_crossfade(engine)
        else:
            self._apply_engine_change(engine)

    def _apply_engine_change(self, engine: TTSEngine) -> None:
        self._current_engine = engine
        self._current_voice = None
        self._repopulate_voices()
        self._settings.engine_preference = (
            [engine.name]
            + [e.name for e in self._registry.available() if e.name != engine.name]
        )

    def _engine_crossfade(self, engine: TTSEngine) -> None:
        if self._engine_xfade_anim is not None:
            self._engine_xfade_anim.stop()

        out_anim = QPropertyAnimation(self._voice_card_opacity, b"opacity", self)
        out_anim.setDuration(200)
        out_anim.setStartValue(self._voice_card_opacity.opacity())
        out_anim.setEndValue(0.35)
        out_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_out_finished() -> None:
            self._apply_engine_change(engine)
            in_anim = QPropertyAnimation(self._voice_card_opacity, b"opacity", self)
            in_anim.setDuration(200)
            in_anim.setStartValue(0.35)
            in_anim.setEndValue(1.0)
            in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._engine_xfade_anim = in_anim
            in_anim.start()

        out_anim.finished.connect(_on_out_finished)
        self._engine_xfade_anim = out_anim
        out_anim.start()

    def _setup_status_bar(self) -> None:
        self._status_label = QLabel()
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self._status_label)
        self._update_status()

    def _connect_signals(self) -> None:
        self._voice_picker.voiceChanged.connect(self._on_voice_picker_changed)

        self._rate_slider.valueChanged.connect(self._on_rate_changed)
        self._pitch_slider.valueChanged.connect(self._on_pitch_changed)
        self._volume_slider.valueChanged.connect(self._on_volume_changed)

        self._playback.state_changed.connect(self._on_playback_state_changed)
        self._playback.error.connect(self._on_playback_error)
        self._playback.finished.connect(self._on_playback_finished)
        self._playback.position_changed.connect(self._on_position_changed)
        self._playback.audio_chunk.connect(self._waveform.push_pcm)
        self._playback.synthesizing.connect(self._on_synthesizing)
        self._playback.segment_changed.connect(self._highlight_segment)

        self._save_finished.connect(self._on_save_finished)
        self._save_failed.connect(self._on_save_failed)

    def _load_settings(self) -> None:
        self._current_engine = self._registry.pick_default(self._settings.engine_preference)
        if self._current_engine is not None and self._settings.last_voice_id:
            result = self._registry.find_voice(self._settings.last_voice_id)
            if result:
                self._current_engine, self._current_voice = result

        self._refresh_engine_pills()
        self._repopulate_voices()

        self._rate_slider.blockSignals(True)
        self._rate_slider.setValue(int(self._settings.rate * 100))
        self._rate_slider.blockSignals(False)

        self._pitch_slider.blockSignals(True)
        self._pitch_slider.setValue(int(self._settings.pitch * 100))
        self._pitch_slider.blockSignals(False)

        self._volume_slider.blockSignals(True)
        self._volume_slider.setValue(int(self._settings.volume * 100))
        self._volume_slider.blockSignals(False)

        self._update_labels()

    def _repopulate_voices(self) -> None:
        if not self._current_engine:
            return

        supports_pitch = self._current_engine.supports_pitch
        self._pitch_slider.setEnabled(supports_pitch)
        label = engine_label(self._current_engine.name)
        self._pitch_slider.setToolTip("" if supports_pitch else f"{label} can't change pitch")

        voices = self._registry.voices(self._current_engine)
        languages: dict[str, list[Voice]] = {}
        for voice in voices:
            lang = voice.language or "Unknown"
            languages.setdefault(lang, []).append(voice)
        ordered: list[Voice] = []
        for lang in sorted(languages.keys()):
            ordered.extend(languages[lang])

        self._voice_picker.blockSignals(True)
        self._voice_picker.setVoices(ordered, engine_name=self._current_engine.name)
        if self._current_voice and self._current_voice in voices:
            self._voice_picker.setCurrentVoice(self._current_voice)
        elif ordered:
            self._current_voice = self._voice_picker.currentVoice()
        self._voice_picker.blockSignals(False)

    @Slot(Voice)
    def _on_voice_picker_changed(self, voice: Voice) -> None:
        self._current_voice = voice
        self._settings.last_voice_id = voice.id

    @Slot(int)
    def _on_rate_changed(self, value: int) -> None:
        self._settings.rate = value / 100.0
        self._rate_label.setText(f"{self._settings.rate:.2f}x")

    @Slot(int)
    def _on_pitch_changed(self, value: int) -> None:
        self._settings.pitch = value / 100.0
        self._pitch_label.setText(f"{self._settings.pitch:.2f}x")

    @Slot(int)
    def _on_volume_changed(self, value: int) -> None:
        self._settings.volume = value / 100.0
        self._volume_label.setText(f"{self._settings.volume:.2f}")

    @Slot()
    def _on_play(self) -> None:
        # While audio is out, this button is labelled Pause / Resume.
        if self._playback.state() in (PlaybackState.PLAYING, PlaybackState.PAUSED):
            self.toggle_pause()
            return
        self._speak_editor_text()

    def _speak_editor_text(self) -> None:
        if not self._current_engine or not self._current_voice:
            return

        text = self._text_edit.toPlainText()
        if not text.strip():
            return

        segments = segment_text(text)
        if not segments:
            return

        engine = self._current_engine
        voice = self._current_voice
        rate = self._settings.rate
        pitch = self._settings.pitch
        volume = self._settings.volume

        def synth_segment(seg: Segment) -> Iterator[bytes]:
            yield from engine.synthesize(seg.text, voice, rate=rate, pitch=pitch, volume=volume)

        self._playback.play_segments(segments, synth_segment)

    @Slot()
    def read_clipboard(self) -> None:
        """Global hotkey / tray: read the clipboard aloud. Again on the same text stops."""
        text = read_clipboard_text(_qapp())
        reading = self._playback.state() != PlaybackState.IDLE
        if reading and (not text or text == self._text_edit.toPlainText()):
            self._on_stop()
            return
        if not text:
            self.statusBar().showMessage("Clipboard has no text to read", 4000)
            return
        self._text_edit.setPlainText(text)
        self._speak_editor_text()

    @Slot()
    def toggle_pause(self) -> None:
        if self._playback.state() == PlaybackState.PLAYING:
            self._playback.pause()
        elif self._playback.state() == PlaybackState.PAUSED:
            self._playback.resume()

    @Slot()
    def _on_stop(self) -> None:
        self._playback.stop()
        self._clear_segment_highlight()

    @Slot()
    def _on_save(self) -> None:
        if not self._current_engine or not self._current_voice:
            return

        text = self._text_edit.toPlainText()
        if not text.strip():
            return

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Audio",
            "",
            "WAV (*.wav);;MP3 (*.mp3);;OGG (*.ogg)",
        )

        if not file_path:
            return

        dest, fmt = resolve_output(Path(file_path), selected_filter)
        # The dialog only confirmed overwriting the name as typed, not with an
        # extension we added.
        if dest != Path(file_path) and dest.exists():
            answer = QMessageBox.question(
                self, "Save Audio", f"{dest.name} already exists. Replace it?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        # Snapshot everything the worker needs; the UI may change while it runs.
        engine = self._current_engine
        voice = self._current_voice
        rate = self._settings.rate
        pitch = self._settings.pitch
        volume = self._settings.volume

        cancel = threading.Event()
        self._save_cancel = cancel

        def save_worker() -> None:
            try:
                export_speech(
                    engine,
                    voice,
                    text,
                    dest,
                    fmt,
                    rate=rate,
                    pitch=pitch,
                    volume=volume,
                    cancel=cancel,
                )
            except ExportCancelled:
                logger.info("Save of %s cancelled", dest)
            except Exception as e:
                logger.exception("Failed to save audio")
                self._save_failed.emit(f"Save failed: {e}")
            else:
                self._save_finished.emit(str(dest))

        self.statusBar().showMessage(f"Saving {dest.name}…")
        self._save_thread = threading.Thread(target=save_worker, daemon=True)
        self._save_thread.start()

    def cancel_save(self, timeout: float = 5.0) -> None:
        """Stop an in-progress save between sentences and wait for it to clean up."""
        self._save_cancel.set()
        if self._save_thread is not None:
            self._save_thread.join(timeout)

    @Slot(str)
    def _on_save_finished(self, path: str) -> None:
        self.statusBar().showMessage(f"Saved {path}", 8000)

    @Slot(str)
    def _on_save_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        self._on_playback_error(message)

    @Slot()
    def _on_rewind(self) -> None:
        self._playback.skip(-10000)

    @Slot()
    def _on_forward(self) -> None:
        self._playback.skip(10000)

    @Slot()
    def _on_seek_released(self) -> None:
        # Seek once on release: each seek reopens the audio device.
        self._playback.seek(self._progress_slider.value())

    @Slot(int, int)
    def _on_position_changed(self, current_ms: int, total_ms: int) -> None:
        self._time_elapsed_label.setText(self._format_time(current_ms))
        self._time_total_label.setText(self._format_time(total_ms))
        if not self._progress_slider.isSliderDown():
            self._progress_slider.setMaximum(total_ms)
            self._progress_slider.setValue(current_ms)

    @staticmethod
    def _format_time(ms: int) -> str:
        total_seconds = ms // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"

    @Slot()
    def _on_browse_voices(self) -> None:
        browser = VoiceBrowser(self._registry)
        accepted = browser.exec() == 1
        self.refresh_engines()  # the browser can download voices
        if accepted:
            voice = browser.selectedVoice()
            if voice:
                result = self._registry.find_voice(voice.id)
                if result:
                    self._current_engine, self._current_voice = result
                    self._refresh_engine_pills()
                    self._repopulate_voices()

    @Slot()
    def _on_preview(self) -> None:
        if not self._current_engine or not self._current_voice:
            return

        # Runs on the synthesis thread: capture now, not when the thread gets to it.
        engine = self._current_engine
        voice = self._current_voice
        text = self._settings.preview_text
        rate = self._settings.rate
        pitch = self._settings.pitch
        volume = self._settings.volume

        def synth_iter() -> Iterator[bytes]:
            yield from engine.synthesize(text, voice, rate=rate, pitch=pitch, volume=volume)

        self._playback.play(synth_iter)

    @Slot()
    def _on_open_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Text File", "", "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            with open(file_path) as f:
                self._text_edit.setPlainText(f.read())

    @Slot()
    def _on_preferences(self) -> None:
        dialog = PreferencesDialog(self._settings, self, rvc_base_voices=self._rvc_base_voices())
        if dialog.exec() == 1:
            save_settings(self._settings)
            self.preferences_changed.emit()

    def _rvc_base_voices(self) -> list[Voice]:
        if self._registry.get("rvc") is None:
            return []
        base = self._registry.get(self._settings.rvc_base_engine)
        if base is None or base not in self._registry.available():
            return []
        return self._registry.voices(base)

    @Slot()
    def _on_rvc_voices(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("RVC voice models")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Experimental: RVC converts Piper speech into another voice. It needs "
            "torch and rvc-inferpy installed; models (.pth) are imported here."
        )
        note.setWordWrap(True)
        note.setProperty("role", "bodyMuted")
        layout.addWidget(note)
        layout.addWidget(RvcCardGrid())
        dialog.exec()

        rvc = self._registry.get("rvc")
        if rvc is not None and hasattr(rvc, "recheck"):
            rvc.recheck()  # models may have been added or removed
        self.refresh_engines()

    @Slot()
    def _on_about(self) -> None:
        QMessageBox.information(
            self,
            "About TTS",
            "TTS\nLocal text-to-speech. No cloud, no accounts.",
        )

    @Slot(int)
    def _on_playback_state_changed(self, state: int) -> None:
        ps = PlaybackState(state)
        active = ps in (PlaybackState.SYNTHESIZING, PlaybackState.PLAYING, PlaybackState.PAUSED)
        if ps == PlaybackState.SYNTHESIZING:
            self._play_btn.setText("Preparing…")
            self._play_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        elif ps == PlaybackState.PLAYING:
            self._play_btn.setText("Pause")
            self._play_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
        elif ps == PlaybackState.PAUSED:
            self._play_btn.setText("Resume")
            self._play_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
        else:
            self._play_btn.setText("Play")
            self._play_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
        seekable = ps in (PlaybackState.PLAYING, PlaybackState.PAUSED)
        self._rewind_btn.setEnabled(seekable)
        self._forward_btn.setEnabled(seekable)
        self._progress_slider.setEnabled(active)
        self._update_state_indicator(ps)
        self._update_status()

    def _update_state_indicator(self, state: PlaybackState) -> None:
        if state == PlaybackState.SYNTHESIZING:
            self._state_label.setText("Preparing audio…")
            self._progress_slider.stop_sweep()
        elif state == PlaybackState.PLAYING:
            self._state_label.setText("Reading")
            self._waveform.start()
            self._progress_slider.start_sweep()
        elif state == PlaybackState.PAUSED:
            self._state_label.setText("Paused")
            self._progress_slider.stop_sweep()
        else:
            self._state_label.setText("")
            self._waveform.stop()
            self._progress_slider.stop_sweep()

    @Slot(str)
    def _on_playback_error(self, error: str) -> None:
        self._status_label.setText(f"Error: {error}")
        self._error_banner.show_error(error)
        self._state_label.setText("")

    @Slot()
    def _on_synthesizing(self) -> None:
        self._error_banner.setVisible(False)
        self._update_status()
        self._update_state_indicator(PlaybackState.SYNTHESIZING)

    @Slot()
    def _on_playback_finished(self) -> None:
        self._update_status()
        self._clear_segment_highlight()

    @Slot(int, int)
    def _highlight_segment(self, start: int, end: int) -> None:
        cursor = self._text_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(224, 164, 88, 70))
        selection.format = fmt
        self._text_edit.setExtraSelections([selection])
        # Scroll so the highlighted region is visible.
        view_cursor = self._text_edit.textCursor()
        view_cursor.setPosition(start)
        self._text_edit.setTextCursor(view_cursor)
        self._text_edit.ensureCursorVisible()

    def _clear_segment_highlight(self) -> None:
        self._text_edit.setExtraSelections([])

    def _update_status(self) -> None:
        if not self._current_engine:
            self._status_label.setText(
                "Loading neural voices…"
                if not self._engines_probed
                else "No engine available"
            )
            return

        voice_count = sum(
            len(self._registry.voices(e)) for e in self._registry.available()
        )
        ps = self._playback._state
        if ps == PlaybackState.SYNTHESIZING:
            state_str = "synthesizing…"
        elif ps == PlaybackState.PLAYING:
            state_str = "playing"
        elif ps == PlaybackState.PAUSED:
            state_str = "paused"
        else:
            state_str = "idle"
        prefix = "Engine ready" if self._engines_probed else "Loading neural voices…"
        self._status_label.setText(
            f"{prefix} · {voice_count} voices · {state_str}"
        )

    @Slot()
    def on_engines_probed(self) -> None:
        self._engines_probed = True
        self.refresh_engines()

    def refresh_engines(self) -> None:
        """Re-check engines and voices, e.g. after voices were installed."""
        self._registry.refresh()
        available = self._registry.available()
        if self._current_engine not in available:
            self._current_engine = self._registry.pick_default(self._settings.engine_preference)
            self._current_voice = None
        self._repopulate_voices()
        self._refresh_engine_pills()

        if self._settings.last_voice_id and not self._current_voice:
            result = self._registry.find_voice(self._settings.last_voice_id)
            if result:
                self._current_engine, self._current_voice = result
                if self._current_engine.name in self._engine_buttons:
                    self._engine_buttons[self._current_engine.name].setChecked(True)
                self._repopulate_voices()

        self._update_status()

    def _update_labels(self) -> None:
        self._rate_label.setText(f"{self._settings.rate:.2f}x")
        self._pitch_label.setText(f"{self._settings.pitch:.2f}x")
        self._volume_label.setText(f"{self._settings.volume:.2f}")

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def set_close_to_tray(self, enabled: bool) -> None:
        """Closing the window hides it instead (the app keeps running in the tray)."""
        self._close_to_tray = enabled

    @Slot()
    def quit_app(self) -> None:
        self._quitting = True
        save_settings(self._settings)
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        save_settings(self._settings)
        # During OS logoff/shutdown a refused close would cancel the session end.
        if (
            self._close_to_tray
            and not self._quitting
            and not _qapp().isSavingSession()
        ):
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            return
        super().closeEvent(event)
