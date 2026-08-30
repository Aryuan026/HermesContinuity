from __future__ import annotations

import copy
import importlib
import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_canonical_source_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")
hermes_adapter = importlib.import_module(f"{PACKAGE}.hermes_adapter")
ContinuityCanonicalSourceService = (
    hermes_adapter.ContinuityCanonicalSourceService
)

UTC = timezone.utc
REFERENCE = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def message(message_id: str, role: str, content: object) -> dict:
    return {
        "message_id": message_id,
        "role": role,
        "content": copy.deepcopy(content),
        "content_hash": context_compactor._content_hash(content),
    }


def group(
    group_id: str,
    occurred: datetime,
    user_text: str,
    assistant_text: str,
) -> dict:
    return {
        "source_prefix_id": group_id,
        "effective_event_at": iso(occurred),
        "messages": [
            message(f"{group_id}-user", "user", user_text),
            message(f"{group_id}-assistant", "assistant", assistant_text),
        ],
    }


def source_result(
    groups: list[dict],
    *,
    status: str = "ready",
    source_evidence: list[dict[str, str]] | None = None,
) -> dict:
    proof = [
        {
            "group_id": item["source_prefix_id"],
            "messages": [
                (row["message_id"], row["content_hash"])
                for row in item["messages"]
            ],
        }
        for item in groups
    ]
    return {
        "status": status,
        "scan_complete": status == "ready",
        "source_snapshot": hermes_adapter._sha256(proof),
        "groups": copy.deepcopy(groups),
        "_group_source_evidence": copy.deepcopy(
            source_evidence
            if source_evidence is not None
            else [
                {"display_kind": "", "internal_kind": ""}
                for _item in groups
            ]
        ),
    }


def session(
    session_id: str,
    source: str,
    last_active: datetime,
    *,
    lineage_root: str = "",
) -> dict:
    row = {
        "id": session_id,
        "source": source,
        "last_active": iso(last_active),
    }
    if lineage_root:
        row["_lineage_root_id"] = lineage_root
    return row


class FakeWindowDB:
    def __init__(
        self,
        sessions: list[dict],
        *,
        lineages: dict[str, list[str]] | None = None,
    ) -> None:
        self.sessions = copy.deepcopy(sessions)
        self.lineages = copy.deepcopy(lineages or {})
        self.list_calls: list[dict] = []
        self.lineage_calls: list[str] = []

    def get_messages_time_window(self, session_id: str, **kwargs) -> dict:
        raise AssertionError("FakeAdapter owns source projection in these tests")

    def get_compression_lineage(self, session_id: str) -> list[str]:
        self.lineage_calls.append(session_id)
        return copy.deepcopy(self.lineages.get(session_id, [session_id]))

    def list_sessions_rich(self, **kwargs) -> list[dict]:
        self.list_calls.append(copy.deepcopy(kwargs))
        excluded = set(kwargs.get("exclude_sources") or [])
        rows = [
            row for row in self.sessions if str(row.get("source")) not in excluded
        ]
        rows.sort(
            key=lambda row: (
                str(row.get("last_active") or ""),
                str(row.get("id") or ""),
            ),
            reverse=True,
        )
        offset = int(kwargs.get("offset") or 0)
        limit = int(kwargs.get("limit") or 20)
        return copy.deepcopy(rows[offset : offset + limit])


class FakeAdapter:
    def __init__(self, session_db: FakeWindowDB, sources: dict[str, dict]) -> None:
        self.session_db = session_db
        self.sources = copy.deepcopy(sources)
        self.read_calls: list[str] = []
        self.read_lineages: list[list[str]] = []
        self.read_options: list[dict] = []

    def read_recent_lineage_source(self, lineage_session_ids, **kwargs) -> dict:
        lineage = list(lineage_session_ids)
        self.read_lineages.append(lineage)
        self.read_options.append(copy.deepcopy(kwargs))
        self.read_calls.append(lineage[-1])
        return copy.deepcopy(self.sources[lineage[-1]])


def request(**overrides) -> dict:
    value = {
        "schema": "continuity_canonical_window_request.v2",
        "current_session_id": "current-session",
        "reference_at": iso(REFERENCE),
    }
    value.update(overrides)
    return value


