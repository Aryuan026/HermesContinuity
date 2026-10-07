"""Accepted H13 consumer over the repaired v3 adapter and real disposable .5 DB."""
from contextlib import closing
from datetime import datetime, timezone
import importlib
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from test_hermes_adapter import PACKAGE, ContinuityMetadataStore, HermesSessionAdapter

adapter_module = importlib.import_module(f"{PACKAGE}.hermes_adapter")
try:
    from hermes_state import SessionDB
    from agent.message_origin import build_message_origin_proof
except ImportError:
    SessionDB = None


@unittest.skipUnless(SessionDB and hasattr(SessionDB, "_encode_origin_proof"), "requires H13")
class H13V3AdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = SessionDB(self.root / "state.db")
        self.addCleanup(self.db.close)
        self.store = ContinuityMetadataStore(self.root / "continuity.sqlite3")
        self.adapter = HermesSessionAdapter(self.db, self.store)
        self.addCleanup(self.adapter.close)
        self.db.create_session("mixed", "qqbot")

    def row(self, role, text, stamp, writer=None, **kwargs):
        proof = build_message_origin_proof(writer) if writer else None
        self.db.append_message("mixed", role, text, timestamp=stamp, origin_proof=proof, **kwargs)

    def recent(self, lineage=("mixed",)):
        result = self.adapter.read_recent_lineage_source(
            lineage, start_timestamp=0, end_timestamp=1000, max_physical_rows=128, max_groups=32)
        self.assertEqual(result["status"], "ready", result)
        return result

    def prepare(self, index=None):
        index = index or self.adapter.history_index
        for _ in range(100):
            result = index.prepare_step("mixed")
            if result["status"] == "ready":
                return
            self.assertEqual(result["status"], "progress", result)
        self.fail("bounded preparation did not finish")

    def test_complete_group_and_missing_proof_do_not_inherit_channel(self):
        for n, writer in enumerate(("gateway.user", "gateway.wakeup", "gateway.internal", "subagent", None)):
            self.row("user", f"question {n}", n*2+1, writer)
            self.row("assistant", f"answer {n}", n*2+2, writer)
        result = self.recent()
        self.assertEqual([p["source_class"] for p in result["_group_source_evidence"]],
                         ["human", "scheduled", "internal", "delegated", "unknown"])
        self.assertEqual(result["_group_source_evidence"][-1]["origin_status"], "missing")

    def test_interrupted_scheduled_user_never_merges_into_human_group_or_index(self):
        self.row("user", "interrupted wake", 1, "gateway.wakeup")
        self.row("user", "human question", 2, "gateway.user")
        self.row("assistant", "human answer", 3, "gateway.user")
        before = [tuple(r) for r in self.db._conn.execute("SELECT * FROM messages ORDER BY id")]
        result = self.recent()
        self.assertEqual(result["groups"][0]["messages"][0]["content"], "human question")
        self.assertEqual(result["_group_source_evidence"][0]["source_class"], "human")
        self.prepare()
        source = self.adapter.read_source("mixed", reference_at="1970-01-01T00:16:40+00:00")
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["groups"], result["groups"])
        with closing(self.store._connect()) as conn:
            self.assertEqual(tuple(conn.execute("SELECT start_position,end_position FROM continuity_group_index").fetchone()), (2, 3))
        self.assertEqual([tuple(r) for r in self.db._conn.execute("SELECT * FROM messages ORDER BY id")], before)

    def test_tool_and_interim_assistant_are_origin_obligations(self):
        self.row("user", "question", 1, "gateway.user")
        self.row("assistant", "working", 2, "gateway.user", finish_reason="tool_calls")
        self.row("tool", "tool result", 3, "gateway.wakeup", tool_name="synthetic")
        self.row("assistant", "answer", 4, "gateway.user", finish_reason="stop")
        result = self.recent()
        self.assertEqual(result["_group_source_evidence"][0]["origin_status"], "conflict")
        self.assertEqual(len(result["groups"][0]["messages"]), 2)

    def test_superseded_physical_origin_conflict_is_group_local(self):
        for role, stamp in (("user", 1), ("assistant", 2)):
            self.row(role, "conflicted " + role, stamp, "gateway.wakeup")
        self.db._execute_write(lambda c: c.execute("UPDATE messages SET active=0,compacted=0"))
        for role, stamp in (("user", 1), ("assistant", 2)):
            self.row(role, "conflicted " + role, stamp, "gateway.user")
        self.row("user", "good question", 3, "gateway.user")
        self.row("assistant", "good answer", 4, "gateway.user")
        result = self.recent()
        self.assertEqual([p["origin_status"] for p in result["_group_source_evidence"]], ["conflict", "verified"])

    def test_lineage_clone_origin_disagreement_is_group_local(self):
        self.row("user", "cloned question", 1, "gateway.wakeup")
        self.row("assistant", "cloned answer", 2, "gateway.wakeup")
        self.db.create_session("tip", "qqbot", parent_session_id="mixed")
        human = build_message_origin_proof("gateway.user")
        for role, text, stamp in (("user", "cloned question", 1), ("assistant", "cloned answer", 2),
                                  ("user", "good question", 3), ("assistant", "good answer", 4)):
            self.db.append_message("tip", role, text, timestamp=stamp, origin_proof=human)
        result = self.recent(("mixed", "tip"))
        self.assertEqual([p["origin_status"] for p in result["_group_source_evidence"]], ["conflict", "verified"])

    def test_old_derived_index_is_rebuilt_without_deleting_checkpoint_or_receipt(self):
        index_module = importlib.import_module(f"{PACKAGE}.history_index")
        self.row("user", "interrupted wake", 1, "gateway.wakeup")
        self.row("user", "human question", 2, "gateway.user")
        self.row("assistant", "answer", 3, "gateway.user")
        legacy = index_module.ContinuityHistoryIndex(self.db, self.store)
        try:
            self.prepare(legacy)
        finally:
            legacy.close()
        self.store.record_receipt(receipt_id="preserved", session_id="mixed", kind="delivery", status="delivered_checkpoint_unchanged")
        with closing(self.store._connect()) as conn:
            before = [tuple(r) for r in conn.execute("SELECT * FROM continuity_receipts")]
            conn.execute("INSERT INTO continuity_checkpoints VALUES (?,?,?,?,?,?,?)",
                         ("mixed", 1, "snapshot", "[]", '{"legacy":"untouched"}', "hash", "timestamp"))
            conn.commit()
        pending = self.adapter.history_index._read_source_once(
            "mixed", reference_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(pending["status"], "pending")
        # Its existing worker owns the preparation lock once requested.
        from importlib import import_module
        lock = import_module(f"{PACKAGE}.resource_budget").PREPARATION_LOCK
        with lock:
            self.prepare()
        with closing(self.store._connect()) as conn:
            self.assertEqual([tuple(r) for r in conn.execute("SELECT * FROM continuity_receipts")], before)
            self.assertEqual(conn.execute("SELECT checkpoint_json FROM continuity_checkpoints").fetchone()[0], '{"legacy":"untouched"}')
            self.assertEqual(tuple(conn.execute("SELECT start_position,end_position FROM continuity_group_index").fetchone()), (2, 3))
            self.assertEqual(conn.execute("SELECT grouping_rule FROM continuity_group_rules").fetchone()[0], index_module.H13_GROUP_RULE)

    def test_valid_pre_h13_checkpoint_and_receipt_survive_rule_change(self):
        from test_runtime import ContinuityRuntime, FakeLlm, project, execute, post, request
        index_module = importlib.import_module(f"{PACKAGE}.history_index")
        checkpoint_module = importlib.import_module(f"{PACKAGE}.checkpoint_v3")
        for n in range(4):
            self.row("user", f"historical question {n}", 1787961600+n*2, "gateway.user")
            self.row("assistant", f"historical answer {n}", 1787961601+n*2, "gateway.user")
        self.db._execute_write(lambda c: c.execute("UPDATE messages SET active=0,compacted=1"))
        legacy = index_module.ContinuityHistoryIndex(self.db, self.store)
        current = self.adapter.history_index
        self.adapter.history_index = legacy
        try:
            self.prepare(legacy)
            runtime = ContinuityRuntime(self.adapter, FakeLlm(),
                estimator=lambda messages: max(1, len(repr(messages))//8),
                clock=lambda: "2026-08-30T00:00:00+00:00")
            try:
                wire = request()
                projected = project(runtime, wire, session="mixed", turn="legacy", api="legacy")
                self.assertIsNotNone(projected, runtime.status_command("mixed"))
                execute(runtime, projected["request"], wire, session="mixed", turn="legacy", api="legacy")
                post(runtime, session="mixed", turn="legacy", api="legacy")
            finally:
                runtime.clear()
        finally:
            self.adapter.history_index = current
            legacy.close()
        with closing(self.store._connect()) as c:
            checkpoint_rows = [tuple(r) for r in c.execute("SELECT * FROM continuity_checkpoints_v3")]
            receipt_rows = [tuple(r) for r in c.execute("SELECT * FROM continuity_receipts")]
            state = json.loads(c.execute("SELECT checkpoint_json FROM continuity_checkpoints_v3").fetchone()[0])
        self.assertEqual(len(checkpoint_rows), 1)
        self.assertEqual(len(receipt_rows), 1)
        self.assertEqual(checkpoint_module.normalize_thread_continuity_checkpoint_v3(state), state)
        self.prepare()
        with self.assertRaisesRegex(ValueError, "checkpoint_grouping_rule_changed"):
            current.validate_checkpoint(state, session_id="mixed")
        with closing(self.store._connect()) as c:
            self.assertEqual([tuple(r) for r in c.execute("SELECT * FROM continuity_checkpoints_v3")], checkpoint_rows)
            self.assertEqual([tuple(r) for r in c.execute("SELECT * FROM continuity_receipts")], receipt_rows)

    def test_real_lean_composite_tail_is_consumed_after_read_only_reopen(self):
        from agent.context_compressor import ContextCompressor
        for n in range(30):
            self.row("user", f"question {n} " + "x"*400, 100+n*2, "gateway.user")
            self.row("assistant", f"answer {n} " + "x"*400, 101+n*2, "gateway.user")
        self.row("user", "live request", 200, "gateway.user")
        with patch("agent.context_compressor.get_model_context_length", return_value=100000):
            compressor = ContextCompressor(model="synthetic", threshold_percent=0.85,
                protect_first_n=0, protect_last_n=1, quiet_mode=True, config_context_length=100000)
        response = MagicMock()
        response.choices[0].message.content = "## Active Task\nsynthetic Lean summary"
        response.choices[0].finish_reason = "stop"
        with patch("agent.context_compressor.call_llm", return_value=response):
            compressed = compressor.compress(self.db.get_messages("mixed"), current_tokens=100000, force=True)
        self.db.publish_compression_child(parent_session_id="mixed", child_session_id="tip",
            source="qqbot", messages=compressed, require_compression_lease=False)
        self.db.append_message("tip", "assistant", "live answer", timestamp=201,
            origin_proof=build_message_origin_proof("gateway.user"))
        reader = SessionDB(self.root / "state.db", read_only=True)
        adapter = HermesSessionAdapter(reader, self.store)
        try:
            result = adapter.read_recent_lineage_source(("mixed", "tip"),
                start_timestamp=0, end_timestamp=1000, max_physical_rows=200, max_groups=32)
            self.assertEqual(result["status"], "ready", result)
            live = result["groups"][-1]
            self.assertEqual([m["content"] for m in live["messages"]], ["live request", "live answer"])
            self.assertEqual(result["_group_source_evidence"][-1]["source_class"], "human")
            self.assertNotIn("synthetic Lean summary", repr(result["groups"]))
        finally:
            adapter.close()
            reader.close()
