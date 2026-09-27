"""Real offline/TUI writer entrypoints; all databases are disposable.

These checks do not launch an agent or the sqlite3 CLI's page salvager. The
lost-and-found fixture is shaped like that CLI's output, and its production
mapper performs the writes. Snapshot restore includes the required explicit
stopped-writer invalidation handoff; file copying alone is not an epoch hook.
"""

from contextlib import closing, nullcontext
import asyncio
import json
import logging
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

try:
    from hermes_state import SessionDB
except ImportError:
    SessionDB = None


@unittest.skipUnless(SessionDB and hasattr(SessionDB, "prepare_history_step"),
                     "requires the Block 3 canonical-history host seam")
class HistoryPortabilityTests(unittest.TestCase):
    session_id = "20260829_010203_portability"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def database(self, name):
        path = self.root / name / "state.db"
        path.parent.mkdir()
        db = SessionDB(db_path=path)
        self.addCleanup(db.close)
        return db

    def seed(self, db):
        db.create_session(self.session_id, source="cli")
        db.append_messages_batch(self.session_id, [
            {"role": "user", "content": "synthetic question", "timestamp": 1787961600},
            {"role": "assistant", "content": "synthetic answer", "timestamp": 1787961601},
        ])
        return self.prepare(db)

    def prepare(self, db, session_id=None):
        session_id = session_id or self.session_id
        epoch = None
        for _ in range(100):
            result = db.prepare_history_step(
                session_id, owner_id="portability-test", activation_epoch=epoch,
                max_pages=2, max_rows_per_page=2, deadline_ms=500)
            epoch = result.get("activation_epoch") or epoch
            if result["status"] == "ready":
                return result["head_token"]
            self.assertEqual(result["status"], "progress", result)
        self.fail("bounded preparation did not finish")

    def assert_fresh_copy(self, db, previous):
        self.assertNotEqual(db.validate_history_prefix(previous)["status"], "valid")
        current = self.prepare(db)
        self.assertNotEqual(current["incarnation"], previous["incarnation"])
        page = db.read_history_page(self.session_id, target=current)
        self.assertEqual(page["status"], "ready", page)
        self.assertEqual([row["content"] for row in page["rows"]],
                         ["synthetic question", "synthetic answer"])
        self.assertEqual(db.validate_history_prefix(current)["status"], "valid")
        self.assertNotEqual(db.validate_history_prefix(previous)["status"], "valid")

    def test_import_sessions_rebuilds_destination_proof_and_keeps_existing_domain(self):
        source = self.database("source")
        previous = self.seed(source)
        target = self.database("imported")
        target.create_session("existing", source="cli")
        target.append_message("existing", "user", "unrelated", timestamp=1)
        existing = self.prepare(target, "existing")
        result = target.import_sessions([source.export_session(self.session_id)])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["imported"], 1)
        self.assert_fresh_copy(target, previous)
        self.assertEqual(target.validate_history_prefix(existing)["status"], "valid")

    def test_tui_branch_writes_real_child_but_cannot_borrow_parent_proof(self):
        from tui_gateway import methods_session

        db = self.database("tui")
        previous = self.seed(db)
        child_id = "20260829_010204_branch"
        session = {"session_key": self.session_id, "history_lock": threading.Lock(),
                   "history": db.get_messages(self.session_id)}
        # HandlerRegistry.install is the real production function rebinding
        # seam. Only UI/config and agent construction are substitutes.
        namespace = SimpleNamespace(
            _methods={}, _profile_scoped=lambda fn: fn, uuid=uuid,
            _sess=lambda params, rid: (session, None),
            _session_db=lambda value: nullcontext(db),
            _coerce_message_text=lambda value: str(value or ""),
            _reconcile_display_with_live=lambda display, live: display,
            _new_session_key=lambda: child_id, _session_source=lambda value: "cli",
            _resolve_model=lambda: "synthetic", _session_cwd=lambda value: str(self.root),
            _set_session_context=lambda value: None, _clear_session_context=lambda value: None,
            _make_agent=lambda *args, **kwargs: SimpleNamespace(),
            _init_session=lambda *args, **kwargs: None,
            _transfer_db_to_agent=lambda *args: None, _sessions={},
            _history_to_messages=lambda history: history, _session_info=lambda *args: {},
            _ok=lambda rid, result: {"result": result},
            _err=lambda rid, code, message: {"error": message},
            logger=logging.getLogger(__name__),
        )
        methods_session.register(namespace)
        result = namespace._methods["session.branch"](1, {"name": "disposable branch"})
        self.assertNotIn("error", result)
        self.assertEqual(result["result"]["stored_session_id"], child_id)
        child = db.get_session(child_id)
        self.assertEqual(child["parent_session_id"], self.session_id)
        self.assertEqual([row["content"] for row in db.get_messages(child_id)],
                         ["synthetic question", "synthetic answer"])
        current = self.prepare(db, child_id)
        self.assertNotEqual(current["domain_id"], previous["domain_id"])
        with self.assertRaisesRegex(ValueError, "different history domain"):
            db.read_history_page(child_id, target=previous)
        self.assertEqual(db.validate_history_prefix(previous)["status"], "valid")
        self.assertEqual(db.validate_history_prefix(current)["status"], "valid")

    def test_cli_recovery_copies_canonical_rows_not_derived_proof(self):
        from hermes_cli.session_recovery import recover_session_database

        source = self.database("source")
        previous = self.seed(source)
        path = source.db_path
        source.close()
        output = self.root / "recovered.db"
        report = recover_session_database(path, output, work_dir=self.root, chunk_size=1)
        self.assertTrue(report["complete"], report)
        self.assertTrue(report["source_unchanged"])
        self.assertFalse(report["installed"])
        with SessionDB(db_path=output) as recovered:
            self.assert_fresh_copy(recovered, previous)

    def test_api_session_handlers_capture_direct_insert_delete_and_ignore_title(self):
        from gateway.platforms import api_server

        db = self.database("api")
        previous = self.seed(db)
        # No server/auth/network is started. Invoke the real handlers, including
        # their asyncio.to_thread -> _execute_write transaction and direct SQL.
        adapter = object.__new__(api_server.APIServerAdapter)
        adapter._check_auth = lambda request: None
        adapter._ensure_session_db_async = AsyncMock(return_value=db)
        adapter._session_runtime_request_from_body = lambda body: {}
        adapter._runtime_lock_error = lambda request: None

        def request(body=None, session_id=None):
            return SimpleNamespace(json=AsyncMock(return_value=body or {}),
                                   match_info={"session_id": session_id})

        async def dispatch():
            created = await adapter._handle_create_session(request(
                {"id": "api-created", "title": "reserved title", "source": "api_server"}))
            self.assertEqual(created.status, 201, created.text)
            self.assertEqual(json.loads(created.text)["session"]["id"], "api-created")
            proof = self.prepare(db, "api-created")
            # This real branch first INSERTs, then DELETEs the new session in
            # the same transaction when another session owns the requested title.
            conflict = await adapter._handle_create_session(request(
                {"id": "api-title-conflict", "title": "reserved title"}))
            self.assertEqual(conflict.status, 400, conflict.text)
            self.assertIsNone(db.get_session("api-title-conflict"))
            with db._read_ctx() as connection:
                events = [row[0] for row in connection.execute(
                    "SELECT operation FROM hermes_history_changes "
                    "WHERE old_session_id=? OR new_session_id=? ORDER BY change_seq",
                    ("api-title-conflict", "api-title-conflict"))]
            self.assertEqual(events, ["insert", "delete"])
            for title in ("renamed synthetic session", "renamed synthetic session"):
                renamed = await adapter._handle_patch_session(
                    request({"title": title}, self.session_id))
                self.assertEqual(renamed.status, 200, renamed.text)
                self.assertEqual(db.get_session(self.session_id)["title"], title)
                self.assertEqual(db.validate_history_prefix(previous)["status"], "valid")
            deleted = await adapter._handle_delete_session(request(session_id="api-created"))
            self.assertEqual(deleted.status, 200, deleted.text)
            self.assertTrue(json.loads(deleted.text)["deleted"])
            self.assertIsNone(db.get_session("api-created"))
            self.assertNotEqual(db.validate_history_prefix(proof)["status"], "valid")

        # aiohttp is optional in this test lane. Only its response container is
        # replaced; authentication and HTTP transport are explicitly out of scope.
        response_container = SimpleNamespace(json_response=lambda data, status=200:
                                             SimpleNamespace(status=status, text=json.dumps(data)))
        with patch.object(api_server, "web", response_container):
            asyncio.run(dispatch())

    def test_a2a_direct_title_writer_preserves_proof_including_noop(self):
        from plugins.platforms.a2a.adapter import A2AAdapter

        db = self.database("a2a")
        previous = self.seed(db)
        context = SimpleNamespace(_profile_state_db=lambda profile: str(db.db_path))
        for title in ("synthetic forwarded title", "synthetic forwarded title"):
            A2AAdapter._title_forward_session(context, "disposable", self.session_id, title)
            self.assertEqual(db.get_session(self.session_id)["title"], title)
            self.assertEqual(db.validate_history_prefix(previous)["status"], "valid")

    def test_lost_and_found_mapper_and_orphan_stub_mint_new_proof(self):
        from hermes_cli.session_lost_and_found import (
            map_lost_and_found_rows, stub_missing_parent_sessions,
        )

        source = self.database("source")
        previous = self.seed(source)
        rows = source._conn.execute("SELECT * FROM messages ORDER BY id").fetchall()
        destination = self.database("salvage")
        path = destination.db_path
        destination.close()
        with closing(sqlite3.connect(":memory:")) as recovered_pages, \
                closing(sqlite3.connect(path, isolation_level=None)) as target:
            fields = len(rows[0])
            recovered_pages.execute(
                "CREATE TABLE lost_and_found(rootpgno,pgno,nfield,id," +
                ",".join(f"c{number}" for number in range(fields)) + ")")
            for row in rows:
                # SQLite INTEGER PRIMARY KEY is NULL inside a recovered record;
                # its rowid is supplied separately by the CLI's output format.
                values = (2, 3, fields, row["id"], None, *tuple(row)[1:])
                recovered_pages.execute(
                    "INSERT INTO lost_and_found VALUES (" + ",".join("?" for _ in values) + ")",
                    values)
            mapped = map_lost_and_found_rows(recovered_pages, target)
            self.assertEqual(mapped["mapped"]["messages"], 2, mapped)
            self.assertEqual(mapped["unmapped_rows"], 0)
            stubbed = stub_missing_parent_sessions(target)
            self.assertEqual(stubbed["sessions_stubbed"], 1)
            self.assertEqual(stubbed["messages_retained"], 2)
        with SessionDB(db_path=path) as recovered:
            self.assertEqual(recovered.get_session(self.session_id)["source"], "recovered")
            self.assert_fresh_copy(recovered, previous)

    def test_quick_restore_requires_explicit_stopped_writer_invalidation(self):
        from hermes_cli.backup import create_quick_snapshot, restore_quick_snapshot

        source = self.database("restore-home")
        previous = self.seed(source)
        path, home = source.db_path, source.db_path.parent
        source.close()
        snapshot = create_quick_snapshot(label="disposable", hermes_home=home)
        self.assertIsNotNone(snapshot)
        with SessionDB(db_path=path) as candidate:
            candidate.append_message(self.session_id, "user", "after snapshot", timestamp=1787961602)
        # This is a restore/preimage control, NOT the candidate-window delta
        # preservation strategy. No writer is open during file replacement.
        self.assertTrue(restore_quick_snapshot(snapshot, hermes_home=home))
        with SessionDB(db_path=path) as restored:
            restored.invalidate_history_for_rollback()
            self.assertNotEqual(restored.validate_history_prefix(previous)["status"], "valid")
            current = self.prepare(restored)
            self.assertNotEqual(current["activation_epoch"], previous["activation_epoch"])
            page = restored.read_history_page(self.session_id, target=current)
            self.assertEqual([row["content"] for row in page["rows"]],
                             ["synthetic question", "synthetic answer"])
            self.assertEqual(restored.validate_history_prefix(current)["status"], "valid")
            self.assertNotEqual(restored.validate_history_prefix(previous)["status"], "valid")


if __name__ == "__main__":
    unittest.main()
