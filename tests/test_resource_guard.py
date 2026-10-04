"""Entry-level guards: observe SQL and decoder calls, not just error labels."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from test_hermes_adapter import (
    ContinuityMetadataStore, FakeSessionDB, HermesSessionAdapter,
    dialogue_rows, row,
)


class ResourceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ContinuityMetadataStore(Path(self.temp.name) / "metadata.db", max_checkpoint_bytes=4096)

    def large_checkpoint(self):
        with sqlite3.connect(self.store.path) as connection:
            connection.execute(
                "INSERT INTO continuity_checkpoints VALUES "
                "('session-1', 1, 'snapshot', '[]', printf('%.*c', 1000000, 'x'), 'hash', 'now')"
            )

    def test_overflow_bundle_does_not_open_checkpoint_store(self):
        self.large_checkpoint()
        adapter = HermesSessionAdapter(FakeSessionDB(dialogue_rows(1, 100, "small")), self.store,
                                       max_full_prefix_physical_rows=1)
        with patch.object(self.store, "_connect", side_effect=AssertionError("checkpoint read")), \
             patch.object(self.store, "_decode_checkpoint", side_effect=AssertionError("decode")):
            result = adapter.read_bundle("session-1")
        self.assertEqual(result["source"]["status"], "overflow")
        self.assertEqual(result["continuity"]["error"], "source_unavailable")

    def test_large_checkpoint_is_null_at_sql_boundary_and_status_never_decodes(self):
        self.large_checkpoint()
        source = HermesSessionAdapter(FakeSessionDB(dialogue_rows(1, 100, "small"))).read_source("session-1")
        with sqlite3.connect(self.store.path) as connection:
            connection.row_factory = sqlite3.Row
            guarded = self.store._bounded_checkpoint_row(connection, "session-1")
            self.assertIsNone(guarded["checkpoint_json"])
        with patch.object(self.store, "_decode_checkpoint", side_effect=AssertionError("decode")):
            self.assertEqual(self.store.read_continuity("session-1", source)["error"],
                             "checkpoint_byte_limit_exceeded")
            status = self.store.status_summary("session-1")
        self.assertEqual(status["checkpoint"]["status"], "byte_limit_exceeded")
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(connection.execute("SELECT length(checkpoint_json) FROM continuity_checkpoints").fetchone()[0], 1000000)

    def test_all_message_payload_columns_are_budgeted_before_fetch_and_decode(self):
        for column in ("content", "api_content", "tool_calls", "display_metadata", "reasoning_content"):
            with self.subTest(column=column):
                message = row(1, "user", "hello", 100)
                message[column] = "x" * 32768
                db = FakeSessionDB([message])
                statements = []
                original = db._read_ctx

                @contextmanager
                def traced():
                    with original() as connection:
                        connection.set_trace_callback(statements.append)
                        yield connection

                db._read_ctx = traced
                with patch.object(db, "_decode_message_rows", side_effect=AssertionError("decode")):
                    result = HermesSessionAdapter(db, max_full_prefix_bytes=8192).read_source("session-1")
                self.assertEqual(result["error"], "source_byte_limit_exceeded")
                self.assertFalse(any("SELECT * FROM messages" in sql for sql in statements))

    def test_aggregate_small_rows_cannot_exceed_byte_budget(self):
        db = FakeSessionDB(dialogue_rows(1, 100, "x" * 5000))
        with patch.object(db, "_decode_message_rows", side_effect=AssertionError("decode")):
            result = HermesSessionAdapter(db, max_full_prefix_bytes=8192).read_source("session-1")
        self.assertEqual(result["error"], "source_byte_limit_exceeded")

    def test_source_unicode_exact_byte_boundary_includes_record_headroom(self):
        db = FakeSessionDB(dialogue_rows(1, 100, "文" * 1600))
        with db._read_ctx() as connection:
            columns = [r[1] for r in connection.execute("PRAGMA table_info(messages)")]
            sizes = "+".join(f'coalesce(length(CAST("{c}" AS BLOB)),0)' for c in columns)
            size = connection.execute(f"SELECT SUM({sizes}) FROM messages").fetchone()[0]
        self.assertGreater(size, 4096)
        for budget in (size - 1, size, size + 1):
            result = HermesSessionAdapter(db, max_full_prefix_bytes=budget).read_source("session-1")
            self.assertEqual(result["status"], "ready" if budget >= size else "overflow")

    def test_rejection_restores_borrowed_connection_limits_and_transaction(self):
        db = FakeSessionDB(dialogue_rows(1, 100, "small"))
        original = db._read_ctx
        inspected = []

        @contextmanager
        def checked():
            with original() as connection:
                before = connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
                try:
                    yield connection
                finally:
                    inspected.append((connection.getlimit(sqlite3.SQLITE_LIMIT_LENGTH), connection.in_transaction))
                    self.assertEqual(inspected[-1], (before, False))

        db._read_ctx = checked
        result = HermesSessionAdapter(db, max_full_prefix_bytes=64).read_source("session-1")
        self.assertEqual(result["error"], "source_byte_limit_exceeded")
        self.assertEqual(len(inspected), 1)

    def test_small_snapshot_preserves_existing_canonical_audit(self):
        db = FakeSessionDB(dialogue_rows(1, 100, "small"))
        adapter = HermesSessionAdapter(db, self.store)
        source = adapter.read_bundle("session-1")
        self.assertEqual(source["source"]["status"], "ready")
        self.assertEqual(source["continuity"]["status"], "absent")
        self.assertEqual(len(source["source"]["groups"]), 1)

    def test_writer_growth_between_probe_and_fetch_cannot_escape_snapshot(self):
        db = FakeSessionDB(dialogue_rows(1, 100, "small"))
        path = Path(self.temp.name) / "source.db"
        with db._read_ctx() as original:
            with sqlite3.connect(path) as copy:
                original.backup(copy)
        with sqlite3.connect(path) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
        mutated = []

        @contextmanager
        def connection_scope():
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            def trace(sql):
                if "SUM(" in sql and not mutated:
                    with sqlite3.connect(path) as writer:
                        writer.execute("UPDATE messages SET content=printf('%.*c',32768,'x') WHERE id=1")
                    mutated.append(True)
            connection.set_trace_callback(trace)
            try:
                yield connection
            finally:
                connection.close()

        db._read_ctx = connection_scope
        adapter = HermesSessionAdapter(db, max_full_prefix_bytes=8192)
        before = adapter.read_source("session-1")
        self.assertEqual(before["status"], "ready")
        self.assertEqual(before["groups"][0]["messages"][0]["content"], "small")
        self.assertEqual(adapter.read_source("session-1")["error"], "source_byte_limit_exceeded")
        self.assertEqual(mutated, [True])


if __name__ == "__main__":
    unittest.main()
