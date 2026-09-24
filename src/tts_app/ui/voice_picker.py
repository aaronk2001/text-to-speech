from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal, Slot
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tts_app.engines.base import Voice

_ROLE_VOICE = Qt.ItemDataRole.UserRole + 1


class VoicePicker(QPushButton):
    voiceChanged = Signal(Voice)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._voices: list[Voice] = []
        self._current: Voice | None = None
        self._popup: _VoicePopup | None = None

        self.setProperty("role", "voicePicker")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.clicked.connect(self._open_popup)

        self._refresh_label()

    def sizeHint(self) -> QSize:
        sh = super().sizeHint()
        return QSize(sh.width(), max(sh.height(), 40))

    def minimumSizeHint(self) -> QSize:
        sh = super().minimumSizeHint()
        return QSize(sh.width(), max(sh.height(), 40))

    def setVoices(self, voices: list[Voice], engine_name: str | None = None) -> None:
        self._voices = list(voices)
        if self._current is None or self._current not in self._voices:
            self._current = self._voices[0] if self._voices else None
        self._engine_name = engine_name
        self._refresh_label()

    def currentVoice(self) -> Voice | None:
        return self._current

    def setCurrentVoice(self, v: Voice | None) -> None:
        if v is self._current:
            return
        self._current = v
        self._refresh_label()

    def _refresh_label(self) -> None:
        if self._current is None:
            self.setText("No voice selected")
            return
        v = self._current
        quality = v.quality if isinstance(v.quality, int) else 3
        dots = "●" * quality + "○" * (5 - quality)
        lang = v.language or "—"
        self.setText(f"{v.name}   ·   {lang}   ·   {dots}")

    def _open_popup(self) -> None:
        if not self._voices:
            return
        if self._popup is not None:
            self._popup.close()
        self._popup = _VoicePopup(self._voices, self._current, self)
        self._popup.voiceChosen.connect(self._on_chosen)
        gp = self.mapToGlobal(QPoint(0, self.height() + 4))
        self._popup.move(gp)
        self._popup.resize(self.width(), 320)
        self._popup.show()
        self._popup.focus_search()

    @Slot(Voice)
    def _on_chosen(self, voice: Voice) -> None:
        self._current = voice
        self._refresh_label()
        self.voiceChanged.emit(voice)
        if self._popup is not None:
            self._popup.close()


class _VoicePopup(QFrame):
    voiceChosen = Signal(Voice)

    def __init__(
        self, voices: list[Voice], current: Voice | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setProperty("role", "voicePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._voices = voices
        self._current = current

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel("VOICES")
        header.setProperty("role", "sectionHeading")
        layout.addWidget(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by name or language…")
        self._search.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._search)

        self._model = QStandardItemModel(self)
        self._view = QListView()
        self._view.setModel(self._model)
        self._view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._view.setStyleSheet("QListView { background: transparent; border: none; }")
        self._view.activated.connect(self._on_activated)
        self._view.clicked.connect(self._on_activated)
        layout.addWidget(self._view, stretch=1)

        self.setLayout(layout)
        self._populate(self._voices)

    def focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.PopupFocusReason)

    def _populate(self, voices: list[Voice]) -> None:
        self._model.clear()
        for v in voices:
            quality = v.quality if isinstance(v.quality, int) else 3
            dots = "●" * quality + "○" * (5 - quality)
            label = f"{v.name}   ·   {v.language or '—'}   ·   {dots}"
            item = QStandardItem(label)
            item.setData(v, _ROLE_VOICE)
            item.setEditable(False)
            self._model.appendRow(item)
            if self._current and v.id == self._current.id:
                self._view.setCurrentIndex(item.index())

    @Slot(str)
    def _on_filter_changed(self, text: str) -> None:
        needle = text.lower().strip()
        if not needle:
            self._populate(self._voices)
            return
        filtered = [
            v
            for v in self._voices
            if needle in v.name.lower() or needle in (v.language or "").lower()
        ]
        self._populate(filtered)

    def _on_activated(self, index) -> None:
        v = index.data(_ROLE_VOICE)
        if isinstance(v, Voice):
            self.voiceChosen.emit(v)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
