import os
import sys
import shutil
import gc
import torch
import logging
from multiprocessing import cpu_count
from pathlib import Path
from urllib.parse import urlparse
import requests
import zipfile
import subprocess
import shlex

from rvc_inferpy.modules import VC
from rvc_inferpy.split_audio import (
    split_silence_nonsilent,
    adjust_audio_lengths,
    combine_silence_nonsilent,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Download URL and model filenames
RVC_DOWNLOAD_LINK = "https://huggingface.co/NeoPy/rvc-base/resolve/main"
RVC_MODELS = [
    "hubert_base.pt",
    "rmvpe.pt",
    "fcpe.pt",
]

BASE_DIR = Path(".").resolve()
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)


def download_manager(url: str, dest_path: Path) -> None:
    """
    Download a file from the given URL to the destination path.
    """
    if dest_path.exists():
        logger.info(f"File {dest_path} already exists. Skipping download.")
        return

    logger.info(f"Downloading {url} to {dest_path}...")
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(response.raw, f)
        logger.info(f"Downloaded {dest_path}.")
    else:
        logger.error(f"Failed to download {url}. Status code: {response.status_code}")
        raise Exception(f"Download failed for {url}")


class Configs:
    """
    Configuration for device and inference parameters.
    """
    def __init__(self, device: str, is_half: bool):
        self.device: str = device
        self.is_half: bool = is_half
        self.n_cpu: int = cpu_count()
        self.gpu_name: str | None = None
        self.gpu_mem: int | None = None
        self.x_pad, self.x_query, self.x_center, self.x_max = self.device_config()

    def device_config(self) -> tuple:
        # Determine the proper device based on available hardware
        if torch.cuda.is_available():
            i_device = int(self.device.split(":")[-1])
            self.gpu_name = torch.cuda.get_device_name(i_device)
        elif torch.backends.mps.is_available():
            logger.info("No supported NVIDIA GPU found, using MPS for inference")
            self.device = "mps"
        else:
            logger.info("No supported GPU found, using CPU for inference")
            self.device = "cpu"

        # Memory configuration based on is_half flag
        if self.is_half:
            x_pad, x_query, x_center, x_max = 3, 10, 60, 65  # 6G memory configuration
        else:
            x_pad, x_query, x_center, x_max = 1, 6, 38, 41  # 5G memory configuration

        if self.gpu_mem is not None and self.gpu_mem <= 4:
            x_pad, x_query, x_center, x_max = 1, 5, 30, 32

        return x_pad, x_query, x_center, x_max


