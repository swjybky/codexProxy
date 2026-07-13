#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/web"
npm install
npm run build

cd "$ROOT"
if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m PyInstaller packaging/CodexProxy.spec --noconfirm --clean

install -Dm644 packaging/icons/app-icon.png \
    dist/CodexProxy/share/icons/hicolor/1024x1024/apps/codex-proxy.png
install -Dm644 packaging/codex-proxy.desktop \
    dist/CodexProxy/share/applications/codex-proxy.desktop

echo "Build complete: $ROOT/dist/CodexProxy"
