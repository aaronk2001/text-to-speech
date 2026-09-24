from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from tts_app.hotkey.global_hotkey import GlobalHotkey  # noqa: E402


class FakeKeyboard:
    def __init__(self) -> None:
        self.added: list[tuple[str, Any, dict[str, Any]]] = []
        self.removed: list[object] = []

    def add_hotkey(self, spec: str, callback: Any, **kwargs: Any) -> object:
        handle = object()
        self.added.append((spec, callback, kwargs))
        return handle

    def remove_hotkey(self, handle: object) -> None:
        self.removed.append(handle)


def test_is_available_true_when_module_supplied(qapp: Any) -> None:
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=FakeKeyboard())
    assert h.is_available() is True
    assert h.install_hint() is None


def test_is_available_false_when_no_module(qapp: Any) -> None:
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=None)
    h._keyboard = None  # type: ignore[attr-defined]
    assert h.is_available() is False
    assert "keyboard" in (h.install_hint() or "")


def test_start_registers(qapp: Any) -> None:
    kb = FakeKeyboard()
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=kb)
    h.start()
    assert len(kb.added) == 1
    assert kb.added[0][0] == "ctrl+alt+s"
    assert kb.added[0][2].get("suppress") is False
    h.start()  # idempotent
    assert len(kb.added) == 1


def test_stop_unregisters(qapp: Any) -> None:
    kb = FakeKeyboard()
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=kb)
    h.start()
    h.stop()
    assert len(kb.removed) == 1


def test_change_binding_replaces_when_running(qapp: Any) -> None:
    kb = FakeKeyboard()
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=kb)
    h.start()
    h.change_binding("ctrl+alt+r")
    assert len(kb.removed) == 1
    assert kb.added[-1][0] == "ctrl+alt+r"


def test_change_binding_when_not_running_updates_spec_only(qapp: Any) -> None:
    kb = FakeKeyboard()
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=kb)
    h.change_binding("ctrl+alt+r")
    assert kb.added == []
    assert h._spec == "ctrl+alt+r"  # type: ignore[attr-defined]


def test_double_stop_is_noop(qapp: Any) -> None:
    kb = FakeKeyboard()
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=kb)
    h.stop()
    h.start()
    h.stop()
    h.stop()
    assert len(kb.removed) == 1


def test_methods_noop_when_unavailable(qapp: Any) -> None:
    h = GlobalHotkey("ctrl+alt+s", keyboard_module=None)
    h._keyboard = None  # type: ignore[attr-defined]
    h.start()
    h.stop()
    h.change_binding("ctrl+alt+r")
    assert h.is_available() is False
