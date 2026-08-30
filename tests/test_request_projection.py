from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hermes_continuity_request_projection_test_module",
    ROOT / "request_projection.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

project_continuity_request = MODULE.project_continuity_request
verify_continuity_request_projection = MODULE.verify_continuity_request_projection

MARKER = "[THREAD CONTINUITY QUOTED REFERENCE marker=tcr_test]"
BRIDGE = (
    "Earlier exact source refs: turn-1 and turn-2.\n"
    "[END THREAD CONTINUITY QUOTED REFERENCE]"
)
BLOCK = f"{MARKER}\n{BRIDGE}"


class RequestProjectionTests(unittest.TestCase):
    def assert_verified(self, result: dict) -> None:
        verified = verify_continuity_request_projection(
            result["request"],
            result["proof"],
            marker=MARKER,
            bridge_body=BRIDGE,
        )
        self.assertEqual(verified["status"], "verified")
        self.assertFalse(verified["body_included"])
        self.assertNotIn(BRIDGE, json.dumps(verified))

    def test_string_content_is_prefixed_without_mutating_caller(self) -> None:
        original = {
            "model": "fixture",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "current exact user body"},
            ],
        }
        before = copy.deepcopy(original)

        result = project_continuity_request(
            original,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(result["proof"]["status"], "projected")
        self.assertEqual(result["proof"]["carrier_index"], 1)
        self.assertEqual(result["proof"]["carrier_kind"], "messages:string")
        self.assertEqual(
            result["request"]["messages"][1]["content"],
            f"{BLOCK}\n\ncurrent exact user body",
        )
        projected_text = result["request"]["messages"][1]["content"]
        self.assertEqual(projected_text.count(MODULE.CONTINUITY_END_BOUNDARY), 1)
        self.assertLess(
            projected_text.index(MODULE.CONTINUITY_END_BOUNDARY),
            projected_text.index("current exact user body"),
        )
        self.assertEqual(original, before)
        self.assertIsNot(result["request"], original)
        self.assertIsNot(result["request"]["messages"], original["messages"])
        self.assert_verified(result)

    def test_multimodal_text_block_preserves_existing_parts_and_order(self) -> None:
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
        tool_result = {"type": "tool_result", "tool_use_id": "call-1", "content": "ok"}
        text = {"type": "text", "text": "look at this"}
        original = {
            "messages": [
                {"role": "user", "content": [image, tool_result, text]},
            ]
        }

        result = project_continuity_request(
            original,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        parts = result["request"]["messages"][0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": BLOCK})
        self.assertEqual(parts[1:], [image, tool_result, text])
        self.assertEqual(original["messages"][0]["content"], [image, tool_result, text])
        self.assert_verified(result)

    def test_openai_image_only_user_uses_text_carrier(self) -> None:
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
        request = {"messages": [{"role": "user", "content": [image]}]}

        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(result["proof"]["carrier_kind"], "messages:text")
        self.assertEqual(
            result["request"]["messages"][0]["content"],
            [{"type": "text", "text": BLOCK}, image],
        )
        self.assert_verified(result)

    def test_anthropic_tool_result_only_tail_is_not_a_real_user_carrier(self) -> None:
        tool_tail = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "content": "tool output"}
            ],
        }
        request = {
            "messages": [
                {"role": "user", "content": "real question"},
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "call-1", "name": "fixture"}],
                },
                tool_tail,
            ]
        }

        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(result["proof"]["carrier_index"], 0)
        self.assertEqual(
            result["request"]["messages"][0]["content"],
            f"{BLOCK}\n\nreal question",
        )
        self.assertEqual(result["request"]["messages"][2], tool_tail)
        self.assert_verified(result)

    def test_bedrock_text_and_tool_result_shapes_keep_the_safe_carrier(self) -> None:
        tool_tail = {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "call-1",
                        "content": [{"text": "tool output"}],
                    }
                }
            ],
        }
        request = {
            "messages": [
                {"role": "user", "content": [{"text": "real question"}]},
                {
                    "role": "assistant",
                    "content": [{"toolUse": {"toolUseId": "call-1", "name": "fixture"}}],
                },
                tool_tail,
            ],
            "image_fixture": b"\x00\xff",
        }

        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(result["proof"]["carrier_index"], 0)
        self.assertEqual(result["proof"]["carrier_kind"], "messages:bedrock_text")
        self.assertEqual(
            result["request"]["messages"][0]["content"],
            [{"text": BLOCK}, {"text": "real question"}],
        )
        self.assertEqual(result["request"]["messages"][2], tool_tail)
        self.assert_verified(result)

    def test_codex_input_uses_input_text_without_changing_other_parts(self) -> None:
        image = {"type": "input_image", "image_url": "data:image/png;base64,AA=="}
        request = {
            "model": "gpt-fixture",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        image,
                        {"type": "input_text", "text": "current request"},
                    ],
                }
            ],
        }

        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        content = result["request"]["input"][0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": BLOCK})
        self.assertEqual(content[1:], [image, {"type": "input_text", "text": "current request"}])
        self.assertEqual(result["proof"]["carrier_kind"], "input:input_text")
        self.assert_verified(result)

    def test_codex_image_only_user_uses_input_text_carrier(self) -> None:
        image = {"type": "input_image", "image_url": "data:image/png;base64,AA=="}
        request = {
            "input": [
                {"type": "message", "role": "user", "content": [image]},
            ]
        }

        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(result["proof"]["carrier_kind"], "input:input_text")
        self.assertEqual(
            result["request"]["input"][0]["content"],
            [{"type": "input_text", "text": BLOCK}, image],
        )
        self.assert_verified(result)

    def test_bedrock_image_and_document_only_users_use_text_carrier(self) -> None:
        fixtures = {
            "image": {"image": {"format": "png", "source": {"bytes": b"fixture"}}},
            "document": {
                "document": {
                    "format": "txt",
                    "name": "fixture",
                    "source": {"bytes": b"fixture"},
                }
            },
        }
        for kind, visible_block in fixtures.items():
            with self.subTest(kind=kind):
                request = {
                    "messages": [{"role": "user", "content": [visible_block]}],
                }
                result = project_continuity_request(
                    request,
                    marker=MARKER,
                    bridge_body=BRIDGE,
                )

                self.assertEqual(
                    result["proof"]["carrier_kind"], "messages:bedrock_text"
                )
                self.assertEqual(
                    result["request"]["messages"][0]["content"],
                    [{"text": BLOCK}, visible_block],
                )
                self.assert_verified(result)

    def test_missing_real_user_returns_blocked_unchanged_request(self) -> None:
        request = {
            "messages": [
                {"role": "assistant", "content": "answer"},
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}],
                },
            ]
        }
        before = copy.deepcopy(request)

        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(result["proof"]["status"], "blocked")
        self.assertEqual(result["proof"]["reason"], "real_user_carrier_missing")
        self.assertEqual(result["request"], before)
        self.assertEqual(request, before)

    def test_same_marker_is_idempotent_and_does_not_duplicate(self) -> None:
        first = project_continuity_request(
            {"messages": [{"role": "user", "content": "body"}]},
            marker=MARKER,
            bridge_body=BRIDGE,
        )
        second = project_continuity_request(
            first["request"],
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(second["proof"]["status"], "projected")
        self.assertEqual(second["request"], first["request"])
        text = second["request"]["messages"][0]["content"]
        self.assertEqual(text.count(MARKER), 1)
        self.assertEqual(text.count(BRIDGE), 1)
        self.assert_verified(second)

    def test_different_dynamic_marker_or_end_namespace_fails_closed(self) -> None:
        other_marker = (
            "[THREAD CONTINUITY QUOTED REFERENCE marker=other-plan]"
        )
        for authored in (
            f"{other_marker}\nother body\n{MODULE.CONTINUITY_END_BOUNDARY}\n\ncurrent",
            f"user text {MODULE.CONTINUITY_END_BOUNDARY}",
        ):
            with self.subTest(authored=authored[:40]):
                original = {"messages": [{"role": "user", "content": authored}]}
                result = project_continuity_request(
                    original,
                    marker=MARKER,
                    bridge_body=BRIDGE,
                )
                self.assertEqual(result["proof"]["status"], "blocked")
                self.assertEqual(
                    result["proof"]["reason"], "projection_namespace_conflict"
                )
                self.assertEqual(result["request"], original)
    def test_top_level_system_and_instructions_conflicts_fail_closed(self) -> None:
        for field in ("system", "instructions"):
            with self.subTest(field=field):
                request = {
                    field: BLOCK,
                    "messages": [{"role": "user", "content": "body"}],
                }
                result = project_continuity_request(
                    request,
                    marker=MARKER,
                    bridge_body=BRIDGE,
                )

                self.assertEqual(result["proof"]["status"], "blocked")
                self.assertEqual(
                    result["proof"]["reason"], "projection_marker_conflict"
                )
                self.assertEqual(result["request"], request)

    def test_verifier_counts_top_level_system_and_instructions_duplicates(self) -> None:
        for field in ("system", "instructions"):
            with self.subTest(field=field):
                result = project_continuity_request(
                    {"messages": [{"role": "user", "content": "body"}]},
                    marker=MARKER,
                    bridge_body=BRIDGE,
                )
                duplicated = copy.deepcopy(result["request"])
                duplicated[field] = BLOCK
                proof = {
                    **result["proof"],
                    "request_sha256": MODULE._request_sha256(duplicated),
                }

                verified = verify_continuity_request_projection(
                    duplicated,
                    proof,
                    marker=MARKER,
                    bridge_body=BRIDGE,
                )

                self.assertEqual(verified["status"], "blocked")
                self.assertEqual(verified["reason"], "projection_drift")

    def test_projection_over_limit_is_blocked_without_truncation(self) -> None:
        request = {"messages": [{"role": "user", "content": "body"}]}
        result = project_continuity_request(
            request,
            marker=MARKER,
            bridge_body=BRIDGE,
            max_projection_chars=len(BLOCK) - 1,
        )

        self.assertEqual(result["proof"]["status"], "blocked")
        self.assertEqual(result["proof"]["reason"], "projection_too_large")
        self.assertEqual(result["request"], request)
        self.assertNotIn("…", json.dumps(result["request"]))

    def test_execution_verifier_rejects_proof_tamper(self) -> None:
        result = project_continuity_request(
            {"messages": [{"role": "user", "content": "body"}]},
            marker=MARKER,
            bridge_body=BRIDGE,
        )
        tampered = {**result["proof"], "carrier_index": 99}

        verified = verify_continuity_request_projection(
            result["request"],
            tampered,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(verified["status"], "blocked")
        self.assertEqual(verified["reason"], "proof_mismatch")
        self.assertFalse(verified["body_included"])

    def test_execution_verifier_rejects_status_tamper(self) -> None:
        result = project_continuity_request(
            {"messages": [{"role": "user", "content": "body"}]},
            marker=MARKER,
            bridge_body=BRIDGE,
        )
        tampered = {**result["proof"], "status": "already_projected"}

        verified = verify_continuity_request_projection(
            result["request"],
            tampered,
            marker=MARKER,
            bridge_body=BRIDGE,
        )

        self.assertEqual(verified["status"], "blocked")
        self.assertEqual(verified["reason"], "proof_mismatch")

    def test_execution_verifier_rejects_loss_drift_and_duplicate(self) -> None:
        result = project_continuity_request(
            {"messages": [{"role": "user", "content": "body"}]},
            marker=MARKER,
            bridge_body=BRIDGE,
        )
        lost = copy.deepcopy(result["request"])
        lost["messages"][0]["content"] = "body"
        drifted = copy.deepcopy(result["request"])
        drifted["messages"][0]["content"] = drifted["messages"][0]["content"].replace(
            BRIDGE, "different bridge"
        )
        duplicated = copy.deepcopy(result["request"])
        duplicated["messages"][0]["content"] = (
            f"{BLOCK}\n\n" + duplicated["messages"][0]["content"]
        )

        for request in (lost, drifted, duplicated):
            with self.subTest(content=request["messages"][0]["content"][:20]):
                verified = verify_continuity_request_projection(
                    request,
                    {**result["proof"], "request_sha256": MODULE._request_sha256(request)},
                    marker=MARKER,
                    bridge_body=BRIDGE,
                )
                self.assertEqual(verified["status"], "blocked")

    def test_request_hash_is_stable_across_mapping_key_order(self) -> None:
        left = {
            "model": "fixture",
            "temperature": 0,
            "messages": [{"role": "user", "content": "body"}],
        }
        right = {
            "messages": [{"content": "body", "role": "user"}],
            "temperature": 0,
            "model": "fixture",
        }

        projected_left = project_continuity_request(left, marker=MARKER, bridge_body=BRIDGE)
        projected_right = project_continuity_request(right, marker=MARKER, bridge_body=BRIDGE)

        self.assertEqual(
            projected_left["proof"]["request_sha256"],
            projected_right["proof"]["request_sha256"],
        )
        self.assertEqual(
            projected_left["proof"]["bridge_body_sha256"],
            projected_right["proof"]["bridge_body_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
