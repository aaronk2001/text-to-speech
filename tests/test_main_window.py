"""MainWindow flows driven end to end with a fake engine and a fake audio sink."""

from __future__ import annotations

import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from tts_app.audio.playback import PlaybackController, PlaybackState
from tts_app.config import AppSettings
from tts_app.engines.base import TTSEngine, Voice
from tts_app.engines.registry import EngineRegistry
from tts_app.ui import main_window
from tts_app.ui.main_window import MainWindow

from .conftest import FakeSink


class _ToneEngine(TTSEngine):
    name = "tone"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def list_voices(self) -> list[Voice]:
        return [Voice(id="tone:1", engine="tone", name="Tone", language="en")]

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        self.calls.append(text)
        yield b"\x01\x00" * 2205  # 0.1 s


@pytest.fixture
def engine() -> _ToneEngine:
    return _ToneEngine()


@pytest.fixture
def window(
    qtbot: Any,
    fake_audio: type[FakeSink],
    engine: _ToneEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[MainWindow]:
    monkeypatch.setattr(main_window, "save_settings", lambda _settings: None)
    clipboard_before = QApplication.clipboard().text()  # tests write to the real clipboard
    playback = PlaybackController()
    w = MainWindow(EngineRegistry([engine]), playback, AppSettings())
    qtbot.addWidget(w)
    yield w
    playback.shutdown()
    QApplication.clipboard().setText(clipboard_before)


def _state(w: MainWindow) -> PlaybackState:
    return w._playback.state()


def test_save_writes_the_file_the_user_picked(
    window: MainWindow,
    engine: _ToneEngine,
    qtbot: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Dialog:
        @staticmethod
        def getSaveFileName(*_args: Any) -> tuple[str, str]:
            return str(tmp_path / "speech"), "WAV (*.wav)"  # no extension typed

    monkeypatch.setattr(main_window, "QFileDialog", _Dialog)
    window._text_edit.setPlainText("Hello there. Goodbye.")

    with qtbot.waitSignal(window._save_finished, timeout=5000):
        window._on_save()

    assert engine.calls == ["Hello there.", "Goodbye."]
    with wave.open(str(tmp_path / "speech.wav"), "rb") as wf:
        assert wf.getnframes() == 2 * 2205
    assert "Saved" in window.statusBar().currentMessage()


def test_save_failure_is_shown(
    window: MainWindow, qtbot: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Dialog:
        @staticmethod
        def getSaveFileName(*_args: Any) -> tuple[str, str]:
            return str(tmp_path / "missing-dir" / "x.mp3"), "MP3 (*.mp3)"

    monkeypatch.setattr(main_window, "QFileDialog", _Dialog)
    monkeypatch.setattr("shutil.which", lambda _name: None)  # no ffmpeg
    window._text_edit.setPlainText("Hello.")

    with qtbot.waitSignal(window._save_failed, timeout=5000) as blocker:
        window._on_save()

    assert "ffmpeg" in blocker.args[0]


def test_play_button_pauses_and_resumes_instead_of_restarting(
    window: MainWindow, qtbot: Any
) -> None:
    window._text_edit.setPlainText("One sentence. Another sentence.")

    window._play_btn.click()
    qtbot.waitUntil(lambda: _state(window) == PlaybackState.PLAYING)

    window._play_btn.click()
    assert _state(window) == PlaybackState.PAUSED
    window._play_btn.click()
    assert _state(window) == PlaybackState.PLAYING
    assert len(FakeSink.instances) == 1  # same run throughout


def test_hotkey_reads_clipboard_and_second_press_stops(
    window: MainWindow, engine: _ToneEngine, qtbot: Any
) -> None:
    QApplication.clipboard().setText("Read this aloud.")

    window.read_clipboard()
    assert window._text_edit.toPlainText() == "Read this aloud."
    qtbot.waitUntil(lambda: _state(window) == PlaybackState.PLAYING)

    window.read_clipboard()
    assert _state(window) == PlaybackState.IDLE


def test_hotkey_with_new_clipboard_text_switches_to_it(
    window: MainWindow, engine: _ToneEngine, qtbot: Any
) -> None:
    QApplication.clipboard().setText("First text.")
    window.read_clipboard()
    qtbot.waitUntil(lambda: _state(window) == PlaybackState.PLAYING)

    QApplication.clipboard().setText("Second text.")
    window.read_clipboard()

    assert window._text_edit.toPlainText() == "Second text."
    qtbot.waitUntil(lambda: engine.calls[-1:] == ["Second text."])
    qtbot.waitUntil(lambda: _state(window) == PlaybackState.PLAYING)


def test_close_hides_to_tray_when_enabled(window: MainWindow, qtbot: Any) -> None:
    window.show()
    window.set_close_to_tray(True)

    with qtbot.waitSignal(window.hidden_to_tray, timeout=1000):
        window.close()

    assert not window.isVisible()
    window.show_and_raise()
    assert window.isVisible()


def test_close_quits_normally_without_tray(window: MainWindow, qtbot: Any) -> None:
    window.show()
    hidden: list[bool] = []
    window.hidden_to_tray.connect(lambda: hidden.append(True))

    assert window.close()
    assert hidden == []


def test_starts_on_the_preferred_engine(
    qtbot: Any, fake_audio: type[FakeSink], monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Other(_ToneEngine):
        name = "other"

        def list_voices(self) -> list[Voice]:
            return [Voice(id="other:1", engine="other", name="Other", language="en")]

    monkeypatch.setattr(main_window, "save_settings", lambda _settings: None)
    playback = PlaybackController()
    settings = AppSettings(engine_preference=["other", "tone"])
    w = MainWindow(EngineRegistry([_ToneEngine(), _Other()]), playback, settings)
    qtbot.addWidget(w)
    try:
        assert w._current_engine is not None and w._current_engine.name == "other"
    finally:
        playback.shutdown()


def test_pitch_slider_only_enabled_for_engines_that_use_it(window: MainWindow) -> None:
    assert not window._pitch_slider.isEnabled()  # _ToneEngine ignores pitch


def test_skip_buttons_enabled_only_while_audio_is_out(window: MainWindow, qtbot: Any) -> None:
    assert not window._forward_btn.isEnabled()
    window._text_edit.setPlainText("Some words here.")
    window._play_btn.click()
    qtbot.waitUntil(lambda: _state(window) == PlaybackState.PLAYING)
    assert window._forward_btn.isEnabled() and window._rewind_btn.isEnabled()


@pytest.mark.parametrize(("answer", "replaced"), [("Yes", True), ("No", False)])
def test_save_asks_before_replacing_a_file_under_the_added_extension(
    window: MainWindow,
    qtbot: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
    replaced: bool,
) -> None:
    existing = tmp_path / "speech.wav"
    existing.write_bytes(b"keep me")
    asked: list[str] = []

    class _Dialog:
        @staticmethod
        def getSaveFileName(*_args: Any) -> tuple[str, str]:
            return str(tmp_path / "speech"), "WAV (*.wav)"

    class _Box:
        class StandardButton:
            Yes = "Yes"
            No = "No"

        @staticmethod
        def question(_parent: Any, _title: str, text: str) -> str:
            asked.append(text)
            return answer

    monkeypatch.setattr(main_window, "QFileDialog", _Dialog)
    monkeypatch.setattr(main_window, "QMessageBox", _Box)
    window._text_edit.setPlainText("Hello.")

    if replaced:
        with qtbot.waitSignal(window._save_finished, timeout=5000):
            window._on_save()
        assert existing.read_bytes() != b"keep me"
    else:
        window._on_save()
        window.cancel_save()
        assert existing.read_bytes() == b"keep me"
    assert asked and "speech.wav" in asked[0]


def test_rvc_models_dialog_rechecks_rvc(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    rechecked: list[bool] = []

    class _Rvc(_ToneEngine):
        name = "rvc"

        def is_available(self) -> bool:
            return False

        def recheck(self) -> None:
            rechecked.append(True)

    window._registry = EngineRegistry([_ToneEngine(), _Rvc()])
    monkeypatch.setattr(main_window.QDialog, "exec", lambda self: 0)

    window._on_rvc_voices()

    assert rechecked == [True]
