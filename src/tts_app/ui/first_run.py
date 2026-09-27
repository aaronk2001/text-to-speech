from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from tts_app.config.schema import AppSettings
from tts_app.engines.registry import EngineRegistry
from tts_app.engines.voices import (
    BUILT_IN_CATALOG,
    PiperVoiceMeta,
    download_voice,
    get_voices_dir,
    installed_voice_files,
)


class WelcomePage(QWizardPage):
    def __init__(self, parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Welcome")
        self.setSubTitle("Let's set up TTS App in 30 seconds.")

        layout = QVBoxLayout()
        label = QLabel(
            "TTS App converts text to speech using high-quality voices.\n\n"
            "This wizard will help you detect available engines, "
            "download a voice model, and test audio output."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()
        self.setLayout(layout)


class EnginesPage(QWizardPage):
    def __init__(self, registry: EngineRegistry, parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Detected engines")
        self.registry = registry
        self.registerField("engines_ready", self, "engines_ready")

        layout = QVBoxLayout()

        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Engine", "Status"])

        for engine in registry.all():
            item = QTreeWidgetItem()
            item.setText(0, engine.name)

            if engine.is_available():
                voices = engine.list_voices()
                voice_count = len(voices)
                status = f"Available · {voice_count} voice{'s' if voice_count != 1 else ''}"
            else:
                hint = engine.install_hint() or "No install hint available"
                status = f"Not available — {hint}"

            item.setText(1, status)
            tree.addTopLevelItem(item)

        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        layout.addWidget(tree)

        self.setLayout(layout)
        self._available_count = len(registry.available())

    def isComplete(self) -> bool:
        return self._available_count > 0

    @property
    def engines_ready(self) -> bool:
        return self._available_count > 0

    @engines_ready.setter
    def engines_ready(self, value: bool) -> None:
        pass


class _VoiceDownloadWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(Path)
    error = Signal(str)

    def __init__(self, meta: PiperVoiceMeta, dest_dir: Path) -> None:
        super().__init__()
        self.meta = meta
        self.dest_dir = dest_dir

    def run(self) -> None:
        try:
            result = download_voice(self.meta, self.dest_dir, on_progress=self._on_progress)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))

    def _on_progress(self, downloaded: int, total: int) -> None:
        self.progress.emit(downloaded, total)


class VoiceDownloadPage(QWizardPage):
    def __init__(self, parent: QWizard | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Download a high-quality voice")

        layout = QVBoxLayout()

        label = QLabel(
            "Pick a Piper voice to install (~60 MB). You can add more later."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        self.voice_list = QListWidget()
        self._populate_voice_list()
        layout.addWidget(self.voice_list)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        button_layout = QVBoxLayout()
        self.skip_button = QPushButton("Skip")
        self.download_button = QPushButton("Download")

        self.skip_button.clicked.connect(self._on_skip)
        self.download_button.clicked.connect(self._on_download)

        button_layout.addWidget(self.skip_button)
        button_layout.addWidget(self.download_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self._download_worker: _VoiceDownloadWorker | None = None
        self._download_complete = False

    def _populate_voice_list(self) -> None:
        installed = {f.stem for f in installed_voice_files(get_voices_dir())}

        for meta in BUILT_IN_CATALOG:
            is_installed = meta.voice_id in installed
            prefix = "✓ Installed — " if is_installed else ""
            display = (
                f"{prefix}{meta.voice_id} — {meta.language} — {meta.quality}"
                f" — ~{meta.size_mb_estimate}MB"
            )

            item = QListWidgetItem(display)
            item.setData(256, meta)
            self.voice_list.addItem(item)

            if meta.voice_id == "en_US-lessac-medium":
                self.voice_list.setCurrentItem(item)

    def isComplete(self) -> bool:
        return self._download_complete

    @Slot()
    def _on_skip(self) -> None:
        self._download_complete = True
        self.completeChanged.emit()

    @Slot()
    def _on_download(self) -> None:
        current_item = self.voice_list.currentItem()
        if not current_item:
            return

        meta: PiperVoiceMeta = current_item.data(256)

        self.skip_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.voice_list.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self._download_worker = _VoiceDownloadWorker(meta, get_voices_dir())
        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.error.connect(self._on_download_error)
        self._download_worker.start()

    @Slot(int, int)
    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            progress = int((downloaded / total) * 100)
            self.progress_bar.setValue(progress)

    @Slot(Path)
    def _on_download_finished(self, path: Path) -> None:
        self.progress_bar.setVisible(False)
        self.skip_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.voice_list.setEnabled(True)

        self._download_complete = True
        self.completeChanged.emit()

    @Slot(str)
    def _on_download_error(self, err: str) -> None:
        self.progress_bar.setVisible(False)
        self.skip_button.setEnabled(True)
        self.download_button.setEnabled(True)
        self.voice_list.setEnabled(True)

        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(self, "Download Error", f"Failed to download voice: {err}")


class AudioTestPage(QWizardPage):
    def __init__(
        self,
        play_test: Callable[[], None],
        parent: QWizard | None = None,
    ) -> None:
        super().__init__(parent)
        self.setTitle("Test audio")
        self.play_test_callable = play_test

        layout = QVBoxLayout()

        label = QLabel("Make sure your speakers are on.")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.play_button = QPushButton("▶ Play test sentence")
        self.play_button.clicked.connect(self._on_play)
        layout.addWidget(self.play_button)

        layout.addSpacing(20)

        self.heard_radio = QRadioButton("I heard it")
        self.not_heard_radio = QRadioButton("I did not hear it")

        self.heard_radio.toggled.connect(self._on_radio_changed)
        self.not_heard_radio.toggled.connect(self._on_radio_changed)

        layout.addWidget(self.heard_radio)
        layout.addWidget(self.not_heard_radio)
        layout.addStretch()

        self.setLayout(layout)

        self.registerField("audio_heard", self.heard_radio)

    @Slot()
    def _on_play(self) -> None:
        self.play_test_callable()

    @Slot(bool)
    def _on_radio_changed(self, _: bool) -> None:
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self.heard_radio.isChecked() or self.not_heard_radio.isChecked()


class FirstRunWizard(QWizard):
    def __init__(
        self,
        parent: QWizard | None = None,
        registry: EngineRegistry | None = None,
        settings: AppSettings | None = None,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("TTS App — First Run")
        self.setModal(True)

        self.registry = registry or EngineRegistry()
        self.settings = settings or AppSettings()
        self.on_complete_callback = on_complete or (lambda: None)

        self.welcome_page = WelcomePage(self)
        self.engines_page = EnginesPage(self.registry, self)
        self.voice_download_page = VoiceDownloadPage(self)
        self.audio_test_page = AudioTestPage(self._create_play_test(), self)

        self.addPage(self.welcome_page)
        self.addPage(self.engines_page)
        self.addPage(self.voice_download_page)
        self.addPage(self.audio_test_page)

        self.setWizardStyle(QWizard.ModernStyle)
        self.resize(QSize(600, 400))

    def _create_play_test(self) -> Callable[[], None]:
        def play_test() -> None:
            from tts_app.audio.playback import PlaybackController

            playback = PlaybackController()

            engine = self.registry.pick_default()
            if not engine:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(
                    self, "Error", "No TTS engine available for audio test."
                )
                return

            voices = engine.list_voices()
            if not voices:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(
                    self, "Error", f"No voices available for {engine.name} engine."
                )
                return

            voice = voices[0]

            def synthesize():
                return engine.synthesize("Audio is working.", voice)

            playback.play(synthesize)

        return play_test

    def accept(self) -> None:
        self.settings.first_run_complete = True
        self.on_complete_callback()
        super().accept()
