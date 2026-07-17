from __future__ import annotations

import hmac
import ipaddress
import json
import mimetypes
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .codex_proxy import CodexProxy, ProxyError
from .runtime_paths import web_dist_dir
from .storage import AppStore, SUPPORTED_MODELS


MAX_BODY_SIZE = 32 * 1024 * 1024
MAX_USAGE_CAPTURE = 2 * 1024 * 1024


def _usage_from_object(payload: Any) -> tuple[int, int, int] | None:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        response = payload.get("response")
        usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_tokens_details")
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else usage.get("cached_input_tokens", 0)
    try:
        return max(0, int(usage.get("input_tokens", 0))), max(0, int(usage.get("output_tokens", 0))), max(0, int(cached))
    except (TypeError, ValueError):
        return None


def extract_token_usage(raw: bytes) -> tuple[int, int, int] | None:
    text = raw.decode("utf-8", errors="replace")
    try:
        usage = _usage_from_object(json.loads(text))
        if usage is not None:
            return usage
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            usage = _usage_from_object(json.loads(data))
        except json.JSONDecodeError:
            continue
        if usage is not None:
            return usage

    # Large non-streaming responses may be captured as a tail rather than a
    # complete JSON document. Usage is emitted near the end, so recover the
    # three numeric fields from the final usage object as a fallback.
    marker = text.rfind('"usage"')
    if marker < 0:
        return None
    tail = text[marker:]
    def number(field: str) -> int:
        match = re.search(rf'"{field}"\s*:\s*(\d+)', tail)
        return int(match.group(1)) if match else 0
    return number("input_tokens"), number("output_tokens"), number("cached_tokens")


def get_lan_ipv4() -> str | None:
    """Return the preferred reachable LAN IPv4 address, if available."""
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("192.0.2.1", 80))
            candidates.append(str(connection.getsockname()[0]))
    except OSError:
        pass

    try:
        candidates.extend(
            address[4][0]
            for address in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        )
    except OSError:
        pass

    addresses: list[tuple[str, ipaddress.IPv4Address]] = []
    for candidate in dict.fromkeys(candidates):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address) and not address.is_loopback and not address.is_link_local:
            addresses.append((candidate, address))

    # Prefer ordinary private LANs over VPN and virtual-adapter ranges that may
    # own the default route (for example 198.18.0.0/15).
    private_lans = (
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("10.0.0.0/8"),
    )
    for network in private_lans:
        for candidate, address in addresses:
            if address in network:
                return candidate
    for candidate, address in addresses:
        if address.is_global:
            return candidate
    return None


class RuntimeState:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.request_count = 0
        self.success_count = 0
        self.last_request_at = ""
        self.last_status = 0
        self._lock = threading.Lock()

    def record(self, status: int) -> None:
        with self._lock:
            self.request_count += 1
            self.last_request_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.last_status = status
            if 200 <= status < 300:
                self.success_count += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "uptime_seconds": int(time.time() - self.started_at),
                "request_count": self.request_count,
                "success_count": self.success_count,
                "last_request_at": self.last_request_at,
                "last_status": self.last_status,
            }


class CodexProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], store: AppStore, static_dir: Path | None = None) -> None:
        self.store = store
        self.proxy = CodexProxy(store)
        self.static_dir = static_dir or web_dist_dir()
        self.runtime = RuntimeState()
        super().__init__(address, RequestHandler)


