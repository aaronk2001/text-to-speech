from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    last_voice_id: str | None = None
    engine_preference: list[str] = ["supertonic", "piper", "sapi"]
    rate: float = Field(1.0, ge=0.25, le=3.0)
    pitch: float = Field(1.0, ge=0.5, le=2.0)
    volume: float = Field(1.0, ge=0.0, le=1.0)
    output_dir: str | None = None
    hotkey: str = "ctrl+alt+s"
    hotkey_enabled: bool = True
    auto_start: bool = False
    dark_mode: bool = True
    recent_files: list[str] = []
    first_run_complete: bool = False
    preview_text: str = "The quick brown fox jumps over the lazy dog."
    rvc_models_dir: str | None = None
    rvc_base_engine: str = "piper"
    rvc_base_voice_id: str | None = None
    reduced_motion: Literal["auto", "on", "off"] = "auto"

    model_config = {"extra": "ignore"}