class CanonicalSourceServiceTests(unittest.TestCase):
    def service(
        self,
        sessions: list[dict],
        sources: dict[str, dict],
        *,
        lineages: dict[str, list[str]] | None = None,
        additional_human_sources: list[str] | None = None,
    ) -> tuple[ContinuityCanonicalSourceService, FakeAdapter, FakeWindowDB]:
        session_db = FakeWindowDB(sessions, lineages=lineages)
        adapter = FakeAdapter(session_db, sources)
        return (
            ContinuityCanonicalSourceService(
                adapter,
                additional_human_sources=additional_human_sources or [],
            ),
            adapter,
            session_db,
        )

    def test_cross_mouth_and_cron_pairs_return_neutral_closed_schema(self):
        qq_group = group(
            "qq-group", REFERENCE - timedelta(minutes=35), "qq hello", "qq answer"
        )
        cron_group = group(
            "cron-group", REFERENCE - timedelta(minutes=5), "cron tick", "cron done"
        )
        service, adapter, session_db = self.service(
            [
                session("qq-session", "qqbot", REFERENCE - timedelta(minutes=30)),
                session("cron-session", "cron", REFERENCE - timedelta(minutes=4)),
            ],
            {
                "qq-session": source_result([qq_group]),
                "cron-session": source_result([cron_group]),
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "ready")
        self.assertTrue(response["scan_complete"])
        self.assertEqual(
            list(response),
            [
                "schema",
                "status",
                "reason",
                "reference_at",
                "horizon_seconds",
                "source_revision",
                "scan_complete",
                "groups",
                "trace",
            ],
        )
        self.assertEqual(
            [item["group_id"] for item in response["groups"]],
            ["qq-group", "cron-group"],
        )
        self.assertEqual(
            set(response["groups"][0]),
            {
                "source_session_id",
                "source",
                "source_class",
                "source_snapshot",
                "group_id",
                "effective_event_at",
                "messages",
            },
        )
        self.assertEqual(
            [item["source_class"] for item in response["groups"]],
            ["human", "scheduled"],
        )
        self.assertEqual(
            set(response["groups"][0]["messages"][0]),
            {"message_id", "role", "content", "content_hash"},
        )
        self.assertEqual(
            set(response["trace"]),
            {
                "schema",
                "listed_session_count",
                "candidate_session_count",
                "source_session_count",
                "returned_group_count",
                "outside_horizon_session_count",
                "outside_horizon_group_count",
                "current_lineage_excluded_count",
                "policy_excluded_group_count",
                "session_proofs_sha256",
                "group_proofs_sha256",
                "body_included",
            },
        )
        # A consumer can derive collision-free neutral aliases without any
        # private Continuity type: session + group, then session + group + message.
        group_aliases = {
            (item["source_session_id"], item["group_id"])
            for item in response["groups"]
        }
        message_aliases = {
            (item["source_session_id"], item["group_id"], row["message_id"])
            for item in response["groups"]
            for row in item["messages"]
        }
        self.assertEqual(len(group_aliases), len(response["groups"]))
        self.assertEqual(
            len(message_aliases),
            sum(len(item["messages"]) for item in response["groups"]),
        )
        self.assertCountEqual(adapter.read_calls, ["qq-session", "cron-session"])
        self.assertCountEqual(
            session_db.lineage_calls,
            ["current-session", "qq-session", "cron-session"],
        )
        self.assertEqual(
            session_db.list_calls[0],
            {
                "exclude_sources": ["subagent", "tool"],
                "limit": 18,
                "offset": 0,
                "include_children": False,
                "project_compression_tips": True,
                "order_by_last_active": True,
                "compact_rows": True,
            },
        )

    def test_source_class_is_closed_and_wakeup_requires_durable_provenance(self):
        rows = [
            ("human", "qqbot", {"display_kind": "", "internal_kind": ""}),
            ("cli", "cli", {"display_kind": "", "internal_kind": ""}),
            (
                "wakeup",
                "qqbot",
                {
                    "display_kind": "internal_notification",
                    "internal_kind": "wakeup",
                },
            ),
            (
                "internal",
                "qqbot",
                {"display_kind": "internal_notification", "internal_kind": ""},
            ),
            ("delegated", "subagent", {"display_kind": "", "internal_kind": ""}),
            ("tool", "provider", {"display_kind": "", "internal_kind": ""}),
            ("unknown", "future_plugin", {"display_kind": "", "internal_kind": ""}),
        ]
        sessions = [
            session(name, source, REFERENCE - timedelta(minutes=index))
            for index, (name, source, _evidence) in enumerate(rows)
        ]
        sources = {
            name: source_result(
                [group(name, REFERENCE - timedelta(minutes=index), name, "done")],
                source_evidence=[evidence],
            )
            for index, (name, _source, evidence) in enumerate(rows)
        }
        service, _adapter, _session_db = self.service(sessions, sources)

        response = service.read_window(request(excluded_sources=[]))

        self.assertEqual(response["status"], "ready")
        self.assertEqual(
            {item["group_id"]: item["source_class"] for item in response["groups"]},
            {
                "human": "human",
                "cli": "human",
                "wakeup": "scheduled",
                "internal": "internal",
                "delegated": "delegated",
                "tool": "tool",
                "unknown": "unknown",
            },
        )

    def test_allowed_source_classes_exclude_policy_groups_without_poisoning_window(self):
        rows = [
            ("human", "qqbot", {"display_kind": "", "internal_kind": ""}),
            (
                "internal",
                "qqbot",
                {"display_kind": "internal_notification", "internal_kind": ""},
            ),
            ("unknown", "future_plugin", {"display_kind": "", "internal_kind": ""}),
        ]
        service, _adapter, _session_db = self.service(
            [
                session(name, source, REFERENCE - timedelta(minutes=index))
                for index, (name, source, _evidence) in enumerate(rows)
            ],
            {
                name: source_result(
                    [group(name, REFERENCE - timedelta(minutes=index), name, "done")],
                    source_evidence=[evidence],
                )
                for index, (name, _source, evidence) in enumerate(rows)
            },
        )

        response = service.read_window(
            request(allowed_source_classes=["human", "scheduled"])
        )

        self.assertEqual(response["status"], "ready")
        self.assertEqual([row["group_id"] for row in response["groups"]], ["human"])
        self.assertEqual(response["trace"]["policy_excluded_group_count"], 2)
        response_text = json.dumps(response, ensure_ascii=False)
        self.assertNotIn('"internal"', response_text)
        self.assertNotIn('"unknown"', response_text)

    def test_explicit_custom_frontend_source_can_be_classified_as_human(self):
        service, _adapter, _session_db = self.service(
            [session("custom", "my_frontend", REFERENCE)],
            {"custom": source_result([group("custom", REFERENCE, "hello", "done")])},
            additional_human_sources=["my_frontend"],
        )

        response = service.read_window(
            request(allowed_source_classes=["human", "scheduled"])
        )

        self.assertEqual(response["status"], "ready")
        self.assertEqual(response["groups"][0]["source_class"], "human")

    def test_hermes_interactive_source_tags_are_human(self):
        source_tags = ["cli", "tui", "hermes_browser", "desktop", "dashboard"]
        service, _adapter, _session_db = self.service(
            [
                session(source, source, REFERENCE - timedelta(seconds=index))
                for index, source in enumerate(source_tags)
            ],
            {
                source: source_result(
                    [group(source, REFERENCE, source, "done")]
                )
                for source in source_tags
            },
        )

        response = service.read_window(
            request(allowed_source_classes=["human", "scheduled"])
        )

        self.assertEqual(response["status"], "ready")
        self.assertEqual(
            {row["source"]: row["source_class"] for row in response["groups"]},
            {source: "human" for source in source_tags},
        )

    def test_all_policy_excluded_groups_return_honest_empty_reason(self):
        service, _adapter, _session_db = self.service(
            [session("unknown", "future_plugin", REFERENCE)],
            {"unknown": source_result([group("unknown", REFERENCE, "x", "y")])},
        )

        response = service.read_window(
            request(allowed_source_classes=["human", "scheduled"])
        )

        self.assertEqual(
            (response["status"], response["reason"], response["groups"]),
            ("empty", "no_allowed_groups_in_window", []),
        )

    def test_disallowed_groups_still_consume_the_whole_window_group_cap(self):
        service, adapter, _session_db = self.service(
            [
                session("unknown-a", "future_a", REFERENCE),
                session("unknown-b", "future_b", REFERENCE - timedelta(seconds=1)),
            ],
            {
                "unknown-a": source_result(
                    [group("unknown-a", REFERENCE, "a", "done")]
                ),
                "unknown-b": source_result(
                    [group("unknown-b", REFERENCE, "b", "done")]
                ),
            },
        )

        response = service.read_window(
            request(
                max_groups=1,
                allowed_source_classes=["human", "scheduled"],
            )
        )

        self.assertEqual(
            (response["status"], response["reason"], response["groups"]),
            ("blocked", "group_limit_exceeded", []),
        )
        self.assertEqual(
            [row["max_groups"] for row in adapter.read_options],
            [1, 0],
        )

    def test_disallowed_ambiguous_candidate_still_blocks_the_whole_window(self):
        service, _adapter, _session_db = self.service(
            [session("unknown", "future_plugin", REFERENCE)],
            {"unknown": source_result([], status="ambiguous")},
        )

        response = service.read_window(
            request(allowed_source_classes=["human", "scheduled"])
        )

        self.assertEqual(
            (response["status"], response["reason"], response["groups"]),
            ("blocked", "candidate_source_ambiguous", []),
        )

    def test_two_hour_boundary_includes_cutoff_and_excludes_older_rows_and_groups(self):
        cutoff = REFERENCE - timedelta(hours=2)
        boundary = group("boundary", cutoff, "at edge", "included")
        older_group = group(
            "older-group", cutoff - timedelta(seconds=1), "old", "excluded"
        )
        service, adapter, _session_db = self.service(
            [
                session("boundary-session", "qqbot", cutoff),
                session("older-session", "cron", cutoff - timedelta(seconds=1)),
            ],
            {
                "boundary-session": source_result([older_group, boundary]),
                "older-session": source_result(
                    [group("unread-old", cutoff - timedelta(seconds=1), "x", "y")]
                ),
            },
        )

        response = service.read_window(request())

        self.assertEqual([item["group_id"] for item in response["groups"]], ["boundary"])
        self.assertEqual(adapter.read_calls, ["boundary-session"])
        self.assertEqual(response["trace"]["outside_horizon_session_count"], 1)
        self.assertEqual(response["trace"]["outside_horizon_group_count"], 1)

    def test_five_minute_clock_skew_is_included_but_later_future_is_not(self):
        within_skew = group(
            "within-skew", REFERENCE + timedelta(minutes=5), "near", "included"
        )
        beyond_skew = group(
            "beyond-skew",
            REFERENCE + timedelta(minutes=5, seconds=1),
            "future",
            "excluded",
        )
        service, adapter, _session_db = self.service(
            [
                session("too-future", "cron", REFERENCE + timedelta(minutes=6)),
                session("near-future", "qqbot", REFERENCE + timedelta(minutes=5)),
            ],
            {
                "too-future": source_result([]),
                "near-future": source_result([beyond_skew, within_skew]),
            },
        )

        response = service.read_window(request())

        self.assertEqual(
            [item["group_id"] for item in response["groups"]], ["within-skew"]
        )
        self.assertEqual(adapter.read_calls, ["near-future"])
        self.assertEqual(response["trace"]["outside_horizon_session_count"], 1)
        self.assertEqual(response["trace"]["outside_horizon_group_count"], 1)

    def test_session_scan_past_a_bounded_future_row_finds_window(self):
        future_rows = [
            session(
                f"future-{index:02d}",
                "cron",
                REFERENCE + timedelta(minutes=6),
            )
            for index in range(2)
        ]
        visible_group = group(
            "paged-visible", REFERENCE - timedelta(minutes=1), "found", "complete"
        )
        service, adapter, session_db = self.service(
            future_rows
            + [session("paged-visible-session", "qqbot", REFERENCE)],
            {
                **{row["id"]: source_result([]) for row in future_rows},
                "paged-visible-session": source_result([visible_group]),
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "ready")
        self.assertEqual(
            [item["group_id"] for item in response["groups"]], ["paged-visible"]
        )
        self.assertEqual(adapter.read_calls, ["paged-visible-session"])
        self.assertEqual([call["offset"] for call in session_db.list_calls], [0])
        self.assertEqual(response["trace"]["outside_horizon_session_count"], 2)

    def test_session_scan_budget_blocks_unbounded_future_rows(self):
        future_rows = [
            session(
                f"future-{index:02d}",
                "cron",
                REFERENCE + timedelta(minutes=6),
            )
            for index in range(40)
        ]
        service, adapter, session_db = self.service(
            future_rows,
            {row["id"]: source_result([]) for row in future_rows},
        )

        response = service.read_window(request(max_sessions=4))

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["reason"], "session_limit_exceeded")
        self.assertEqual(response["groups"], [])
        self.assertEqual(adapter.read_calls, [])
        self.assertEqual(response["trace"]["listed_session_count"], 6)
        self.assertEqual(
            [call["limit"] for call in session_db.list_calls],
            [6],
        )

    def test_current_compression_lineage_is_excluded_as_one_conversation(self):
        service, adapter, _session_db = self.service(
            [
                session("root", "cli", REFERENCE - timedelta(minutes=1)),
                session("middle", "cli", REFERENCE - timedelta(minutes=2)),
                session(
                    "tip",
                    "cli",
                    REFERENCE - timedelta(minutes=3),
                    lineage_root="root",
                ),
                session("other", "qqbot", REFERENCE - timedelta(minutes=4)),
            ],
            {
                "root": source_result([]),
                "middle": source_result([]),
                "tip": source_result([]),
                "other": source_result(
                    [group("other-group", REFERENCE - timedelta(minutes=5), "u", "a")]
                ),
            },
            lineages={
                "current-session": ["root", "middle", "current-session", "tip"]
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "ready")
        self.assertEqual(adapter.read_calls, ["other"])
        self.assertEqual(response["trace"]["current_lineage_excluded_count"], 3)

    def test_candidate_tip_reads_real_ancestor_to_tip_lineage_once(self):
        ancestor_group = group(
            "ancestor-group", REFERENCE - timedelta(minutes=10), "old", "kept"
        )
        tip_group = group(
            "tip-group", REFERENCE - timedelta(minutes=1), "new", "kept"
        )
        service, adapter, _session_db = self.service(
            [
                session(
                    "candidate-tip",
                    "qqbot",
                    REFERENCE,
                    lineage_root="candidate-root",
                )
            ],
            {
                "candidate-tip": source_result([ancestor_group, tip_group]),
            },
            lineages={
                "current-session": ["current-session"],
                "candidate-tip": ["candidate-root", "candidate-tip"],
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "ready")
        self.assertEqual(
            [item["group_id"] for item in response["groups"]],
            ["ancestor-group", "tip-group"],
        )
        self.assertEqual(adapter.read_lineages, [["candidate-root", "candidate-tip"]])
        self.assertEqual(adapter.read_options[0]["max_physical_rows"], 2_048)
        self.assertEqual(adapter.read_options[0]["max_groups"], 64)

    def test_unknown_current_lineage_fails_before_listing_or_source_read(self):
        service, adapter, session_db = self.service(
            [session("other", "qqbot", REFERENCE)],
            {"other": source_result([])},
            lineages={"current-session": []},
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["reason"], "session_list_failed")
        self.assertEqual(response["groups"], [])
        self.assertEqual(session_db.list_calls, [])
        self.assertEqual(adapter.read_calls, [])

    def test_candidate_physical_overflow_is_visible_and_atomic(self):
        service, _adapter, _session_db = self.service(
            [session("overflow", "qqbot", REFERENCE)],
            {
                "overflow": {
                    "status": "overflow",
                    "scan_complete": False,
                    "source_snapshot": "",
                    "groups": [],
                    "error": "source_physical_row_limit_exceeded",
                }
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["reason"], "candidate_source_unavailable")
        self.assertEqual(response["groups"], [])

    def test_candidate_lineage_generation_cap_blocks_before_source_reads(self):
        lineage = [f"generation-{index}" for index in range(64)] + ["tip"]
        service, adapter, _session_db = self.service(
            [session("tip", "qqbot", REFERENCE)],
            {"tip": source_result([])},
            lineages={
                "current-session": ["current-session"],
                "tip": lineage,
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["reason"], "candidate_source_unavailable")
        self.assertEqual(response["groups"], [])
        self.assertEqual(adapter.read_calls, [])

    def test_missing_bounded_host_seam_fails_visibly(self):
        service, adapter, session_db = self.service([], {})
        session_db.get_messages_time_window = None

        response = service.read_window(request())

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["reason"], "host_incompatible")
        self.assertEqual(adapter.read_calls, [])

    def test_default_source_exclusion_and_filter_revision_are_explicit(self):
        shared_group = group(
            "visible-group", REFERENCE - timedelta(minutes=1), "visible", "answer"
        )
        sessions = [
            session("visible", "qqbot", REFERENCE),
            session("tool-run", "tool", REFERENCE),
            session("delegate", "subagent", REFERENCE),
        ]
        sources = {
            "visible": source_result([shared_group]),
            "tool-run": source_result([]),
            "delegate": source_result([]),
        }
        service, adapter, _session_db = self.service(sessions, sources)

        default_response = service.read_window(request())
        changed_filter = service.read_window(
            request(excluded_sources=["subagent", "tool", "never-present"])
        )

        self.assertEqual(adapter.read_calls, ["visible", "visible"])
        self.assertEqual(default_response["groups"], changed_filter["groups"])
        self.assertNotEqual(
            default_response["source_revision"], changed_filter["source_revision"]
        )

        human_scheduled = service.read_window(
            request(allowed_source_classes=["human", "scheduled"])
        )
        scheduled_human = service.read_window(
            request(allowed_source_classes=["scheduled", "human"])
        )
        human_only = service.read_window(
            request(allowed_source_classes=["human"])
        )
        self.assertEqual(
            human_scheduled["source_revision"],
            scheduled_human["source_revision"],
        )
        self.assertNotEqual(
            human_scheduled["source_revision"],
            human_only["source_revision"],
        )

    def test_ambiguous_candidate_blocks_the_whole_window(self):
        service, _adapter, _session_db = self.service(
            [
                session("ready", "qqbot", REFERENCE),
                session("ambiguous", "cron", REFERENCE - timedelta(seconds=1)),
            ],
            {
                "ready": source_result(
                    [group("ready-group", REFERENCE, "secret one", "answer one")]
                ),
                "ambiguous": source_result([], status="ambiguous"),
            },
        )

        response = service.read_window(request())

        self.assertEqual(response["status"], "blocked")
        self.assertEqual(response["reason"], "candidate_source_ambiguous")
        self.assertFalse(response["scan_complete"])
        self.assertEqual(response["groups"], [])

    def test_session_and_group_caps_block_instead_of_returning_partial_windows(self):
        sessions = [
            session("one", "qqbot", REFERENCE),
            session("two", "cron", REFERENCE - timedelta(seconds=1)),
        ]
        sources = {
            "one": source_result(
                [
                    group("one-a", REFERENCE - timedelta(minutes=2), "u1", "a1"),
                    group("one-b", REFERENCE - timedelta(minutes=1), "u2", "a2"),
                ]
            ),
            "two": source_result([]),
        }
        service, adapter, _session_db = self.service(sessions, sources)

        session_block = service.read_window(request(max_sessions=1))
        group_block = service.read_window(request(max_groups=1))

        self.assertEqual(
            (session_block["status"], session_block["reason"], session_block["groups"]),
            ("blocked", "session_limit_exceeded", []),
        )
        self.assertEqual(
            (group_block["status"], group_block["reason"], group_block["groups"]),
            ("blocked", "group_limit_exceeded", []),
        )
        self.assertEqual(adapter.read_calls, ["one"])

    def test_revision_tracks_content_hash_and_trace_is_body_free(self):
        first = group("stable-group", REFERENCE, "private user", "private answer")
        service, adapter, _session_db = self.service(
            [session("stable", "qqbot", REFERENCE)],
            {"stable": source_result([first])},
        )
        first_response = service.read_window(request())

        changed = group("stable-group", REFERENCE, "changed user", "private answer")
        adapter.sources["stable"] = source_result([changed])
        changed_response = service.read_window(request())

        self.assertNotEqual(
            first_response["source_revision"], changed_response["source_revision"]
        )
        trace_text = json.dumps(first_response["trace"], ensure_ascii=False)
        self.assertNotIn("private user", trace_text)
        self.assertNotIn("private answer", trace_text)
        self.assertFalse(first_response["trace"]["body_included"])
        self.assertEqual(len(first_response["trace"]["session_proofs_sha256"]), 64)
        self.assertEqual(len(first_response["trace"]["group_proofs_sha256"]), 64)

    def test_unknown_request_field_fails_closed(self):
        service, adapter, _session_db = self.service([], {})

        response = service.read_window(request(user_id="must-not-be-accepted"))

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["reason"], "request_invalid")

    def test_obsolete_v1_source_contract_fails_closed(self):
        service, adapter, session_db = self.service([], {})
        old_request = request()
        old_request["schema"] = "continuity_canonical_window_request.v1"

        response = service.read_window(old_request)

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["reason"], "request_invalid")
        self.assertEqual(adapter.read_calls, [])
        self.assertEqual(session_db.list_calls, [])
        self.assertFalse(response["scan_complete"])
        self.assertEqual(response["groups"], [])
        self.assertEqual(adapter.read_calls, [])


if __name__ == "__main__":
    unittest.main()
