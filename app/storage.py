from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_paths import data_dir, default_codex_auth_path


DEFAULT_SETTINGS: dict[str, Any] = {
    "listen_port": 1455,
    "upstream_base_url": "https://chatgpt.com",
    "proxy_url": "",
    "system_prompt": "",
    "system_prompt_override": False,
    "default_model": "gpt-5.4",
}

SUPPORTED_MODELS = [
    "gpt-5",
    "gpt-5-codex",
    "gpt-5-codex-mini",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.4",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded)
        return claims if isinstance(claims, dict) else {}
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return {}


def normalize_credentials(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("OAuth 凭证必须是 JSON 对象")

    source = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else payload
    normalized = {
        "id_token": str(source.get("id_token") or payload.get("id_token") or "").strip(),
        "access_token": str(source.get("access_token") or payload.get("access_token") or "").strip(),
        "refresh_token": str(source.get("refresh_token") or payload.get("refresh_token") or "").strip(),
        "account_id": str(source.get("account_id") or payload.get("account_id") or "").strip(),
        "last_refresh": str(payload.get("last_refresh") or source.get("last_refresh") or _utc_now()).strip(),
        "email": str(source.get("email") or payload.get("email") or "").strip(),
        "type": str(source.get("type") or payload.get("type") or "codex").strip(),
        "expired": str(source.get("expired") or payload.get("expired") or "").strip(),
    }

    if not normalized["access_token"]:
        raise ValueError("OAuth 凭证缺少 access_token")

    claims = _decode_jwt_claims(normalized["access_token"])
    auth_claim = claims.get("https://api.openai.com/auth", {})
    if not normalized["account_id"] and isinstance(auth_claim, dict):
        normalized["account_id"] = str(auth_claim.get("chatgpt_account_id") or "").strip()
    if not normalized["email"]:
        normalized["email"] = str(claims.get("email") or "").strip()
    if not normalized["expired"] and isinstance(claims.get("exp"), (int, float)):
        normalized["expired"] = datetime.fromtimestamp(
            claims["exp"], tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")

    if not normalized["account_id"]:
        raise ValueError("OAuth 凭证缺少 account_id，且无法从 access_token 提取")
    return normalized


class AppStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.root / "settings.json"
        self.credentials_path = self.root / "credentials.json"
        self._lock = threading.RLock()
        self._ensure_settings()

    def _read_json(self, path: Path, fallback: Any) -> Any:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return fallback

    def _write_json(self, path: Path, value: Any, secret: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600 if secret else 0o600)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _ensure_settings(self) -> None:
        with self._lock:
            current = self._read_json(self.settings_path, {})
            if not isinstance(current, dict):
                current = {}
            merged = {**DEFAULT_SETTINGS, **current}
            if not isinstance(merged.get("local_api_key"), str) or not merged["local_api_key"].strip():
                merged["local_api_key"] = "cp_" + secrets.token_urlsafe(30)
            if not isinstance(merged.get("admin_token"), str) or not merged["admin_token"].strip():
                merged["admin_token"] = "admin_" + secrets.token_urlsafe(36)
            self._write_json(self.settings_path, merged)

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            stored = self._read_json(self.settings_path, {})
            return {**DEFAULT_SETTINGS, **stored}

    def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "upstream_base_url",
            "proxy_url",
            "system_prompt",
            "system_prompt_override",
            "default_model",
        }
        with self._lock:
            settings = self.get_settings()
            for key in allowed:
                if key in updates:
                    settings[key] = updates[key]
            settings["upstream_base_url"] = str(settings["upstream_base_url"]).strip().rstrip("/")
            if not settings["upstream_base_url"].startswith(("https://", "http://")):
                raise ValueError("上游地址必须以 http:// 或 https:// 开头")
            settings["proxy_url"] = str(settings["proxy_url"]).strip()
            if settings["proxy_url"] and not settings["proxy_url"].startswith(("http://", "https://")):
                raise ValueError("网络代理必须以 http:// 或 https:// 开头")
            settings["system_prompt"] = str(settings["system_prompt"])
            settings["system_prompt_override"] = bool(settings["system_prompt_override"])
            settings["default_model"] = str(settings["default_model"]).strip() or "gpt-5.4"
            self._write_json(self.settings_path, settings)
            return settings

    def regenerate_api_key(self) -> str:
        with self._lock:
            settings = self.get_settings()
            settings["local_api_key"] = "cp_" + secrets.token_urlsafe(30)
            self._write_json(self.settings_path, settings)
            return settings["local_api_key"]

    def get_credentials(self) -> dict[str, str] | None:
        with self._lock:
            value = self._read_json(self.credentials_path, None)
            return value if isinstance(value, dict) else None

    def save_credentials(self, payload: Any) -> dict[str, str]:
        normalized = normalize_credentials(payload)
        with self._lock:
            self._write_json(self.credentials_path, normalized, secret=True)
        return normalized

    def import_credentials_text(self, raw: str) -> dict[str, str]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("OAuth 凭证不是有效 JSON") from error
        return self.save_credentials(payload)

    def import_default_codex_credentials(self) -> dict[str, str]:
        source = default_codex_auth_path()
        try:
            raw = source.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"未找到 Codex 登录文件：{source}") from error
        return self.import_credentials_text(raw)

    def credentials_summary(self) -> dict[str, Any]:
        credentials = self.get_credentials()
        if not credentials:
            return {"configured": False}
        return {
            "configured": True,
            "account_id": credentials.get("account_id", ""),
            "email": credentials.get("email", ""),
            "expired": credentials.get("expired", ""),
            "last_refresh": credentials.get("last_refresh", ""),
            "refreshable": bool(credentials.get("refresh_token")),
        }
