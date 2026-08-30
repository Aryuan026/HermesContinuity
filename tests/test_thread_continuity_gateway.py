from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "hermes_continuity_gateway_test_plugin"
if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package

context_compactor = importlib.import_module(f"{PACKAGE_NAME}.context_compactor")
gateway = importlib.import_module(f"{PACKAGE_NAME}.thread_continuity_gateway")

build_thread_continuity_checkpoint_v2 = (
    context_compactor.build_thread_continuity_checkpoint_v2
)
build_thread_continuity_linker_projection = (
    gateway.build_thread_continuity_linker_projection
)
project_thread_continuity_linker_trace = (
    gateway.project_thread_continuity_linker_trace
)


class ThreadContinuityGatewayTests(unittest.TestCase):
    def test_continuity_linker_separates_retirement_bridge_and_raw_suffix(self) -> None:
        groups = [
            {
                "source_prefix_id": "g-covered",
                "logical_turn_id": "turn-covered",
                "record_id": "cap-covered",
                "canonical_ids": ["canonical-covered"],
                "message_ids": ["u-covered", "a-covered"],
                "messages": [
                    {"role": "user", "message_id": "u-covered", "content": "covered"},
                    {"role": "assistant", "message_id": "a-covered", "content": "done"},
                ],
            },
            {
                "source_prefix_id": "g-raw",
                "logical_turn_id": "turn-raw",
                "record_id": "cap-raw",
                "canonical_ids": ["canonical-raw"],
                "message_ids": ["u-raw", "a-raw"],
                "messages": [
                    {"role": "user", "message_id": "u-raw", "content": "raw"},
                    {"role": "assistant", "message_id": "a-raw", "content": "reply"},
                ],
            },
        ]
        legacy_body = "旧版摘要只保留为未验证的可见兼容体"
        linker = build_thread_continuity_linker_projection(
            source_groups=groups,
            checkpoint={
                "revision": 3,
                "revision_id": "tcr_" + "3" * 64,
                "summary_text": legacy_body,
                "summary_sha256": hashlib.sha256(legacy_body.encode("utf-8")).hexdigest(),
                "covered_through": {"source_prefix_ids": ["g-covered"]},
            },
            source_snapshot="e" * 64,
            current_ephemeral={
                "message_id": "u-current",
                "canonical_ids": ["canonical-current"],
            },
        )

        self.assertEqual(linker["candidate_unretired_group_ids"], ["g-raw"])
        self.assertTrue({"g-raw", "cap-raw", "u-raw", "a-raw"}.issubset(
            set(linker["candidate_unretired_aliases"])
        ))
        self.assertEqual(linker["retired_group_ids"], ["g-covered"])
        self.assertTrue({"g-covered", "cap-covered", "u-covered", "a-covered"}.issubset(
            set(linker["retired_aliases"])
        ))
        self.assertTrue(set(linker["candidate_unretired_aliases"]).isdisjoint(
            linker["retired_aliases"]
        ))
        self.assertEqual(linker["bridge_represented_group_ids"], [])
        self.assertEqual(linker["bridge_represented_aliases"], [])
        self.assertEqual(linker["bridge_status"], "legacy_unverified")
        self.assertEqual(
            linker["current_ephemeral_aliases"],
            ["u-current", "canonical-current"],
        )
        self.assertEqual(linker["continuity_revision"], 3)
        self.assertEqual(linker["continuity_revision_id"], "tcr_" + "3" * 64)
        self.assertEqual(linker["source_snapshot"], "e" * 64)
        self.assertEqual(
            linker["bridge_body_sha256"],
            hashlib.sha256(legacy_body.encode("utf-8")).hexdigest(),
        )
        self.assertFalse(linker["body_included"])

    def test_continuity_linker_public_trace_is_bounded_and_body_free(self) -> None:
        groups = [
            {
                "source_prefix_id": f"g-{index}",
                "record_id": f"cap-{index}",
                "messages": [
                    {
                        "role": "user",
                        "message_id": f"u-{index}",
                        "content": f"PRIVATE_BODY_{index}",
                    }
                ],
            }
            for index in range(90)
        ]
        linker = build_thread_continuity_linker_projection(
            source_groups=groups,
            checkpoint={
                "revision": 4,
                "revision_id": "tcr_" + "4" * 64,
                "summary_sha256": "c" * 64,
                "covered_through": {
                    "source_prefix_ids": [f"g-{index}" for index in range(70)]
                },
            },
            source_snapshot="f" * 64,
            current_ephemeral={"message_id": "u-current"},
        )
        trace = project_thread_continuity_linker_trace(linker)

        self.assertEqual(trace["canonical_source_alias_count"], 270)
        self.assertEqual(trace["retired_group_count"], 70)
        self.assertEqual(trace["candidate_unretired_group_count"], 20)
        self.assertEqual(trace["bridge_represented_group_count"], 0)
        self.assertNotIn("sample", json.dumps(trace))
        self.assertNotIn("truncated", json.dumps(trace))
        self.assertNotIn("canonical_source_aliases", trace)
        self.assertNotIn("candidate_unretired_aliases", trace)
        self.assertNotIn("retired_aliases", trace)
        self.assertNotIn("bridge_represented_aliases", trace)
        self.assertNotIn("PRIVATE_BODY", json.dumps(trace))
        self.assertFalse(trace["body_included"])

    def test_v2_recent_bridge_public_trace_carries_only_counts_and_digests(self) -> None:
        groups = [
            {
                "group_kind": "dialogue_turn",
                "source_prefix_id": "g-bridge",
                "logical_turn_id": "turn-bridge",
                "record_id": "cap-bridge",
                "effective_event_at": "2026-08-16T12:00:00Z",
                "message_ids": ["u-bridge", "a-bridge"],
                "messages": [
                    {
                        "role": "user",
                        "message_id": "u-bridge",
                        "content": "PRIVATE_BRIDGE_BODY /Users/owner/private/path",
                    },
                    {
                        "role": "assistant",
                        "message_id": "a-bridge",
                        "content": "只在私有 checkpoint 正文中",
                    },
                ],
            }
        ]
        checkpoint = build_thread_continuity_checkpoint_v2(
            previous_state=None,
            source_groups=groups,
            retired_source_group_ids=["g-bridge"],
            bridge_source_group_ids=["g-bridge"],
            bridge_text="PRIVATE_BRIDGE_BODY /Users/owner/private/path",
            bridge_policy={
                "reference_at": "2026-08-16T16:00:00Z",
                "recent_horizon_hours": 72,
                "source_token_limit": 24000,
                "output_token_limit": 2048,
            },
        )
        linker = build_thread_continuity_linker_projection(
            source_groups=groups,
            checkpoint=checkpoint,
            source_snapshot="9" * 64,
            current_ephemeral={"message_id": "u-current"},
        )
        trace = project_thread_continuity_linker_trace(linker)

        self.assertEqual(trace["bridge_represented_group_count"], 1)
        encoded = json.dumps(trace, ensure_ascii=False)
        self.assertNotIn("PRIVATE_BRIDGE_BODY", encoded)
        self.assertNotIn("/Users/owner/private/path", encoded)
        self.assertNotIn("g-bridge", encoded)
        self.assertFalse(trace["body_included"])

    def test_continuity_linker_public_trace_rejects_malformed_or_open_projection(self) -> None:
        valid = build_thread_continuity_linker_projection(
            source_groups=[{
                "source_prefix_id": "g-1",
                "record_id": "cap-1",
                "messages": [{"role": "user", "message_id": "u-1"}],
            }],
            checkpoint=None,
            source_snapshot="1" * 64,
            current_ephemeral={"message_id": "u-current"},
        )
        attacks = (
            {**valid, "unknown": "PRIVATE_MARKER"},
            {key: value for key, value in valid.items() if key != "source_snapshot"},
            {**valid, "canonical_source_aliases": "PRIVATE_MARKER"},
            {**valid, "continuity_revision": True},
            {**valid, "continuity_revision": -1},
            {**valid, "source_snapshot": "/Users/owner/PRIVATE_PATH"},
            {**valid, "continuity_revision_id": "PRIVATE_MARKER"},
            {**valid, "bridge_body_sha256": "PRIVATE_MARKER"},
        )

        for attack in attacks:
            with self.subTest(keys=sorted(attack)):
                self.assertEqual(project_thread_continuity_linker_trace(attack), {})

    def test_continuity_linker_shared_alias_stays_bookkeeping_only(self) -> None:
        linker = build_thread_continuity_linker_projection(
            source_groups=[
                {
                    "source_prefix_id": "g-covered",
                    "canonical_ids": ["shared-alias"],
                    "messages": [{"role": "user", "message_id": "u-covered"}],
                },
                {
                    "source_prefix_id": "g-candidate",
                    "canonical_ids": ["shared-alias"],
                    "messages": [{"role": "user", "message_id": "u-candidate"}],
                },
            ],
            checkpoint={
                "revision": 1,
                "revision_id": "tcr_" + "1" * 64,
                "summary_sha256": "2" * 64,
                "covered_through": {"source_prefix_ids": ["g-covered"]},
            },
            source_snapshot="3" * 64,
            current_ephemeral={"message_id": "u-current"},
        )

        self.assertIn("shared-alias", linker["retired_aliases"])
        self.assertIn("shared-alias", linker["candidate_unretired_aliases"])
        self.assertNotIn("shared-alias", linker["bridge_represented_aliases"])
        trace = project_thread_continuity_linker_trace(linker)
        self.assertNotIn("shared-alias", json.dumps(trace))


if __name__ == "__main__":
    unittest.main()
