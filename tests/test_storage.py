from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.storage import AppStore, normalize_credentials


def jwt(claims: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


class CredentialsTest(unittest.TestCase):
    def test_normalizes_codex_cli_auth_shape_and_extracts_claims(self) -> None:
        token = jwt(
            {
                "email": "dev@example.com",
                "exp": 1893456000,
                "https://api.openai.com/auth": {"chatgpt_account_id": "acc_123"},
            }
        )
        result = normalize_credentials(
            {"tokens": {"access_token": token, "refresh_token": "refresh-value"}}
        )

        self.assertEqual(result["account_id"], "acc_123")
        self.assertEqual(result["email"], "dev@example.com")
        self.assertEqual(result["refresh_token"], "refresh-value")
        self.assertTrue(result["expired"].startswith("2030-01-01"))

    def test_rejects_credentials_without_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "account_id"):
            normalize_credentials({"access_token": "opaque-token"})

    def test_store_generates_stable_local_key_and_persists_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = AppStore(root)
            key = first.get_settings()["local_api_key"]
            admin_token = first.get_settings()["admin_token"]
            first.save_credentials({"access_token": "access", "account_id": "account"})

            second = AppStore(root)
            self.assertEqual(second.get_settings()["local_api_key"], key)
            self.assertEqual(second.get_settings()["admin_token"], admin_token)
            self.assertEqual(second.get_credentials()["account_id"], "account")
            # Windows only exposes the read-only bit through chmod/stat and
            # cannot represent POSIX 0600 permission bits.
            if os.name != "nt":
                self.assertEqual(second.credentials_path.stat().st_mode & 0o777, 0o600)


class TokenUsageTest(unittest.TestCase):
    def test_aggregates_usage_without_request_level_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = AppStore(Path(temporary))
            store.record_token_usage(120, 30, 80)
            store.record_token_usage(20, 10, 5)

            usage = store.token_usage("24h")
            self.assertEqual(usage["totals"]["input_tokens"], 140)
            self.assertEqual(usage["totals"]["output_tokens"], 40)
            self.assertEqual(usage["totals"]["cached_tokens"], 85)
            self.assertEqual(usage["totals"]["total_tokens"], 180)
            self.assertEqual(len(usage["points"]), 1)
            stored = json.loads(store.usage_path.read_text(encoding="utf-8"))
            self.assertEqual(list(stored), ["buckets"])
            self.assertEqual(len(stored["buckets"]), 1)

    def test_resets_key_quota_without_clearing_token_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AppStore(root)
            created = store.create_api_key("测试用户", 5_000_000)
            store.record_token_usage(120, 30, 80)
            store.record_token_usage(400, 100, 20, key_id=created["id"])

            keys = store.list_api_keys()
            self.assertEqual(keys[0]["name"], "测试用户")
            self.assertEqual(keys[0]["used_tokens"], 500)
            self.assertEqual(keys[0]["remaining_tokens"], 4_999_500)
            self.assertEqual(store.token_usage("all", "admin")["totals"]["total_tokens"], 150)
            self.assertEqual(store.token_usage("all", created["id"])["totals"]["total_tokens"], 500)
            self.assertEqual(store.token_usage("all")["totals"]["total_tokens"], 650)
            self.assertEqual(store.authenticate_api_key(created["key"])["id"], created["id"])

            usage_before_reset = store.usage_path.read_text(encoding="utf-8")
            reset = store.reset_api_key_usage(created["id"])
            self.assertEqual(reset["used_tokens"], 0)
            self.assertEqual(reset["remaining_tokens"], 5_000_000)
            self.assertNotIn("usage_offset_tokens", reset)
            self.assertEqual(store.usage_path.read_text(encoding="utf-8"), usage_before_reset)
            self.assertEqual(store.token_usage("all", created["id"])["totals"]["total_tokens"], 500)
            self.assertEqual(store.token_usage("all", "admin")["totals"]["total_tokens"], 150)

            store.record_token_usage(40, 10, 5, key_id=created["id"])
            restarted = AppStore(root)
            key_after_recharge = restarted.list_api_keys()[0]
            self.assertEqual(key_after_recharge["used_tokens"], 50)
            self.assertEqual(key_after_recharge["remaining_tokens"], 4_999_950)
            self.assertEqual(
                restarted.token_usage("all", created["id"])["totals"]["total_tokens"],
                550,
            )

    def test_requires_unique_name_and_supported_quota(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = AppStore(Path(temporary))
            with self.assertRaisesRegex(ValueError, "名称"):
                store.create_api_key(" ", 5_000_000)
            with self.assertRaisesRegex(ValueError, "500 万"):
                store.create_api_key("用户", 123)
            store.create_api_key("用户", 10_000_000)
            with self.assertRaisesRegex(ValueError, "已存在"):
                store.create_api_key("用户", 20_000_000)

    def test_updates_key_quota_without_resetting_token_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = AppStore(Path(temporary))
            created = store.create_api_key("额度用户", 20_000_000)
            store.record_token_usage(1_200, 300, key_id=created["id"])

            usage_before_update = store.usage_path.read_text(encoding="utf-8")
            updated = store.update_api_key_limit(created["id"], 100_000_000)

            self.assertEqual(updated["token_limit"], 100_000_000)
            self.assertEqual(updated["used_tokens"], 1_500)
            self.assertEqual(updated["remaining_tokens"], 99_998_500)
            self.assertEqual(store.usage_path.read_text(encoding="utf-8"), usage_before_update)
            self.assertEqual(
                store.token_usage("all", created["id"])["totals"]["total_tokens"],
                1_500,
            )
            with self.assertRaisesRegex(ValueError, "500 万"):
                store.update_api_key_limit(created["id"], 123)
            with self.assertRaisesRegex(ValueError, "不存在"):
                store.update_api_key_limit("missing", 5_000_000)


if __name__ == "__main__":
    unittest.main()
