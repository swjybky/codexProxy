from __future__ import annotations

import base64
import json
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
            self.assertEqual(second.credentials_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
