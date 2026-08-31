from __future__ import annotations

import copy
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_adapter_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")
hermes_adapter = importlib.import_module(f"{PACKAGE}.hermes_adapter")
HermesSessionAdapter = hermes_adapter.HermesSessionAdapter
ContinuityMetadataStore = hermes_adapter.ContinuityMetadataStore
build_thread_continuity_checkpoint_v2 = (
    context_compactor.build_thread_continuity_checkpoint_v2
)


def row(
    row_id: int,
    role: str,
    content: object,
    timestamp: float,
    *,
    active: int = 1,
    compacted: int = 0,
    platform_message_id: str | None = None,
    tool_call_id: str | None = None,
    tool_calls: object = None,
    tool_name: str | None = None,
    finish_reason: str | None = None,
    api_content: str | None = None,
    display_kind: str | None = None,
    display_metadata: dict | None = None,
) -> dict:
    return {
        "id": row_id,
        "session_id": "session-1",
        "role": role,
        "content": content,
        "tool_call_id": tool_call_id,
        "tool_calls": tool_calls,
        "tool_name": tool_name,
        "effect_disposition": None,
        "timestamp": timestamp,
        "token_count": None,
        "finish_reason": finish_reason,
        "reasoning": None,
        "reasoning_content": None,
        "reasoning_details": None,
        "codex_reasoning_items": None,
        "codex_message_items": None,
        "platform_message_id": platform_message_id,
        "observed": 0,
        "active": active,
        "compacted": compacted,
        "api_content": api_content,
        "display_kind": display_kind,
        "display_metadata": display_metadata,
    }


