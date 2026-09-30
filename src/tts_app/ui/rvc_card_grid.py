from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from tts_app.engines.rvc_engine import get_rvc_models_dir
from tts_app.ui.rvc_browser import _DownloadModelWorker, _SearchWorker

logger = logging.getLogger(__name__)

ROLE_MODEL_ID = Qt.ItemDataRole.UserRole + 1
ROLE_AUTHOR = Qt.ItemDataRole.UserRole + 2
ROLE_DOWNLOADS = Qt.ItemDataRole.UserRole + 3
ROLE_LIKES = Qt.ItemDataRole.UserRole + 4

CARD_W = 220
CARD_H = 132


class _CardDelegate(QStyledItemDelegate):
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(CARD_W, CARD_H)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.setBrush(QColor(59, 130, 246, 26))
            painter.setPen(QPen(QColor(59, 130, 246, 77), 1))
        elif hovered:
            painter.setBrush(QColor("#1a2333"))
            painter.setPen(QPen(QColor(255, 255, 255, 31), 1))
        else:
            painter.setBrush(QColor("#111827"))
            painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawRoundedRect(rect, 16, 16)

        title = str(index.data(ROLE_MODEL_ID) or "")
        author = str(index.data(ROLE_AUTHOR) or "")
        downloads = index.data(ROLE_DOWNLOADS) or 0
        likes = index.data(ROLE_LIKES) or 0

        title_font = QFont("Archivo", 11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#f8fafc"))
        title_rect = QRectF(
            rect.left() + 14,
            rect.top() + 14,
            rect.width() - 28,
            42,
        )
        fm = QFontMetrics(title_font)
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, int(title_rect.width() * 2))
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            | int(Qt.TextFlag.TextWordWrap),
            elided,
        )

        painter.setFont(QFont("Space Grotesk", 9))
        painter.setPen(QColor("#94a3b8"))
        author_rect = QRectF(rect.left() + 14, rect.bottom() - 42, rect.width() - 28, 16)
        painter.drawText(
            author_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), author
        )

        painter.setFont(QFont("JetBrains Mono", 8))
        painter.setPen(QColor("#cbd5e1"))
        stats_rect = QRectF(rect.left() + 14, rect.bottom() - 22, rect.width() - 28, 16)
        try:
            d_text = f"{int(downloads):,}"
            l_text = f"{int(likes):,}"
        except (TypeError, ValueError):
            d_text, l_text = str(downloads), str(likes)
        painter.drawText(
            stats_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"↓ {d_text}    ♥ {l_text}",
        )

        painter.restore()


