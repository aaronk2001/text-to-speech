from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tts_app.engines.base import Voice
from tts_app.engines.registry import EngineRegistry
from tts_app.engines.voices import (
    BUILT_IN_CATALOG,
    download_voice,
    get_voices_dir,
    installed_voice_files,
)

logger = logging.getLogger(__name__)


class _DownloadWorker(QThread):
    progress = Signal(int, int)
    finished_download = Signal()
    error_occurred = Signal(str)

    def __init__(self, voice_id: str) -> None:
        super().__init__()
        self.voice_id = voice_id
        self.meta = None
        for m in BUILT_IN_CATALOG:
            if m.voice_id == voice_id:
                self.meta = m
                break

    def run(self) -> None:
        if not self.meta:
            self.error_occurred.emit(f"Voice {self.voice_id} not found")
            return
        try:
            def on_progress(downloaded: int, total: int) -> None:
                self.progress.emit(downloaded, total)

            download_voice(self.meta, get_voices_dir(), on_progress=on_progress)
            self.finished_download.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


class VoiceBrowser(QDialog):
    SOURCES = ("Installed", "Download Piper")

    def __init__(self, registry: EngineRegistry) -> None:
        super().__init__()
        self.setObjectName("voicePalette")
        self.setWindowTitle("Add a Voice")
        self.setMinimumSize(760, 580)
        self.setModal(True)

        self._registry = registry
        self._selected_voice: Voice | None = None
        self._download_worker: _DownloadWorker | None = None

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._search = QLineEdit()
        self._search.setProperty("role", "paletteSearch")
        self._search.setPlaceholderText("Search voices, accents, characters…")
        self._search.textChanged.connect(self._on_search_changed)
        self._search.returnPressed.connect(self._on_search_submit)
        outer.addWidget(self._search)

        pill_row = QHBoxLayout()
        pill_row.setContentsMargins(20, 14, 20, 6)
        pill_row.setSpacing(8)
        self._pill_group = QButtonGroup(self)
        self._pill_group.setExclusive(True)
        self._pill_buttons: dict[str, QPushButton] = {}
        for src in self.SOURCES:
            btn = QPushButton(src)
            btn.setProperty("role", "enginePill")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, s=src: self._switch_source(s))
            pill_row.addWidget(btn)
            self._pill_group.addButton(btn)
            self._pill_buttons[src] = btn
        pill_row.addStretch()
        outer.addLayout(pill_row)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._create_installed_view())
        self._stack.addWidget(self._create_download_view())
        outer.addWidget(self._stack, stretch=1)

        footer = QHBoxLayout()
        footer.setContentsMargins(20, 14, 20, 16)
        footer.setSpacing(8)
        cancel = QPushButton("Cancel")
        cancel.setProperty("role", "ghost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        use = QPushButton("Use voice")
        use.setProperty("role", "primary")
        use.setCursor(Qt.CursorShape.PointingHandCursor)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(use)
        outer.addLayout(footer)

        cancel.clicked.connect(self.reject)
        use.clicked.connect(self._on_use_clicked)

        self.setLayout(outer)

        self._pill_buttons["Installed"].setChecked(True)
        self._switch_source("Installed")

    def _switch_source(self, src: str) -> None:
        idx = self.SOURCES.index(src)
        self._stack.setCurrentIndex(idx)
        self._search.setPlaceholderText("Search voices, accents, characters…")
        self._on_search_changed(self._search.text())

    def _create_installed_view(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout()
        v.setContentsMargins(20, 8, 20, 8)
        v.setSpacing(0)
        self._installed_list = QListWidget()
        self._installed_list.setSpacing(2)
        self._installed_list.itemDoubleClicked.connect(self._on_installed_double)
        self._installed_list.itemSelectionChanged.connect(self._on_installed_select)
        v.addWidget(self._installed_list)
        container.setLayout(v)
        self._populate_installed()
        return container

    def _populate_installed(self) -> None:
        self._installed_list.clear()
        engine_for: dict[str, str] = {}
        for engine in self._registry.available():
            for v in self._registry.voices(engine):
                engine_for[v.id] = engine.name.upper()
        for voice in self._registry.all_voices():
            engine_name = engine_for.get(voice.id, "?")
            quality = (
                f"q{voice.quality}"
                if isinstance(voice.quality, int)
                else (voice.quality or "—")
            )
            label = (
                f"{voice.name}  ·  {engine_name}  ·  "
                f"{voice.language or '—'}  ·  {quality}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, voice)
            self._installed_list.addItem(item)

    def _on_installed_select(self) -> None:
        items = self._installed_list.selectedItems()
        if items:
            v = items[0].data(Qt.ItemDataRole.UserRole)
            if isinstance(v, Voice):
                self._selected_voice = v

    def _on_installed_double(self, item: QListWidgetItem) -> None:
        v = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(v, Voice):
            self._selected_voice = v
            self.accept()

    def _create_download_view(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout()
        v.setContentsMargins(20, 8, 20, 8)
        v.setSpacing(8)

        self._download_tree = QTreeWidget()
        self._download_tree.setColumnCount(5)
        self._download_tree.setHeaderLabels(
            ["Name", "Language", "Quality", "Size MB", "Status"]
        )
        self._download_tree.setRootIsDecorated(False)
        v.addWidget(self._download_tree)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addStretch()
        download_btn = QPushButton("Download")
        download_btn.setProperty("role", "primary")
        download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        download_btn.clicked.connect(self._on_download)
        action_row.addWidget(download_btn)
        v.addLayout(action_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        v.addWidget(self._progress_bar)

        container.setLayout(v)
        self._populate_download()
        return container

    def _populate_download(self) -> None:
        self._download_tree.clear()
        installed = {f.stem for f in installed_voice_files(get_voices_dir())}
        for meta in BUILT_IN_CATALOG:
            item = QTreeWidgetItem()
            item.setText(0, meta.name)
            item.setText(1, meta.language)
            item.setText(2, meta.quality or "standard")
            item.setText(3, f"{meta.size_mb:.1f}")
            onnx_file = f"{meta.voice_id}.onnx"
            is_installed = onnx_file in installed
            item.setText(4, "Installed" if is_installed else "Available")
            item.setData(0, Qt.ItemDataRole.UserRole, meta)
            self._download_tree.addTopLevelItem(item)

    def _on_download(self) -> None:
        selected = self._download_tree.selectedItems()
        if not selected:
            return
        item = selected[0]
        meta = item.data(0, Qt.ItemDataRole.UserRole)
        if not meta:
            return

        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._download_worker = _DownloadWorker(meta.voice_id)
        self._download_worker.progress.connect(
            lambda d, t: self._progress_bar.setValue(
                int(100 * d / t) if t > 0 else 0
            )
        )
        self._download_worker.finished_download.connect(self._on_download_finished)
        self._download_worker.error_occurred.connect(self._on_download_error)
        self._download_worker.start()

    @Slot()
    def _on_download_finished(self) -> None:
        self._progress_bar.setVisible(False)
        self._registry.refresh()  # a new voice can make Piper available
        self._populate_download()
        self._populate_installed()

    @Slot(str)
    def _on_download_error(self, error: str) -> None:
        self._progress_bar.setVisible(False)
        logger.error(f"Download error: {error}")


    def _on_search_changed(self, text: str) -> None:
        needle = text.lower().strip()
        idx = self._stack.currentIndex()
        if idx == 0:
            for i in range(self._installed_list.count()):
                item = self._installed_list.item(i)
                item.setHidden(bool(needle) and needle not in item.text().lower())
        elif idx == 1:
            root = self._download_tree.invisibleRootItem()
            for i in range(root.childCount()):
                row = root.child(i)
                row_text = " ".join(
                    row.text(c) for c in range(row.columnCount())
                ).lower()
                row.setHidden(bool(needle) and needle not in row_text)

    def _on_search_submit(self) -> None:
        return

    def _on_use_clicked(self) -> None:
        if self._stack.currentIndex() == 0 and self._selected_voice is not None:
            self.accept()
        elif self._stack.currentIndex() == 0:
            return
        else:
            return

    def selectedVoice(self) -> Voice | None:
        return self._selected_voice
