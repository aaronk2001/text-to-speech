from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import platformdirs

from .schema import AppSettings

logger = logging.getLogger(__name__)


def settings_path() -> Path:
    config_dir = Path(platformdirs.user_config_dir("TTSApp", appauthor=False))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_settings() -> AppSettings:
    path = settings_path()

    if not path.exists():
        return AppSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AppSettings.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to load settings: {e}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt_path = path.parent / f"{path.name}.corrupt-{timestamp}"
        path.rename(corrupt_path)
        logger.info(f"Moved corrupt config to {corrupt_path}")
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    data = settings.model_dump(mode="json")
    temp_path = path.parent / f"{path.name}.tmp"

    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(temp_path), str(path))