class RVCConverter:
    """
    Handles model setup and voice conversion inference.
    """
    def __init__(
        self,
        device: str = "cuda:0",
        is_half: bool = True,
        models_dir: Path = MODELS_DIR,
        download_if_missing: bool = True,
    ):
        self.device: str = device
        self.is_half: bool = is_half
        self.models_dir: Path = models_dir
        self.download_if_missing: bool = download_if_missing

        # Retrieve model paths from environment or download defaults if missing.
        self.hubert_model_path = self.get_or_download_model(
            env_var="hubert_model_path", filename="hubert_base.pt"
        )
        self.rmvpe_model_path = self.get_or_download_model(
            env_var="rmvpe_model_path", filename="rmvpe.pt"
        )
        self.fcpe_model_path = self.get_or_download_model(
            env_var="fcpe_model_path", filename="fcpe.pt"
        )

        self.configs = Configs(self.device, self.is_half)
        self.vc = VC(self.configs)

    def get_or_download_model(self, env_var: str, filename: str) -> str:
        model_path = os.environ.get(env_var)
        if model_path:
            logger.info(f"Using {env_var} from environment: {model_path}")
        else:
            model_path = str(self.models_dir / filename)
        if self.download_if_missing and not Path(model_path).exists():
            download_manager(f"{RVC_DOWNLOAD_LINK}/{filename}", Path(model_path))
    return model_path
    
    @staticmethod
    def get_model(voice_model: str) -> tuple:
        """
        Return the pth and index file paths for the given voice model.
        Expects the voice model files to reside in:
            {current_working_dir}/models/{voice_model}/
        """
        model_dir = Path(os.getcwd()) / "models" / voice_model
        if not model_dir.exists():
            logger.error(f"Model directory {model_dir} does not exist.")
            return None, None

        model_filename = None
        index_filename = None
        for file in os.listdir(model_dir):
            ext = Path(file).suffix
            if ext == ".pth":
                model_filename = file
            elif ext == ".index":
                index_filename = file

        if not model_filename:
            logger.error(f"No model file exists in {model_dir}.")
            return None, None

        pth_path = str(model_dir / model_filename)
        index_path = str(model_dir / index_filename) if index_filename else ""
        return pth_path, index_path

    def _run_inference(
        self,
        input_audio: str,
        index_path: str,
        f0_change: int,
        f0_method: str,
        index_rate: float,
        filter_radius: int,
        resample_sr: int,
        rms_mix_rate: float,
        protect: float,
        audio_format: str,
        crepe_hop_length: int,
        do_formant: bool,
        quefrency: int,
        timbre: int,
        min_pitch: str,
        max_pitch: str,
        f0_autotune: bool,
    ) -> tuple:
        """
        Helper function to run inference on a single audio segment.
        """
        inference_info, audio_data, output_path = self.vc.vc_single(
            0,
            input_audio,
            f0_change,
            f0_method,
            index_path,
            index_path,
            index_rate,
            filter_radius,
            resample_sr,
            rms_mix_rate,
            protect,
            audio_format,
            crepe_hop_length,
            do_formant,
            quefrency,
            timbre,
            min_pitch,
            max_pitch,
            f0_autotune,
            self.hubert_model_path,
        )
        if inference_info[0] == "Success.":
            logger.info("Inference ran successfully.")
            logger.info(inference_info[1])
            times = inference_info[2]
            logger.info(
                f"Times:\nnpy: {times[0]:.2f}s f0: {times[1]:.2f}s infer: {times[2]:.2f}s\nTotal time: {sum(times):.2f}s"
            )
        else:
            logger.error(f"An error occurred: {inference_info[0]}")
        return inference_info, audio_data, output_path

    def infer_audio(
        self,
        voice_model: str,
        audio_path: str,
        f0_change: int = 0,
        f0_method: str = "rmvpe+",
        min_pitch: str = "50",
        max_pitch: str = "1100",
        crepe_hop_length: int = 128,
        index_rate: float = 0.75,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
        split_infer: bool = False,
        min_silence: int = 500,
        silence_threshold: int = -50,
        seek_step: int = 1,
        keep_silence: int = 100,
        do_formant: bool = False,
        quefrency: int = 0,
        timbre: int = 1,
        f0_autotune: bool = False,
        audio_format: str = "wav",
        resample_sr: int = 0,
    ) -> str:
        """
        Perform voice conversion inference on the provided audio file.
        If split_infer is True, the audio will first be segmented based on silence.
        """
        pth_path, index_path = self.get_model(voice_model)
        if pth_path is None:
            logger.error("Model loading failed.")
            return ""

        # Preload the voice conversion engine
        self.vc.get_vc(pth_path, protect, 0.5)

        if split_infer:
            inferred_files = []
            temp_dir = Path(os.getcwd()) / "separate" / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Splitting audio into silence and nonsilent segments.")
            silence_files, nonsilent_files = split_silence_nonsilent(
                audio_path, min_silence, silence_threshold, seek_step, keep_silence
            )
            logger.info(
                f"Total silence segments: {len(silence_files)}. Total nonsilent segments: {len(nonsilent_files)}."
            )
            for i, segment in enumerate(nonsilent_files):
                logger.info(f"Inferring nonsilent audio segment {i+1}")
                inference_info, _, segment_output = self._run_inference(
                    input_audio=segment,
                    index_path=index_path,
                    f0_change=f0_change,
                    f0_method=f0_method,
                    index_rate=index_rate,
                    filter_radius=filter_radius,
                    resample_sr=resample_sr,
                    rms_mix_rate=rms_mix_rate,
                    protect=protect,
                    audio_format=audio_format,
                    crepe_hop_length=crepe_hop_length,
                    do_formant=do_formant,
                    quefrency=quefrency,
                    timbre=timbre,
                    min_pitch=min_pitch,
                    max_pitch=max_pitch,
                    f0_autotune=f0_autotune,
                )
                if inference_info[0] != "Success.":
                    return ""
                inferred_files.append(segment_output)

            logger.info("Adjusting inferred audio lengths.")
            adjusted_inferred_files = adjust_audio_lengths(nonsilent_files, inferred_files)
            logger.info("Combining silence and inferred audios.")
            output_dir = Path(os.getcwd()) / "output"
            output_dir.mkdir(exist_ok=True)
            output_count = 1
            while True:
                output_path = output_dir / f"{Path(audio_path).stem}_{voice_model}_{f0_method.capitalize()}_{output_count}.{audio_format}"
                if not output_path.exists():
                    break
                output_count += 1

            output_path = combine_silence_nonsilent(
                silence_files, adjusted_inferred_files, keep_silence, str(output_path)
            )
            # Move temporary inferred files to temp directory and clean up
            for file in inferred_files:
                shutil.move(file, temp_dir)
            shutil.rmtree(temp_dir)
        else:
            inference_info, _, output_path = self._run_inference(
                input_audio=audio_path,
                index_path=index_path,
                f0_change=f0_change,
                f0_method=f0_method,
                index_rate=index_rate,
                filter_radius=filter_radius,
                resample_sr=resample_sr,
                rms_mix_rate=rms_mix_rate,
                protect=protect,
                audio_format=audio_format,
                crepe_hop_length=crepe_hop_length,
                do_formant=do_formant,
                quefrency=quefrency,
                timbre=timbre,
                min_pitch=min_pitch,
                max_pitch=max_pitch,
                f0_autotune=f0_autotune,
            )
            if inference_info[0] != "Success.":
                return ""
        return output_path


if __name__ == "__main__":
    # Download base models if not provided via environment variables.
    for model_file in RVC_MODELS:
        model_path = BASE_DIR / model_file
        if not model_path.exists():
            download_manager(f"{RVC_DOWNLOAD_LINK}/{model_file}", model_path)