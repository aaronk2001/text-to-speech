from __future__ import annotations

import logging
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
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
from tts_app.audio.export import export_speech
from tts_app.audio.playback import PlaybackController, PlaybackState
from tts_app.clipboard import read_clipboard_text
from tts_app.config import AppSettings, save_settings
from tts_app.engines.base import TTSEngine, Voice
from tts_app.engines.registry import EngineRegistry
from tts_app.text.segment import Segment, segment_text
from tts_app.ui.effects import HoverGlow, OpacityPulse
from tts_app.ui.motion import policy as motion_policy
from tts_app.ui.motion import should_animate
from tts_app.ui.transport_progress import TransportProgressSlider
from tts_app.ui.voice_browser import VoiceBrowser
from tts_app.ui.voice_picker import VoicePicker
from tts_app.ui.waveform import WaveformWidget
from tts_app.ui.widgets import ErrorBanner, HamburgerButton, StatusDot, Wordmark

logger = logging.getLogger(__name__)


def _section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setProperty("role", "sectionHeading")
    return label


def _glass_card(content: QVBoxLayout) -> QFrame:
    card = QFrame()
    card.setProperty("role", "glassCard")
    content.setContentsMargins(20, 18, 20, 18)
    content.setSpacing(12)
    card.setLayout(content)
    return card


