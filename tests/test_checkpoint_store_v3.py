from __future__ import annotations

import copy
import importlib
import json
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_checkpoint_store_v3_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

checkpoint_v3 = importlib.import_module(f"{PACKAGE}.checkpoint_v3")
checkpoint_store_v3 = importlib.import_module(f"{PACKAGE}.checkpoint_store_v3")
hermes_adapter = importlib.import_module(f"{PACKAGE}.hermes_adapter")
context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")

ContinuityMetadataStore = hermes_adapter.ContinuityMetadataStore
build_checkpoint_v2 = context_compactor.build_thread_continuity_checkpoint_v2
build_checkpoint = checkpoint_v3.build_thread_continuity_checkpoint_v3
initialize_store = checkpoint_store_v3.initialize_checkpoint_store_v3
read_checkpoint = checkpoint_store_v3.read_checkpoint_v3
record_delivery = checkpoint_store_v3.record_checkpoint_delivery_v3
settle_checkpoint = checkpoint_store_v3.settle_checkpoint_delivery_v3
status_checkpoint = checkpoint_store_v3.checkpoint_v3_status


def _group(source_id: str = "group-1", text: str = "hello") -> dict:
    return {
        "group_kind": "dialogue_turn",
        "source_prefix_id": source_id,
        "logical_turn_id": f"turn-{source_id}",
        "record_id": f"record-{source_id}",
        "effective_event_at": "2026-09-28T00:00:00+00:00",
        "messages": [
            {
                "role": "user",
                "message_id": f"message-{source_id}-u",
                "content": text,
            },
            {
                "role": "assistant",
                "message_id": f"message-{source_id}-a",
                "content": f"answer {text}",
            },
        ],
    }


def _source_material(*, suffix: str = "1") -> tuple[dict, dict]:
    prefix_hash = suffix * 64
    group_root = str((int(suffix) + 1) % 10) * 64
    prefix = {
        "schema": "thread_continuity_prefix_descriptor.v1",
        "through_anchor": f"anchor-{suffix}",
        "canonical_count": 2,
        "group_count": 1,
        "prefix_hash": prefix_hash,
        "group_root": group_root,
    }
    proof = {
        "host_token": {
            "schema": "hermes.canonical_history_prefix.v1",
            "realm_id": "realm-1",
            "incarnation": f"incarnation-{suffix}",
            "activation_epoch": f"epoch-{suffix}",
            "domain_id": "session-1",
            "topology_revision": f"topology-{suffix}",
            "canonical_rule_version": "canonical-rule.v1",
            "indexed_change_seq": int(suffix),
            "end_anchor": f"anchor-{suffix}",
            "canonical_count": 2,
            "prefix_hash": prefix_hash,
        },
        "grouping_rule_version": "groups.v1",
        "group_count": 1,
        "group_root": group_root,
    }
    return proof, prefix


def _checkpoint(
    *,
    previous: dict | None = None,
    rebuilt: bool = False,
    body: str = "private generated bridge",
    suffix: str = "1",
) -> dict:
    proof, prefix = _source_material(suffix=suffix)
    return build_checkpoint(
        previous_state=previous,
        source_proof=proof,
        retirement_prefix=prefix,
        bridge_source_groups=[_group(text=f"hello-{suffix}")],
        bridge_text=body,
        bridge_policy={
            "reference_at": "2026-09-28T00:00:00+00:00",
            "recent_horizon_hours": 72,
            "source_token_limit": 24_000,
            "output_token_limit": 2_048,
        },
        continue_lineage=previous is not None and not rebuilt,
    )


