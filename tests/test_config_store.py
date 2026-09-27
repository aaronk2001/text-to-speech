from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError

from tts_app.config import AppSettings, load_settings, save_settings, settings_path


@pytest.fixture
def mock_config_dir(tmp_path, monkeypatch):
    def mock_user_config_dir(appname, appauthor=False):
        return str(tmp_path)

    monkeypatch.setattr(
        "tts_app.config.store.platformdirs.user_config_dir",
        mock_user_config_dir,
    )
    return tmp_path


def test_load_defaults_when_missing(mock_config_dir):
    settings = load_settings()
    assert settings.last_voice_id is None
    assert settings.rate == 1.0
    assert settings.hotkey == "ctrl+alt+s"
    assert settings.dark_mode is True


def test_round_trip_save_and_load(mock_config_dir):
    original = AppSettings(
        last_voice_id="voice123",
        rate=1.5,
        dark_mode=False,
        recent_files=["file1.txt", "file2.txt"],
    )
    save_settings(original)

    loaded = load_settings()
    assert loaded.last_voice_id == "voice123"
    assert loaded.rate == 1.5
    assert loaded.dark_mode is False
    assert loaded.recent_files == ["file1.txt", "file2.txt"]


def test_corrupt_json_returns_defaults(mock_config_dir, caplog):
    config_path = settings_path()
    config_path.write_text("{ invalid json }", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        settings = load_settings()

    assert settings.rate == 1.0
    assert "Failed to load settings" in caplog.text
    assert config_path.exists() is False
    corrupt_files = list(config_path.parent.glob("config.json.corrupt-*"))
    assert len(corrupt_files) == 1


def test_unknown_key_ignored_on_load(mock_config_dir):
    config_path = settings_path()
    config_data = {
        "rate": 1.2,
        "unknown_field": "should_be_ignored",
        "another_mystery": 42,
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")

    settings = load_settings()
    assert settings.rate == 1.2
    assert not hasattr(settings, "unknown_field")


def test_field_bounds_enforced():
    with pytest.raises(ValidationError):
        AppSettings(rate=10.0)

    with pytest.raises(ValidationError):
        AppSettings(pitch=0.1)

    with pytest.raises(ValidationError):
        AppSettings(volume=1.5)


def test_atomic_write(mock_config_dir):
    settings = AppSettings(rate=1.8, hotkey="ctrl+shift+t")
    save_settings(settings)

    config_path = settings_path()
    assert config_path.exists()

    content = config_path.read_text(encoding="utf-8")
    data = json.loads(content)
    assert data["rate"] == 1.8
    assert data["hotkey"] == "ctrl+shift+t"