class MainWindow(QMainWindow):
    hidden_to_tray = Signal()

    # Emitted from the save worker thread; delivered on the UI thread.
    _save_finished = Signal(str)
    _save_failed = Signal(str)

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
        self.setMinimumSize(1000, 820)

        self._current_engine: TTSEngine | None = None
        self._current_voice: Voice | None = None
        self._engines_probed = False
        self._engine_buttons: dict[str, QPushButton] = {}
        self._close_to_tray = False
        self._quitting = False

        self._setup_ui()
        self._setup_status_bar()
        self._connect_signals()
        self._load_settings()
        self._install_effects()

    def _setup_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        layout.addWidget(self._create_topbar())
        self._error_banner = ErrorBanner()
        layout.addWidget(self._error_banner)
        layout.addWidget(self._create_text_card(), stretch=1)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(16)
        self._voice_card = self._create_voice_card()
        self._voice_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self._transport_card = self._create_transport_card()
        self._transport_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        bottom_row.addWidget(self._voice_card, stretch=1)
        bottom_row.addWidget(self._transport_card, stretch=1)
        bottom_container = QWidget()
        bottom_container.setLayout(bottom_row)
        layout.addWidget(bottom_container, stretch=1)

        central.setLayout(layout)
        self.setCentralWidget(central)

    def _create_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(56)

        row = QHBoxLayout()
        row.setContentsMargins(24, 0, 24, 0)
        row.setSpacing(14)

        wordmark = Wordmark("TTS")

        self._status_dot = StatusDot()
        self._dot_pulse = OpacityPulse(self._status_dot, period_ms=1400, floor=0.45)

        row.addWidget(wordmark)
        row.addWidget(self._status_dot)
        row.addStretch()

        self._add_voice_btn = QPushButton("+ Add voice")
        self._add_voice_btn.setProperty("role", "primary")
        self._add_voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_voice_btn.clicked.connect(self._on_browse_voices)

        self._settings_btn = HamburgerButton()
        self._settings_btn.setToolTip("Menu")
        self._settings_btn.setMenu(self._build_settings_menu())

        row.addWidget(self._add_voice_btn)
        row.addWidget(self._settings_btn)

        bar.setLayout(row)
        return bar

    def _build_settings_menu(self) -> QMenu:
        menu = QMenu(self)

        motion_menu = QMenu("Reduced Motion", menu)
        self._motion_actions: dict[str, QAction] = {}
        for label, value in (("Follow OS", "auto"), ("Always On", "on"), ("Always Off", "off")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, v=value: self._set_reduced_motion(v))
            motion_menu.addAction(act)
            self._motion_actions[value] = act
        self._motion_actions[self._settings.reduced_motion].setChecked(True)
        menu.addMenu(motion_menu)

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

    def _set_reduced_motion(self, value: str) -> None:
        p = motion_policy()
        if p is not None:
            p.set_preference(value)
        else:
            self._settings.reduced_motion = value  # type: ignore[assignment]
        save_settings(self._settings)
        for v, act in self._motion_actions.items():
            act.setChecked(v == value)

    def _create_text_card(self) -> QFrame:
        layout = QVBoxLayout()
        layout.addWidget(_section_label("Text"))

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        open_btn = QPushButton("Open File…")
        open_btn.setProperty("role", "ghost")
        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("role", "ghost")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        button_row.addWidget(open_btn)
        button_row.addWidget(clear_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setPlaceholderText("Paste text or open a file…")
        self._text_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._text_edit, stretch=1)

        open_btn.clicked.connect(self._on_open_file)
        clear_btn.clicked.connect(self._text_edit.clear)

        return _glass_card(layout)

    def _create_voice_card(self) -> QFrame:
        layout = QVBoxLayout()
        layout.addWidget(_section_label("Voice"))

        self._engine_group = QButtonGroup(self)
        self._engine_group.setExclusive(True)
        engine_pill_container = QWidget()
        engine_pill_container.setFixedHeight(34)
        self._engine_pill_row = QHBoxLayout()
        self._engine_pill_row.setContentsMargins(0, 0, 0, 0)
        self._engine_pill_row.setSpacing(8)
        self._engine_pill_row.addStretch()
        engine_pill_container.setLayout(self._engine_pill_row)
        layout.addWidget(engine_pill_container)

        voice_row = QHBoxLayout()
        voice_row.setSpacing(8)
        self._voice_picker = VoicePicker()
        self._voice_picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        preview_btn = QPushButton("▶  Preview")
        preview_btn.setProperty("role", "ghost")
        preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_btn.clicked.connect(self._on_preview)
        voice_row.addWidget(self._voice_picker, stretch=1)
        voice_row.addWidget(preview_btn)
        layout.addLayout(voice_row)

        layout.addSpacing(4)
        layout.addWidget(self._param_row("Rate", 25, 300, 100, "rate"))
        layout.addWidget(self._param_row("Pitch", 50, 200, 100, "pitch"))
        layout.addWidget(self._param_row("Volume", 0, 100, 100, "volume"))

        card = _glass_card(layout)
        card.setMinimumHeight(260)
        self._voice_card_opacity = QGraphicsOpacityEffect(card)
        self._voice_card_opacity.setOpacity(1.0)
        card.setGraphicsEffect(self._voice_card_opacity)
        self._engine_xfade_anim: QPropertyAnimation | None = None
        return card

    def _param_row(
        self,
        name: str,
        minimum: int,
        maximum: int,
        initial: int,
        attr: str,
    ) -> QWidget:
        container = QWidget()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        label = QLabel(name)
        label.setProperty("role", "bodyMuted")
        label.setMinimumWidth(60)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(initial)

        value = QLabel(
            f"{initial / 100:.2f}x" if attr != "volume" else f"{initial / 100:.2f}"
        )
        value.setProperty("role", "paramValue")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        reset = QPushButton("↺")
        reset.setProperty("role", "paramReset")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.setToolTip("Reset to default")
        reset.setVisible(False)
        reset.setFixedSize(22, 22)
        reset.clicked.connect(lambda _checked=False, s=slider, d=initial: s.setValue(d))

        def _on_value_changed(val: int) -> None:
            reset.setVisible(val != initial)

        slider.valueChanged.connect(_on_value_changed)

        row.addWidget(label)
        row.addWidget(slider, stretch=1)
        row.addWidget(value)
        row.addWidget(reset)

        setattr(self, f"_{attr}_slider", slider)
        setattr(self, f"_{attr}_label", value)

        container.setLayout(row)
        return container

    def _create_transport_card(self) -> QFrame:
        layout = QVBoxLayout()
        layout.addWidget(_section_label("Transport"))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._rewind_btn = QPushButton("⏪  10s")
        self._play_btn = QPushButton("▶  Play")
        self._pause_btn = QPushButton("❚❚")
        self._stop_btn = QPushButton("■")
        self._forward_btn = QPushButton("10s  ⏩")
        self._save_btn = QPushButton("Save audio…")

        for b in (self._rewind_btn, self._pause_btn, self._stop_btn, self._forward_btn):
            b.setProperty("role", "transport")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setProperty("role", "play")
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setProperty("role", "ghost")
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_row.addWidget(self._rewind_btn)
        btn_row.addWidget(self._play_btn)
        btn_row.addWidget(self._pause_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._forward_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._save_btn)

        layout.addLayout(btn_row)

        self._waveform = WaveformWidget()
        layout.addWidget(self._waveform)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)

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

        self._play_btn.clicked.connect(self._on_play)
        self._pause_btn.clicked.connect(self.toggle_pause)
        self._stop_btn.clicked.connect(self._on_stop)
        self._save_btn.clicked.connect(self._on_save)
        self._rewind_btn.clicked.connect(self._on_rewind)
        self._forward_btn.clicked.connect(self._on_forward)
        self._progress_slider.sliderMoved.connect(self._on_seek)

        return _glass_card(layout)

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
            btn = QPushButton(engine.name.upper())
            btn.setProperty("role", "enginePill")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, e=engine: self._select_engine(e))
            self._engine_group.addButton(btn)
            self._engine_buttons[engine.name] = btn
            self._engine_pill_row.addWidget(btn)

        self._engine_pill_row.addStretch()

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

    def _install_effects(self) -> None:
        HoverGlow(self._add_voice_btn, color="#3b82f6", max_radius=24)
        HoverGlow(self._play_btn, color="#3b82f6", max_radius=28)

    def _load_settings(self) -> None:
        engines = self._registry.available()
        if engines:
            self._current_engine = engines[0]
            if self._settings.last_voice_id:
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

        voices = self._current_engine.list_voices()
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

        def synth_segment(seg: Segment):
            yield from engine.synthesize(seg.text, voice, rate=rate, pitch=pitch, volume=volume)

        self._playback.play_segments(segments, synth_segment)

    @Slot()
    def read_clipboard(self) -> None:
        """Global hotkey / tray: read the clipboard aloud. Again on the same text stops."""
        text = read_clipboard_text(QApplication.instance())
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
        # Snapshot everything the worker needs; the UI may change while it runs.
        engine = self._current_engine
        voice = self._current_voice
        rate = self._settings.rate
        pitch = self._settings.pitch
        volume = self._settings.volume

        def save_worker() -> None:
            try:
                export_speech(
                    engine, voice, text, dest, fmt, rate=rate, pitch=pitch, volume=volume
                )
            except Exception as e:
                logger.exception("Failed to save audio")
                self._save_failed.emit(f"Save failed: {e}")
            else:
                self._save_finished.emit(str(dest))

        self.statusBar().showMessage(f"Saving {dest.name}…")
        thread = Thread(target=save_worker, daemon=True)
        thread.start()

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

    @Slot(int)
    def _on_seek(self, value: int) -> None:
        self._playback.seek(value)

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
        if browser.exec() == 1:
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

        def synth_iter():
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
        QMessageBox.information(self, "Preferences", "Coming soon!")

    @Slot()
    def _on_about(self) -> None:
        QMessageBox.information(
            self,
            "About TTS",
            "TTS · NEXUS Dark\nA premium text-to-speech application.",
        )

    @Slot(int)
    def _on_playback_state_changed(self, state: int) -> None:
        ps = PlaybackState(state)
        active = ps in (PlaybackState.SYNTHESIZING, PlaybackState.PLAYING, PlaybackState.PAUSED)
        if ps == PlaybackState.SYNTHESIZING:
            self._play_btn.setText("Synthesizing…")
            self._play_btn.setEnabled(False)
            self._pause_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        elif ps == PlaybackState.PLAYING:
            self._play_btn.setText("❚❚  Pause")
            self._play_btn.setEnabled(True)
            self._pause_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
        elif ps == PlaybackState.PAUSED:
            self._play_btn.setText("▶  Resume")
            self._play_btn.setEnabled(True)
            self._pause_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
        else:
            self._play_btn.setText("▶  Play")
            self._play_btn.setEnabled(True)
            self._pause_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
        self._rewind_btn.setEnabled(False)
        self._forward_btn.setEnabled(False)
        self._progress_slider.setEnabled(active)
        self._update_status_dot(ps)
        self._update_status()

    def _update_status_dot(self, state: PlaybackState) -> None:
        if state == PlaybackState.SYNTHESIZING:
            self._status_dot.set_state("synthesizing", "Synthesizing…")
            self._dot_pulse.start()
            self._progress_slider.stop_sweep()
        elif state == PlaybackState.PLAYING:
            self._status_dot.set_state("playing", "Playing")
            self._dot_pulse.stop()
            self._waveform.start()
            self._progress_slider.start_sweep()
        elif state == PlaybackState.PAUSED:
            self._status_dot.set_state("paused", "Paused")
            self._dot_pulse.stop()
            self._progress_slider.stop_sweep()
        else:
            self._status_dot.set_state("idle", "Idle")
            self._dot_pulse.stop()
            self._waveform.stop()
            self._progress_slider.stop_sweep()

    @Slot(str)
    def _on_playback_error(self, error: str) -> None:
        self._status_label.setText(f"Error: {error}")
        self._error_banner.show_error(error)
        self._status_dot.set_state("error", "Error")
        self._dot_pulse.stop()

    @Slot()
    def _on_synthesizing(self) -> None:
        self._error_banner.setVisible(False)
        self._update_status()
        self._update_status_dot(PlaybackState.SYNTHESIZING)

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
        fmt.setBackground(QColor(59, 130, 246, 56))
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
            len(e.list_voices()) for e in self._registry.available()
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

    def closeEvent(self, event) -> None:
        save_settings(self._settings)
        # During OS logoff/shutdown a refused close would cancel the session end.
        if (
            self._close_to_tray
            and not self._quitting
            and not QApplication.instance().isSavingSession()
        ):
            event.ignore()
            self.hide()
            self.hidden_to_tray.emit()
            return
        super().closeEvent(event)
