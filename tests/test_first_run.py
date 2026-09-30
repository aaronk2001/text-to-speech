from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tts_app import app as app_module
from tts_app.audio.playback import PlaybackController, PlaybackState
from tts_app.config import AppSettings
from tts_app.engines.registry import EngineRegistry
from tts_app.ui import first_run
from tts_app.ui.first_run import FirstRunWizard

from .conftest import FakeSink
from .test_main_window import _ToneEngine


@pytest.fixture
def playback(fake_audio: type[FakeSink]) -> Iterator[PlaybackController]:
    p = PlaybackController()
    yield p
    p.shutdown()


def _wizard(qtbot: Any, registry: EngineRegistry, playback: PlaybackController) -> FirstRunWizard:
    w = FirstRunWizard(registry=registry, settings=AppSettings(), playback=playback)
    qtbot.addWidget(w)
    return w


def test_engine_page_does_not_block_when_nothing_is_installed(
    qtbot: Any, playback: PlaybackController
) -> None:
    w = _wizard(qtbot, EngineRegistry([]), playback)
    assert w.engines_page.isComplete()


def test_audio_test_uses_the_shared_player(
    qtbot: Any, playback: PlaybackController
) -> None:
    engine = _ToneEngine()
    w = _wizard(qtbot, EngineRegistry([engine]), playback)

    w.audio_test_page.play_button.click()

    qtbot.waitUntil(lambda: playback.state() == PlaybackState.PLAYING)
    assert engine.calls == ["Audio is working."]


def test_cannot_close_while_a_voice_is_downloading(
    qtbot: Any, playback: PlaybackController, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = _wizard(qtbot, EngineRegistry([_ToneEngine()]), playback)
    w.show()
    monkeypatch.setattr(w.voice_download_page, "is_downloading", lambda: True)

    w.reject()
    assert w.isVisible()

    monkeypatch.setattr(w.voice_download_page, "is_downloading", lambda: False)
    w.reject()
    assert not w.isVisible()


def test_app_runs_the_wizard_once(
    qtbot: Any, fake_audio: type[FakeSink], monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[bool] = []
    shown: list[FirstRunWizard] = []
    monkeypatch.setattr(app_module, "build_default_engines", lambda: [_ToneEngine()])
    monkeypatch.setattr(app_module, "load_settings", AppSettings)
    monkeypatch.setattr(
        app_module, "save_settings", lambda s: saved.append(s.first_run_complete)
    )
    monkeypatch.setattr("tts_app.ui.main_window.save_settings", lambda _s: None)
    monkeypatch.setattr(first_run.FirstRunWizard, "exec", lambda self: shown.append(self) or 0)

    a = app_module.App([])
    window = app_module.MainWindow(a._registry, a._playback, a._settings)
    qtbot.addWidget(window)
    try:
        a._run_first_run(window)
    finally:
        a._playback.shutdown()

    assert len(shown) == 1 and shown[0].playback is a._playback
    assert a._settings.first_run_complete and saved == [True]
