from __future__ import annotations

import logging

import pytest

from tts_app.log import setup_logging


@pytest.fixture
def mock_log_dir(tmp_path, monkeypatch):
    def mock_user_log_dir(appname, appauthor=False):
        return str(tmp_path)

    monkeypatch.setattr(
        "tts_app.log.platformdirs.user_log_dir",
        mock_user_log_dir,
    )
    return tmp_path


def test_setup_logging_creates_file_and_logs(mock_log_dir):
    log_path = setup_logging(logging.INFO)

    logger = logging.getLogger("test_logger")
    logger.info("Test message")

    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "Test message" in content


def test_setup_logging_returns_correct_path(mock_log_dir):
    log_path = setup_logging(logging.DEBUG)

    assert log_path.name == "tts_app.log"
    assert log_path.parent == mock_log_dir
