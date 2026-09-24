from __future__ import annotations

import logging
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tts_app.engines.rvc_engine import get_rvc_models_dir

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api/models"


class _SearchWorker(QThread):
    results_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, query: str) -> None:
        super().__init__()
        self._query = query

    def run(self) -> None:
        try:
            params = {
                "search": f"rvc {self._query}",
                "filter": "audio",
                "sort": "downloads",
                "direction": "-1",
                "limit": "30",
            }
            resp = requests.get(HF_API, params=params, timeout=15)
            resp.raise_for_status()
            models = resp.json()
            results = []
            for m in models:
                results.append({
                    "id": m.get("id", ""),
                    "author": m.get("author", "unknown"),
                    "downloads": m.get("downloads", 0),
                    "likes": m.get("likes", 0),
                    "tags": m.get("tags", []),
                })
            self.results_ready.emit(results)
        except Exception as e:
            self.error_occurred.emit(str(e))


class _DownloadModelWorker(QThread):
    progress = Signal(int, int)
    finished_download = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, model_id: str) -> None:
        super().__init__()
        self._model_id = model_id

    def run(self) -> None:
        try:
            # Fetch file list from HuggingFace API
            resp = requests.get(
                f"https://huggingface.co/api/models/{self._model_id}",
                timeout=15,
            )
            resp.raise_for_status()
            model_info = resp.json()

            siblings = model_info.get("siblings", [])
            pth_files = [s["rfilename"] for s in siblings if s["rfilename"].endswith(".pth")]
            index_files = [s["rfilename"] for s in siblings if s["rfilename"].endswith(".index")]

            if not pth_files:
                self.error_occurred.emit("No .pth model files found in this repository")
                return

            dest_dir = get_rvc_models_dir() / self._model_id.replace("/", "_")
            dest_dir.mkdir(parents=True, exist_ok=True)

            files_to_download = pth_files[:1] + index_files[:1]  # First .pth + first .index
            total_files = len(files_to_download)

            for i, filename in enumerate(files_to_download):
                url = f"https://huggingface.co/{self._model_id}/resolve/main/{filename}"
                dest_path = dest_dir / Path(filename).name

                resp = requests.get(url, stream=True, timeout=30)
                resp.raise_for_status()
                total_bytes = int(resp.headers.get("content-length", 0))
                downloaded = 0

                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if self.isInterruptionRequested():
                            return
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            overall = int(((i + downloaded / max(total_bytes, 1)) / total_files) * 100)
                            self.progress.emit(overall, 100)

            self.finished_download.emit(str(dest_dir))
        except Exception as e:
            self.error_occurred.emit(str(e))


class RvcBrowserWidget(QWidget):
    voice_downloaded = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._search_worker: _SearchWorker | None = None
        self._download_worker: _DownloadModelWorker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("e.g. trump, morgan freeman, anime...")
        self._search_btn = QPushButton("Search HuggingFace")
        search_layout.addWidget(self._search_input)
        search_layout.addWidget(self._search_btn)
        layout.addLayout(search_layout)

        # Results tree
        self._results_tree = QTreeWidget()
        self._results_tree.setColumnCount(4)
        self._results_tree.setHeaderLabels(["Model", "Author", "Downloads", "Likes"])
        self._results_tree.setColumnWidth(0, 300)
        layout.addWidget(self._results_tree)

        # Download section
        dl_layout = QHBoxLayout()
        self._download_btn = QPushButton("Download Selected")
        self._download_btn.setEnabled(False)
        dl_layout.addWidget(self._download_btn)
        dl_layout.addStretch()

        self._status_label = QLabel("")
        dl_layout.addWidget(self._status_label)
        layout.addLayout(dl_layout)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Installed models section
        installed_label = QLabel("Installed RVC Models:")
        installed_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(installed_label)

        self._installed_tree = QTreeWidget()
        self._installed_tree.setColumnCount(2)
        self._installed_tree.setHeaderLabels(["Model Name", "Path"])
        self._installed_tree.setMaximumHeight(120)
        layout.addWidget(self._installed_tree)

        self.setLayout(layout)

        # Connections
        self._search_btn.clicked.connect(self._on_search)
        self._search_input.returnPressed.connect(self._on_search)
        self._download_btn.clicked.connect(self._on_download)
        self._results_tree.itemSelectionChanged.connect(self._on_selection_changed)

        self._refresh_installed()

    def run_search(self, query: str) -> None:
        self._search_input.setText(query)
        self._on_search()

    def _on_search(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return

        self._search_btn.setEnabled(False)
        self._status_label.setText("Searching...")
        self._results_tree.clear()

        self._search_worker = _SearchWorker(query)
        self._search_worker.results_ready.connect(self._on_search_results)
        self._search_worker.error_occurred.connect(self._on_search_error)
        self._search_worker.start()

    @Slot(list)
    def _on_search_results(self, results: list) -> None:
        self._search_btn.setEnabled(True)
        self._status_label.setText(f"Found {len(results)} models")

        for model in results:
            item = QTreeWidgetItem()
            item.setText(0, model["id"])
            item.setText(1, model["author"])
            item.setText(2, str(model["downloads"]))
            item.setText(3, str(model["likes"]))
            item.setData(0, Qt.ItemDataRole.UserRole, model["id"])
            self._results_tree.addTopLevelItem(item)

    @Slot(str)
    def _on_search_error(self, error: str) -> None:
        self._search_btn.setEnabled(True)
        self._status_label.setText(f"Search failed: {error}")

    def _on_selection_changed(self) -> None:
        self._download_btn.setEnabled(bool(self._results_tree.selectedItems()))

    def _on_download(self) -> None:
        selected = self._results_tree.selectedItems()
        if not selected:
            return

        model_id = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not model_id:
            return

        self._download_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText(f"Downloading {model_id}...")

        self._download_worker = _DownloadModelWorker(model_id)
        self._download_worker.progress.connect(
            lambda cur, tot: self._progress_bar.setValue(cur)
        )
        self._download_worker.finished_download.connect(self._on_download_finished)
        self._download_worker.error_occurred.connect(self._on_download_error)
        self._download_worker.start()

    @Slot(str)
    def _on_download_finished(self, path: str) -> None:
        self._progress_bar.setVisible(False)
        self._download_btn.setEnabled(True)
        self._status_label.setText(f"Downloaded to: {path}")
        self._refresh_installed()
        self.voice_downloaded.emit()

    @Slot(str)
    def _on_download_error(self, error: str) -> None:
        self._progress_bar.setVisible(False)
        self._download_btn.setEnabled(True)
        self._status_label.setText(f"Download failed: {error}")
        QMessageBox.warning(self, "Download Error", error)

    def _refresh_installed(self) -> None:
        self._installed_tree.clear()
        models_dir = get_rvc_models_dir()
        for pth in sorted(models_dir.glob("**/*.pth")):
            item = QTreeWidgetItem()
            item.setText(0, pth.stem)
            item.setText(1, str(pth.parent.relative_to(models_dir)))
            self._installed_tree.addTopLevelItem(item)
