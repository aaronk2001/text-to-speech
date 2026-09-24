from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

_INSTALLED_HANDLERS: list[logging.Handler] = []


def setup_logging(level: int = logging.INFO) -> Path:
    log_dir = Path(platformdirs.user_log_dir("TTSApp", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tts_app.log"

    root = logging.getLogger()
    root.setLevel(level)

    for h in list(_INSTALLED_HANDLERS):
        try:
            root.removeHandler(h)
            h.close()
        except Exception:  # noqa: BLE001
            pass
        _INSTALLED_HANDLERS.remove(h)

    file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3)
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(file_handler)
    _INSTALLED_HANDLERS.append(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(stream_handler)
    _INSTALLED_HANDLERS.append(stream_handler)

    file_handler.emit(logging.LogRecord("tts_app", level, __file__, 0, "log started", None, None))
    file_handler.flush()
    return log_path


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
