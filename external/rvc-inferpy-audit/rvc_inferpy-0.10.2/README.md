<div align="center">
  
  # Python RVC Inference
  
</div>
  
[![PyPI](https://img.shields.io/pypi/v/rvc-inferpy?logo=pypi&logoColor=white)](https://pypi.org/project/rvc-inferpy/)

**Note:** This project is currently under development.

`rvc_inferpy` is a Python library for performing audio inference using Retrieval-based Voice Conversion (RVC). It offers a straightforward command-line interface (CLI) and can be easily integrated into Python projects for advanced audio processing with customizable parameters.

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
- [Terms of Use](#terms-of-use)
- [Disclaimer](#disclaimer)
- [Credits](#credits)
- [License](#license)

## Installation

Install the package using pip:

```bash
pip install rvc-inferpy
```
For additional dependencies, install the required version of Fairseq:
```
pip install git+https://github.com/One-sixth/fairseq.git
```
## Usage

Below is an example of how to use rvc-inferpy in your Python project:
```
from rvc_inferpy import RVCConverter

# Initialize the converter with default settings
converter = RVCConverter(device="cuda:0", is_half=True)

# Define the voice model name (ensure the model exists under "models/{voice_model}/")
voice_model = "default"

# Path to the input audio file
audio_path = "input_audio.wav"

# Perform voice conversion
output_path = converter.infer_audio(
    voice_model=voice_model,
    audio_path=audio_path,
    f0_change=0,           # Pitch change (in semitones)
    f0_method="rmvpe+",     # Pitch estimation method
    split_infer=False,      # Whether to split audio based on silence
    index_rate=0.75,        # Index rate (adjusts voice timbre)
    filter_radius=3,        # Filter smoothing radius
    resample_sr=0,          # Resample audio (0 keeps original sample rate)
    protect=0.33,           # Protect voiced consonants from distortion
)

# Output the path to the generated audio file
print(f"Generated voice conversion output: {output_path}")
```
The infer_audio function returns the processed audio object based on the provided parameters.

## Terms of Use

The following uses of the converted voice are prohibited:

Criticizing or attacking individuals.

Advocating for or opposing specific political positions, religions, or ideologies.

Publicly displaying strongly stimulating expressions without proper zoning.

Selling voice models or generated voice clips.

Impersonating the original voice owner with malicious intent.

Using the software for fraudulent purposes such as identity theft or fraudulent phone calls.

## Disclaimer

The author is not liable for any direct, indirect, consequential, incidental, or special damages arising from the use, misuse, or inability to use this software.

## Credits

IAHispano's Applio: Base of this project.

RVC-Project: Original RVC repository.


