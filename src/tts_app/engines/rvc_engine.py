from __future__ import annotations

import logging
import os
import shutil
import tempfile
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import platformdirs

from tts_app.engines.base import PCM_SAMPLE_RATE, TTSEngine, Voice

logger = logging.getLogger(__name__)


def get_rvc_models_dir() -> Path:
    d = Path(platformdirs.user_data_dir("TTSApp", appauthor=False)) / "rvc_models"
    d.mkdir(parents=True, exist_ok=True)
    return Path(os.path.realpath(d))


def get_rvc_assets_dir() -> Path:
    d = Path(platformdirs.user_data_dir("TTSApp", appauthor=False)) / "rvc_assets"
    d.mkdir(parents=True, exist_ok=True)
    return Path(os.path.realpath(d))


def get_rvc_stage_dir() -> Path:
    d = Path(platformdirs.user_data_dir("TTSApp", appauthor=False)) / "rvc_stage"
    (d / "models").mkdir(parents=True, exist_ok=True)
    return Path(os.path.realpath(d))


class RvcEngine(TTSEngine):
    name: ClassVar[str] = "rvc"
    supports_pitch: ClassVar[bool] = True  # mapped to RVC's semitone shift

    def __init__(self, base_engine: TTSEngine | None = None) -> None:
        self._base_engine = base_engine
        self._models_dir = get_rvc_models_dir()
        self._torch_status: str = "unknown"
        self._converter = None  # cached RVCConverter (loads HuBERT once)

    def torch_status(self) -> str:
        return self._torch_status

    def probe_torch(self) -> None:
        if self._torch_status != "unknown":
            return
        if not any(self._models_dir.glob("**/*.pth")):
            self._torch_status = "missing"
            return
        try:
            import torch  # noqa: F401
            from rvc_inferpy import RVCConverter  # noqa: F401
            self._torch_status = "ready"
        except ImportError:
            self._torch_status = "missing"

    def recheck(self) -> None:
        self._torch_status = "unknown"
        self.probe_torch()

    def is_available(self) -> bool:
        if self._torch_status != "ready":
            return False
        return self._base_engine is not None and self._base_engine.is_available()

    def install_hint(self) -> str | None:
        return "pip install torch rvc-inferpy and a fairseq build compatible with Python 3.11"

    def list_voices(self) -> list[Voice]:
        voices: list[Voice] = []
        for pth_file in sorted(self._models_dir.glob("**/*.pth")):
            voice_id = f"rvc:{pth_file.stem}"
            voices.append(Voice(
                id=voice_id,
                engine="rvc",
                name=pth_file.stem.replace("_", " ").replace("-", " ").title(),
                language="any",
                gender=None,
                quality=4,
            ))
        return voices

    def set_base_engine(self, engine: TTSEngine) -> None:
        self._base_engine = engine

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        if not self._base_engine:
            raise RuntimeError("No base engine configured for RVC")

        model_name = voice.id.removeprefix("rvc:")
        model_path = self._find_model(model_name)
        if not model_path:
            raise RuntimeError(f"RVC model not found: {model_name}")

        base_voices = self._base_engine.list_voices()
        if not base_voices:
            raise RuntimeError("Base engine has no voices available")
        base_voice = base_voices[0]

        pcm_chunks = list(self._base_engine.synthesize(text, base_voice, rate, 1.0, volume))
        pcm_data = b"".join(pcm_chunks)
        if not pcm_data:
            return

        staging = get_rvc_stage_dir()
        self._stage_model(model_name, model_path, staging)

        fd, tmp_in_str = tempfile.mkstemp(suffix=".wav", dir=str(staging))
        os.close(fd)
        tmp_in = Path(tmp_in_str)
        with wave.open(str(tmp_in), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(PCM_SAMPLE_RATE)
            wf.writeframes(pcm_data)

        prev_cwd = os.getcwd()
        out_path: Path | None = None
        try:
            os.chdir(staging)
            conv = self._get_converter()
            f0_change = int(round((pitch - 1.0) * 12))
            out_str = conv.infer_audio(
                voice_model=model_name,
                audio_path=str(tmp_in),
                f0_change=f0_change,
                f0_method="rmvpe+",
                index_rate=0.75,
                protect=0.33,
                do_formant=False,
                audio_format="wav",
            )
            if not out_str or not os.path.isfile(out_str):
                raise RuntimeError(
                    "rvc-inferpy returned no audio (conversion failed upstream); "
                    f"got out_str={out_str!r}"
                )
            out_path = Path(out_str)
            yield from self._yield_pcm(out_path, volume)
        finally:
            os.chdir(prev_cwd)
            tmp_in.unlink(missing_ok=True)
            if out_path is not None:
                Path(out_path).unlink(missing_ok=True)

    def _get_converter(self):
        if self._converter is not None:
            return self._converter
        import torch
        from rvc_inferpy import RVCConverter

        self._ensure_base_assets()
        # RVC is unstable in fp16 on small (<=4GB) consumer GPUs (device-side
        # asserts in leaky_relu). Use CUDA only when there's clearly enough VRAM
        # to run the full HuBERT + RMVPE + RVC stack in fp32; otherwise CPU.
        device = "cpu"
        if torch.cuda.is_available():
            try:
                total = torch.cuda.get_device_properties(0).total_memory
                if total >= 6 * 1024 ** 3:
                    device = "cuda:0"
            except Exception:
                pass
        is_half = False
        self._converter = RVCConverter(
            device=device,
            is_half=is_half,
            models_dir=get_rvc_assets_dir(),
            download_if_missing=True,
        )
        return self._converter

    def _ensure_base_assets(self) -> None:
        # rmvpe+ never loads fcpe.pt; set fcpe_model_path so rvc-inferpy skips
        # its fcpe download (lj1995 returns 404 for that file).
        assets = get_rvc_assets_dir()
        base = "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main"
        hubert = assets / "hubert_base.pt"
        rmvpe = assets / "rmvpe.pt"
        self._download_if_missing(f"{base}/hubert_base.pt", hubert, min_size=180_000_000)
        self._download_if_missing(f"{base}/rmvpe.pt", rmvpe, min_size=120_000_000)
        os.environ["hubert_model_path"] = str(hubert)  # noqa: SIM112 (name set by rvc-inferpy)
        os.environ["rmvpe_model_path"] = str(rmvpe)  # noqa: SIM112
        os.environ.setdefault("fcpe_model_path", str(assets / "fcpe.pt"))
        self._ensure_ffmpeg(assets)

    def _ensure_ffmpeg(self, assets: Path) -> None:
        # rvc-inferpy calls `ffmpeg` via ffmpeg-python; the binary must be
        # discoverable on PATH as `ffmpeg.exe`. Use imageio-ffmpeg's bundled
        # binary when no system ffmpeg is present.
        if shutil.which("ffmpeg"):
            return
        target = assets / "ffmpeg.exe"
        if not target.exists():
            try:
                import imageio_ffmpeg
                src = Path(imageio_ffmpeg.get_ffmpeg_exe())
            except Exception as e:
                raise RuntimeError(
                    "ffmpeg not on PATH and imageio-ffmpeg missing; "
                    "pip install imageio-ffmpeg"
                ) from e
            try:
                os.link(src, target)
            except OSError:
                shutil.copy2(src, target)
        sep = os.pathsep
        if str(assets) not in os.environ.get("PATH", "").split(sep):
            os.environ["PATH"] = str(assets) + sep + os.environ.get("PATH", "")

    def _download_if_missing(self, url: str, dest: Path, min_size: int) -> None:
        if dest.exists() and dest.stat().st_size >= min_size:
            return
        import urllib.request
        logger.info("downloading %s -> %s", url, dest)
        tmp = dest.with_name(dest.name + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "TTSApp/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, length=1024 * 1024)
        if tmp.stat().st_size < min_size:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"downloaded {url} too small ({tmp.stat().st_size} bytes)")
        tmp.replace(dest)

    def _stage_model(self, name: str, src: Path, staging: Path) -> None:
        target_dir = staging / "models" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{name}.pth"
        if target.exists() and target.stat().st_size == src.stat().st_size:
            return
        if target.exists():
            target.unlink()
        try:
            os.link(src, target)
        except OSError:
            shutil.copy2(src, target)
        src_index = src.with_suffix(".index")
        if not src_index.exists():
            found = list(src.parent.glob("*.index"))
            src_index = found[0] if found else None  # type: ignore[assignment]
        if src_index and Path(src_index).exists():
            tgt_index = target_dir / Path(src_index).name
            if not tgt_index.exists():
                try:
                    os.link(src_index, tgt_index)
                except OSError:
                    shutil.copy2(src_index, tgt_index)

    def _yield_pcm(self, wav_path: Path, volume: float) -> Iterator[bytes]:
        import numpy as np

        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())

        if sw == 2:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif sw == 1:
            audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            raise RuntimeError(f"Unsupported RVC output sample width: {sw}")

        if nch > 1:
            audio = audio.reshape(-1, nch).mean(axis=1)

        if sr != PCM_SAMPLE_RATE:
            import torch
            import torchaudio
            t = torch.from_numpy(audio).unsqueeze(0)
            t = torchaudio.functional.resample(t, sr, PCM_SAMPLE_RATE)
            audio = t.squeeze(0).numpy()

        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak > 0:
            audio = audio / peak * 0.95 * max(0.0, min(volume, 1.0))
        pcm = (audio * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()

        chunk_size = PCM_SAMPLE_RATE * 2
        for i in range(0, len(pcm), chunk_size):
            yield pcm[i:i + chunk_size]

    def _find_model(self, name: str) -> Path | None:
        exact = self._models_dir / f"{name}.pth"
        if exact.exists():
            return exact
        for pth in self._models_dir.glob(f"**/{name}.pth"):
            return pth
        return None
