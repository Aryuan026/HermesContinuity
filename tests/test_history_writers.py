from __future__ import annotations

import json
import sqlite3
import time

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from hermes_state import SessionDB, repair_state_db_schema
except ImportError:
    SessionDB = None


def _seed(db: SessionDB, session_id: str, **session_fields) -> None:
    db.create_session(
        session_id,
        source=session_fields.pop("source", "cli"),
        **session_fields,
    )
    db.append_message(session_id, "user", f"{session_id}-user", timestamp=1)
    db.append_message(session_id, "assistant", f"{session_id}-assistant", timestamp=2)


def _prepare(
    db: SessionDB,
    session_id: str,
    *,
    owner: str,
    activation_epoch: str | None = None,
) -> dict:
    result = None
    epoch = activation_epoch
    for _ in range(100):
        result = db.prepare_history_step(
            session_id,
            owner_id=owner,
            activation_epoch=epoch,
            max_pages=2,
            max_rows_per_page=8,
            deadline_ms=1_000,
        )
        epoch = result.get("activation_epoch") or epoch
        if result["status"] != "progress":
            return result
    raise AssertionError(f"history preparation did not finish: {result}")


def _ready(db: SessionDB, session_id: str, *, owner: str) -> dict:
    result = _prepare(db, session_id, owner=owner)
    assert result["status"] == "ready", result
    return result


def _reprepare(db: SessionDB, session_id: str, prepared: dict, *, owner: str) -> dict:
    result = _prepare(
        db,
        session_id,
        owner=owner,
        activation_epoch=prepared["activation_epoch"],
    )
    assert result["status"] == "ready", result
    return result


@unittest.skipUnless(SessionDB and hasattr(SessionDB, "prepare_history_step"),
                     "requires the Block 3 canonical-history host seam")
class HistoryWriterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"HERMES_HOME": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        self.db = SessionDB(self.root / "case" / "state.db")
        self.addCleanup(self.db.close)

    def test_replace_messages_active_only_and_archive_dropped_reverify_real_rows(self):
        db, tmp_path = self.db, self.root
        _seed(db, "replace")
        original = db.get_messages("replace")
        db.archive_and_compact("replace", original)
        first = _ready(db, "replace", owner="replace-owner")

        db.replace_messages(
            "replace",
            [
                {"role": "user", "content": "active-only-user", "timestamp": 10},
                {"role": "assistant", "content": "active-only-assistant", "timestamp": 11},
            ],
            active_only=True,
        )
        assert db.validate_history_prefix(first["head_token"])["status"] == "pending"
        second = _reprepare(db, "replace", first, owner="replace-owner")
        first_validation = db.validate_history_prefix(first["head_token"])
        assert first_validation["status"] == "valid"
        assert first_validation["invalidated_from_position"] == 1
        assert second["canonical_count"] == 4

        db.replace_messages(
            "replace",
            [
                {"role": "user", "content": "archived-user", "timestamp": 20},
                {"role": "assistant", "content": "archived-assistant", "timestamp": 21},
            ],
            archive_dropped=True,
        )
        assert db.validate_history_prefix(second["head_token"])["status"] == "pending"
        third = _reprepare(db, "replace", second, owner="replace-owner")
        assert db.validate_history_prefix(second["head_token"])["status"] == "changed"
        assert [row["content"] for row in db.get_messages("replace")] == [
            "archived-user",
            "archived-assistant",
        ]
        assert len(db.get_messages("replace", include_inactive=True, include_compacted=True)) == 6
        assert third["canonical_count"] == 4


    def test_api_content_reaction_and_seen_writers_reverify_sidecars(self):
        db, tmp_path = self.db, self.root
        _seed(db, "sidecars")
        first = _ready(db, "sidecars", owner="sidecar-owner")

        assert db.set_latest_user_api_content(
            "sidecars", "sidecars-user", "sidecars-user\n\nprovider-context"
        ) == 1
        assert db.validate_history_prefix(first["head_token"])["status"] == "pending"
        second = _reprepare(db, "sidecars", first, owner="sidecar-owner")
        assert db.validate_history_prefix(first["head_token"])["status"] == "changed"

        assistant_id = db.get_messages("sidecars")[-1]["id"]
        assert db.set_message_reaction("sidecars", assistant_id, "👍", author="user")
        third = _reprepare(db, "sidecars", second, owner="sidecar-owner")
        assert db.validate_history_prefix(second["head_token"])["status"] == "changed"

        unseen = db.take_unseen_reactions("sidecars", author="user")
        assert [item["emoji"] for item in unseen] == ["👍"]
        _reprepare(db, "sidecars", third, owner="sidecar-owner")
        assert db.validate_history_prefix(third["head_token"])["status"] == "changed"


    def test_clear_delete_bulk_prune_and_delegate_cascade_invalidate_real_domains(self):
        db, tmp_path = self.db, self.root
        _seed(db, "clear")
        clear_ready = _ready(db, "clear", owner="clear-owner")
        db.clear_messages("clear")
        cleared = _reprepare(db, "clear", clear_ready, owner="clear-owner")
        assert cleared["canonical_count"] == 0
        assert db.validate_history_prefix(clear_ready["head_token"])["status"] == "changed"

        _seed(db, "single-delete")
        single_ready = _ready(db, "single-delete", owner="single-delete-owner")
        assert db.delete_session("single-delete") is True
        assert db.validate_history_prefix(single_ready["head_token"])["status"] == "incompatible"

        _seed(db, "bulk-a")
        _seed(db, "bulk-b")
        bulk_a = _ready(db, "bulk-a", owner="bulk-a-owner")
        bulk_b = _ready(db, "bulk-b", owner="bulk-b-owner")
        assert db.delete_sessions(["bulk-a", "bulk-b", "missing"]) == 2
        assert db.validate_history_prefix(bulk_a["head_token"])["status"] == "incompatible"
        assert db.validate_history_prefix(bulk_b["head_token"])["status"] == "incompatible"

        _seed(db, "pruned")
        pruned_ready = _ready(db, "pruned", owner="prune-owner")
        db.end_session("pruned", "finished")
        assert db.prune_sessions(
            older_than_days=None,
            source="cli",
            last_active_before=time.time() + 1,
        ) >= 1
        assert db.get_session("pruned") is None
        assert db.validate_history_prefix(pruned_ready["head_token"])["status"] == "incompatible"

        _seed(db, "delegate-parent")
        _seed(
            db,
            "delegate-child",
            source="subagent",
            parent_session_id="delegate-parent",
            model_config={"_delegate_from": "delegate-parent"},
        )
        child_ready = _ready(db, "delegate-child", owner="delegate-child-owner")
        assert db.delete_session("delegate-parent") is True
        assert db.get_session("delegate-child") is None
        assert db.validate_history_prefix(child_ready["head_token"])["status"] == "incompatible"


    def test_purge_stale_tool_marker_reverifies_content(self):
        db, tmp_path = self.db, self.root
        db.create_session("marker", source="cli")
        db.append_message("marker", "user", "run tool", timestamp=1)
        db.append_message(
            "marker",
            "assistant",
            "[memory]",
            timestamp=2,
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "memory", "arguments": "{}"},
                }
            ],
        )
        prepared = _ready(db, "marker", owner="marker-owner")

        report = db.purge_stale_tool_call_markers(backup=False)
        assert report["rows_affected"] == 1
        rebuilt = _reprepare(db, "marker", prepared, owner="marker-owner")
        assert db.validate_history_prefix(prepared["head_token"])["status"] == "changed"
        assert db.read_history_page("marker", target=rebuilt["head_token"])["rows"][-1][
            "content"
        ] == ""


    def test_session_topology_writers_and_ui_writers_keep_separate_proofs(self):
        db, tmp_path = self.db, self.root
        _seed(db, "meta")
        original = _ready(db, "meta", owner="meta-owner")

        db.set_session_title("meta", "Visible title")
        db.set_session_pinned("meta", True)
        db.set_session_read("meta", False)
        assert db.validate_history_prefix(original["head_token"])["status"] == "valid"

        db.update_session_meta("meta", json.dumps({"browser_model_lock": "runtime-only"}))
        runtime_only = _reprepare(db, "meta", original, owner="meta-owner")
        assert db.validate_history_prefix(original["head_token"])["status"] == "valid"
        assert runtime_only["prefix_hash"] == original["prefix_hash"]

        db.patch_session_model_config("meta", {"_branched_from": "parent"})
        assert db.validate_history_prefix(runtime_only["head_token"])["status"] == "incompatible"
        lineage = _reprepare(db, "meta", runtime_only, owner="meta-owner")
        assert lineage["head_token"]["topology_revision"] != runtime_only["head_token"][
            "topology_revision"
        ]

        _seed(db, "peer")
        peer = _ready(db, "peer", owner="peer-owner")
        db.record_gateway_session_peer("peer", source="telegram", session_key="peer-key")
        assert db.validate_history_prefix(peer["head_token"])["status"] == "incompatible"

        workspace = tmp_path / "kanban" / "workspaces"
        _seed(db, "kanban-legacy", cwd=str(workspace / "task"))
        kanban = _ready(db, "kanban-legacy", owner="kanban-owner")
        assert db.retag_kanban_worker_sessions(str(workspace)) == 1
        assert db.validate_history_prefix(kanban["head_token"])["status"] == "incompatible"


    def test_ensure_end_and_reopen_session_topology_are_captured(self):
        db, tmp_path = self.db, self.root
        db.create_session("parent", source="cli")
        _seed(db, "ensured")
        original = _ready(db, "ensured", owner="ensure-owner")

        db.ensure_session(
            "ensured",
            source="cli",
            parent_session_id="parent",
            model_config={"_branched_from": "parent"},
        )
        assert db.validate_history_prefix(original["head_token"])["status"] == "incompatible"
        ensured = _reprepare(db, "ensured", original, owner="ensure-owner")

        db.end_session("ensured", "session_reset")
        assert db.validate_history_prefix(ensured["head_token"])["status"] == "incompatible"
        ended = _reprepare(db, "ensured", ensured, owner="ensure-owner")

        db.reopen_session("ensured")
        assert db.validate_history_prefix(ended["head_token"])["status"] == "incompatible"
        reopened = _reprepare(db, "ensured", ended, owner="ensure-owner")
        assert reopened["canonical_count"] == 2


    def test_publish_compression_child_captures_parent_topology_and_child_watermark(self):
        db, tmp_path = self.db, self.root
        _seed(db, "compression-parent")
        parent = _ready(db, "compression-parent", owner="compression-parent-owner")
        watermark = db.get_active_message_watermark("compression-parent")
        assert db.try_acquire_compression_lock(
            "compression-parent", "compressor", ttl_seconds=60
        )
        db.append_message("compression-parent", "user", "concurrent-tail", timestamp=3)
        ceiling = db.get_active_message_watermark("compression-parent")

        db.publish_compression_child(
            parent_session_id="compression-parent",
            child_session_id="compression-child",
            source="cli",
            messages=[
                {"role": "user", "content": "summary-user", "timestamp": 10},
                {"role": "assistant", "content": "summary-assistant", "timestamp": 11},
            ],
            compression_lock_holder="compressor",
            watermark=watermark,
            watermark_ceiling=ceiling,
        )

        assert db.validate_history_prefix(parent["head_token"])["status"] == "incompatible"
        child = _ready(db, "compression-child", owner="compression-child-owner")
        assert [row["content"] for row in db.get_messages("compression-child")] == [
            "summary-user",
            "summary-assistant",
            "concurrent-tail",
        ]
        assert child["canonical_count"] == 3
        assert db.get_compression_lineage("compression-child") == [
            "compression-parent",
            "compression-child",
        ]


    def test_fts_schema_repair_preserves_canonical_proof_and_future_capture(self):
        db, tmp_path = self.db, self.root
        db_path = tmp_path / "state.db"
        store = SessionDB(db_path)
        _seed(store, "repair")
        prepared = _ready(store, "repair", owner="repair-owner")
        store.close()

        raw = sqlite3.connect(db_path, isolation_level=None)
        try:
            raw.execute("UPDATE messages_fts_data SET block = X'BADC0FFEE0DDF00D'")
        finally:
            raw.close()

        report = repair_state_db_schema(db_path, backup=False)
        assert report["repaired"] is True, report

        reopened = SessionDB(db_path)
        try:
            assert reopened.validate_history_prefix(prepared["head_token"])["status"] == "valid"
            reopened.append_message("repair", "user", "after-repair", timestamp=3)
            assert reopened.validate_history_prefix(prepared["head_token"])["status"] == "pending"
            refreshed = _reprepare(reopened, "repair", prepared, owner="repair-owner")
            assert refreshed["canonical_count"] == 3
            assert reopened.validate_history_prefix(prepared["head_token"])["status"] == "valid"
        finally:
            reopened.close()
