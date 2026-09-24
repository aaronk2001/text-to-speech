from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import platformdirs
import requests


def get_voices_dir() -> Path:
    """Get or create the voices directory."""
    d = Path(platformdirs.user_data_dir("TTSApp", appauthor=False)) / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class PiperVoiceMeta:
    voice_id: str
    language: str
    quality: str
    name: str
    gender: str | None
    download_url_onnx: str
    download_url_json: str
    size_mb_estimate: int
    size_mb: float


def _hf_url(lang_family: str, lang_code: str, voice_name: str, quality: str, voice_id: str, ext: str) -> str:
    """Build HuggingFace resolve URL."""
    return f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang_family}/{lang_code}/{voice_name}/{quality}/{voice_id}{ext}"


BUILT_IN_CATALOG: tuple[PiperVoiceMeta, ...] = (
    PiperVoiceMeta(
        voice_id="en_US-lessac-medium",
        language="en_US",
        quality="medium",
        name="Lessac",
        gender="Male",
        download_url_onnx=_hf_url("en", "en_US", "lessac", "medium", "en_US-lessac-medium", ".onnx"),
        download_url_json=_hf_url("en", "en_US", "lessac", "medium", "en_US-lessac-medium", ".onnx.json"),
        size_mb_estimate=60,
        size_mb=63.5,
    ),
    PiperVoiceMeta(
        voice_id="en_US-amy-medium",
        language="en_US",
        quality="medium",
        name="Amy",
        gender="Female",
        download_url_onnx=_hf_url("en", "en_US", "amy", "medium", "en_US-amy-medium", ".onnx"),
        download_url_json=_hf_url("en", "en_US", "amy", "medium", "en_US-amy-medium", ".onnx.json"),
        size_mb_estimate=60,
        size_mb=63.1,
    ),
    PiperVoiceMeta(
        voice_id="en_US-ryan-high",
        language="en_US",
        quality="high",
        name="Ryan",
        gender="Male",
        download_url_onnx=_hf_url("en", "en_US", "ryan", "high", "en_US-ryan-high", ".onnx"),
        download_url_json=_hf_url("en", "en_US", "ryan", "high", "en_US-ryan-high", ".onnx.json"),
        size_mb_estimate=110,
        size_mb=109.9,
    ),
    PiperVoiceMeta(
        voice_id="en_GB-alan-medium",
        language="en_GB",
        quality="medium",
        name="Alan",
        gender="Male",
        download_url_onnx=_hf_url("en", "en_GB", "alan", "medium", "en_GB-alan-medium", ".onnx"),
        download_url_json=_hf_url("en", "en_GB", "alan", "medium", "en_GB-alan-medium", ".onnx.json"),
        size_mb_estimate=60,
        size_mb=63.0,
    ),
    PiperVoiceMeta(
        voice_id="en_GB-jenny_dioco-medium",
        language="en_GB",
        quality="medium",
        name="Jenny Dioco",
        gender="Female",
        download_url_onnx=_hf_url("en", "en_GB", "jenny_dioco", "medium", "en_GB-jenny_dioco-medium", ".onnx"),
        download_url_json=_hf_url("en", "en_GB", "jenny_dioco", "medium", "en_GB-jenny_dioco-medium", ".onnx.json"),
        size_mb_estimate=60,
        size_mb=63.4,
    ),
    PiperVoiceMeta(
        voice_id="es_ES-davefx-medium",
        language="es_ES",
        quality="medium",
        name="DaveFX",
        gender="Male",
        download_url_onnx=_hf_url("es", "es_ES", "davefx", "medium", "es_ES-davefx-medium", ".onnx"),
        download_url_json=_hf_url("es", "es_ES", "davefx", "medium", "es_ES-davefx-medium", ".onnx.json"),
        size_mb_estimate=60,
        size_mb=63.2,
    ),
)


def installed_voice_files(dir: Path) -> list[Path]:
    """Return list of installed .onnx voice files."""
    return sorted(dir.glob("*.onnx"))


def download_voice(
    meta: PiperVoiceMeta,
    dest_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download voice model from HuggingFace.

    Returns path to .onnx file. Raises RuntimeError on HTTP errors or disk space issues.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    size_bytes = meta.size_mb_estimate * 1024 * 1024
    _, free_bytes, _ = shutil.disk_usage(dest_dir)
    if free_bytes < size_bytes * 2:
        raise RuntimeError(f"Not enough disk space: need {size_bytes * 2 / (1024**2):.0f} MB, have {free_bytes / (1024**2):.0f} MB")

    onnx_path = dest_dir / f"{meta.voice_id}.onnx"
    tmp_path = onnx_path.with_suffix(".onnx.tmp")

    resp = requests.get(meta.download_url_onnx, stream=True)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))

    with open(tmp_path, "wb") as f:
        downloaded = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)

    resp = requests.get(meta.download_url_json)
    resp.raise_for_status()
    with open(onnx_path.with_suffix(".onnx.json"), "wb") as f:
        f.write(resp.content)

    tmp_path.rename(onnx_path)
    return onnx_path
