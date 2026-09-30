[CmdletBinding()]
param(
    [switch]$NoFirstRun,
    [switch]$DesktopOnly
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSCommandPath
$VenvPython = Join-Path $Repo '.venv\Scripts\python.exe'

function Info($msg) { Write-Host "[install] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[install] $msg" -ForegroundColor Yellow }

Info "Repo: $Repo"

# 1. Verify Python >= 3.11
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { throw "python not found on PATH. Install Python 3.11+ first." }
$pyVersion = & python --version
Info "Found: $pyVersion"

# 2. Create venv if missing
if (-not (Test-Path $VenvPython)) {
    Info "Creating .venv..."
    & python -m venv (Join-Path $Repo '.venv')
}

# 3. Install project + deps
Info "Installing dependencies..."
& $VenvPython -m pip install --upgrade pip setuptools wheel | Out-Null
& $VenvPython -m pip install -e "`"$Repo`""

# 4. Resolve icon
$IconCandidate = Join-Path $Repo 'assets\icon.ico'
if (Test-Path $IconCandidate) {
    $IconLocation = $IconCandidate
} else {
    $IconLocation = "$env:SystemRoot\System32\SndVol.exe,0"
    Warn "No assets\icon.ico found - using default Windows speaker icon."
}

# 5. Build shortcut(s)
$Wsh = New-Object -ComObject WScript.Shell
$BatTarget = Join-Path $Repo 'tts_app.bat'

function New-Shortcut([string]$Path) {
    $sc = $Wsh.CreateShortcut($Path)
    $sc.TargetPath = $BatTarget
    $sc.WorkingDirectory = $Repo
    $sc.IconLocation = $IconLocation
    $sc.Description = 'Local text-to-speech desktop app'
    $sc.WindowStyle = 7  # Minimized; pythonw is windowless anyway
    $sc.Save()
    Info "Shortcut: $Path"
}

$DesktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'TTS App.lnk'
New-Shortcut $DesktopLnk

if (-not $DesktopOnly) {
    $StartMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    if (-not (Test-Path $StartMenuDir)) { New-Item -ItemType Directory -Path $StartMenuDir | Out-Null }
    New-Shortcut (Join-Path $StartMenuDir 'TTS App.lnk')
}

# 6. Launch the app (optional)
if (-not $NoFirstRun) {
    Info "Launching TTS App..."
    Start-Process -FilePath (Join-Path $Repo '.venv\Scripts\pythonw.exe') `
        -ArgumentList @((Join-Path $Repo 'launcher.py')) `
        -WorkingDirectory $Repo
}

Info "Install complete."
