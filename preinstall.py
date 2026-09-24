"""Download piper.exe + all BUILT_IN_CATALOG voices into the right places.

Run:  python preinstall.py
Idempotent — skips files that already exist.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tts_app.engines.voices import BUILT_IN_CATALOG, get_voices_dir  # noqa: E402

PIPER_URL = (
    "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
    "piper_windows_amd64.zip"
)
ASSETS_BIN = ROOT / "assets" / "bin"


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _stream_download(url: str, dest: Path) -> None:
    print(f"  fetching {url}")
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    last_pct = -10
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = int(downloaded * 100 / total)
                if pct >= last_pct + 5:
                    print(f"    {pct:3d}%  {_human(downloaded)}/{_human(total)}", end="\r")
                    last_pct = pct
    print()
    tmp.replace(dest)


def install_piper() -> Path:
    ASSETS_BIN.mkdir(parents=True, exist_ok=True)
    piper_exe = ASSETS_BIN / "piper.exe"
    if piper_exe.exists():
        print(f"piper.exe already at {piper_exe}")
        return piper_exe

    print("downloading piper Windows binary...")
    r = requests.get(PIPER_URL, stream=True, timeout=120)
    r.raise_for_status()
    blob = io.BytesIO(r.content)

    with zipfile.ZipFile(blob) as zf:
        zf.extractall(ASSETS_BIN)
    # Some releases extract into ASSETS_BIN/piper/, normalize:
    nested = ASSETS_BIN / "piper"
    if nested.is_dir() and not piper_exe.exists():
        for item in nested.iterdir():
            target = ASSETS_BIN / item.name
            if target.exists() and target.is_dir():
                continue
            item.replace(target)
        try:
            nested.rmdir()
        except OSError:
            pass
    print(f"piper.exe installed at {piper_exe}")
    return piper_exe


def _ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0


def install_voices() -> None:
    voices_dir = get_voices_dir()
    print(f"voices dir: {voices_dir}")
    for meta in BUILT_IN_CATALOG:
        onnx = voices_dir / f"{meta.voice_id}.onnx"
        json_p = voices_dir / f"{meta.voice_id}.onnx.json"
        if _ok(onnx) and _ok(json_p):
            print(f"  [skip] {meta.voice_id} already installed")
            continue
        print(f"  [download] {meta.voice_id}  (~{meta.size_mb_estimate} MB)")
        if not _ok(onnx):
            _stream_download(meta.download_url_onnx, onnx)
        if not _ok(json_p):
            _stream_download(meta.download_url_json, json_p)


def main() -> int:
    install_piper()
    install_voices()
    print("\nALL DONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
