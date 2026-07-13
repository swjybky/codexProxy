from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO

from .storage import AppStore, normalize_credentials


CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"

RESPONSES_FIELDS = {
    "model",
    "input",
    "include",
    "conversation",
    "context_management",
    "instructions",
    "max_output_tokens",
    "top_logprobs",
    "metadata",
    "parallel_tool_calls",
    "previous_response_id",
    "reasoning",
    "service_tier",
    "store",
    "prompt_cache_key",
    "prompt_cache_retention",
    "safety_identifier",
    "stream",
    "stream_options",
    "temperature",
    "text",
    "tool_choice",
    "tools",
    "top_p",
    "truncation",
    "user",
    "max_tool_calls",
    "prompt",
    "enable_thinking",
    "preset",
}
COMPACT_FIELDS = {"model", "input", "instructions", "previous_response_id"}


class ProxyError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request_error") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def transform_request(payload: Any, compact: bool, system_prompt: str, override: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProxyError("请求体必须是 JSON 对象")
    if not isinstance(payload.get("model"), str) or not payload["model"].strip():
        raise ProxyError("model 字段不能为空")

    allowed = COMPACT_FIELDS if compact else RESPONSES_FIELDS
    converted = {key: value for key, value in payload.items() if key in allowed}

    prompt = system_prompt.strip()
    if prompt:
        if "instructions" not in converted or converted["instructions"] is None:
            converted["instructions"] = prompt
        elif override:
            existing = converted["instructions"]
            if isinstance(existing, str) and existing.strip():
                converted["instructions"] = prompt + "\n" + existing.strip()
            else:
                converted["instructions"] = prompt

    if "instructions" not in converted or converted["instructions"] is None:
        converted["instructions"] = ""

    if not compact:
        converted["store"] = False
        converted.pop("max_output_tokens", None)
        converted.pop("temperature", None)
    return converted


class CodexProxy:
    def __init__(self, store: AppStore) -> None:
        self.store = store
        self._refresh_lock = threading.RLock()

    def _opener(self, proxy_url: str) -> urllib.request.OpenerDirector:
        if proxy_url:
            return urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            )
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def prepare(self, payload: Any, compact: bool) -> tuple[urllib.request.Request, bool]:
        settings = self.store.get_settings()
        credentials = self.store.get_credentials()
        if not credentials:
            raise ProxyError("尚未导入 Codex OAuth 凭证", 503, "credentials_missing")

        expired_at = str(credentials.get("expired", "")).strip()
        refresh_token = str(credentials.get("refresh_token", "")).strip()
        if expired_at and refresh_token:
            try:
                parsed_expiry = datetime.fromisoformat(expired_at.replace("Z", "+00:00"))
                if parsed_expiry.tzinfo is None:
                    parsed_expiry = parsed_expiry.replace(tzinfo=timezone.utc)
                if parsed_expiry <= datetime.now(timezone.utc) + timedelta(minutes=5):
                    try:
                        self.refresh_credentials()
                        credentials = self.store.get_credentials() or credentials
                    except ProxyError:
                        if parsed_expiry <= datetime.now(timezone.utc):
                            raise
            except ValueError:
                pass

        access_token = str(credentials.get("access_token", "")).strip()
        account_id = str(credentials.get("account_id", "")).strip()
        if not access_token or not account_id:
            raise ProxyError("OAuth 凭证缺少 access_token 或 account_id", 503, "credentials_invalid")

        converted = transform_request(
            payload,
            compact=compact,
            system_prompt=str(settings.get("system_prompt", "")),
            override=bool(settings.get("system_prompt_override", False)),
        )
        stream = bool(converted.get("stream")) and not compact
        suffix = "/backend-api/codex/responses/compact" if compact else "/backend-api/codex/responses"
        url = str(settings["upstream_base_url"]).rstrip("/") + suffix
        body = json.dumps(converted, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Authorization", "Bearer " + access_token)
        request.add_header("chatgpt-account-id", account_id)
        request.add_header("OpenAI-Beta", "responses=experimental")
        request.add_header("originator", "codex_cli_rs")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "text/event-stream" if stream else "application/json")
        return request, stream

    def open(self, payload: Any, compact: bool) -> tuple[BinaryIO, bool]:
        request, stream = self.prepare(payload, compact)
        proxy_url = str(self.store.get_settings().get("proxy_url", ""))
        try:
            response = self._opener(proxy_url).open(request, timeout=300)
            return response, stream
        except urllib.error.HTTPError as error:
            credentials = self.store.get_credentials() or {}
            if error.code == 401 and str(credentials.get("refresh_token", "")).strip():
                error.close()
                self.refresh_credentials()
                retry_request, stream = self.prepare(payload, compact)
                try:
                    return self._opener(proxy_url).open(retry_request, timeout=300), stream
                except urllib.error.HTTPError as retry_error:
                    return retry_error, stream
                except urllib.error.URLError as retry_error:
                    raise ProxyError(
                        f"无法连接 Codex 上游：{retry_error.reason}",
                        502,
                        "upstream_connection_error",
                    ) from retry_error
            return error, stream
        except urllib.error.URLError as error:
            raise ProxyError(f"无法连接 Codex 上游：{error.reason}", 502, "upstream_connection_error") from error

    def refresh_credentials(self) -> dict[str, Any]:
        with self._refresh_lock:
            return self._refresh_credentials_locked()

    def _refresh_credentials_locked(self) -> dict[str, Any]:
        credentials = self.store.get_credentials()
        refresh_token = str((credentials or {}).get("refresh_token", "")).strip()
        if not refresh_token:
            raise ProxyError("当前凭证没有 refresh_token", 400, "refresh_token_missing")

        form = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            }
        ).encode("ascii")
        request = urllib.request.Request(CODEX_OAUTH_TOKEN_URL, data=form, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        request.add_header("Accept", "application/json")
        proxy_url = str(self.store.get_settings().get("proxy_url", ""))
        try:
            with self._opener(proxy_url).open(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read(2048).decode("utf-8", errors="replace")
            raise ProxyError(f"OAuth 刷新失败（HTTP {error.code}）：{detail}", 502, "oauth_refresh_failed") from error
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise ProxyError(f"OAuth 刷新失败：{error}", 502, "oauth_refresh_failed") from error

        if not isinstance(payload, dict) or not str(payload.get("access_token", "")).strip():
            raise ProxyError("OAuth 刷新响应缺少 access_token", 502, "oauth_refresh_failed")
        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise ProxyError("OAuth 刷新响应缺少有效 expires_in", 502, "oauth_refresh_failed")

        updated = dict(credentials or {})
        updated["access_token"] = str(payload["access_token"]).strip()
        updated["refresh_token"] = str(payload.get("refresh_token") or refresh_token).strip()
        updated["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        updated["expired"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat().replace(
            "+00:00", "Z"
        )
        self.store.save_credentials(normalize_credentials(updated))
        return self.store.credentials_summary()

    def connection_test(self, model: str) -> dict[str, Any]:
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "你好呀",
                        }
                    ],
                }
            ],
            "stream": False,
        }
        response, _ = self.open(payload, compact=False)
        try:
            raw = response.read()
            if getattr(response, "status", 200) < 200 or getattr(response, "status", 200) >= 300:
                detail = raw[:2048].decode("utf-8", errors="replace")
                raise ProxyError(
                    f"上游测试失败（HTTP {getattr(response, 'status', 502)}）：{detail}",
                    502,
                    "connection_test_failed",
                )
            result = json.loads(raw.decode("utf-8"))
            return {"ok": True, "response_id": result.get("id", ""), "model": result.get("model", model)}
        finally:
            response.close()
