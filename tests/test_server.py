from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.server import CodexProxyServer
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
            body = b'data: {"type":"response.completed"}\n\ndata: [DONE]\n\n'
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
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["endpoint"], f"http://127.0.0.1:{self.server.server_port}/v1")
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

        self.assertIn("response.completed", body)
        self.assertEqual(UpstreamHandler.received_path, "/backend-api/codex/responses")
        self.assertEqual(UpstreamHandler.received_headers["Chatgpt-Account-Id"], "account-42")
        self.assertEqual(UpstreamHandler.received_headers["Originator"], "codex_cli_rs")
        self.assertEqual(UpstreamHandler.received_payload["instructions"], "")
        self.assertIs(UpstreamHandler.received_payload["store"], False)
        self.assertNotIn("temperature", UpstreamHandler.received_payload)

    def test_connection_test_sends_list_input_to_codex_upstream(self) -> None:
        request = self.admin_request("/api/connection-test", {"model": "gpt-5.4"})
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read())

        self.assertIs(payload["ok"], True)
        self.assertEqual(
            UpstreamHandler.received_payload["input"],
            [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "你好呀"}],
                }
            ],
        )
        self.assertIs(UpstreamHandler.received_payload["stream"], False)

    def test_rejects_invalid_local_api_key(self) -> None:
        request = self.request("/v1/responses", {"model": "gpt-5.4"}, "wrong")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 401)
        payload = json.loads(raised.exception.read())
        self.assertEqual(payload["error"]["code"], "invalid_api_key")


if __name__ == "__main__":
    unittest.main()
