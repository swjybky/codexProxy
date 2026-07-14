#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_VENV="$ROOT/.venv-linux-build"
if [[ -x /usr/bin/python3 ]]; then
    PYTHON="${PYTHON:-/usr/bin/python3}"
else
    PYTHON="${PYTHON:-$(command -v python3)}"
fi
BOOTSTRAP_PYTHON="${BOOTSTRAP_PYTHON:-$(command -v python3)}"

cd "$ROOT/web"
npm ci
npm run build

cd "$ROOT"
if [[ ! -x "$BUILD_VENV/bin/python" ]] || \
    [[ "$(readlink -f "$BUILD_VENV/bin/python")" != "$(readlink -f "$PYTHON")" ]] || \
    ! "$BUILD_VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    if "$PYTHON" -c "import ensurepip" >/dev/null 2>&1; then
        "$PYTHON" -m venv --clear "$BUILD_VENV"
    else
        "$PYTHON" -m venv --clear --without-pip "$BUILD_VENV"
        "$BOOTSTRAP_PYTHON" -m pip --python "$BUILD_VENV/bin/python" install pip
    fi
fi

"$BUILD_VENV/bin/python" -m pip install -r requirements.txt
QT_API=pyside6 "$BUILD_VENV/bin/python" -m PyInstaller \
    packaging/CodexProxy.spec --noconfirm --clean

install -Dm644 packaging/icons/app-icon.png \
    dist/CodexProxy/share/icons/hicolor/1024x1024/apps/codex-proxy.png
install -Dm644 packaging/codex-proxy.desktop \
    dist/CodexProxy/share/applications/codex-proxy.desktop

echo "Build complete: $ROOT/dist/CodexProxy"