def hermes_key(message: dict) -> tuple:
    def frozen(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    return (
        message["role"],
        frozen(message["content"]),
        frozen(message["timestamp"]),
        frozen(message["tool_call_id"]),
        frozen(message["tool_calls"]),
        frozen(message["tool_name"]),
    )


class FakeSessionDB:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = copy.deepcopy(rows)
        self.calls: list[dict] = []

    def get_messages(
        self,
        session_id: str,
        include_inactive: bool = False,
        include_compacted: bool = False,
    ) -> list[dict]:
        self.calls.append(
            {
                "session_id": session_id,
                "include_inactive": include_inactive,
                "include_compacted": include_compacted,
            }
        )
        if include_inactive:
            return copy.deepcopy(self.rows)
        if include_compacted:
            relevant = [
                message
                for message in self.rows
                if message["active"] == 1 or message["compacted"] == 1
            ]
            winners: dict[tuple, dict] = {}
            for message in relevant:
                key = hermes_key(message)
                current = winners.get(key)
                if current is None or (message["active"], message["id"]) > (
                    current["active"],
                    current["id"],
                ):
                    winners[key] = message
            return copy.deepcopy(sorted(winners.values(), key=lambda message: message["id"]))
        return copy.deepcopy([message for message in self.rows if message["active"] == 1])


def dialogue_rows(start_id: int, timestamp: float, text: str) -> list[dict]:
    return [
        row(start_id, "user", text, timestamp, platform_message_id=f"p-{start_id}"),
        row(
            start_id + 1,
            "assistant",
            f"答：{text}",
            timestamp + 1,
            platform_message_id=f"p-{start_id + 1}",
        ),
    ]


def checkpoint(source: dict, previous: dict | None = None) -> dict:
    groups = source["groups"]
    return build_thread_continuity_checkpoint_v2(
        previous_state=previous,
        source_groups=groups,
        retired_source_group_ids=[groups[0]["source_prefix_id"]],
        bridge_source_group_ids=[],
        bridge_text="",
        bridge_policy={
            "reference_at": groups[-1]["effective_event_at"],
            "recent_horizon_hours": 72,
            "source_token_limit": 24_000,
            "output_token_limit": 2_048,
        },
    )


class HermesSourceProjectionTests(unittest.TestCase):
    def test_same_text_with_distinct_timestamps_remains_distinct(self) -> None:
        rows = dialogue_rows(1, 100.0, "same") + dialogue_rows(3, 200.0, "same")
        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 2)
        self.assertNotEqual(
            source["groups"][0]["source_prefix_id"],
            source["groups"][1]["source_prefix_id"],
        )

    def test_normal_compaction_clones_resolve_to_one_active_message(self) -> None:
        original_user, original_assistant = dialogue_rows(1, 100.0, "clone")
        baseline = HermesSessionAdapter(
            FakeSessionDB([original_user, original_assistant])
        ).read_source("session-1")
        original_user.update(active=0, compacted=1)
        original_assistant.update(active=0, compacted=1)
        active_user = {**original_user, "id": 3, "active": 1, "compacted": 0}
        active_assistant = {**original_assistant, "id": 4, "active": 1, "compacted": 0}
        source = HermesSessionAdapter(
            FakeSessionDB([original_user, original_assistant, active_user, active_assistant])
        ).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertEqual(source["groups"], baseline["groups"])
        self.assertEqual(source["source_snapshot"], baseline["source_snapshot"])
        self.assertEqual(source["stats"]["compacted_prefix_group_ids"], [])

    def test_compaction_clones_use_original_logical_order_not_winner_ids(self) -> None:
        head = dialogue_rows(1, 100.0, "head")
        middle = dialogue_rows(3, 200.0, "middle")
        tail = dialogue_rows(5, 300.0, "tail")
        originals = head + middle + tail
        for message in originals:
            message.update(active=0, compacted=1)
        active_head = [
            {**message, "id": 7 + index, "active": 1, "compacted": 0}
            for index, message in enumerate(head)
        ]
        active_tail = [
            {**message, "id": 9 + index, "active": 1, "compacted": 0}
            for index, message in enumerate(tail)
        ]

        source = HermesSessionAdapter(
            FakeSessionDB([*originals, *active_head, *active_tail])
        ).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(
            [group["messages"][0]["content"] for group in source["groups"]],
            ["head", "middle", "tail"],
        )

    def test_multiple_compacted_generations_without_active_clone_are_valid(self) -> None:
        originals = dialogue_rows(1, 100.0, "retired clone")
        for message in originals:
            message.update(active=0, compacted=1)
        later_generation = [
            {**message, "id": 3 + index}
            for index, message in enumerate(originals)
        ]

        source = HermesSessionAdapter(
            FakeSessionDB([*originals, *later_generation])
        ).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertEqual(
            source["stats"]["compacted_prefix_group_ids"],
            [source["groups"][0]["source_prefix_id"]],
        )

    def test_platform_or_sidecar_collision_fails_closed(self) -> None:
        compacted = row(
            1,
            "user",
            "same",
            100.0,
            active=0,
            compacted=1,
            platform_message_id="platform-old",
            api_content="old-sidecar",
        )
        active = {
            **compacted,
            "id": 2,
            "active": 1,
            "compacted": 0,
            "platform_message_id": "platform-new",
            "api_content": "new-sidecar",
        }
        source = HermesSessionAdapter(FakeSessionDB([compacted, active])).read_source(
            "session-1"
        )

        self.assertEqual(source["status"], "ambiguous")
        self.assertEqual(source["error"], "canonical_clone_sidecar_collision")

    def test_api_content_never_becomes_continuity_material(self) -> None:
        sentinel = "PRIVATE_API_INJECTION_SENTINEL"
        rows = dialogue_rows(1, 100.0, "clean user")
        rows[0]["api_content"] = f"clean user\n{sentinel}"
        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(source["groups"][0]["messages"][0]["content"], "clean user")
        self.assertNotIn(sentinel, repr(source))

    def test_undo_rows_are_excluded_from_source_and_audit(self) -> None:
        undone = dialogue_rows(1, 50.0, "undone")
        for message in undone:
            message.update(active=0, compacted=0)
        live = dialogue_rows(3, 100.0, "live")
        source = HermesSessionAdapter(FakeSessionDB(undone + live)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertNotIn("undone", repr(source))

    def test_incomplete_tail_user_stays_out_of_durable_prefix(self) -> None:
        rows = dialogue_rows(1, 100.0, "complete")
        rows.append(row(3, "user", "current", 200.0))
        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertTrue(source["stats"]["tail_user_incomplete"])
        self.assertNotIn("current", repr(source["groups"]))
        self.assertNotIn("current_ephemeral", source)

    def test_tool_loop_keeps_only_user_and_final_visible_assistant(self) -> None:
        rows = [
            row(1, "user", "查一下", 100.0),
            row(
                2,
                "assistant",
                "",
                101.0,
                tool_calls=[{"id": "call-1", "type": "function"}],
                finish_reason="tool_calls",
            ),
            row(3, "tool", "tool private output", 102.0, tool_call_id="call-1"),
            row(4, "assistant", "最终可见回答", 103.0, finish_reason="stop"),
        ]
        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        messages = source["groups"][0]["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[-1]["content"], "最终可见回答")
        self.assertNotIn("tool private output", repr(source))

    def test_verification_candidate_is_not_the_final_assistant(self) -> None:
        rows = [
            row(1, "user", "实现并验证", 100.0),
            row(
                2,
                "assistant",
                "尚未验证的候选回答",
                101.0,
                finish_reason="verification_required",
            ),
            row(3, "assistant", "验证完成后的最终回答", 102.0, finish_reason="stop"),
        ]

        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertEqual(
            source["groups"][0]["messages"][-1]["content"],
            "验证完成后的最终回答",
        )
        self.assertNotIn("尚未验证的候选回答", repr(source["groups"]))

    def test_incomplete_only_assistant_leaves_user_out_of_durable_prefix(self) -> None:
        rows = [
            *dialogue_rows(1, 100.0, "complete"),
            row(3, "user", "still running", 200.0),
            row(4, "assistant", "interim", 201.0, finish_reason="incomplete"),
        ]

        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertTrue(source["stats"]["tail_user_incomplete"])
        self.assertNotIn("still running", repr(source["groups"]))
        self.assertNotIn("interim", repr(source["groups"]))

    def test_synthetic_summary_is_excluded_and_unverified_proactive_fails_closed(self) -> None:
        summary = row(
            1,
            "assistant",
            "[CONTEXT SUMMARY]: synthetic handoff",
            50.0,
            active=0,
            compacted=1,
        )
        live = dialogue_rows(2, 100.0, "live")
        source = HermesSessionAdapter(FakeSessionDB([summary, *live])).read_source(
            "session-1"
        )
        self.assertEqual(source["status"], "ready")
        self.assertNotIn("synthetic handoff", repr(source))

        proactive = HermesSessionAdapter(
            FakeSessionDB([row(1, "assistant", "orphan assistant", 100.0)])
        ).read_source("session-1")
        self.assertEqual(proactive["status"], "ambiguous")
        self.assertEqual(proactive["error"], "proactive_event_unverified")

    def test_host_session_metadata_is_excluded_from_canonical_dialogue(self) -> None:
        metadata = row(
            1,
            "session_meta",
            '{"host_control":"not dialogue"}',
            50.0,
            active=0,
            compacted=1,
        )
        source = HermesSessionAdapter(
            FakeSessionDB([metadata, *dialogue_rows(2, 100.0, "live")])
        ).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertNotIn("host_control", repr(source))

    def test_nonvisible_provider_scaffolds_never_become_dialogue(self) -> None:
        rows = [
            row(1, "user", "visible question", 100.0),
            row(
                2,
                "assistant",
                "tool request",
                101.0,
                tool_calls=[{"id": "call-1", "type": "function"}],
                finish_reason="tool_calls",
            ),
            row(
                3,
                "user",
                "",
                102.0,
                api_content="provider-only continuation",
            ),
            row(4, "assistant", "visible answer", 103.0, finish_reason="stop"),
            row(
                5,
                "assistant",
                "",
                104.0,
                api_content="neutral interruption placeholder",
                display_kind="hidden",
            ),
        ]
        source = HermesSessionAdapter(FakeSessionDB(rows)).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(len(source["groups"]), 1)
        self.assertNotIn("provider-only continuation", repr(source))
        self.assertNotIn("neutral interruption placeholder", repr(source))

        inbound_empty = HermesSessionAdapter(
            FakeSessionDB(
                [
                    row(
                        1,
                        "user",
                        "",
                        100.0,
                        api_content="provider-only continuation",
                        platform_message_id="inbound-1",
                    ),
                    row(2, "assistant", "answer", 101.0),
                ]
            )
        ).read_source("session-1")
        self.assertEqual(inbound_empty["status"], "ambiguous")
        self.assertEqual(inbound_empty["error"], "source_visible_content_invalid")

    def test_host_role_runs_preserve_visible_text_as_closed_groups(self) -> None:
        source = HermesSessionAdapter(
            FakeSessionDB(
                [
                    row(1, "user", "first user message", 100.0),
                    row(2, "user", "second user message", 101.0),
                    row(3, "assistant", "first answer", 102.0, finish_reason="stop"),
                    row(
                        4,
                        "assistant",
                        "follow-up answer",
                        103.0,
                        finish_reason="stop",
                    ),
                ]
            )
        ).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(
            [group["group_kind"] for group in source["groups"]],
            ["dialogue_turn", "proactive_assistant_event"],
        )
        self.assertEqual(
            source["groups"][0]["messages"][0]["content"],
            "first user message\n\nsecond user message",
        )
        self.assertEqual(
            source["groups"][1]["messages"][0]["content"],
            "follow-up answer",
        )

        unmergeable = HermesSessionAdapter(
            FakeSessionDB(
                [
                    row(
                        1,
                        "user",
                        [
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.invalid/a.png"},
                            }
                        ],
                        100.0,
                    ),
                    row(2, "user", "second user message", 101.0),
                    row(3, "assistant", "answer", 102.0),
                ]
            )
        ).read_source("session-1")
        self.assertEqual(unmergeable["status"], "ambiguous")
        self.assertEqual(
            unmergeable["error"], "consecutive_user_content_unmergeable"
        )

    def test_compacted_prefix_is_contiguous_whole_groups_only(self) -> None:
        compacted = dialogue_rows(1, 100.0, "old")
        for message in compacted:
            message.update(active=0, compacted=1)
        active = dialogue_rows(3, 200.0, "new")
        later_compacted = dialogue_rows(5, 300.0, "later-old")
        for message in later_compacted:
            message.update(active=0, compacted=1)
        source = HermesSessionAdapter(
            FakeSessionDB(compacted + active + later_compacted)
        ).read_source("session-1")

        self.assertEqual(source["status"], "ready")
        self.assertEqual(
            source["stats"]["compacted_prefix_group_ids"],
            [source["groups"][0]["source_prefix_id"]],
        )

    def test_unexplained_canonical_view_or_multiple_active_rows_is_ambiguous(self) -> None:
        class MissingCanonical(FakeSessionDB):
            def get_messages(self, session_id: str, include_inactive: bool = False,
                             include_compacted: bool = False) -> list[dict]:
                rows = super().get_messages(session_id, include_inactive, include_compacted)
                return [] if include_compacted else rows

        missing = HermesSessionAdapter(
            MissingCanonical(dialogue_rows(1, 100.0, "live"))
        ).read_source("session-1")
        self.assertEqual(missing["status"], "ambiguous")
        self.assertEqual(missing["error"], "canonical_view_unexplained")

        duplicate = row(1, "user", "same", 100.0)
        two_active = HermesSessionAdapter(
            FakeSessionDB([duplicate, {**duplicate, "id": 2}])
        ).read_source("session-1")
        self.assertEqual(two_active["status"], "ambiguous")
        self.assertEqual(two_active["error"], "canonical_active_collision")

    def test_invalid_or_colliding_origin_ids_fail_closed(self) -> None:
        invalid = dialogue_rows(1, 100.0, "invalid id")
        invalid[0]["id"] = "1"
        invalid[1]["id"] = "2"
        invalid_source = HermesSessionAdapter(FakeSessionDB(invalid)).read_source(
            "session-1"
        )

        colliding = dialogue_rows(1, 100.0, "colliding id")
        colliding[1]["id"] = colliding[0]["id"]
        colliding_source = HermesSessionAdapter(FakeSessionDB(colliding)).read_source(
            "session-1"
        )

        self.assertEqual(invalid_source["status"], "ambiguous")
        self.assertEqual(invalid_source["error"], "source_row_id_invalid")
        self.assertEqual(colliding_source["status"], "ambiguous")
        self.assertEqual(colliding_source["error"], "source_origin_collision")


class FakeBoundedWindowDB:
    def __init__(self, rows_by_session: dict[str, list[dict]]) -> None:
        self.rows_by_session = copy.deepcopy(rows_by_session)
        self.window_calls: list[dict] = []

    def get_messages(self, *args, **kwargs):
        raise AssertionError("recent source must not call full get_messages")

    def get_messages_time_window(
        self,
        session_id: str,
        *,
        start_timestamp: float,
        end_timestamp: float,
        include_inactive: bool = False,
        include_compacted: bool = False,
        max_physical_rows: int,
    ) -> dict:
        self.window_calls.append(
            {
                "session_id": session_id,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "include_inactive": include_inactive,
                "include_compacted": include_compacted,
                "max_physical_rows": max_physical_rows,
            }
        )
        rows = [
            item
            for item in self.rows_by_session.get(session_id, [])
            if start_timestamp <= float(item["timestamp"]) <= end_timestamp
            and (
                include_inactive
                or (
                    include_compacted
                    and (item["active"] == 1 or item["compacted"] == 1)
                )
                or (not include_compacted and item["active"] == 1)
            )
        ]
        rows.sort(key=lambda item: item["id"])
        physical_count = min(len(rows), max_physical_rows + 1)
        if len(rows) > max_physical_rows:
            return {
                "messages": [],
                "scan_complete": False,
                "overflow": True,
                "physical_row_count": physical_count,
                "max_physical_rows": max_physical_rows,
            }
        if include_compacted and not include_inactive:
            winners: dict[tuple, dict] = {}
            for item in rows:
                key = hermes_key(item)
                current = winners.get(key)
                if current is None or (item["active"], item["id"]) > (
                    current["active"],
                    current["id"],
                ):
                    winners[key] = item
            rows = sorted(winners.values(), key=lambda item: item["id"])
        return {
            "messages": copy.deepcopy(rows),
            "scan_complete": True,
            "overflow": False,
            "physical_row_count": physical_count,
            "max_physical_rows": max_physical_rows,
        }


class RecentLineageSourceTests(unittest.TestCase):
    def test_ancestor_to_tip_union_collapses_exact_compaction_clones(self) -> None:
        root_rows = dialogue_rows(1, 100.0, "ancestor")
        for item in root_rows:
            item.update(session_id="root", active=0, compacted=1)
        cloned = [
            {
                **item,
                "id": item["id"] + 10,
                "session_id": "tip",
                "active": 1,
                "compacted": 0,
            }
            for item in root_rows
        ]
        tip_new = dialogue_rows(20, 200.0, "tip new")
        for item in tip_new:
            item["session_id"] = "tip"
        session_db = FakeBoundedWindowDB(
            {"root": root_rows, "tip": [*cloned, *tip_new]}
        )

        source = HermesSessionAdapter(session_db).read_recent_lineage_source(
            ["root", "tip"],
            start_timestamp=90.0,
            end_timestamp=300.0,
            max_physical_rows=16,
            max_groups=8,
        )

        self.assertEqual(source["status"], "ready")
        self.assertEqual(
            [item["messages"][0]["content"] for item in source["groups"]],
            ["ancestor", "tip new"],
        )
        self.assertEqual(len(source["groups"]), 2)
        self.assertEqual(len(session_db.window_calls), 4)
        self.assertEqual(
            [call["max_physical_rows"] for call in session_db.window_calls],
            [16, 16, 14, 14],
        )

    def test_lineage_uses_one_decrementing_physical_row_budget(self) -> None:
        rows_by_session = {
            "root": dialogue_rows(1, 100.0, "root"),
            "middle": dialogue_rows(3, 200.0, "middle"),
            "tip": dialogue_rows(5, 300.0, "tip"),
        }
        for session_id, rows in rows_by_session.items():
            for item in rows:
                item["session_id"] = session_id
        session_db = FakeBoundedWindowDB(rows_by_session)

        source = HermesSessionAdapter(session_db).read_recent_lineage_source(
            ["root", "middle", "tip"],
            start_timestamp=90.0,
            end_timestamp=400.0,
            max_physical_rows=5,
            max_groups=8,
        )

        self.assertEqual(source["status"], "overflow")
        self.assertEqual(source["groups"], [])
        self.assertEqual(source["error"], "source_physical_row_limit_exceeded")
        self.assertEqual(
            [call["max_physical_rows"] for call in session_db.window_calls],
            [5, 5, 3, 3, 1],
        )

    def test_cross_lineage_sidecar_collision_fails_closed(self) -> None:
        root_rows = dialogue_rows(1, 100.0, "clone")
        for item in root_rows:
            item.update(session_id="root", active=0, compacted=1)
        tip_rows = [
            {
                **item,
                "id": item["id"] + 10,
                "session_id": "tip",
                "active": 1,
                "compacted": 0,
            }
            for item in root_rows
        ]
        tip_rows[0]["platform_message_id"] = "different-sidecar"
        session_db = FakeBoundedWindowDB({"root": root_rows, "tip": tip_rows})

        source = HermesSessionAdapter(session_db).read_recent_lineage_source(
            ["root", "tip"],
            start_timestamp=90.0,
            end_timestamp=300.0,
            max_physical_rows=16,
            max_groups=8,
        )

        self.assertEqual(source["status"], "ambiguous")
        self.assertEqual(source["error"], "lineage_clone_sidecar_collision")

    def test_physical_row_overflow_returns_no_partial_source(self) -> None:
        rows = [
            row(index + 1, "user", f"row-{index}", 100.0 + index)
            for index in range(20)
        ]
        session_db = FakeBoundedWindowDB({"session-1": rows})

        source = HermesSessionAdapter(session_db).read_recent_lineage_source(
            ["session-1"],
            start_timestamp=90.0,
            end_timestamp=300.0,
            max_physical_rows=8,
            max_groups=8,
        )

        self.assertEqual(source["status"], "overflow")
        self.assertEqual(source["groups"], [])
        self.assertEqual(source["error"], "source_physical_row_limit_exceeded")
        self.assertEqual(len(session_db.window_calls), 1)
        self.assertEqual(session_db.window_calls[0]["max_physical_rows"], 8)


class HermesSessionDBIntegrationTests(unittest.TestCase):
    def test_real_archive_and_compact_keeps_logical_turn_order(self) -> None:
        source_root = os.environ.get("HERMES_SOURCE_ROOT", "").strip()
        if not source_root:
            self.skipTest("set HERMES_SOURCE_ROOT to run against a Hermes checkout")
        sys.path.insert(0, source_root)
        try:
            from hermes_state import SessionDB

            with tempfile.TemporaryDirectory() as temp_dir:
                session_db = SessionDB(Path(temp_dir) / "state.db")
                try:
                    session_db.create_session("session-1", source="continuity-test")
                    for role, content, timestamp in (
                        ("user", "head", 100.0),
                        ("assistant", "答：head", 101.0),
                        ("user", "middle", 200.0),
                        ("assistant", "答：middle", 201.0),
                        ("user", "tail", 300.0),
                        ("assistant", "答：tail", 301.0),
                    ):
                        session_db.append_message(
                            "session-1",
                            role=role,
                            content=content,
                            timestamp=timestamp,
                        )
                    active = session_db.get_messages("session-1")
                    session_db.archive_and_compact(
                        "session-1",
                        [
                            active[0],
                            active[1],
                            {
                                "role": "assistant",
                                "content": (
                                    "[CONTEXT COMPACTION — REFERENCE ONLY] "
                                    "middle summary"
                                ),
                                "timestamp": 250.0,
                            },
                            active[4],
                            active[5],
                        ],
                    )

                    source = HermesSessionAdapter(session_db).read_source("session-1")

                    self.assertEqual(source["status"], "ready")
                    self.assertEqual(
                        [
                            group["messages"][0]["content"]
                            for group in source["groups"]
                        ],
                        ["head", "middle", "tail"],
                    )
                finally:
                    session_db.close()
        finally:
            sys.path.remove(source_root)

    def test_real_candidate_compression_lineage_is_unioned_exactly_once(self) -> None:
        source_root = os.environ.get("HERMES_SOURCE_ROOT", "").strip()
        if not source_root:
            self.skipTest("set HERMES_SOURCE_ROOT to run against a Hermes checkout")
        sys.path.insert(0, source_root)
        try:
            from hermes_state import SessionDB

            with tempfile.TemporaryDirectory() as temp_dir:
                session_db = SessionDB(Path(temp_dir) / "state.db")
                try:
                    base = time.time() - 60
                    session_db.create_session("candidate-root", source="qqbot")
                    for role, content, timestamp in (
                        ("user", "root turn", base),
                        ("assistant", "root answer", base + 1),
                    ):
                        session_db.append_message(
                            "candidate-root",
                            role=role,
                            content=content,
                            timestamp=timestamp,
                        )
                    session_db.end_session("candidate-root", "compression")
                    session_db.create_session(
                        "candidate-tip",
                        source="qqbot",
                        parent_session_id="candidate-root",
                    )
                    for role, content, timestamp in (
                        ("user", "root turn", base),
                        ("assistant", "root answer", base + 1),
                        ("user", "tip turn", base + 20),
                        ("assistant", "tip answer", base + 21),
                    ):
                        session_db.append_message(
                            "candidate-tip",
                            role=role,
                            content=content,
                            timestamp=timestamp,
                        )

                    lineage = session_db.get_compression_lineage("candidate-tip")
                    source = HermesSessionAdapter(
                        session_db
                    ).read_recent_lineage_source(
                        lineage,
                        start_timestamp=base - 1,
                        end_timestamp=base + 30,
                        max_physical_rows=32,
                        max_groups=8,
                    )

                    self.assertEqual(lineage, ["candidate-root", "candidate-tip"])
                    self.assertEqual(source["status"], "ready")
                    self.assertEqual(
                        [
                            item["messages"][0]["content"]
                            for item in source["groups"]
                        ],
                        ["root turn", "tip turn"],
                    )
                finally:
                    session_db.close()
        finally:
            sys.path.remove(source_root)

    def test_real_long_transcript_hits_public_bounded_window_cap(self) -> None:
        source_root = os.environ.get("HERMES_SOURCE_ROOT", "").strip()
        if not source_root:
            self.skipTest("set HERMES_SOURCE_ROOT to run against a Hermes checkout")
        sys.path.insert(0, source_root)
        try:
            from hermes_state import SessionDB

            with tempfile.TemporaryDirectory() as temp_dir:
                session_db = SessionDB(Path(temp_dir) / "state.db")
                try:
                    base = time.time() - 120
                    session_db.create_session("long-session", source="qqbot")
                    session_db.append_messages_batch(
                        "long-session",
                        [
                            {
                                "role": "user" if index % 2 == 0 else "assistant",
                                "content": f"row-{index}",
                                "timestamp": base + index,
                            }
                            for index in range(40)
                        ],
                    )

                    bounded = session_db.get_messages_time_window(
                        "long-session",
                        start_timestamp=base - 1,
                        end_timestamp=base + 60,
                        include_compacted=True,
                        max_physical_rows=8,
                    )
                    source = HermesSessionAdapter(
                        session_db
                    ).read_recent_lineage_source(
                        ["long-session"],
                        start_timestamp=base - 1,
                        end_timestamp=base + 60,
                        max_physical_rows=8,
                        max_groups=8,
                    )

                    self.assertTrue(bounded["overflow"])
                    self.assertFalse(bounded["scan_complete"])
                    self.assertEqual(bounded["messages"], [])
                    self.assertEqual(bounded["physical_row_count"], 9)
                    self.assertEqual(source["status"], "overflow")
                    self.assertEqual(source["groups"], [])
                    self.assertEqual(
                        source["error"], "source_physical_row_limit_exceeded"
                    )
                finally:
                    session_db.close()
        finally:
            sys.path.remove(source_root)


class ContinuityMetadataStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "continuity.sqlite3"
        self.store = ContinuityMetadataStore(self.db_path)
        self.source = HermesSessionAdapter(
            FakeSessionDB(dialogue_rows(1, 100.0, "first"))
        ).read_source("session-1")
        self.candidate = checkpoint(self.source)

    def receipts(self, session_id: str) -> list[dict]:
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT receipt_id, session_id, receipt_kind, status,
                       source_ids_json, hashes_json, counts_json, recorded_at
                FROM continuity_receipts
                WHERE session_id = ? ORDER BY recorded_at, receipt_id
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                "receipt_id": row[0],
                "session_id": row[1],
                "kind": row[2],
                "status": row[3],
                "source_ids": json.loads(row[4]),
                "hashes": json.loads(row[5]),
                "counts": json.loads(row[6]),
                "recorded_at": row[7],
            }
            for row in rows
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_metadata_store_rejects_another_plugin_owner_before_creating_tables(self):
        foreign_path = Path(self.temp.name) / "foreign.sqlite3"
        with sqlite3.connect(foreign_path) as connection:
            connection.execute(
                """
                CREATE TABLE hermes_plugin_store_owner (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    owner_id TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                "INSERT INTO hermes_plugin_store_owner VALUES (1, ?)",
                ("hermes-global-hot.v1",),
            )

        with self.assertRaisesRegex(ValueError, "owner_conflict"):
            ContinuityMetadataStore(foreign_path)

        with sqlite3.connect(foreign_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertNotIn("continuity_checkpoints", tables)
        self.assertNotIn("continuity_receipts", tables)

    def test_metadata_store_rejects_unclaimed_table_or_view_before_claiming(self):
        for kind, statement in (
            ("table", "CREATE TABLE orphan (value TEXT)"),
            ("view", "CREATE VIEW orphan AS SELECT 1 AS value"),
        ):
            with self.subTest(kind=kind):
                path = Path(self.temp.name) / f"unclaimed-{kind}.sqlite3"
                with sqlite3.connect(path) as connection:
                    connection.execute(statement)

                with self.assertRaisesRegex(ValueError, "unclaimed"):
                    ContinuityMetadataStore(path)

                with sqlite3.connect(path) as connection:
                    objects = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master"
                        )
                    }
                self.assertNotIn("hermes_plugin_store_owner", objects)
                self.assertNotIn("continuity_checkpoints", objects)
                self.assertNotIn("continuity_receipts", objects)

    def test_metadata_store_rejects_claimed_hermes_canonical_schema(self):
        path = Path(self.temp.name) / "canonical.sqlite3"
        ContinuityMetadataStore(path)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE messages (content TEXT)")

        with self.assertRaisesRegex(ValueError, "canonical_conflict"):
            ContinuityMetadataStore(path)

    def test_status_summary_reports_checkpoint_and_delivery_without_body(self):
        candidate = build_thread_continuity_checkpoint_v2(
            previous_state=None,
            source_groups=self.source["groups"],
            retired_source_group_ids=self.source["source_prefix_ids"],
            bridge_source_group_ids=self.source["source_prefix_ids"],
            bridge_text="private generated bridge",
            bridge_policy={
                "reference_at": self.source["groups"][-1]["effective_event_at"],
                "recent_horizon_hours": 72,
                "source_token_limit": 24_000,
                "output_token_limit": 2_048,
            },
        )
        settled = self.store.settle_checkpoint_delivery(
            "session-1",
            source_reread=lambda _session_id: copy.deepcopy(self.source),
            **{
                **self.settlement_kwargs("receipt-status"),
                "checkpoint_candidate": candidate,
            },
        )

        status = self.store.status_summary("session-1")

        self.assertTrue(settled["ok"])
        self.assertEqual(status["checkpoint"]["revision"], 1)
        self.assertEqual(status["checkpoint"]["recent_bridge_status"], "ready")
        self.assertEqual(
            status["last_delivery"]["status"],
            "delivered_checkpoint_applied",
        )
        self.assertFalse(status["body_included"])
        self.assertNotIn("private generated bridge", repr(status))

    def settlement_kwargs(self, receipt_id: str) -> dict:
        return {
            "expected_revision": 0,
            "expected_source_snapshot": self.source["source_snapshot"],
            "checkpoint_candidate": self.candidate,
            "receipt_id": receipt_id,
            "source_ids": self.source["source_prefix_ids"],
            "hashes": {"source_snapshot": self.source["source_snapshot"]},
            "counts": {"represented_source_group_count": 1},
        }

    def test_snapshot_and_revision_settlement_survive_restart(self) -> None:
        applied = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("restart-applied"),
            source_reread=lambda _session_id: self.source,
        )
        conflict = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("restart-conflict"),
            source_reread=lambda _session_id: self.source,
        )
        restarted = ContinuityMetadataStore(self.db_path)
        readback = restarted.read_continuity("session-1", self.source)

        self.assertEqual(applied["status"], "applied")
        self.assertEqual(conflict["error"], "thread_continuity_revision_conflict")
        self.assertEqual(readback["status"], "ready")
        self.assertEqual(readback["state"]["checkpoint"], self.candidate)

    def test_tail_growth_is_accepted_without_expanding_checkpoint_source(self) -> None:
        grown = HermesSessionAdapter(
            FakeSessionDB(
                dialogue_rows(1, 100.0, "first")
                + dialogue_rows(3, 200.0, "tail")
            )
        ).read_source("session-1")
        applied = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("tail-growth"),
            source_reread=lambda _session_id: grown,
        )

        self.assertTrue(applied["ok"])
        readback = self.store.read_continuity("session-1", grown)
        self.assertEqual(readback["status"], "ready")
        self.assertEqual(
            readback["state"]["checkpoint"]["source_group_ids"],
            self.candidate["source_group_ids"],
        )
        self.assertEqual(len(readback["state"]["source_prefix_ids"]), 1)
        self.assertTrue(readback["state"]["source_advanced"])

    def test_undo_of_uncompiled_grown_tail_keeps_checkpoint_valid(self) -> None:
        grown = HermesSessionAdapter(
            FakeSessionDB(
                dialogue_rows(1, 100.0, "first")
                + dialogue_rows(3, 200.0, "uncompiled tail")
            )
        ).read_source("session-1")
        applied = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("tail-undo"),
            source_reread=lambda _session_id: grown,
        )

        readback = self.store.read_continuity("session-1", self.source)

        self.assertTrue(applied["ok"])
        self.assertEqual(
            applied["source_snapshot"], self.source["source_snapshot"]
        )
        self.assertEqual(readback["status"], "ready")
        self.assertFalse(readback["state"]["source_advanced"])

    def test_prefix_rewrite_or_ambiguous_reread_rejects_publish(self) -> None:
        rewritten = HermesSessionAdapter(
            FakeSessionDB(dialogue_rows(1, 100.0, "rewritten"))
        ).read_source("session-1")
        rewrite = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("rewrite-conflict"),
            source_reread=lambda _session_id: rewritten,
        )
        ambiguous = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("ambiguous-conflict"),
            source_reread=lambda _session_id: {"status": "ambiguous"},
        )

        self.assertEqual(rewrite["error"], "thread_continuity_source_conflict")
        self.assertEqual(ambiguous["error"], "thread_continuity_source_ambiguous")
        self.assertEqual(
            self.store.read_continuity("session-1", self.source)["status"],
            "absent",
        )

    def test_concurrent_settlement_has_one_checkpoint_winner(self) -> None:
        barrier = threading.Barrier(2)

        def publish(index: int) -> dict:
            barrier.wait()
            return self.store.settle_checkpoint_delivery(
                "session-1",
                **self.settlement_kwargs(f"concurrent-{index}"),
                source_reread=lambda _session_id: self.source,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(publish, range(2)))

        self.assertEqual(sum(result.get("ok") is True for result in results), 1)
        self.assertEqual(
            sum(
                result.get("error") == "thread_continuity_revision_conflict"
                for result in results
            ),
            1,
        )

    def test_atomic_settlement_applies_checkpoint_and_receipt_via_adapter(self) -> None:
        adapter = HermesSessionAdapter(
            FakeSessionDB(dialogue_rows(1, 100.0, "first")),
            metadata_store=self.store,
        )

        result = adapter.settle_checkpoint_delivery(
            "session-1", **self.settlement_kwargs("settlement-applied")
        )

        readback = self.store.read_continuity("session-1", self.source)
        receipts = self.receipts("session-1")
        self.assertEqual(result["status"], "applied")
        self.assertTrue(result["receipt_recorded"])
        self.assertEqual(readback["state"]["checkpoint"], self.candidate)
        self.assertEqual(
            [receipt["status"] for receipt in receipts],
            ["delivered_checkpoint_applied"],
        )

    def test_atomic_settlement_records_unchanged_without_source_reread(self) -> None:
        values = self.settlement_kwargs("settlement-unchanged")
        values["checkpoint_candidate"] = None

        result = self.store.settle_checkpoint_delivery(
            "session-1",
            **values,
            source_reread=lambda _session_id: self.fail("unexpected source reread"),
        )

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(
            self.store.read_continuity("session-1", self.source)["status"],
            "absent",
        )
        self.assertEqual(
            self.receipts("session-1")[0]["status"],
            "delivered_checkpoint_unchanged",
        )

    def test_atomic_settlement_records_conflict_without_changing_checkpoint(self) -> None:
        self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("settlement-seed"),
            source_reread=lambda _session_id: self.source,
        )

        result = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("settlement-conflict"),
            source_reread=lambda _session_id: self.source,
        )

        readback = self.store.read_continuity("session-1", self.source)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["error"], "thread_continuity_revision_conflict")
        self.assertEqual(readback["state"]["checkpoint"], self.candidate)
        self.assertEqual(
            self.receipts("session-1")[-1]["status"],
            "delivered_checkpoint_conflict",
        )

    def test_atomic_settlement_receipt_failure_rolls_back_checkpoint(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_settlement_receipt
                BEFORE INSERT ON continuity_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'receipt rejected');
                END
                """
            )

        result = self.store.settle_checkpoint_delivery(
            "session-1",
            **self.settlement_kwargs("settlement-rejected"),
            source_reread=lambda _session_id: self.source,
        )

        self.assertEqual(result["error"], "checkpoint_storage_failed")
        self.assertFalse(result["receipt_recorded"])
        self.assertEqual(
            self.store.read_continuity("session-1", self.source)["status"],
            "absent",
        )
        self.assertEqual(self.receipts("session-1"), [])

    def test_slow_source_reread_does_not_block_unrelated_receipt_writer(self) -> None:
        reread_started = threading.Event()
        release_reread = threading.Event()

        def slow_reread(_session_id: str) -> dict:
            reread_started.set()
            self.assertTrue(release_reread.wait(timeout=2))
            return self.source

        def settle() -> dict:
            return self.store.settle_checkpoint_delivery(
                "session-1",
                **self.settlement_kwargs("settlement-slow"),
                source_reread=slow_reread,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            settlement = executor.submit(settle)
            self.assertTrue(reread_started.wait(timeout=1))
            writer = executor.submit(
                self.store.record_receipt,
                receipt_id="unrelated-writer",
                session_id="other-session",
                kind="delivery",
                status="settled",
            )
            try:
                self.assertEqual(
                    writer.result(timeout=1)["receipt_id"], "unrelated-writer"
                )
            finally:
                release_reread.set()
            self.assertEqual(settlement.result(timeout=2)["status"], "applied")

    def test_concurrent_atomic_settlement_is_idempotent(self) -> None:
        barrier = threading.Barrier(2)

        def settle() -> dict:
            def reread(_session_id: str) -> dict:
                barrier.wait(timeout=2)
                return self.source

            return self.store.settle_checkpoint_delivery(
                "session-1",
                **self.settlement_kwargs("settlement-idempotent"),
                source_reread=reread,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: settle(), range(2)))

        self.assertEqual([result["status"] for result in results], ["applied"] * 2)
        self.assertEqual(
            sorted(result["idempotent"] for result in results), [False, True]
        )
        self.assertEqual(len(self.receipts("session-1")), 1)
        self.assertEqual(
            self.store.read_continuity("session-1", self.source)["state"]["revision"],
            1,
        )

    def test_delivery_and_failure_receipts_are_body_free_and_restart_safe(self) -> None:
        sentinel = "PRIVATE CONVERSATION BODY SENTINEL"
        digest = self.source["source_snapshot"]
        self.store.record_receipt(
            receipt_id="delivery-1",
            session_id="session-1",
            kind="delivery",
            status="settled",
            source_ids=[self.source["source_prefix_ids"][0]],
            hashes={"source": digest},
            counts={"message_count": 2},
            recorded_at="2026-08-30T00:00:00Z",
        )
        self.store.record_receipt(
            receipt_id="failure-1",
            session_id="session-1",
            kind="failure",
            status="compile_timeout",
            hashes={"source": digest},
            counts={"attempt_count": 1},
            recorded_at="2026-08-30T00:01:00Z",
        )
        with self.assertRaises(ValueError):
            self.store.record_receipt(
                receipt_id="bad",
                session_id="session-1",
                kind="failure",
                status=sentinel,
            )

        with sqlite3.connect(self.db_path) as connection:
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'continuity_receipts'"
            ).fetchone()[0]
            stored = repr(
                connection.execute("SELECT * FROM continuity_receipts").fetchall()
            )
        receipts = self.receipts("session-1")

        self.assertNotIn("body", schema.lower())
        self.assertNotIn(sentinel, stored)
        self.assertEqual([receipt["kind"] for receipt in receipts], ["delivery", "failure"])
        self.assertEqual(receipts[0]["counts"], {"message_count": 2})


if __name__ == "__main__":
    unittest.main()