class CheckpointStoreV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "continuity.sqlite3"
        self.store = ContinuityMetadataStore(self.path)
        initialize_store(self.store)
        self.candidate = _checkpoint()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def valid(checkpoint: dict) -> dict:
        return copy.deepcopy(checkpoint)

    def settle(self, receipt_id: str, **overrides) -> dict:
        values = {
            "expected_revision": 0,
            "checkpoint_candidate": self.candidate,
            "receipt_id": receipt_id,
            "validate_checkpoint_source": self.valid,
            "source_ids": self.candidate["recent_bridge"]["source_group_ids"],
            "hashes": {"provider_body": "a" * 64},
            "counts": {"provider_request_count": 1},
            "recorded_at": "2026-09-28T00:01:00Z",
        }
        values.update(overrides)
        return settle_checkpoint(self.store, "session-1", **values)

    def receipts(self) -> list[dict]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT receipt_id,status,source_ids_json,hashes_json,counts_json "
                "FROM continuity_receipts ORDER BY receipt_id"
            ).fetchall()
        return [
            {
                "receipt_id": row[0],
                "status": row[1],
                "source_ids": json.loads(row[2]),
                "hashes": json.loads(row[3]),
                "counts": json.loads(row[4]),
            }
            for row in rows
        ]

    def test_initializer_is_explicit_and_leaves_v2_row_exact(self) -> None:
        separate = Path(self.temp.name) / "legacy.sqlite3"
        store = ContinuityMetadataStore(separate)
        legacy = (
            "session-1",
            7,
            "b" * 64,
            '["old-group"]',
            '{"old":"checkpoint"}',
            "c" * 64,
            "2026-09-28T00:00:00+00:00",
        )
        with sqlite3.connect(separate) as connection:
            connection.execute(
                "INSERT INTO continuity_checkpoints VALUES (?,?,?,?,?,?,?)", legacy
            )
            before = connection.execute(
                "SELECT * FROM continuity_checkpoints"
            ).fetchall()
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='continuity_checkpoints_v3'"
                ).fetchone()
            )

        initialize_store(store)

        with sqlite3.connect(separate) as connection:
            after = connection.execute(
                "SELECT * FROM continuity_checkpoints"
            ).fetchall()
            columns = [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(continuity_checkpoints_v3)"
                )
            ]
        self.assertEqual(after, before)
        self.assertEqual(columns, list(checkpoint_store_v3._TABLE_COLUMNS))

    def test_nonempty_v2_and_receipt_survive_v3_build_and_old_decoder_reopen(
        self,
    ) -> None:
        path = Path(self.temp.name) / "v2-v3-rollback.sqlite3"
        legacy_store = ContinuityMetadataStore(path)
        normalized = hermes_adapter.normalize_complete_thread_groups(
            [_group("legacy-group", "legacy user body")]
        )
        self.assertTrue(normalized["complete"])
        legacy_groups = normalized["groups"]
        legacy_ids = [group["source_prefix_id"] for group in legacy_groups]
        legacy_source = {
            "status": "ready",
            "scan_complete": True,
            "groups": legacy_groups,
            "source_prefix_ids": legacy_ids,
            "source_snapshot": hermes_adapter._source_snapshot(legacy_groups),
        }
        legacy_checkpoint = build_checkpoint_v2(
            previous_state=None,
            source_groups=legacy_groups,
            retired_source_group_ids=legacy_ids,
            bridge_source_group_ids=legacy_ids,
            bridge_text="legacy generated bridge body",
            bridge_policy={
                "reference_at": legacy_groups[-1]["effective_event_at"],
                "recent_horizon_hours": 72,
                "source_token_limit": 24_000,
                "output_token_limit": 2_048,
            },
        )
        legacy_settlement = legacy_store.settle_checkpoint_delivery(
            "session-1",
            expected_revision=0,
            expected_source_snapshot=legacy_source["source_snapshot"],
            checkpoint_candidate=legacy_checkpoint,
            receipt_id="legacy-delivery",
            source_ids=legacy_ids,
            hashes={"source_snapshot": legacy_source["source_snapshot"]},
            counts={"represented_source_group_count": 1},
            recorded_at="2026-09-28T00:01:00Z",
            source_reread=lambda _session_id: copy.deepcopy(legacy_source),
        )
        self.assertEqual(legacy_settlement["status"], "applied")

        # This is deliberately the unchanged v2 store decoder.  The regression
        # proves a later v3 table/receipt does not become part of its read path.
        before = legacy_store.read_continuity("session-1", legacy_source)
        with legacy_store._connect() as connection:
            legacy_row_before = tuple(
                connection.execute(
                    "SELECT * FROM continuity_checkpoints WHERE session_id = ?",
                    ("session-1",),
                ).fetchone()
            )
            legacy_receipt_before = legacy_store._decode_receipt(
                connection.execute(
                    "SELECT * FROM continuity_receipts WHERE receipt_id = ?",
                    ("legacy-delivery",),
                ).fetchone()
            )

        initialize_store(legacy_store)
        v3_candidate = _checkpoint()
        v3_settlement = settle_checkpoint(
            legacy_store,
            "session-1",
            expected_revision=0,
            checkpoint_candidate=v3_candidate,
            receipt_id="v3-delivery",
            validate_checkpoint_source=lambda checkpoint: copy.deepcopy(checkpoint),
            source_ids=v3_candidate["recent_bridge"]["source_group_ids"],
            hashes={"provider_body": "a" * 64},
            counts={"provider_request_count": 1},
            recorded_at="2026-09-28T00:02:00Z",
        )
        self.assertEqual(v3_settlement["status"], "stored_unvalidated")

        reopened = ContinuityMetadataStore(path)
        after = reopened.read_continuity("session-1", legacy_source)
        self.assertEqual(after["status"], "ready")
        self.assertEqual(before["status"], "ready")
        for field in (
            "revision",
            "source_snapshot",
            "source_prefix_ids",
            "checkpoint",
            "checkpoint_sha256",
            "updated_at",
            "source_advanced",
        ):
            with self.subTest(v2_checkpoint_field=field):
                self.assertEqual(after["state"][field], before["state"][field])

        with reopened._connect() as connection:
            legacy_row_after = tuple(
                connection.execute(
                    "SELECT * FROM continuity_checkpoints WHERE session_id = ?",
                    ("session-1",),
                ).fetchone()
            )
            legacy_receipt_after = reopened._decode_receipt(
                connection.execute(
                    "SELECT * FROM continuity_receipts WHERE receipt_id = ?",
                    ("legacy-delivery",),
                ).fetchone()
            )
            receipt_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT receipt_id FROM continuity_receipts ORDER BY receipt_id"
                )
            ]
        self.assertEqual(legacy_row_after, legacy_row_before)
        for field in (
            "receipt_id",
            "session_id",
            "kind",
            "status",
            "source_ids",
            "hashes",
            "counts",
            "recorded_at",
        ):
            with self.subTest(v2_receipt_field=field):
                self.assertEqual(
                    legacy_receipt_after[field], legacy_receipt_before[field]
                )
        self.assertEqual(receipt_ids, ["legacy-delivery", "v3:v3-delivery"])

        v3_readback = read_checkpoint(
            reopened,
            "session-1",
            validate_checkpoint_source=lambda checkpoint: copy.deepcopy(checkpoint),
        )
        self.assertEqual(v3_readback["status"], "ready")
        self.assertEqual(v3_readback["state"]["checkpoint"], v3_candidate)

    def test_round_trip_preserves_exact_checkpoint_and_body_free_receipt(self) -> None:
        calls: list[str] = []

        def validate(checkpoint: dict) -> dict:
            calls.append(checkpoint["revision_id"])
            return copy.deepcopy(checkpoint)

        settled = self.settle(
            "round-trip", validate_checkpoint_source=validate
        )
        readback = read_checkpoint(
            self.store,
            "session-1",
            validate_checkpoint_source=validate,
        )

        self.assertEqual(settled["status"], "stored_unvalidated")
        self.assertEqual(readback["status"], "ready")
        self.assertEqual(readback["state"]["checkpoint"], self.candidate)
        self.assertEqual(calls, [self.candidate["revision_id"]] * 2)
        with sqlite3.connect(self.path) as connection:
            stored = json.loads(
                connection.execute(
                    "SELECT checkpoint_json FROM continuity_checkpoints_v3"
                ).fetchone()[0]
            )
        self.assertEqual(stored, self.candidate)
        receipt = self.receipts()[0]
        self.assertEqual(receipt["receipt_id"], "v3:round-trip")
        self.assertEqual(
            receipt["status"], "delivered_checkpoint_stored_unvalidated"
        )
        self.assertEqual(
            receipt["source_ids"],
            self.candidate["recent_bridge"]["source_group_ids"],
        )
        self.assertEqual(
            receipt["hashes"]["checkpoint_revision_sha256"],
            self.candidate["revision_id"].removeprefix("tcr_"),
        )
        self.assertEqual(receipt["counts"]["checkpoint_revision"], 1)
        self.assertNotIn(self.candidate["recent_bridge"]["body"], repr(receipt))

    def test_source_race_can_store_but_next_read_rejects_body(self) -> None:
        current = {"valid": True}

        def validate(checkpoint: dict) -> dict:
            if not current["valid"]:
                raise ValueError("source changed")
            return copy.deepcopy(checkpoint)

        settled = self.settle(
            "raced-source", validate_checkpoint_source=validate
        )
        current["valid"] = False
        readback = read_checkpoint(
            self.store,
            "session-1",
            validate_checkpoint_source=validate,
        )

        self.assertEqual(settled["status"], "stored_unvalidated")
        self.assertEqual(readback["status"], "unavailable")
        self.assertEqual(
            readback["error"], "thread_continuity_checkpoint_source_invalid"
        )
        self.assertEqual(
            readback["state"],
            {
                "revision": 1,
                "revision_id": self.candidate["revision_id"],
                "storage_state": "stored_unvalidated",
            },
        )
        self.assertNotIn(self.candidate["recent_bridge"]["body"], repr(readback))

    def test_source_validation_conflict_still_records_delivery(self) -> None:
        def changed(_checkpoint: dict) -> dict:
            raise ValueError("source changed")

        result = self.settle(
            "source-conflict", validate_checkpoint_source=changed
        )

        self.assertEqual(result["status"], "conflict")
        self.assertTrue(result["receipt_recorded"])
        self.assertEqual(
            self.receipts()[0]["status"], "delivered_checkpoint_conflict"
        )
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM continuity_checkpoints_v3"
                ).fetchone()[0],
                0,
            )

    def test_two_candidates_have_one_cas_winner_without_retry(self) -> None:
        barrier = threading.Barrier(2)
        validation_calls: list[str] = []
        lock = threading.Lock()

        def validate(checkpoint: dict) -> dict:
            with lock:
                validation_calls.append(checkpoint["revision_id"])
            barrier.wait(timeout=2)
            return copy.deepcopy(checkpoint)

        def settle(index: int) -> dict:
            return self.settle(
                f"concurrent-{index}", validate_checkpoint_source=validate
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(settle, range(2)))

        self.assertEqual(
            [result["status"] for result in results].count("stored_unvalidated"),
            1,
        )
        self.assertEqual(
            [result["status"] for result in results].count("conflict"), 1
        )
        self.assertEqual(len(validation_calls), 2)
        self.assertEqual(
            sorted(receipt["status"] for receipt in self.receipts()),
            [
                "delivered_checkpoint_conflict",
                "delivered_checkpoint_stored_unvalidated",
            ],
        )

    def test_checkpoint_and_receipt_roll_back_together(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_v3_receipt
                BEFORE INSERT ON continuity_receipts
                WHEN NEW.receipt_id LIKE 'v3:%'
                BEGIN
                    SELECT RAISE(ABORT, 'receipt rejected');
                END
                """
            )

        result = self.settle("receipt-rejected")

        self.assertEqual(result["error"], "checkpoint_v3_storage_failed")
        self.assertFalse(result["receipt_recorded"])
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM continuity_checkpoints_v3"
                ).fetchone()[0],
                0,
            )

    def test_write_and_read_use_the_same_utf8_byte_budget(self) -> None:
        encoded_size = len(
            checkpoint_store_v3._json_text(self.candidate).encode("utf-8")
        )
        for budget in (encoded_size - 1, encoded_size):
            with self.subTest(budget=budget):
                path = Path(self.temp.name) / f"budget-{budget}.sqlite3"
                store = ContinuityMetadataStore(
                    path, max_checkpoint_bytes=budget
                )
                initialize_store(store)
                result = settle_checkpoint(
                    store,
                    "session-1",
                    expected_revision=0,
                    checkpoint_candidate=self.candidate,
                    receipt_id="budget",
                    validate_checkpoint_source=self.valid,
                    source_ids=self.candidate["recent_bridge"][
                        "source_group_ids"
                    ],
                )
                readback = read_checkpoint(
                    store,
                    "session-1",
                    validate_checkpoint_source=self.valid,
                )
                if budget < encoded_size:
                    self.assertEqual(
                        result["error"], "checkpoint_v3_byte_limit_exceeded"
                    )
                    self.assertEqual(readback["status"], "absent")
                else:
                    self.assertEqual(result["status"], "stored_unvalidated")
                    self.assertEqual(readback["status"], "ready")

        path = Path(self.temp.name) / "oversize-read.sqlite3"
        store = ContinuityMetadataStore(
            path, max_checkpoint_bytes=encoded_size
        )
        initialize_store(store)
        result = settle_checkpoint(
            store,
            "session-1",
            expected_revision=0,
            checkpoint_candidate=self.candidate,
            receipt_id="oversize-read",
            validate_checkpoint_source=self.valid,
            source_ids=self.candidate["recent_bridge"]["source_group_ids"],
        )
        self.assertTrue(result["ok"])
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE continuity_checkpoints_v3 SET checkpoint_json = ?",
                ("x" * (encoded_size + 1),),
            )
        calls: list[dict] = []
        readback = read_checkpoint(
            store,
            "session-1",
            validate_checkpoint_source=lambda value: calls.append(value) or value,
        )
        self.assertEqual(readback["status"], "unavailable")
        self.assertEqual(
            readback["error"], "checkpoint_v3_byte_limit_exceeded"
        )
        self.assertEqual(calls, [])

    def test_v2_and_v3_receipt_ids_do_not_collide_and_v3_is_idempotent(self) -> None:
        self.store.record_receipt(
            receipt_id="same-delivery",
            session_id="session-1",
            kind="delivery",
            status="delivered_checkpoint_applied",
        )
        first = self.settle("same-delivery")
        replay = self.settle("same-delivery")

        self.assertEqual(first["status"], "stored_unvalidated")
        self.assertEqual(replay["status"], "stored_unvalidated")
        self.assertTrue(replay["idempotent"])
        self.assertEqual(
            [receipt["receipt_id"] for receipt in self.receipts()],
            ["same-delivery", "v3:same-delivery"],
        )

    def test_terminal_plan_deliveries_record_v3_outcomes_without_another_cas(self) -> None:
        first = self.settle("initial")
        results = [
            record_delivery(
                self.store,
                "session-1",
                checkpoint=self.candidate,
                receipt_id=f"later-{outcome}",
                outcome=outcome,
                source_ids=self.candidate["recent_bridge"]["source_group_ids"],
                hashes={"provider_body": "a" * 64},
                counts={"provider_request_count": 1},
            )
            for outcome in ("unchanged", "conflict", "failed")
        ]

        self.assertEqual(first["status"], "stored_unvalidated")
        self.assertEqual(
            [result["status"] for result in results],
            ["unchanged", "conflict", "failed"],
        )
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT revision FROM continuity_checkpoints_v3"
                ).fetchone()[0],
                1,
            )
        self.assertEqual(
            {
                receipt["receipt_id"]: receipt["status"]
                for receipt in self.receipts()
            },
            {
                "v3:initial": "delivered_checkpoint_stored_unvalidated",
                "v3:later-unchanged": "delivered_checkpoint_unchanged",
                "v3:later-conflict": "delivered_checkpoint_conflict",
                "v3:later-failed": "delivered_checkpoint_failed",
            },
        )

    def test_absent_v3_reports_legacy_identity_without_loading_v2_body(self) -> None:
        path = Path(self.temp.name) / "legacy-presence.sqlite3"
        store = ContinuityMetadataStore(path, max_checkpoint_bytes=512)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO continuity_checkpoints VALUES (?,?,?,?,?,?,?)",
                (
                    "session-1",
                    7,
                    "d" * 64,
                    "[]",
                    "PRIVATE" * 10_000,
                    "e" * 64,
                    "2026-09-28T00:00:00+00:00",
                ),
            )
        initialize_store(store)

        result = read_checkpoint(
            store,
            "session-1",
            validate_checkpoint_source=lambda _value: self.fail(
                "absent v3 must not validate or load v2"
            ),
        )

        self.assertEqual(result["status"], "absent")
        self.assertEqual(result["state"], {"legacy_checkpoint_present": True})
        self.assertNotIn("PRIVATE", repr(result))

    def test_status_is_metadata_only_and_does_not_normalize_checkpoint(self) -> None:
        empty_path = Path(self.temp.name) / "status-no-v3.sqlite3"
        empty_store = ContinuityMetadataStore(empty_path)
        self.assertEqual(
            status_checkpoint(empty_store, "session-1"),
            {
                "checkpoint_count": 0,
                "checkpoint": {},
                "body_included": False,
                "error": "",
            },
        )
        self.assertTrue(self.settle("status")["ok"])
        original = checkpoint_store_v3.normalize_thread_continuity_checkpoint_v3
        checkpoint_store_v3.normalize_thread_continuity_checkpoint_v3 = (
            lambda *_args, **_kwargs: self.fail("status must not normalize body")
        )
        try:
            status = status_checkpoint(self.store, "session-1")
        finally:
            checkpoint_store_v3.normalize_thread_continuity_checkpoint_v3 = original

        self.assertEqual(status["checkpoint_count"], 1)
        self.assertEqual(status["checkpoint"]["revision"], 1)
        self.assertEqual(
            status["checkpoint"]["revision_id"], self.candidate["revision_id"]
        )
        self.assertEqual(status["checkpoint"]["status"], "stored_unvalidated")
        self.assertGreater(status["checkpoint"]["stored_bytes"], 0)
        self.assertFalse(status["body_included"])
        self.assertNotIn(self.candidate["recent_bridge"]["body"], repr(status))

    def test_source_invalid_revision_can_be_rebuilt_with_next_cas_revision(self) -> None:
        first = self.settle("initial")
        stale = read_checkpoint(
            self.store,
            "session-1",
            validate_checkpoint_source=lambda _value: (_ for _ in ()).throw(
                ValueError("source changed")
            ),
        )
        rebuilt = _checkpoint(
            previous=self.candidate,
            rebuilt=True,
            body="replacement bridge",
            suffix="4",
        )

        result = self.settle(
            "rebuilt",
            expected_revision=stale["state"]["revision"],
            checkpoint_candidate=rebuilt,
            source_ids=rebuilt["recent_bridge"]["source_group_ids"],
        )

        self.assertEqual(first["revision"], 1)
        self.assertEqual(result["status"], "stored_unvalidated")
        self.assertEqual(result["revision"], 2)
        self.assertEqual(rebuilt["lineage_status"], "rebuilt")
        self.assertEqual(
            rebuilt["predecessor_revision_id"], self.candidate["revision_id"]
        )


if __name__ == "__main__":
    unittest.main()