class RvcCardGrid(QWidget):
    voice_downloaded = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._search_worker: _SearchWorker | None = None
        self._download_worker: _DownloadModelWorker | None = None
        self._last_query: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setAcceptDrops(True)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        browse_btn = QPushButton("Browse voice-models.com ↗")
        browse_btn.setProperty("role", "primary")
        browse_btn.setToolTip(
            "Open the voice-models.com search engine in your browser.\n"
            "Download a model zip, then drag the .pth here."
        )
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse_voice_models)
        import_btn = QPushButton("Import .pth…")
        import_btn.setProperty("role", "ghost")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self._on_import_clicked)
        open_folder_btn = QPushButton("Open folder")
        open_folder_btn.setProperty("role", "ghost")
        open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_folder_btn.clicked.connect(self._on_open_folder)
        drop_hint = QLabel("or drop .pth files anywhere on this panel")
        drop_hint.setProperty("role", "bodyMuted")
        toolbar.addWidget(browse_btn)
        toolbar.addWidget(import_btn)
        toolbar.addWidget(open_folder_btn)
        toolbar.addWidget(drop_hint)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        self._model = QStandardItemModel(self)
        self._view = QListView()
        self._view.setModel(self._model)
        self._view.setItemDelegate(_CardDelegate(self))
        self._view.setViewMode(QListView.ViewMode.IconMode)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setMovement(QListView.Movement.Static)
        self._view.setUniformItemSizes(True)
        self._view.setSpacing(12)
        self._view.setMouseTracking(True)
        self._view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._view.setStyleSheet("QListView { background: transparent; border: none; }")
        sel_model = self._view.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection_changed)
        outer.addWidget(self._view, stretch=1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "bodyMuted")
        action_row.addWidget(self._status_label, stretch=1)
        self._download_btn = QPushButton("Download Selected")
        self._download_btn.setProperty("role", "primary")
        self._download_btn.setEnabled(False)
        self._download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download_btn.clicked.connect(self._on_download)
        action_row.addWidget(self._download_btn)
        outer.addLayout(action_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        outer.addWidget(self._progress_bar)

        installed_label = QLabel("Installed")
        installed_label.setProperty("role", "sectionHeading")
        outer.addWidget(installed_label)

        self._installed_view = QListView()
        self._installed_model = QStandardItemModel(self)
        self._installed_view.setModel(self._installed_model)
        self._installed_view.setMaximumHeight(80)
        outer.addWidget(self._installed_view)

        self.setLayout(outer)
        self._refresh_installed()

    def run_search(self, query: str) -> None:
        q = query.strip()
        if not q:
            return
        self._last_query = q
        self._status_label.setText("Searching…")
        self._model.clear()
        self._search_worker = _SearchWorker(q)
        self._search_worker.results_ready.connect(self._on_search_results)
        self._search_worker.error_occurred.connect(self._on_search_error)
        self._search_worker.start()

    @Slot(list)
    def _on_search_results(self, results: list[dict[str, Any]]) -> None:
        self._status_label.setText(f"{len(results)} models")
        self._model.clear()
        for r in results:
            item = QStandardItem()
            item.setData(r.get("id", ""), Qt.ItemDataRole.DisplayRole)
            item.setData(r.get("id", ""), ROLE_MODEL_ID)
            item.setData(r.get("author", ""), ROLE_AUTHOR)
            item.setData(r.get("downloads", 0), ROLE_DOWNLOADS)
            item.setData(r.get("likes", 0), ROLE_LIKES)
            item.setEditable(False)
            self._model.appendRow(item)

    @Slot(str)
    def _on_search_error(self, error: str) -> None:
        self._status_label.setText(f"Search failed: {error}")

    def _on_selection_changed(self, *_args: object) -> None:
        sel = self._view.selectionModel()
        self._download_btn.setEnabled(bool(sel and sel.selectedIndexes()))

    def _on_download(self) -> None:
        sel = self._view.selectionModel()
        if sel is None:
            return
        idxs = sel.selectedIndexes()
        if not idxs:
            return
        model_id = idxs[0].data(ROLE_MODEL_ID)
        if not model_id:
            return
        self._download_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText(f"Downloading {model_id}…")
        self._download_worker = _DownloadModelWorker(model_id)
        self._download_worker.progress.connect(lambda c, _t: self._progress_bar.setValue(c))
        self._download_worker.finished_download.connect(self._on_download_finished)
        self._download_worker.error_occurred.connect(self._on_download_error)
        self._download_worker.start()

    @Slot(str)
    def _on_download_finished(self, path: str) -> None:
        self._progress_bar.setVisible(False)
        self._download_btn.setEnabled(True)
        self._status_label.setText(f"Installed → {path}")
        self._refresh_installed()
        self.voice_downloaded.emit()

    @Slot(str)
    def _on_download_error(self, error: str) -> None:
        self._progress_bar.setVisible(False)
        self._download_btn.setEnabled(True)
        self._status_label.setText(f"Download failed: {error}")

    def _refresh_installed(self) -> None:
        self._installed_model.clear()
        models_dir = get_rvc_models_dir()
        for pth in sorted(models_dir.glob("**/*.pth")):
            item = QStandardItem(pth.stem)
            item.setEditable(False)
            self._installed_model.appendRow(item)

    def _on_import_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select RVC .pth model(s)",
            "",
            "RVC models (*.pth)",
        )
        if paths:
            self._import_files(paths)

    def _on_open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(get_rvc_models_dir())))

    def _on_browse_voice_models(self) -> None:
        from urllib.parse import quote_plus
        if self._last_query:
            url = f"https://voice-models.com/?search={quote_plus(self._last_query)}"
        else:
            url = "https://voice-models.com/"
        QDesktopServices.openUrl(QUrl(url))

    def _import_files(self, paths: list[str]) -> None:
        try:
            dest = get_rvc_models_dir()
        except Exception as e:
            logger.exception("rvc import: cannot resolve models dir")
            self._status_label.setText(f"Import failed: {e}")
            return

        imported = 0
        last_err = ""
        for p in paths:
            try:
                src = Path(p)
                if not src.exists() or src.suffix.lower() != ".pth":
                    continue
                shutil.copy2(src, dest / src.name)
                sib = src.with_suffix(".index")
                if sib.exists():
                    shutil.copy2(sib, dest / sib.name)
                imported += 1
            except Exception as e:
                logger.exception("rvc import failed for %s", p)
                last_err = str(e)

        if imported:
            self._status_label.setText(f"Imported {imported} model(s)")
            try:
                self._refresh_installed()
            except Exception:
                logger.exception("rvc refresh_installed failed")
            self.voice_downloaded.emit()
        elif last_err:
            self._status_label.setText(f"Import failed: {last_err}")
        else:
            self._status_label.setText("No .pth files imported")

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        md = e.mimeData()
        if md.hasUrls() and any(
            u.toLocalFile().lower().endswith(".pth") for u in md.urls()
        ):
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        paths = [
            u.toLocalFile()
            for u in e.mimeData().urls()
            if u.toLocalFile().lower().endswith(".pth")
        ]
        if paths:
            self._import_files(paths)
            e.acceptProposedAction()
