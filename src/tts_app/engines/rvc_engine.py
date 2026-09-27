from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import numpy as np
import platformdirs

from tts_app.engines._wav import float_to_pcm16, resample_mono
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


class RvcEngine(TTSEngine):
    name: ClassVar[str] = "rvc"
    supports_pitch: ClassVar[bool] = True  # mapped to RVC's semitone shift

    def __init__(self, base_engine: TTSEngine | None = None) -> None:
        self._base_engine = base_engine
        self._base_voice_id: str | None = None
        self._models_dir = get_rvc_models_dir()
        self._torch_status: str = "unknown"
        self._converter = None  # cached RVCConverter (loads HuBERT once)
        self._loaded_model: Path | None = None  # .pth currently loaded into the converter

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

    def set_base_voice(self, voice_id: str | None) -> None:
        """Voice of the base engine whose speech gets converted; None = its first voice."""
        self._base_voice_id = voice_id

    def _base_voice(self) -> Voice:
        assert self._base_engine is not None
        voices = self._base_engine.list_voices()
        if not voices:
            raise RuntimeError("Base engine has no voices available")
        for v in voices:
            if v.id == self._base_voice_id:
                return v
        return voices[0]

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

        base_voice = self._base_voice()
        pcm_data = b"".join(self._base_engine.synthesize(text, base_voice, rate, 1.0, volume))
        if not pcm_data:
            return

        conv = self._get_converter()
        if self._loaded_model != model_path:
            conv.vc.get_vc(str(model_path), _PROTECT, 0.5)
            self._loaded_model = model_path

        fd, tmp_in_str = tempfile.mkstemp(suffix=".wav", dir=str(get_rvc_assets_dir()))
        os.close(fd)
        tmp_in = Path(tmp_in_str)
        out_path: str | None = None
        try:
            with wave.open(str(tmp_in), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(PCM_SAMPLE_RATE)
                wf.writeframes(pcm_data)

            # Call the single-file inference step with explicit model/index paths.
            # RVCConverter.infer_audio() would look the model up under
            # <cwd>/models/, which needed a process-wide chdir from this thread.
            info, audio_data, out_path = conv._run_inference(
                input_audio=str(tmp_in),
                index_path=str(self._find_index(model_path) or ""),
                f0_change=int(round((pitch - 1.0) * 12)),
                f0_method="rmvpe+",
                index_rate=0.75,
                filter_radius=3,
                resample_sr=0,
                rms_mix_rate=0.25,
                protect=_PROTECT,
                audio_format="wav",
                crepe_hop_length=128,
                do_formant=False,
                quefrency=0,
                timbre=1,
                min_pitch="50",
                max_pitch="1100",
                f0_autotune=False,
            )
            if not info or info[0] != "Success.":
                detail = info[0] if info else "no result"
                raise RuntimeError(f"RVC conversion failed: {detail}")
            sample_rate, audio = audio_data
            yield from _to_pcm_chunks(audio, int(sample_rate), volume)
        finally:
            tmp_in.unlink(missing_ok=True)
            _discard_output(out_path)

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

    def _find_index(self, model_path: Path) -> Path | None:
        index = model_path.with_suffix(".index")
        if index.exists():
            return index
        return next(iter(sorted(model_path.parent.glob("*.index"))), None)

    def _find_model(self, name: str) -> Path | None:
        exact = self._models_dir / f"{name}.pth"
        if exact.exists():
            return exact
        for pth in self._models_dir.glob(f"**/{name}.pth"):
            return pth
        return None


_PROTECT = 0.33  # rvc-inferpy's default consonant protection


def _to_pcm_chunks(audio: np.ndarray, sample_rate: int, volume: float) -> Iterator[bytes]:
    audio = np.asarray(audio)
    if np.issubdtype(audio.dtype, np.integer):
        audio = audio.astype(np.float32) / float(np.iinfo(audio.dtype).max + 1)
    audio = audio.astype(np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = resample_mono(audio, sample_rate, PCM_SAMPLE_RATE)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0:
        audio = audio / peak * 0.95 * max(0.0, min(volume, 1.0))
    pcm = float_to_pcm16(audio)
    chunk_size = PCM_SAMPLE_RATE * 2
    for i in range(0, len(pcm), chunk_size):
        yield pcm[i:i + chunk_size]


def _discard_output(out_path: str | None) -> None:
    """rvc-inferpy always also writes its result under <cwd>/output; clean that up."""
    if not out_path:
        return
    out = Path(out_path)
    out.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        out.parent.rmdir()  # only succeeds if we left it empty
