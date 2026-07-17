from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timedelta, timezone
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

USER_KEY_TOKEN_LIMITS = (5_000_000, 10_000_000, 20_000_000, 100_000_000)
USAGE_FIELDS = ("input_tokens", "output_tokens", "cached_tokens")


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
        self.api_keys_path = self.root / "api_keys.json"
        self.usage_path = self.root / "token_usage.json"
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

    def _managed_keys(self) -> list[dict[str, Any]]:
        stored = self._read_json(self.api_keys_path, {})
        raw_keys = stored.get("keys", []) if isinstance(stored, dict) else []
        return [item for item in raw_keys if isinstance(item, dict)]

    def _write_managed_keys(self, keys: list[dict[str, Any]]) -> None:
        self._write_json(self.api_keys_path, {"keys": keys}, secret=True)

    def _usage_by_key(self) -> dict[str, dict[str, int]]:
        stored = self._read_json(self.usage_path, {})
        raw_buckets = stored.get("buckets", {}) if isinstance(stored, dict) else {}
        totals: dict[str, dict[str, int]] = {}
        for counts in raw_buckets.values() if isinstance(raw_buckets, dict) else []:
            for key_id, key_counts in self._bucket_key_counts(counts).items():
                target = totals.setdefault(key_id, {field: 0 for field in USAGE_FIELDS})
                for field in USAGE_FIELDS:
                    target[field] += max(0, int(key_counts.get(field, 0)))
        return totals

    def list_api_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            usage = self._usage_by_key()
            result = []
            for item in self._managed_keys():
                key_id = str(item.get("id", ""))
                counts = usage.get(key_id, {})
                total_used_tokens = max(0, int(counts.get("input_tokens", 0))) + max(
                    0, int(counts.get("output_tokens", 0))
                )
                # A recharge starts quota accounting from the saved cumulative total;
                # reporting still reads the complete, immutable usage history.
                usage_offset = max(0, int(item.get("usage_offset_tokens", 0)))
                used_tokens = max(0, total_used_tokens - usage_offset)
                token_limit = max(0, int(item.get("token_limit", 0)))
                public_item = {
                    key: value
                    for key, value in item.items()
                    if key != "usage_offset_tokens"
                }
                result.append(
                    {
                        **public_item,
                        "used_tokens": used_tokens,
                        "remaining_tokens": max(0, token_limit - used_tokens),
                    }
                )
            return result

    def create_api_key(self, name: Any, token_limit: Any) -> dict[str, Any]:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("秘钥名称不能为空")
        if len(normalized_name) > 60:
            raise ValueError("秘钥名称不能超过 60 个字符")
        try:
            normalized_limit = int(token_limit)
        except (TypeError, ValueError) as error:
            raise ValueError("请选择有效的 Token 额度") from error
        if normalized_limit not in USER_KEY_TOKEN_LIMITS:
            raise ValueError("Token 额度只能选择 500 万、1000 万、2000 万或 1 亿")

        with self._lock:
            keys = self._managed_keys()
            if any(str(item.get("name", "")).strip().casefold() == normalized_name.casefold() for item in keys):
                raise ValueError("秘钥名称已存在")
            now = _utc_now()
            created = {
                "id": "key_" + secrets.token_urlsafe(12),
                "name": normalized_name,
                "key": "cp_user_" + secrets.token_urlsafe(30),
                "token_limit": normalized_limit,
                "created_at": now,
            }
            keys.append(created)
            self._write_managed_keys(keys)
            return {**created, "used_tokens": 0, "remaining_tokens": normalized_limit}

    def delete_api_key(self, key_id: str) -> None:
        with self._lock:
            keys = self._managed_keys()
            remaining = [item for item in keys if str(item.get("id", "")) != key_id]
            if len(remaining) == len(keys):
                raise ValueError("秘钥不存在")
            self._write_managed_keys(remaining)
            self._remove_key_usage(key_id)

    def update_api_key_limit(self, key_id: str, token_limit: Any) -> dict[str, Any]:
        try:
            normalized_limit = int(token_limit)
        except (TypeError, ValueError) as error:
            raise ValueError("请选择有效的 Token 额度") from error
        if normalized_limit not in USER_KEY_TOKEN_LIMITS:
            raise ValueError("Token 额度只能选择 500 万、1000 万、2000 万或 1 亿")

        with self._lock:
            keys = self._managed_keys()
            target = next((item for item in keys if str(item.get("id", "")) == key_id), None)
            if target is None:
                raise ValueError("秘钥不存在")
            target["token_limit"] = normalized_limit
            self._write_managed_keys(keys)
            return next(item for item in self.list_api_keys() if item["id"] == key_id)

    def reset_api_key_usage(self, key_id: str) -> dict[str, Any]:
        with self._lock:
            keys = self._managed_keys()
            target = next((item for item in keys if str(item.get("id", "")) == key_id), None)
            if target is None:
                raise ValueError("秘钥不存在")
            counts = self._usage_by_key().get(key_id, {})
            # Preserve token_usage.json for statistics and move only the quota baseline.
            target["usage_offset_tokens"] = max(0, int(counts.get("input_tokens", 0))) + max(
                0, int(counts.get("output_tokens", 0))
            )
            self._write_managed_keys(keys)
            return next(item for item in self.list_api_keys() if item["id"] == key_id)

    def authenticate_api_key(self, supplied: str) -> dict[str, Any] | None:
        if not supplied:
            return None
        with self._lock:
            admin_key = str(self.get_settings().get("local_api_key", ""))
            if admin_key and secrets.compare_digest(admin_key, supplied):
                return {"id": "admin", "name": "管理员 Key", "token_limit": None, "used_tokens": 0}
            for item in self.list_api_keys():
                stored_key = str(item.get("key", ""))
                if stored_key and secrets.compare_digest(stored_key, supplied):
                    return {
                        "id": item["id"],
                        "name": item["name"],
                        "token_limit": item["token_limit"],
                        "used_tokens": item["used_tokens"],
                    }
        return None

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

    @staticmethod
    def _bucket_key_counts(counts: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(counts, dict):
            return {}
        # Compatibility with the original format where a bucket directly held
        # token fields. Those historical records belong to the admin key.
        if any(field in counts for field in USAGE_FIELDS):
            return {"admin": counts}
        return {str(key_id): value for key_id, value in counts.items() if isinstance(value, dict)}

    def _remove_key_usage(self, key_id: str) -> None:
        stored = self._read_json(self.usage_path, {})
        raw_buckets = stored.get("buckets", {}) if isinstance(stored, dict) else {}
        cleaned: dict[str, dict[str, dict[str, Any]]] = {}
        for timestamp, counts in raw_buckets.items() if isinstance(raw_buckets, dict) else []:
            by_key = self._bucket_key_counts(counts)
            by_key.pop(key_id, None)
            if by_key:
                cleaned[str(timestamp)] = by_key
        self._write_json(self.usage_path, {"buckets": cleaned})

    def record_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        key_id: str = "admin",
    ) -> None:
        """Persist token counts in hourly buckets without retaining request-level data."""
        values = {
            "input_tokens": max(0, int(input_tokens)),
            "output_tokens": max(0, int(output_tokens)),
            "cached_tokens": max(0, int(cached_tokens)),
        }
        if not any(values.values()):
            return
        bucket = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")
        with self._lock:
            stored = self._read_json(self.usage_path, {})
            if not isinstance(stored, dict):
                stored = {}
            buckets = stored.get("buckets")
            if not isinstance(buckets, dict):
                buckets = {}
            by_key = self._bucket_key_counts(buckets.get(bucket))
            current = by_key.get(key_id, {})
            by_key[key_id] = {
                key: max(0, int(current.get(key, 0))) + value
                for key, value in values.items()
            }
            buckets[bucket] = by_key
            self._write_json(self.usage_path, {"buckets": buckets})

    def token_usage(self, range_name: str, key_id: str | None = None) -> dict[str, Any]:
        ranges = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "all": None,
        }
        selected = range_name if range_name in ranges else "24h"
        now = datetime.now(timezone.utc)
        since = now - ranges[selected] if ranges[selected] is not None else None
        with self._lock:
            stored = self._read_json(self.usage_path, {})
            raw_buckets = stored.get("buckets", {}) if isinstance(stored, dict) else {}

        grouped: dict[str, dict[str, int]] = {}
        for timestamp, counts in raw_buckets.items() if isinstance(raw_buckets, dict) else []:
            if not isinstance(counts, dict):
                continue
            try:
                point_time = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if since is not None and point_time < since:
                continue
            group_time = point_time if selected == "24h" else point_time.replace(hour=0)
            key = group_time.isoformat().replace("+00:00", "Z")
            by_key = self._bucket_key_counts(counts)
            selected_counts = [by_key[key_id]] if key_id and key_id in by_key else (
                [] if key_id else list(by_key.values())
            )
            if not selected_counts:
                continue
            target = grouped.setdefault(key, {field: 0 for field in USAGE_FIELDS})
            for key_counts in selected_counts:
                for field in target:
                    target[field] += max(0, int(key_counts.get(field, 0)))

        points = [{"timestamp": timestamp, **grouped[timestamp]} for timestamp in sorted(grouped)]
        totals = {
            field: sum(point[field] for point in points)
            for field in ("input_tokens", "output_tokens", "cached_tokens")
        }
        totals["total_tokens"] = totals["input_tokens"] + totals["output_tokens"]
        return {
            "range": selected,
            "bucket": "hour" if selected == "24h" else "day",
            "key_id": key_id or "all",
            "totals": totals,
            "points": points,
        }
