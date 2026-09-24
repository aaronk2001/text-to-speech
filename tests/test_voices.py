from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tts_app.engines.voices import BUILT_IN_CATALOG, PiperVoiceMeta, download_voice, installed_voice_files


def test_built_in_catalog_not_empty():
    assert len(BUILT_IN_CATALOG) > 0


def test_built_in_catalog_valid_urls():
    for voice in BUILT_IN_CATALOG:
        assert voice.download_url_onnx.startswith("https://huggingface.co/")
        assert voice.download_url_json.startswith("https://huggingface.co/")
        assert ".onnx" in voice.download_url_onnx
        assert ".onnx.json" in voice.download_url_json


def test_installed_voice_files_empty(tmp_path):
    result = installed_voice_files(tmp_path)
    assert result == []


def test_installed_voice_files_finds_onnx(tmp_path):
    (tmp_path / "voice1.onnx").touch()
    (tmp_path / "voice2.onnx").touch()
    (tmp_path / "readme.txt").touch()

    result = installed_voice_files(tmp_path)
    assert len(result) == 2
    assert all(p.suffix == ".onnx" for p in result)


def test_download_voice_success(tmp_path, monkeypatch):
    meta = PiperVoiceMeta(
        voice_id="test-model",
        language="en_US",
        quality="medium",
        name="Test",
        gender="Male",
        download_url_onnx="https://example.com/test.onnx",
        download_url_json="https://example.com/test.onnx.json",
        size_mb_estimate=60,
    )

    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [b"test_data"]
    mock_resp.headers = {"content-length": "9"}
    mock_resp.raise_for_status.return_value = None

    mock_json_resp = MagicMock()
    mock_json_resp.text = '{"test": "json"}'
    mock_json_resp.raise_for_status.return_value = None

    def mock_get(url, **kwargs):
        if ".json" in url:
            return mock_json_resp
        return mock_resp

    monkeypatch.setattr("tts_app.engines.voices.requests.get", mock_get)

    progress_calls = []

    def on_progress(downloaded, total):
        progress_calls.append((downloaded, total))

    result = download_voice(meta, tmp_path, on_progress=on_progress)

    assert result.exists()
    assert result.name == "test-model.onnx"
    assert (tmp_path / "test-model.onnx.json").exists()
    assert len(progress_calls) > 0


def test_download_voice_disk_space_check(tmp_path, monkeypatch):
    meta = PiperVoiceMeta(
        voice_id="test",
        language="en_US",
        quality="medium",
        name="Test",
        gender="Male",
        download_url_onnx="https://example.com/test.onnx",
        download_url_json="https://example.com/test.onnx.json",
        size_mb_estimate=60,
    )

    monkeypatch.setattr(
        "tts_app.engines.voices.shutil.disk_usage",
        lambda p: (0, 1, 0),
    )

    with pytest.raises(RuntimeError, match="Not enough disk space"):
        download_voice(meta, tmp_path)


def test_download_voice_http_error(tmp_path, monkeypatch):
    meta = PiperVoiceMeta(
        voice_id="test",
        language="en_US",
        quality="medium",
        name="Test",
        gender="Male",
        download_url_onnx="https://example.com/test.onnx",
        download_url_json="https://example.com/test.onnx.json",
        size_mb_estimate=60,
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("HTTP 404")

    monkeypatch.setattr("tts_app.engines.voices.requests.get", lambda *a, **k: mock_resp)

    with pytest.raises(Exception):
        download_voice(meta, tmp_path)
