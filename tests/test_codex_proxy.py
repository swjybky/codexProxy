from __future__ import annotations

import unittest

from app.codex_proxy import ProxyError, transform_request


class TransformRequestTest(unittest.TestCase):
    def test_responses_request_matches_codex_adaptor_contract(self) -> None:
        converted = transform_request(
            {
                "model": "gpt-5.4",
                "input": "hello",
                "instructions": "client prompt",
                "store": True,
                "max_output_tokens": 1024,
                "temperature": 0.3,
                "unknown_parameter": "drop-me",
                "stream": True,
            },
            compact=False,
            system_prompt="gateway prompt",
            override=True,
        )

        self.assertEqual(converted["instructions"], "gateway prompt\nclient prompt")
        self.assertIs(converted["store"], False)
        self.assertNotIn("max_output_tokens", converted)
        self.assertNotIn("temperature", converted)
        self.assertNotIn("unknown_parameter", converted)
        self.assertIs(converted["stream"], True)

    def test_responses_defaults_instructions_to_empty_string(self) -> None:
        converted = transform_request(
            {"model": "gpt-5-codex", "input": []},
            compact=False,
            system_prompt="",
            override=False,
        )
        self.assertEqual(converted["instructions"], "")
        self.assertIs(converted["store"], False)

    def test_compact_keeps_only_compaction_dto_fields(self) -> None:
        converted = transform_request(
            {
                "model": "gpt-5.4",
                "input": [],
                "previous_response_id": "resp_1",
                "store": True,
                "stream": True,
                "temperature": 1,
            },
            compact=True,
            system_prompt="compact prompt",
            override=False,
        )
        self.assertEqual(
            converted,
            {
                "model": "gpt-5.4",
                "input": [],
                "previous_response_id": "resp_1",
                "instructions": "compact prompt",
            },
        )

    def test_requires_model(self) -> None:
        with self.assertRaises(ProxyError):
            transform_request({}, compact=False, system_prompt="", override=False)


if __name__ == "__main__":
    unittest.main()

