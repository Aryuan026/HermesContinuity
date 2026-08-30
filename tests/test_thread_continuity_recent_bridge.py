from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_algorithm_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")
build_thread_continuity_checkpoint = context_compactor.build_thread_continuity_checkpoint
build_thread_continuity_checkpoint_v2 = (
    context_compactor.build_thread_continuity_checkpoint_v2
)
normalize_thread_continuity_checkpoint = (
    context_compactor.normalize_thread_continuity_checkpoint
)
select_thread_continuity_recent_bridge = (
    context_compactor.select_thread_continuity_recent_bridge
)
thread_continuity_bridge_projection = (
    context_compactor.thread_continuity_bridge_projection
)
thread_continuity_retirement_source_group_ids = (
    context_compactor.thread_continuity_retirement_source_group_ids
)


def group(source_id: str, event_at: str, text: str) -> dict:
    return {
        "group_kind": "dialogue_turn",
        "source_prefix_id": source_id,
        "logical_turn_id": source_id,
        "record_id": f"record-{source_id}",
        "effective_event_at": event_at,
        "messages": [
            {"role": "user", "message_id": f"user-{source_id}", "content": text},
            {"role": "assistant", "message_id": f"assistant-{source_id}", "content": f"答：{text}"},
        ],
    }


def estimate(messages: list[dict]) -> int:
    return sum(len(str(message.get("content") or "")) for message in messages)


class ThreadContinuityRecentBridgeTests(unittest.TestCase):
    def test_v1_is_conservatively_read_as_retirement_with_unverified_bridge(self) -> None:
        rows = [
            group("g-1", "2026-08-10T00:00:00Z", "旧一"),
            group("g-2", "2026-08-11T00:00:00Z", "旧二"),
        ]
        v1 = build_thread_continuity_checkpoint(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["g-1", "g-2"],
            summary_text="旧 lifetime summary 只作迁移兼容正文",
        )

        normalized = normalize_thread_continuity_checkpoint(v1, source_groups=rows)
        bridge = thread_continuity_bridge_projection(normalized)

        self.assertEqual(
            thread_continuity_retirement_source_group_ids(normalized),
            ["g-1", "g-2"],
        )
        self.assertEqual(bridge["status"], "legacy_unverified")
        self.assertEqual(bridge["relation"], "legacy_unverified")
        self.assertEqual(bridge["represented_source_group_ids"], [])
        self.assertEqual(bridge["body"], "旧 lifetime summary 只作迁移兼容正文")

    def test_recent_bridge_slice_is_contiguous_recent_and_token_bounded(self) -> None:
        rows = [
            group("old", "2026-08-01T00:00:00Z", "很旧"),
            group("recent-1", "2026-08-14T12:00:00Z", "一" * 20),
            group("recent-2", "2026-08-15T12:00:00Z", "二" * 20),
            group("recent-3", "2026-08-16T12:00:00Z", "三" * 20),
        ]

        selected = select_thread_continuity_recent_bridge(
            rows,
            retired_source_group_ids=[row["source_prefix_id"] for row in rows],
            reference_at="2026-08-16T16:00:00Z",
            recent_horizon_hours=72,
            source_token_limit=90,
            estimate_messages=estimate,
        )

        self.assertEqual(selected["status"], "ready")
        self.assertEqual(selected["source_group_ids"], ["recent-2", "recent-3"])
        self.assertLessEqual(selected["estimated_source_tokens"], 90)
        self.assertEqual(selected["excluded_by_currentness_count"], 1)
        self.assertEqual(selected["excluded_by_token_count"], 1)

    def test_recent_bridge_never_jumps_across_a_currentness_gap(self) -> None:
        rows = [
            group("recent-before-gap", "2026-08-15T12:00:00Z", "不能跨缝拼接"),
            group("expired-gap", "2026-08-01T00:00:00Z", "过期边界"),
            group("recent-tail", "2026-08-16T12:00:00Z", "只保留连续尾片"),
        ]

        selected = select_thread_continuity_recent_bridge(
            rows,
            retired_source_group_ids=[row["source_prefix_id"] for row in rows],
            reference_at="2026-08-16T16:00:00Z",
            recent_horizon_hours=72,
            source_token_limit=24000,
            estimate_messages=estimate,
        )

        self.assertEqual(selected["source_group_ids"], ["recent-tail"])
        self.assertEqual(selected["excluded_by_currentness_count"], 2)

    def test_v2_retirement_is_monotonic_while_bridge_may_slide(self) -> None:
        rows = [
            group("g-1", "2026-08-13T00:00:00Z", "一"),
            group("g-2", "2026-08-14T00:00:00Z", "二"),
            group("g-3", "2026-08-15T00:00:00Z", "三"),
            group("g-4", "2026-08-16T00:00:00Z", "四"),
        ]
        policy = {
            "reference_at": "2026-08-16T16:00:00Z",
            "recent_horizon_hours": 72,
            "source_token_limit": 24000,
            "output_token_limit": 2048,
        }
        first = build_thread_continuity_checkpoint_v2(
            previous_state=None,
            source_groups=rows,
            retired_source_group_ids=["g-1", "g-2", "g-3"],
            bridge_source_group_ids=["g-2", "g-3"],
            bridge_text="二和三的近场桥",
            bridge_policy=policy,
        )
        second = build_thread_continuity_checkpoint_v2(
            previous_state=first,
            source_groups=rows,
            retired_source_group_ids=["g-1", "g-2", "g-3", "g-4"],
            bridge_source_group_ids=["g-4"],
            bridge_text="只重建四的近场桥",
            bridge_policy=policy,
        )

        self.assertEqual(
            thread_continuity_retirement_source_group_ids(second),
            ["g-1", "g-2", "g-3", "g-4"],
        )
        bridge = thread_continuity_bridge_projection(second)
        self.assertEqual(bridge["represented_source_group_ids"], ["g-4"])
        self.assertEqual(bridge["relation"], "represented_in_recent_bridge")
        self.assertEqual(bridge["body"], "只重建四的近场桥")
        self.assertEqual(second["predecessor_revision_id"], first["revision_id"])

        with self.assertRaisesRegex(ValueError, "retirement_cursor_regression"):
            build_thread_continuity_checkpoint_v2(
                previous_state=second,
                source_groups=rows,
                retired_source_group_ids=["g-1", "g-2"],
                bridge_source_group_ids=["g-2"],
                bridge_text="不得倒退",
                bridge_policy=policy,
            )

    def test_empty_recent_bridge_keeps_retirement_without_visible_representation(self) -> None:
        rows = [group("old", "2026-07-01T00:00:00Z", "已经离开近场")]
        checkpoint = build_thread_continuity_checkpoint_v2(
            previous_state=None,
            source_groups=rows,
            retired_source_group_ids=["old"],
            bridge_source_group_ids=[],
            bridge_text="",
            bridge_policy={
                "reference_at": "2026-08-16T16:00:00Z",
                "recent_horizon_hours": 72,
                "source_token_limit": 24000,
                "output_token_limit": 2048,
            },
        )

        self.assertEqual(thread_continuity_retirement_source_group_ids(checkpoint), ["old"])
        self.assertEqual(
            thread_continuity_bridge_projection(checkpoint),
            {
                "status": "empty",
                "relation": "no_visible_representation",
                "body": "",
                "body_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "represented_source_group_ids": [],
                "source_group_fingerprints": [],
                "source_slice_fingerprint": "",
                "reference_at": "2026-08-16T16:00:00+00:00",
                "recent_horizon_hours": 72,
                "source_token_limit": 24000,
                "output_token_limit": 2048,
            },
        )
