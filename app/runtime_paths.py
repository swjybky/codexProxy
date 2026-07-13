from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "CodexProxy"


def resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def web_dist_dir() -> Path:
    return resource_root() / "web" / "dist"


def app_icon_path() -> Path:
    return resource_root() / "packaging" / "icons" / "app-icon.png"


def data_dir() -> Path:
    override = os.environ.get("CODEX_PROXY_DATA_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        path = base / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = base / "codex-proxy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_codex_auth_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    return (Path(codex_home).expanduser() if codex_home else Path.home() / ".codex") / "auth.json"
