#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "macOS packaging must run on macOS." >&2
    exit 1
fi

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

echo "Build complete: $ROOT/dist/CodexProxy.app"
