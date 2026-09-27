from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from tts_app.engines._wav import float_to_pcm16, resample_mono, stream_wav_as_pcm
from tts_app.engines.base import PCM_SAMPLE_RATE, SynthesisError, TTSEngine, Voice
from tts_app.engines.voices import get_voices_dir, installed_voice_files

logger = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _try_import_piper() -> Any | None:
    try:
        from piper import PiperVoice, SynthesisConfig

        return (PiperVoice, SynthesisConfig)
    except Exception as e:
        logger.info("piper-tts python module unavailable: %s", e)
        return None


def _piper_module_runnable() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "piper", "--help"],
            capture_output=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        return False


class PiperEngine(TTSEngine):
    name: ClassVar[str] = "piper"

    def __init__(self, piper_exe: str | Path | None = None) -> None:
        self.piper_exe = self._locate_piper_exe(piper_exe)
        self._module_ok: bool | None = None
        self._inproc = _try_import_piper()
        self._loaded_voices: dict[str, Any] = {}

    @staticmethod
    def _locate_piper_exe(override: str | Path | None) -> Path | None:
        if override:
            p = Path(override)
            return p if p.exists() else None
        env_raw = os.environ.get("TTS_APP_PIPER", "")
        if env_raw:
            p = Path(env_raw)
            if p.exists():
                return p
        bundled = Path(__file__).resolve().parents[3] / "assets" / "bin" / "piper.exe"
        if bundled.exists():
            return bundled
        which_path = shutil.which("piper")
        if which_path:
            return Path(which_path)
        return None

    def _module_available(self) -> bool:
        if self._module_ok is None:
            self._module_ok = _piper_module_runnable()
        return self._module_ok

    def _in_process_available(self) -> bool:
        return self._inproc is not None

    def is_available(self) -> bool:
        has_runtime = (
            self._in_process_available()
            or (self.piper_exe and self.piper_exe.exists())
            or self._module_available()
        )
        if not has_runtime:
            return False
        return len(installed_voice_files(get_voices_dir())) > 0

    def list_voices(self) -> list[Voice]:
        voices_dir = get_voices_dir()
        voices: list[Voice] = []
        for onnx_path in installed_voice_files(voices_dir):
            json_path = onnx_path.with_suffix(".onnx.json")
            if not json_path.exists():
                continue
            try:
                if json_path.stat().st_size == 0:
                    continue
                with open(json_path, encoding="utf-8") as f:
                    meta = json.load(f)
                lang_code = meta.get("language", {}).get("code", "und")
                stem = onnx_path.stem
                quality = 4
                if "-low" in stem:
                    quality = 3
                elif "-high" in stem:
                    quality = 5
                voices.append(
                    Voice(
                        id=f"piper:{onnx_path.name}",
                        engine=self.name,
                        name=stem,
                        language=lang_code,
                        gender=None,
                        quality=quality,
                    )
                )
            except Exception:
                continue
        return voices

    def synthesize(
        self,
        text: str,
        voice: Voice,
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ) -> Iterator[bytes]:
        if voice.engine != self.name:
            raise SynthesisError(f"voice {voice.id} not a Piper voice")

        onnx_filename = voice.id.removeprefix("piper:")
        onnx_path = get_voices_dir() / onnx_filename
        if not onnx_path.exists():
            raise SynthesisError(f"voice model not found: {onnx_path}")

        if self._in_process_available():
            yield from self._synth_in_process(text, onnx_path, rate, volume)
            return

        yield from self._synth_subprocess(text, onnx_path, rate)

    def _synth_in_process(
        self, text: str, onnx_path: Path, rate: float, volume: float
    ) -> Iterator[bytes]:
        assert self._inproc is not None
        PiperVoice, SynthesisConfig = self._inproc

        key = str(onnx_path)
        voice_obj = self._loaded_voices.get(key)
        if voice_obj is None:
            try:
                voice_obj = PiperVoice.load(key)
            except Exception as e:
                raise SynthesisError(f"failed to load piper voice: {e}") from e
            self._loaded_voices[key] = voice_obj

        cfg = SynthesisConfig(
            length_scale=1.0 / max(rate, 0.25),
            noise_scale=0.667,
            noise_w_scale=0.8,
            volume=max(0.0, min(1.0, volume)),
        )

        try:
            for chunk in voice_obj.synthesize(text, syn_config=cfg):
                if chunk.sample_rate == PCM_SAMPLE_RATE:
                    data = chunk.audio_int16_bytes
                else:
                    # low/x_low voices are 16 kHz; playback assumes PCM_SAMPLE_RATE.
                    data = float_to_pcm16(
                        resample_mono(
                            chunk.audio_float_array, chunk.sample_rate, PCM_SAMPLE_RATE
                        )
                    )
                if data:
                    yield data
        except Exception as e:
            raise SynthesisError(f"piper synth failed: {e}") from e

    def _synth_subprocess(
        self, text: str, onnx_path: Path, rate: float
    ) -> Iterator[bytes]:
        length_scale = 1.0 / max(rate, 0.25)

        with tempfile.TemporaryDirectory(prefix="tts_piper_") as td:
            out = Path(td) / "out.wav"
            argv = self._build_argv(onnx_path, out, length_scale)
            try:
                result = subprocess.run(
                    argv,
                    input=text,
                    text=True,
                    capture_output=True,
                    timeout=120,
                    check=False,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except subprocess.TimeoutExpired as e:
                raise SynthesisError("piper timeout") from e
            except Exception as e:
                raise SynthesisError(f"piper exec failed: {e}") from e

            if result.returncode != 0:
                err = (result.stderr or "").strip() or f"exit code {result.returncode}"
                raise SynthesisError(f"piper failed: {err}")
            if not out.exists() or out.stat().st_size == 0:
                raise SynthesisError("piper produced no audio")
            yield from stream_wav_as_pcm(out)

    def _build_argv(self, model_path: Path, out_wav: Path, length_scale: float) -> list[str]:
        if self._module_available():
            return [
                sys.executable, "-m", "piper",
                "--model", str(model_path),
                "--output-file", str(out_wav),
                "--length-scale", f"{length_scale:.4f}",
                "--noise-scale", "0.667",
                "--noise-w-scale", "0.8",
            ]
        if self.piper_exe and self.piper_exe.exists():
            return [
                str(self.piper_exe),
                "--model", str(model_path),
                "--output_file", str(out_wav),
                "--length_scale", f"{length_scale:.4f}",
                "--noise_scale", "0.667",
                "--noise_w", "0.8",
            ]
        raise SynthesisError("Piper not available (no module and no binary)")

    def install_hint(self) -> str | None:
        if self.is_available():
            return None
        if not (
            self._in_process_available()
            or self._module_available()
            or (self.piper_exe and self.piper_exe.exists())
        ):
            return (
                "Piper not available. Install via: pip install piper-tts "
                "(or place piper.exe in assets/bin/)."
            )
        return "No Piper voices installed. Open the voice palette to download one."
