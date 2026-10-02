from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_hermes_adapter import ContinuityMetadataStore, HermesSessionAdapter

try:
    from hermes_state import SessionDB
except ImportError:
    SessionDB = None


@unittest.skipUnless(SessionDB and hasattr(SessionDB, "prepare_history_step"),
                     "requires the Block 3 canonical-history host seam")
class HistoryIndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.writer = SessionDB(db_path=self.root / "state.db")
        self.writer.create_session("session-1", source="cli")
        self.reader = SessionDB(db_path=self.root / "state.db", read_only=True)
        self.store = ContinuityMetadataStore(self.root / "continuity.sqlite3")
        self.adapter = HermesSessionAdapter(self.reader, self.store)

    def tearDown(self):
        self.adapter.close()
        self.reader.close()
        self.writer.close()
        self.directory.cleanup()

    def seed(self, pairs):
        for start in range(0, pairs, 100):
            self.writer.append_messages_batch("session-1", [
                {"role": role, "content": f"{role} {index}", "timestamp": 1787961600+index*2+offset}
                for index in range(start, min(start+100, pairs))
                for offset, role in enumerate(("user", "assistant"))
            ])
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=0,compacted=1 WHERE session_id='session-1'"))

    def prepare(self):
        for _ in range(2000):
            result = self.adapter.history_index.prepare_step("session-1")
            if result["status"] == "ready":
                return result
            self.assertEqual(result["status"], "progress", result)
        self.fail("history preparation did not finish within bounded work steps")

    def test_evidenced_notification_clone_remains_in_complete_dialogue(self):
        self.writer.append_message("session-1", "user", "notification", timestamp=1787961600,
                                   display_kind="internal_notification")
        missing = dict(self.writer.get_messages("session-1")[0], display_kind=None)
        self.writer.archive_and_compact("session-1", [missing])
        self.writer.archive_and_compact("session-1", [missing])
        self.writer.append_message("session-1", "assistant", "reply", timestamp=1787961601)
        before = [tuple(row) for row in self.writer._conn.execute("SELECT * FROM messages ORDER BY id")]
        self.prepare()
        source = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["source_proof"]["group_count"], 1)
        self.assertEqual([message["content"] for message in source["groups"][0]["messages"]],
                         ["notification", "reply"])
        self.assertEqual([tuple(row) for row in self.writer._conn.execute("SELECT * FROM messages ORDER BY id")], before)

    def test_mixed_user_provenance_retains_dialogue_without_granting_hot_authority(self):
        self.writer.append_message("session-1", "user", "system notice", timestamp=1787961600,
                                   display_kind="internal_notification")
        self.writer.append_message("session-1", "user", "human reply", timestamp=1787961601)
        self.writer.append_message("session-1", "assistant", "answer", timestamp=1787961602)
        before = [tuple(row) for row in self.writer._conn.execute("SELECT * FROM messages ORDER BY id")]
        self.prepare()
        source = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["groups"][0]["messages"][0]["content"], "system notice\n\nhuman reply")
        from test_hermes_adapter import PACKAGE
        import importlib
        adapter = importlib.import_module(f"{PACKAGE}.hermes_adapter")
        classified = adapter._project_canonical_source(
            "session-1", self.writer.get_messages("session-1"), full_prefix=True,
            include_lineage_proofs=True)
        self.assertEqual(classified["error"], "source_evidence_ambiguous")
        self.assertEqual([tuple(row) for row in self.writer._conn.execute("SELECT * FROM messages ORDER BY id")], before)

    def test_more_than_2048_rows_has_compact_proof_and_bounded_suffix(self):
        self.seed(1200)
        self.prepare()
        source = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["source_proof"]["group_count"], 1200)
        self.assertLessEqual(source["stats"]["workset_rows"], 2048)
        self.assertGreater(source["prefix_before_groups"]["group_count"], 0)
        self.assertFalse(source["stats"]["full_prefix"])
        from test_hermes_adapter import PACKAGE
        import importlib
        normalizer = importlib.import_module(f"{PACKAGE}.checkpoint_v3").normalize_thread_continuity_compact_source
        self.assertEqual(normalizer(source), source)
        with closing(self.store._connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_group_index").fetchone()[0], 1200)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(continuity_group_index)")}
            self.assertFalse(columns & {"content", "body", "messages", "transcript"})

    def test_old_live_hole_cannot_silently_grant_retirement_to_later_compacted_groups(self):
        self.seed(1200)
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=1,compacted=0 WHERE id IN "
            "(SELECT id FROM messages ORDER BY id LIMIT 2 OFFSET 20)"))
        self.prepare()
        source = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(source["status"], "overflow")
        self.assertEqual(source["error"], "foreground_group_limit_exceeded")
        with closing(self.store._connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_group_index").fetchone()[0], 1200)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_checkpoints_v3").fetchone()[0], 0)
        self.assertEqual(self.writer._conn.execute("SELECT COUNT(*) FROM messages WHERE active=1").fetchone()[0], 2)

    def test_pending_user_then_assistant_preserves_full_group(self):
        self.seed(2)
        self.writer.append_message("session-1", "user", "unfinished", timestamp=1787961610)
        self.prepare()
        self.writer.append_message("session-1", "assistant", "completed", timestamp=1787961611)
        self.prepare()
        source = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["source_proof"]["group_count"], 3)
        self.assertEqual(source["groups"][-1]["messages"][0]["content"], "unfinished")
        self.assertEqual(source["retirement_eligibility"]["prefix"]["group_count"], 2)

    def test_oversized_complete_group_never_advances_partial_retirement(self):
        self.writer.append_messages_batch("session-1", [
            {"role": "user", "content": f"part {number}", "timestamp": 1787961600+number}
            for number in range(2049)
        ] + [{"role": "assistant", "content": "complete", "timestamp": 1787963650}])
        for _ in range(200):
            result = self.adapter.history_index.prepare_step("session-1")
            if result["status"] != "progress":
                break
        self.assertEqual(result, {"status": "overflow", "reason": "complete_group_limit_exceeded"})
        with closing(self.store._connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_group_index").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_checkpoints_v3").fetchone()[0], 0)
        self.writer.create_session("small", source="cli")
        self.writer.append_messages_batch("small", [
            {"role": "user", "content": "still works", "timestamp": 1787961600},
            {"role": "assistant", "content": "yes", "timestamp": 1787961601},
        ])
        for _ in range(100):
            result = self.adapter.history_index.prepare_step("small")
            if result["status"] == "ready":
                break
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.adapter.read_source("small", reference_at="2026-08-30T00:00:00+00:00")["status"], "ready")

    def test_plugin_groups_reach_ready_during_continuous_small_appends(self):
        self.seed(1200)
        ready = None
        for step in range(100):
            result = self.adapter.history_index.prepare_step("session-1")
            self.writer.append_messages_batch("session-1", [
                {"role": "user", "content": f"new user {step}", "timestamp": 1787970000+step*2},
                {"role": "assistant", "content": f"new answer {step}", "timestamp": 1787970001+step*2},
            ])
            if result["status"] == "ready":
                ready = result
                break
            self.assertEqual(result["status"], "progress", result)
        self.assertIsNotNone(ready)
        with closing(self.store._connect()) as connection:
            row = connection.execute("SELECT group_count,ready FROM continuity_group_progress").fetchone()
        self.assertGreaterEqual(row[0], 1200)
        self.assertEqual(row[1], 1)

    def test_full_sized_group_spans_shared_quanta_without_tail_starvation(self):
        self.writer.append_messages_batch("session-1", [
            {"role": "user", "content": f"fragment {number}", "timestamp": 1787961600+number}
            for number in range(2047)
        ] + [{"role": "assistant", "content": "whole group", "timestamp": 1787963647}])
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=0,compacted=1 WHERE session_id='session-1'"))
        ready, pending_observed = None, False
        for step in range(100):
            result = self.adapter.history_index.prepare_step("session-1")
            pending_observed |= self.adapter.history_index._pending_group is not None
            self.writer.append_messages_batch("session-1", [
                {"role": "user", "content": f"tail {step}", "timestamp": 1787970000+step*2},
                {"role": "assistant", "content": f"answer {step}", "timestamp": 1787970001+step*2},
            ])
            if result["status"] == "ready":
                ready = result
                break
            self.assertEqual(result["status"], "progress", result)
        self.assertIsNotNone(ready)
        self.assertTrue(pending_observed)
        self.assertIsNone(self.adapter.history_index._pending_group)
        with closing(self.store._connect()) as connection:
            first = connection.execute("SELECT start_position,end_position FROM continuity_group_index WHERE ordinal=1").fetchone()
        self.assertEqual(tuple(first), (1, 2048))

    def test_lifecycle_refresh_changes_retirement_not_logical_group_identity(self):
        self.seed(3)
        self.prepare()
        old = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=1,compacted=0 WHERE id>=5"))
        self.prepare()
        fresh = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(fresh["status"], "ready", fresh)
        self.assertEqual([g["source_prefix_id"] for g in old["groups"]],
                         [g["source_prefix_id"] for g in fresh["groups"]])
        self.assertEqual(fresh["retirement_eligibility"]["prefix"]["group_count"], 2)

    def test_edit_prepared_prefix_rebuilds_dependent_groups(self):
        self.seed(140)
        self.prepare()
        old = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET content='edited' WHERE id=1"))
        self.prepare()
        fresh = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(fresh["status"], "ready", fresh)
        self.assertEqual(fresh["source_proof"]["group_count"], 140)
        self.assertNotEqual(old["source_proof"]["group_root"], fresh["source_proof"]["group_root"])
        self.assertEqual(fresh["groups"][0]["messages"][0]["content"], "edited")

    def test_newer_host_watermark_covers_unchanged_group_prefix(self):
        self.seed(3)
        self.prepare()
        before = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.writer.append_message("session-1", "user", "new pending tail", timestamp=1787961700)
        for _ in range(100):
            result = self.reader.prepare_history_step(
                "session-1", owner_id=self.adapter.history_index.owner_id,
                activation_epoch=self.adapter.history_index.activation_epoch)
            if result["status"] == "ready":
                break
        self.assertEqual(result["status"], "ready")
        after = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(after["status"], "ready", after)
        self.assertEqual(after["source_proof"], before["source_proof"])

    def test_physical_change_after_page_read_rejects_old_retirement(self):
        self.seed(3)
        self.prepare()
        original = self.reader.validate_history_prefix
        checks = 0

        def validation(token):
            nonlocal checks
            checks += 1
            result = original(token)
            if checks == 2:
                result = {**result, "status": "valid", "invalidated_from_position": 1}
            return result

        with patch.object(self.reader, "validate_history_prefix", side_effect=validation), \
                patch.object(self.adapter.history_index, "request"):
            source = self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(source["status"], "pending")

    def test_checkpoint_cannot_borrow_another_session_domain(self):
        from test_runtime import ContinuityRuntime, FakeLlm, project, execute, post, request
        self.seed(3)
        self.prepare()
        runtime = ContinuityRuntime(self.adapter, FakeLlm(),
                                    estimator=lambda messages: max(1, len(repr(messages))//8),
                                    clock=lambda: "2026-08-30T00:00:00+00:00")
        try:
            wire = request()
            projected = project(runtime, wire, session="session-1")
            self.assertIsNotNone(projected)
            execute(runtime, projected["request"], wire, session="session-1")
            post(runtime, session="session-1")
        finally:
            runtime.clear()
        checkpoint = self.adapter.read_bundle("session-1", reference_at="2026-08-30T00:00:00+00:00")["continuity"]["state"]["checkpoint"]
        with patch.object(self.reader, "validate_history_prefix") as host_check:
            with self.assertRaisesRegex(ValueError, "checkpoint_domain_mismatch"):
                self.adapter.history_index.validate_checkpoint(checkpoint, session_id="session-2")
        host_check.assert_not_called()

    def test_preparation_payload_read_does_not_hold_metadata_writer(self):
        self.seed(140)
        index = self.adapter.history_index
        original = index._page
        writes = []

        def page(*args, **kwargs):
            with closing(sqlite3.connect(self.store.path, timeout=0.1)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("UPDATE continuity_group_progress SET ready=ready")
                connection.commit()
            writes.append(True)
            return original(*args, **kwargs)

        with patch.object(index, "_page", side_effect=page):
            self.prepare()
        self.assertGreater(len(writes), 0)

    def test_suffix_cleanup_seeks_past_unchanged_occurrences(self):
        with closing(self.store._connect()) as connection:
            plan = [row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT rowid FROM continuity_group_occurrences "
                "WHERE session_id=? AND position>? LIMIT 256", ("session-1", 9998))]
            self.assertTrue(any("continuity_group_occurrence_position" in detail
                                and "position>?" in detail for detail in plan), plan)
            steps = []
            for size in (1000, 10000):
                connection.execute("DELETE FROM continuity_group_occurrences")
                connection.executemany("INSERT INTO continuity_group_occurrences VALUES (?,?,?,?,?)",
                    [("session-1", "message", position, str(position), 1) for position in range(size)])
                count = 0

                def progress():
                    nonlocal count
                    count += 10
                    return 0

                connection.set_progress_handler(progress, 10)
                self.adapter.history_index._discard_suffix(connection, "session-1", size-2)
                connection.set_progress_handler(None, 0)
                steps.append(count)
            self.assertLessEqual(max(steps), 400, steps)

    def test_committed_writer_notification_prepares_without_foreground_request(self):
        self.seed(3)
        index = self.adapter.history_index
        index.request("session-1")

        def groups_ready(count):
            with closing(self.store._connect()) as connection:
                row = connection.execute(
                    "SELECT group_count,ready FROM continuity_group_progress WHERE session_id='session-1'"
                ).fetchone()
            return row is not None and tuple(row) == (count, 1)

        with index._wake:
            self.assertTrue(index._wake.wait_for(lambda: groups_ready(3), timeout=5))
        self.writer.append_messages_batch("session-1", [
            {"role": "user", "content": "notification user", "timestamp": 1787961800},
            {"role": "assistant", "content": "notification answer", "timestamp": 1787961801},
        ])
        with index._wake:
            self.assertTrue(index._wake.wait_for(lambda: groups_ready(4), timeout=5))
        index.close()
        self.assertFalse(index._worker.is_alive())
        self.assertEqual(index._listeners, {})
        with patch.object(index, "request") as wake:
            self.writer.append_message("session-1", "user", "after unload")
        wake.assert_not_called()

    def test_unload_waits_for_page_and_prevents_late_group_publication(self):
        self.seed(3)
        index = self.adapter.history_index
        entered, release = threading.Event(), threading.Event()
        original = index._page

        def page(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError("unload test did not release bounded page")
            return original(*args, **kwargs)

        with patch.object(index, "_page", side_effect=page):
            index.request("session-1")
            self.assertTrue(entered.wait(5))
            closer = threading.Thread(target=index.close)
            closer.start()
            try:
                with index._wake:
                    self.assertTrue(index._wake.wait_for(lambda: index._closed, timeout=2))
            finally:
                release.set()
                closer.join(3)
            self.assertFalse(closer.is_alive())
        self.assertFalse(index._worker.is_alive())
        with closing(self.store._connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_group_index").fetchone()[0], 0)

    def test_old_worker_page_cannot_publish_after_real_epoch_handoff(self):
        self.seed(3)
        index = self.adapter.history_index
        page = index._page
        handoff = []

        def transfer_after_page(*args, **kwargs):
            result = page(*args, **kwargs)
            if not handoff:
                old_epoch = index.activation_epoch
                self.writer.invalidate_history_for_rollback()
                for _ in range(100):
                    prepared = self.writer.prepare_history_step(
                        "session-1", owner_id="replacement-owner", deadline_ms=1000)
                    if prepared["status"] == "ready":
                        break
                    self.assertEqual(prepared["status"], "progress", prepared)
                self.assertEqual(prepared["status"], "ready")
                self.assertNotEqual(old_epoch, prepared["activation_epoch"])
                handoff.append(prepared)
            return result

        with patch.object(index, "_page", side_effect=transfer_after_page):
            result = index.prepare_step("session-1")
        self.assertEqual(result["status"], "progress", result)
        self.assertTrue(handoff)
        with closing(self.store._connect()) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM continuity_group_index").fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT position FROM continuity_group_progress").fetchone()[0], 0)
        self.assertEqual(index.prepare_step("session-1")["status"], "incompatible")
        replacement = HermesSessionAdapter(self.reader, self.store)
        try:
            for _ in range(100):
                prepared = replacement.history_index.prepare_step("session-1")
                if prepared["status"] == "ready":
                    break
                self.assertEqual(prepared["status"], "progress", prepared)
            source = replacement.read_source(
                "session-1", reference_at="2026-08-30T00:00:00+00:00")
            self.assertEqual(source["status"], "ready", source)
            self.assertEqual(source["source_proof"]["group_count"], 3)
        finally:
            replacement.close()

    def test_process_capacity_refuses_before_source_read_then_recovers(self):
        import importlib
        from test_hermes_adapter import PACKAGE
        from test_runtime import ContinuityRuntime, FakeLlm, project, request
        budget = importlib.import_module(f"{PACKAGE}.resource_budget").ACTIVE_WORKSETS
        self.seed(3)
        self.prepare()
        occupied = object()
        self.assertTrue(budget.acquire(occupied, budget.limit))
        runtime = ContinuityRuntime(self.adapter, FakeLlm(),
                                    estimator=lambda messages: max(1, len(repr(messages))//8),
                                    clock=lambda: "2026-08-30T00:00:00+00:00")
        try:
            with patch.object(self.adapter, "read_bundle", wraps=self.adapter.read_bundle) as read:
                self.assertIsNone(project(runtime, request(), session="session-1", turn="busy"))
                read.assert_not_called()
                budget.release(occupied)
                self.assertIsNotNone(project(runtime, request(), session="session-1", turn="recovered"))
                self.assertEqual(read.call_count, 1)
        finally:
            budget.release(occupied)
            runtime.clear()

    def test_real_async_summary_cancellation_releases_admission_for_new_runtime(self):
        import asyncio
        from test_runtime import runtime_module, ContinuityRuntime, FakeLlm, project, request
        self.seed(24)
        self.prepare()
        class CancelledLlm:
            async def acomplete(self, *args, **kwargs):
                task = asyncio.current_task()
                task.cancel()
                await asyncio.sleep(0)
        other_profile = object()
        budget = runtime_module.ACTIVE_WORKSETS
        self.assertTrue(budget.acquire(other_profile, 8*1024*1024))
        try:
            for turn in range(4):
                runtime = ContinuityRuntime(self.adapter, CancelledLlm(),
                    estimator=lambda messages: max(1, len(repr(messages))//8),
                    clock=lambda: "2026-08-30T00:00:00+00:00")
                try:
                    with self.assertRaises(asyncio.CancelledError):
                        project(runtime, request(), session="session-1", turn=f"cancel-{turn}")
                    self.assertEqual(runtime._turns, {})
                    self.assertEqual(runtime._compiling, set())
                    self.assertNotIn(runtime._budget_key(("session-1", f"cancel-{turn}")), budget._leases)
                finally:
                    runtime.clear()
                    budget.release(runtime._budget_key(("session-1", f"cancel-{turn}")))
            runtime = ContinuityRuntime(self.adapter, FakeLlm(),
                estimator=lambda messages: max(1, len(repr(messages))//8),
                clock=lambda: "2026-08-30T00:00:00+00:00")
            try:
                self.assertIsNotNone(project(runtime, request(), session="session-1", turn="after-cancel"))
            finally:
                runtime.clear()
            self.assertEqual(budget._leases[other_profile], 8*1024*1024)
        finally:
            budget.release(other_profile)

    def test_legacy_settings_cannot_raise_v3_admission_ceiling(self):
        self.adapter.max_full_prefix_physical_rows = 1000000
        self.adapter.max_full_prefix_bytes = 2**30
        with patch.object(self.adapter.history_index, "read_source", return_value={}) as read:
            self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(read.call_args.kwargs["max_rows"], 2048)
        self.assertEqual(read.call_args.kwargs["max_bytes"], 4*1024*1024)
        self.adapter.max_full_prefix_physical_rows = 10
        self.adapter.max_full_prefix_bytes = 4096
        with patch.object(self.adapter.history_index, "read_source", return_value={}) as read:
            self.adapter.read_source("session-1", reference_at="2026-08-30T00:00:00+00:00")
        self.assertEqual(read.call_args.kwargs["max_rows"], 10)
        self.assertEqual(read.call_args.kwargs["max_bytes"], 4096)

    def test_long_history_projects_settles_and_reuses_without_second_summary(self):
        from test_runtime import ContinuityRuntime, FakeLlm, project, execute, post, request
        self.seed(1200)
        self.prepare()
        llm = FakeLlm()
        for number in range(2):
            runtime = ContinuityRuntime(
                self.adapter, llm, estimator=lambda messages: max(1, len(repr(messages))//8),
                clock=lambda: "2026-08-30T00:00:00+00:00")
            try:
                wire = request()
                projected = project(runtime, wire, session="session-1", turn=f"turn-{number}", api=f"api-{number}")
                self.assertIsNotNone(projected, runtime.status_command("session-1"))
                _, sent = execute(runtime, projected["request"], wire, session="session-1",
                                  turn=f"turn-{number}", api=f"api-{number}")
                self.assertEqual(len(sent), 1)
                post(runtime, session="session-1", turn=f"turn-{number}", api=f"api-{number}")
            finally:
                runtime.clear()
        with closing(self.store._connect()) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_receipts").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT revision FROM continuity_checkpoints_v3").fetchone()[0], 1)
        self.assertEqual(llm.calls, 1)

    def test_canonical_edit_after_validation_before_cas_never_reuses_old_body(self):
        from test_runtime import ContinuityRuntime, FakeLlm, project, execute, post, request
        self.seed(24)
        self.prepare()
        runtime = ContinuityRuntime(
            self.adapter, FakeLlm(), estimator=lambda messages: max(1, len(repr(messages))//8),
            clock=lambda: "2026-08-30T00:00:00+00:00")
        try:
            wire = request()
            projected = project(runtime, wire, session="session-1", turn="race", api="race")
            self.assertIsNotNone(projected)
            _, sent = execute(runtime, projected["request"], wire,
                              session="session-1", turn="race", api="race")
            validate = self.adapter.history_index.validate_checkpoint
            edits = []

            def edit_after_validation(checkpoint, **kwargs):
                result = validate(checkpoint, **kwargs)
                self.writer._execute_write(lambda connection: connection.execute(
                    "UPDATE messages SET content='changed after source validation' "
                    "WHERE session_id='session-1' AND id=1"))
                edits.append(True)
                return result

            with patch.object(self.adapter.history_index, "validate_checkpoint",
                              side_effect=edit_after_validation):
                post(runtime, session="session-1", turn="race", api="race")
            self.assertEqual(edits, [True])
            self.assertEqual(len(sent), 1)
            with closing(self.store._connect()) as connection:
                self.assertEqual(connection.execute(
                    "SELECT status FROM continuity_receipts").fetchone()[0],
                    "delivered_checkpoint_stored_unvalidated")
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM continuity_checkpoints_v3").fetchone()[0], 1)
            # Actual host journal/index catch up, then the ordinary bundle read
            # must reject the persisted stale proof rather than exposing its body.
            self.prepare()
            bundle = self.adapter.read_bundle(
                "session-1", reference_at="2026-08-30T00:00:00+00:00")
            self.assertEqual(bundle["source"]["status"], "ready")
            self.assertEqual(bundle["continuity"]["error"],
                             "thread_continuity_checkpoint_source_invalid")
            self.assertNotIn("recent_bridge", bundle["continuity"].get("state", {}))
        finally:
            runtime.clear()


if __name__ == "__main__":
    unittest.main()