class RequestHandler(BaseHTTPRequestHandler):
    server: CodexProxyServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[codex-proxy] {self.address_string()} {format_string % args}")

    def _json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(encoded)
        self.close_connection = True

    def _error(self, error: Exception, status: int = 500, code: str = "internal_error") -> None:
        if isinstance(error, ProxyError):
            status, code = error.status, error.code
        self._json(status, {"error": {"message": str(error), "type": code, "code": code}})

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _read_json(self) -> Any:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ProxyError("Content-Length 无效") from error
        if content_length <= 0:
            raise ProxyError("请求体不能为空")
        if content_length > MAX_BODY_SIZE:
            raise ProxyError("请求体超过 32 MB 限制", 413, "request_too_large")
        try:
            return json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProxyError("请求体不是有效 JSON") from error

    def _discard_request_body(self) -> None:
        """Drain rejected POST bodies so Windows can deliver the JSON error before closing."""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < content_length <= MAX_BODY_SIZE:
            self.rfile.read(content_length)

    def _api_key_identity(self) -> dict[str, Any] | None:
        authorization = self.headers.get("Authorization", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not supplied:
            supplied = self.headers.get("X-API-Key", "").strip()
        return self.server.store.authenticate_api_key(supplied)

    def _admin_authorized(self) -> bool:
        expected = str(self.server.store.get_settings().get("admin_token", ""))
        supplied = self.headers.get("X-Admin-Token", "").strip()
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))

    def _require_admin(self) -> bool:
        if self._admin_authorized():
            return True
        self._error(ProxyError("桌面管理令牌无效，请从应用窗口访问", 401, "invalid_admin_token"))
        return False

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key, X-Admin-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/health":
            self._json(200, {"status": "ok", "service": "codex-proxy"})
            return
        if path == "/api/usage":
            if not self._require_admin():
                return
            query = parse_qs(parsed_url.query)
            range_name = query.get("range", ["24h"])[0]
            selected_key = query.get("key_id", ["all"])[0]
            self._json(200, self.server.store.token_usage(range_name, None if selected_key == "all" else selected_key))
            return
        if path == "/api/keys":
            if not self._require_admin():
                return
            self._json(200, {"keys": self.server.store.list_api_keys()})
            return
        if path == "/api/status":
            if not self._require_admin():
                return
            settings = self.server.store.get_settings()
            private_keys = {"local_api_key", "admin_token"}
            lan_ip = get_lan_ipv4()
            self._json(
                200,
                {
                    "service": self.server.runtime.snapshot(),
                    "credentials": self.server.store.credentials_summary(),
                    "endpoint": f"http://127.0.0.1:{self.server.server_port}/v1",
                    "lan_endpoint": f"http://{lan_ip}:{self.server.server_port}/v1" if lan_ip else None,
                    "local_api_key": settings["local_api_key"],
                    "settings": {key: value for key, value in settings.items() if key not in private_keys},
                    "models": SUPPORTED_MODELS,
                },
            )
            return
        if path == "/v1/models":
            if not self._api_key_identity():
                self._error(ProxyError("本地 API Key 无效", 401, "invalid_api_key"))
                return
            self._json(200, {"object": "list", "data": [{"id": model, "object": "model"} for model in SUPPORTED_MODELS]})
            return
        self._serve_static(path)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if not self._require_admin():
            return
        try:
            if path == "/api/settings":
                settings = self.server.store.update_settings(self._read_json())
                private_keys = {"local_api_key", "admin_token"}
                self._json(200, {"settings": {key: value for key, value in settings.items() if key not in private_keys}})
            elif re.fullmatch(r"/api/keys/[^/]+", path):
                payload = self._read_json()
                if not isinstance(payload, dict):
                    raise ProxyError("请求体必须是 JSON 对象")
                key_id = unquote(path.split("/")[3])
                updated = self.server.store.update_api_key_limit(key_id, payload.get("token_limit"))
                self._json(200, {"key": updated})
            else:
                self._error(ProxyError("接口不存在", 404, "not_found"))
        except (ProxyError, ValueError) as error:
            self._error(error, 400, "invalid_settings")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path in ("/v1/responses", "/v1/responses/compact"):
            self._relay(compact=path.endswith("/compact"))
            return
        if path.startswith("/api/") and not self._require_admin():
            return
        try:
            if path == "/api/credentials/import":
                payload = self._read_json()
                raw = payload.get("raw") if isinstance(payload, dict) else None
                if not isinstance(raw, str):
                    raise ProxyError("raw 字段不能为空")
                self.server.store.import_credentials_text(raw)
                self._json(200, {"credentials": self.server.store.credentials_summary()})
            elif path == "/api/credentials/import-default":
                self.server.store.import_default_codex_credentials()
                self._json(200, {"credentials": self.server.store.credentials_summary()})
            elif path == "/api/credentials/refresh":
                self._json(200, {"credentials": self.server.proxy.refresh_credentials()})
            elif path == "/api/key/regenerate":
                self._json(200, {"local_api_key": self.server.store.regenerate_api_key()})
            elif path == "/api/keys":
                payload = self._read_json()
                if not isinstance(payload, dict):
                    raise ProxyError("请求体必须是 JSON 对象")
                created = self.server.store.create_api_key(payload.get("name"), payload.get("token_limit"))
                self._json(201, {"key": created})
            elif re.fullmatch(r"/api/keys/[^/]+/reset", path):
                key_id = unquote(path.split("/")[3])
                self._json(200, {"key": self.server.store.reset_api_key_usage(key_id)})
            elif path == "/api/connection-test":
                payload = self._read_json()
                model = str(payload.get("model", "gpt-5.4")) if isinstance(payload, dict) else "gpt-5.4"
                self._json(200, self.server.proxy.connection_test(model))
            else:
                self._error(ProxyError("接口不存在", 404, "not_found"))
        except (ProxyError, ValueError) as error:
            self._error(error, 400, "invalid_request_error")

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not self._require_admin():
            return
        try:
            if not re.fullmatch(r"/api/keys/[^/]+", path):
                raise ProxyError("接口不存在", 404, "not_found")
            self.server.store.delete_api_key(unquote(path.split("/")[3]))
            self._json(200, {"deleted": True})
        except (ProxyError, ValueError) as error:
            self._error(error, 400, "invalid_request_error")

    def _relay(self, compact: bool) -> None:
        identity = self._api_key_identity()
        if not identity:
            self._discard_request_body()
            self.server.runtime.record(401)
            self._error(ProxyError("本地 API Key 无效", 401, "invalid_api_key"))
            return
        token_limit = identity.get("token_limit")
        if token_limit is not None and int(identity.get("used_tokens", 0)) >= int(token_limit):
            self._discard_request_body()
            self.server.runtime.record(429)
            self._error(ProxyError("用量不足，请找管理员重置", 429, "insufficient_quota"))
            return
        try:
            payload = self._read_json()
            upstream, is_stream = self.server.proxy.open(payload, compact)
            status = int(getattr(upstream, "status", getattr(upstream, "code", 502)))
            self.send_response(status)
            content_type = upstream.headers.get("Content-Type") or (
                "text/event-stream" if is_stream else "application/json"
            )
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache" if is_stream else "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self._cors_headers()
            self.end_headers()
            usage_capture = bytearray()
            try:
                read = getattr(upstream, "read1", upstream.read)
                while True:
                    chunk = read(8192)
                    if not chunk:
                        break
                    usage_capture.extend(chunk)
                    if len(usage_capture) > MAX_USAGE_CAPTURE:
                        del usage_capture[:-MAX_USAGE_CAPTURE]
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                upstream.close()
                self.close_connection = True
            usage = extract_token_usage(bytes(usage_capture))
            if usage is not None:
                self.server.store.record_token_usage(*usage, key_id=str(identity["id"]))
            self.server.runtime.record(status)
        except (ProxyError, ValueError) as error:
            status = error.status if isinstance(error, ProxyError) else 400
            self.server.runtime.record(status)
            self._error(error, 400, "invalid_request_error")

    def _serve_static(self, request_path: str) -> None:
        root = self.server.static_dir.resolve()
        relative = unquote(request_path).lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        if root not in candidate.parents and candidate != root:
            self._error(ProxyError("文件不存在", 404, "not_found"))
            return
        if not candidate.is_file():
            candidate = root / "index.html"
        if not candidate.is_file():
            message = (
                "前端尚未构建。请先运行：cd web && npm install && npm run build"
            ).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)
            return
        content = candidate.read_bytes()
        mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".js":
            mime_type = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", mime_type + ("; charset=utf-8" if mime_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=31536000")
        self.end_headers()
        self.wfile.write(content)


def start_server(store: AppStore, port: int | None = None, static_dir: Path | None = None) -> CodexProxyServer:
    chosen_port = port or int(store.get_settings().get("listen_port", 1455))
    server = CodexProxyServer(("0.0.0.0", chosen_port), store, static_dir=static_dir)
    thread = threading.Thread(target=server.serve_forever, name="codex-proxy-http", daemon=True)
    thread.start()
    return server
