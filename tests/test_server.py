from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from app.server import CodexProxyServer, extract_token_usage
from app.storage import AppStore


class UpstreamHandler(BaseHTTPRequestHandler):
    received_path = ""
    received_headers: dict[str, str] = {}
    received_payload: dict[str, object] = {}

    def log_message(self, *_: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).received_path = self.path
        type(self).received_headers = dict(self.headers)
        type(self).received_payload = json.loads(self.rfile.read(length))
        if self.received_payload.get("stream"):
            body = b'data: {"type":"response.created","response":{"id":"resp_test","model":"gpt-5.4"}}\n\ndata: {"type":"response.completed","response":{"id":"resp_test","model":"gpt-5.4","usage":{"input_tokens":120,"output_tokens":30,"input_tokens_details":{"cached_tokens":80}}}}\n\ndata: [DONE]\n\n'
            content_type = "text/event-stream"
        else:
            body = b'{"id":"resp_test","object":"response"}'
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ServerIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()

        self.store = AppStore(self.root / "data")
        self.store.save_credentials({"access_token": "upstream-access", "account_id": "account-42"})
        self.store.update_settings({"upstream_base_url": f"http://127.0.0.1:{self.upstream.server_port}"})
        static = self.root / "static"
        static.mkdir()
        (static / "index.html").write_text("ok", encoding="utf-8")
        self.server = CodexProxyServer(("127.0.0.1", 0), self.store, static_dir=static)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.temporary.cleanup()

    def request(self, path: str, payload: dict[str, object], key: str | None = None) -> urllib.request.Request:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}{path}",
            data=json.dumps(payload).encode(),
            method="POST",
        )
        request.add_header("Content-Type", "application/json")
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        return request

    def admin_request(self, path: str, payload: dict[str, object]) -> urllib.request.Request:
        request = self.request(path, payload)
        request.add_header("X-Admin-Token", self.store.get_settings()["admin_token"])
        return request

    def test_status_requires_separate_admin_token(self) -> None:
        url = f"http://127.0.0.1:{self.server.server_port}/api/status"
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(url, timeout=3)
        self.assertEqual(raised.exception.code, 401)

        request = urllib.request.Request(url)
        request.add_header("X-Admin-Token", self.store.get_settings()["admin_token"])
        with mock.patch("app.server.get_lan_ipv4", return_value="192.168.1.23"):
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read())
        self.assertEqual(payload["endpoint"], f"http://127.0.0.1:{self.server.server_port}/v1")
        self.assertEqual(payload["lan_endpoint"], f"http://192.168.1.23:{self.server.server_port}/v1")
        self.assertNotIn("admin_token", payload["settings"])

    def test_forwards_responses_with_codex_headers_and_transformation(self) -> None:
        key = self.store.get_settings()["local_api_key"]
        request = self.request(
            "/v1/responses",
            {"model": "gpt-5.4", "input": "hello", "stream": True, "temperature": 0.2},
            key,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read().decode()

        self.assertIn("data:", body)
        self.assertEqual(UpstreamHandler.received_path, "/backend-api/codex/responses")
        self.assertEqual(UpstreamHandler.received_headers["Chatgpt-Account-Id"], "account-42")
        self.assertEqual(UpstreamHandler.received_headers["Originator"], "codex_cli_rs")
        self.assertEqual(UpstreamHandler.received_payload["instructions"], "")
        self.assertIs(UpstreamHandler.received_payload["store"], False)
        self.assertNotIn("temperature", UpstreamHandler.received_payload)

        usage_request = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}/api/usage?range=24h")
        usage_request.add_header("X-Admin-Token", self.store.get_settings()["admin_token"])
        with urllib.request.urlopen(usage_request, timeout=3) as response:
            usage = json.loads(response.read())
        self.assertEqual(usage["totals"]["input_tokens"], 120)
        self.assertEqual(usage["totals"]["output_tokens"], 30)
        self.assertEqual(usage["totals"]["cached_tokens"], 80)

    def test_connection_test_sends_list_input_to_codex_upstream(self) -> None:
        request = self.admin_request("/api/connection-test", {"model": "gpt-5.4"})
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())

        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["response_id"], "resp_test")
        self.assertEqual(payload["model"], "gpt-5.4")
        self.assertEqual(
            UpstreamHandler.received_payload["input"],
            [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "你好呀"}],
                }
            ],
        )
        self.assertIs(UpstreamHandler.received_payload["stream"], True)

    def test_rejects_invalid_local_api_key(self) -> None:
        request = self.request("/v1/responses", {"model": "gpt-5.4"}, "wrong")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 401)
        payload = json.loads(raised.exception.read())
        self.assertEqual(payload["error"]["code"], "invalid_api_key")

    def test_manages_named_keys_and_blocks_exhausted_quota_until_reset(self) -> None:
        create = self.admin_request(
            "/api/keys",
            {"name": "协作用户", "token_limit": 5_000_000},
        )
        with urllib.request.urlopen(create, timeout=3) as response:
            created = json.loads(response.read())["key"]
        self.assertEqual(created["name"], "协作用户")
        self.assertEqual(created["token_limit"], 5_000_000)

        self.store.record_token_usage(4_500_000, 500_000, key_id=created["id"])
        exhausted = self.request(
            "/v1/responses",
            {"model": "gpt-5.4", "input": "hello", "stream": True},
            created["key"],
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(exhausted, timeout=3)
        self.assertEqual(raised.exception.code, 429)
        error = json.loads(raised.exception.read())["error"]
        self.assertEqual(error["code"], "insufficient_quota")
        self.assertEqual(error["message"], "用量不足，请找管理员重置")

        reset = self.admin_request(f"/api/keys/{created['id']}/reset", {})
        with urllib.request.urlopen(reset, timeout=3) as response:
            self.assertEqual(json.loads(response.read())["key"]["used_tokens"], 0)

        allowed = self.request(
            "/v1/responses",
            {"model": "gpt-5.4", "input": "hello", "stream": True},
            created["key"],
        )
        with urllib.request.urlopen(allowed, timeout=3) as response:
            self.assertEqual(response.status, 200)

        usage_url = (
            f"http://127.0.0.1:{self.server.server_port}/api/usage"
            f"?range=all&key_id={created['id']}"
        )
        usage_request = urllib.request.Request(usage_url)
        usage_request.add_header("X-Admin-Token", self.store.get_settings()["admin_token"])
        with urllib.request.urlopen(usage_request, timeout=3) as response:
            usage = json.loads(response.read())
        self.assertEqual(usage["key_id"], created["id"])
        self.assertEqual(usage["totals"]["total_tokens"], 150)


class TokenUsageParsingTest(unittest.TestCase):
    def test_extracts_non_streaming_usage(self) -> None:
        raw = json.dumps({
            "id": "resp_1",
            "usage": {
                "input_tokens": 44,
                "output_tokens": 12,
                "input_tokens_details": {"cached_tokens": 31},
            },
        }).encode()
        self.assertEqual(extract_token_usage(raw), (44, 12, 31))


if __name__ == "__main__":
    unittest.main()
