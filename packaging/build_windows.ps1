$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Push-Location (Join-Path $Root "web")
try {
    npm install
    npm run build
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $Root ".venv"))) {
    python -m venv (Join-Path $Root ".venv")
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
& $Python -m PyInstaller (Join-Path $Root "packaging\CodexProxy.spec") --noconfirm --clean

Write-Host "Build complete: $Root\dist\CodexProxy" -ForegroundColor Green

