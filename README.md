# TTS App

Local-first, free, MIT-licensed text-to-speech desktop app for Windows. Paste text, pick a voice, hit play. Or press `Ctrl+Alt+S` from anywhere and it reads your clipboard.

No cloud calls. No telemetry. No accounts.

## Why

I read a lot of articles. Existing options either phone home, cost money, sound like 2003, or require a terminal. This is the one I want on my desktop.

## Engines

| Engine        | Quality | Notes                                               |
|---------------|---------|-----------------------------------------------------|
| **Piper**     | High    | Neural ONNX, CPU-only, ~60 MB per voice. Primary.   |
| **SAPI5**     | Medium  | Windows built-in, zero-config fallback (`pyttsx3`). |
| **eSpeak-NG** | Robotic | Tiny, last-resort, supports 100+ languages.         |

Piper and eSpeak-NG run as separate subprocesses to keep this codebase MIT.

## Install

Requirements:

- Windows 10/11
- Python 3.11+ on PATH (`winget install Python.Python.3.11`)
- Optional: `ffmpeg` on PATH if you want MP3/OGG export
- Optional: `piper.exe` and `espeak-ng.exe` on PATH or in `assets/bin/` (Piper download from <https://github.com/OHF-Voice/piper1-gpl/releases>)

One-shot install:

```powershell
git clone <this-repo> C:\path\to\Text-to-speach
cd C:\path\to\Text-to-speach
.\install.ps1
```

That creates a venv, installs deps, drops a `TTS App.lnk` on your Desktop and Start Menu, and launches the first-run wizard.

## Run

Double-click the desktop icon. Or:

```powershell
.\tts_app.bat
```

Or directly:

```powershell
.\.venv\Scripts\pythonw.exe launcher.py
```

## Hotkey

Default global hotkey is `Ctrl+Alt+S`. Pressing it from any window reads your clipboard in the last-used voice. Disable or rebind in Settings.

## Adding voices

In-app: open the Voice Browser → "Download Piper voices" tab → pick → Download.

By hand: drop `<voice_id>.onnx` and `<voice_id>.onnx.json` into `%APPDATA%\TTSApp\voices\` and restart.

## Development

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src
```

Project layout:

```
src/tts_app/
  engines/    # TTSEngine ABC + Piper, SAPI, eSpeak adapters
  audio/      # QAudioSink playback + WAV/MP3/OGG encode
  ui/         # main window, voice browser, first-run wizard, tray
  config/     # %APPDATA%\TTSApp\config.json (pydantic)
  hotkey/     # global Ctrl+Alt+S
launcher.py   # pythonw entry point
tts_app.bat   # Windows launch shim
install.ps1   # creates venv + Desktop/Start Menu shortcuts
```

Add a new engine: subclass `TTSEngine` in `src/tts_app/engines/`, register it in `engines/registry.py:build_default_engines()`. Tests in `tests/test_<engine>_engine.py`.

## Files written at runtime

- `%APPDATA%\TTSApp\config.json` — settings
- `%APPDATA%\TTSApp\voices\` — downloaded Piper voice models
- `%LOCALAPPDATA%\TTSApp\Logs\app.log` (rotated) — runtime log

Delete the config file to reset to defaults; the first-run wizard re-runs.

## License

MIT (see `LICENSE`). Piper voice models carry their own per-voice licenses (mostly MIT/CC0); see <https://huggingface.co/rhasspy/piper-voices>.
