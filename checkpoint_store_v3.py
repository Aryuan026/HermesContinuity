"""Bounded SQLite storage for conditionally reusable continuity checkpoints.

The canonical transcript and its source proof remain owned by Hermes.  This
module stores only a generated v3 checkpoint plus body-free delivery receipts.
It deliberately validates source state before, not inside, the plugin SQLite
transaction: a successful CAS is therefore ``stored_unvalidated`` until every
consumer validates the checkpoint against a fresh Hermes source snapshot.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
from typing import Any, Callable, Dict, Mapping, Sequence

from .checkpoint_v3 import normalize_thread_continuity_checkpoint_v3


_TABLE = "continuity_checkpoints_v3"
_RECEIPT_PREFIX = "v3:"
_MAX_BRIDGE_SOURCE_IDS = 2_048
_TABLE_COLUMNS = (
    "session_id",
    "revision",
    "revision_id",
    "checkpoint_json",
    "checkpoint_sha256",
    "updated_at",
)
_RECEIPT_OUTCOMES = {
    "delivered_checkpoint_stored_unvalidated": "stored_unvalidated",
    "delivered_checkpoint_unchanged": "unchanged",
    "delivered_checkpoint_conflict": "conflict",
    "delivered_checkpoint_failed": "failed",
}


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _max_checkpoint_bytes(store: Any) -> int:
    value = getattr(store, "max_checkpoint_bytes", None)
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        raise ValueError("max_checkpoint_bytes_invalid")
    # V3 admission reserves the protocol ceiling before reading. A legacy
    # setting may lower it, but cannot enlarge a live v3 allocation afterward.
    return min(value, 1024 * 1024)


def initialize_checkpoint_store_v3(store: Any) -> None:
    """Explicitly add the independent v3 table to an existing metadata store."""

    with closing(store._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    session_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    revision_id TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    checkpoint_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = tuple(
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({_TABLE})")
            )
            if columns != _TABLE_COLUMNS:
                raise ValueError("checkpoint_v3_table_incompatible")
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _bounded_checkpoint_row(
    store: Any,
    connection: sqlite3.Connection,
    session_id: str,
) -> sqlite3.Row | Mapping[str, Any] | None:
    """Read one JSON value only when the same SQL row is within its byte cap."""

    budget = _max_checkpoint_bytes(store)
    old_limit = connection.setlimit(
        sqlite3.SQLITE_LIMIT_LENGTH,
        min(2**31 - 1, budget + 4096),
    )
    try:
        return connection.execute(
            f"SELECT revision, revision_id, checkpoint_sha256, updated_at, "
            "CASE WHEN length(CAST(checkpoint_json AS BLOB)) <= :budget "
            "THEN checkpoint_json END AS checkpoint_json "
            f"FROM {_TABLE} WHERE session_id = :session",
            {"budget": budget, "session": session_id},
        ).fetchone()
    except sqlite3.DataError:
        return {"checkpoint_json": None}
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, old_limit)


def _decode_checkpoint_row(
    row: sqlite3.Row | Mapping[str, Any] | None,
) -> Dict[str, Any]:
    if row is None:
        return {}
    if row["checkpoint_json"] is None:
        return {"error": "checkpoint_v3_byte_limit_exceeded"}
    try:
        decoded = json.loads(row["checkpoint_json"])
        normalized = normalize_thread_continuity_checkpoint_v3(decoded)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"error": "checkpoint_v3_state_corrupt"}
    if (
        normalized != decoded
        or row["checkpoint_sha256"] != _sha256(normalized)
        or row["revision"] != normalized["revision"]
        or row["revision_id"] != normalized["revision_id"]
    ):
        return {"error": "checkpoint_v3_state_corrupt"}
    return {
        "revision": normalized["revision"],
        "revision_id": normalized["revision_id"],
        "checkpoint": normalized,
        "checkpoint_sha256": str(row["checkpoint_sha256"]),
        "updated_at": str(row["updated_at"]),
    }


def _validated_checkpoint(
    checkpoint: Mapping[str, Any],
    validate_checkpoint_source: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> Dict[str, Any]:
    validated = validate_checkpoint_source(checkpoint)
    if not isinstance(validated, Mapping) or dict(validated) != dict(checkpoint):
        raise ValueError("thread_continuity_checkpoint_source_invalid")
    return dict(validated)


def _unavailable_identity(state: Mapping[str, Any]) -> Dict[str, Any]:
    if "revision" not in state or "revision_id" not in state:
        return {}
    return {
        "revision": state["revision"],
        "revision_id": state["revision_id"],
        "storage_state": "stored_unvalidated",
    }


def read_checkpoint_v3(
    store: Any,
    session_id: str,
    *,
    validate_checkpoint_source: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> Dict[str, Any]:
    """Read and validate one v3 checkpoint against a fresh source snapshot."""

    try:
        session_id = store._code(session_id, "session_id")
    except (AttributeError, TypeError, ValueError):
        return {"status": "unavailable", "state": {}, "error": "checkpoint_v3_input_invalid"}
    try:
        with closing(store._connect()) as connection:
            row = _bounded_checkpoint_row(store, connection, session_id)
            legacy_checkpoint_present = bool(
                row is None
                and connection.execute(
                    "SELECT 1 FROM continuity_checkpoints "
                    "WHERE session_id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
            )
    except sqlite3.Error:
        return {"status": "unavailable", "state": {}, "error": "checkpoint_v3_storage_failed"}
    if row is None:
        return {
            "status": "absent",
            "state": (
                {"legacy_checkpoint_present": True}
                if legacy_checkpoint_present
                else {}
            ),
            "error": "",
        }
    state = _decode_checkpoint_row(row)
    if state.get("error"):
        return {"status": "unavailable", "state": {}, "error": state["error"]}
    try:
        checkpoint = _validated_checkpoint(
            state["checkpoint"], validate_checkpoint_source
        )
    except Exception:
        return {
            "status": "unavailable",
            "state": _unavailable_identity(state),
            "error": "thread_continuity_checkpoint_source_invalid",
        }
    return {
        "status": "ready",
        "state": {**state, "checkpoint": checkpoint},
        "error": "",
    }


def checkpoint_v3_status(store: Any, session_id: str = "") -> Dict[str, Any]:
    """Report v3 storage metadata without decoding or validating body state."""

    session_id = str(session_id or "").strip()
    try:
        if session_id:
            session_id = store._code(session_id, "session_id")
        with closing(store._connect()) as connection:
            table_exists = bool(
                connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (_TABLE,),
                ).fetchone()
            )
            if not table_exists:
                return {
                    "checkpoint_count": 0,
                    "checkpoint": {},
                    "body_included": False,
                    "error": "",
                }
            checkpoint_count = int(
                connection.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0]
            )
            row = None
            if session_id:
                row = connection.execute(
                    f"SELECT revision,revision_id,updated_at,"
                    "length(CAST(checkpoint_json AS BLOB)) AS stored_bytes "
                    f"FROM {_TABLE} WHERE session_id=?",
                    (session_id,),
                ).fetchone()
    except (AttributeError, TypeError, ValueError):
        return {
            "checkpoint_count": 0,
            "checkpoint": {},
            "body_included": False,
            "error": "checkpoint_v3_input_invalid",
        }
    except sqlite3.Error:
        return {
            "checkpoint_count": 0,
            "checkpoint": {},
            "body_included": False,
            "error": "checkpoint_v3_storage_failed",
        }
    checkpoint = dict(row) if row is not None else {}
    if checkpoint:
        checkpoint["status"] = "stored_unvalidated"
    return {
        "checkpoint_count": checkpoint_count,
        "checkpoint": checkpoint,
        "body_included": False,
        "error": "",
    }


def _namespaced_receipt_id(receipt_id: Any) -> str:
    return f"{_RECEIPT_PREFIX}{str(receipt_id or '').strip()}"


def _same_delivery(existing: Mapping[str, Any], receipt: Mapping[str, Any]) -> bool:
    return bool(
        existing.get("session_id") == receipt["session_id"]
        and existing.get("kind") == receipt["kind"]
        and existing.get("source_ids") == receipt["source_ids"]
        and existing.get("hashes") == receipt["hashes"]
        and existing.get("counts") == receipt["counts"]
    )


def _receipt_result(existing: Mapping[str, Any]) -> Dict[str, Any]:
    outcome = _RECEIPT_OUTCOMES.get(str(existing.get("status") or ""))
    if outcome is None:
        return {
            "ok": False,
            "status": "failed",
            "error": "checkpoint_v3_settlement_receipt_conflict",
            "receipt_recorded": False,
        }
    result = {
        "ok": outcome in {"stored_unvalidated", "unchanged"},
        "status": outcome,
        "error": (
            ""
            if outcome in {"stored_unvalidated", "unchanged"}
            else "thread_continuity_checkpoint_source_conflict"
            if outcome == "conflict"
            else "checkpoint_v3_settlement_failed"
        ),
        "receipt_recorded": True,
        "idempotent": True,
    }
    revision = existing.get("counts", {}).get("checkpoint_revision")
    revision_hash = existing.get("hashes", {}).get("checkpoint_revision_sha256")
    if (
        outcome in {"stored_unvalidated", "unchanged"}
        and type(revision) is int
        and isinstance(revision_hash, str)
        and len(revision_hash) == 64
    ):
        result.update(revision=revision, revision_id=f"tcr_{revision_hash}")
    return result


def record_checkpoint_delivery_v3(
    store: Any,
    session_id: str,
    *,
    checkpoint: Mapping[str, Any],
    receipt_id: str,
    outcome: str,
    source_ids: Sequence[str] = (),
    hashes: Mapping[str, str] | None = None,
    counts: Mapping[str, int] | None = None,
    recorded_at: str | None = None,
) -> Dict[str, Any]:
    """Record a later physical delivery after this plan's CAS is terminal."""

    try:
        if outcome not in {"unchanged", "conflict", "failed"}:
            raise ValueError("checkpoint_v3_delivery_outcome_invalid")
        if isinstance(source_ids, (str, bytes)):
            raise ValueError("source_ids_invalid")
        session_id = store._code(session_id, "session_id")
        normalized = normalize_thread_continuity_checkpoint_v3(dict(checkpoint))
        if normalized != dict(checkpoint):
            raise ValueError("checkpoint_invalid")
        receipt_source_ids = list(source_ids)
        bridge_ids = list(normalized["recent_bridge"]["source_group_ids"])
        if (
            receipt_source_ids != bridge_ids
            or len(receipt_source_ids) > _MAX_BRIDGE_SOURCE_IDS
        ):
            raise ValueError("source_ids_invalid")
        safe_hashes = dict(hashes or {})
        safe_hashes.update(
            checkpoint_revision_sha256=normalized["revision_id"].removeprefix(
                "tcr_"
            ),
            checkpoint_sha256=_sha256(normalized),
            source_proof_sha256=_sha256(normalized["source_proof"]),
        )
        safe_counts = dict(counts or {})
        safe_counts.update(
            checkpoint_revision=normalized["revision"],
            retired_group_count=normalized["retirement_cursor"]["group_count"],
            bridge_group_count=len(bridge_ids),
        )
        receipt = store._receipt_row(
            receipt_id=_namespaced_receipt_id(receipt_id),
            session_id=session_id,
            kind="delivery",
            status=f"delivered_checkpoint_{outcome}",
            source_ids=receipt_source_ids,
            hashes=safe_hashes,
            counts=safe_counts,
            recorded_at=recorded_at,
        )
    except (AttributeError, TypeError, ValueError):
        return {
            "ok": False,
            "status": "failed",
            "error": "checkpoint_v3_settlement_input_invalid",
            "receipt_recorded": False,
        }

    connection: sqlite3.Connection | None = None
    try:
        connection = store._connect()
        connection.execute("BEGIN IMMEDIATE")
        existing_row = connection.execute(
            "SELECT * FROM continuity_receipts WHERE receipt_id = ?",
            (receipt["receipt_id"],),
        ).fetchone()
        if existing_row is not None:
            existing = store._decode_receipt(existing_row)
            if existing is None or not _same_delivery(existing, receipt):
                connection.rollback()
                return {
                    "ok": False,
                    "status": "failed",
                    "error": "checkpoint_v3_settlement_receipt_conflict",
                    "receipt_recorded": False,
                }
            connection.commit()
            return _receipt_result(existing)
        store._insert_receipt(connection, receipt)
        connection.commit()
        result = _receipt_result(receipt)
        result["idempotent"] = False
        return result
    except sqlite3.Error:
        if connection is not None:
            connection.rollback()
        return {
            "ok": False,
            "status": "failed",
            "error": "checkpoint_v3_storage_failed",
            "receipt_recorded": False,
        }
    finally:
        if connection is not None:
            connection.close()


def _write_checkpoint(
    store: Any,
    connection: sqlite3.Connection,
    session_id: str,
    checkpoint: Mapping[str, Any],
    checkpoint_json: str,
    checkpoint_sha256: str,
    updated_at: str,
) -> None:
    budget = _max_checkpoint_bytes(store)
    old_limit = connection.setlimit(
        sqlite3.SQLITE_LIMIT_LENGTH,
        min(2**31 - 1, budget + 4096),
    )
    try:
        connection.execute(
            f"""
            INSERT INTO {_TABLE} (
                session_id, revision, revision_id, checkpoint_json,
                checkpoint_sha256, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                revision = excluded.revision,
                revision_id = excluded.revision_id,
                checkpoint_json = excluded.checkpoint_json,
                checkpoint_sha256 = excluded.checkpoint_sha256,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                checkpoint["revision"],
                checkpoint["revision_id"],
                checkpoint_json,
                checkpoint_sha256,
                updated_at,
            ),
        )
    finally:
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, old_limit)


def settle_checkpoint_delivery_v3(
    store: Any,
    session_id: str,
    *,
    expected_revision: int,
    checkpoint_candidate: Mapping[str, Any],
    receipt_id: str,
    validate_checkpoint_source: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    source_ids: Sequence[str] = (),
    hashes: Mapping[str, str] | None = None,
    counts: Mapping[str, int] | None = None,
    recorded_at: str | None = None,
) -> Dict[str, Any]:
    """Settle delivery with one plugin-DB CAS and receipt transaction.

    Source validation intentionally precedes ``BEGIN IMMEDIATE`` because the
    source and metadata live in separately owned databases.  The stored result
    is conditional and every later read validates it again.
    """

    try:
        if isinstance(source_ids, (str, bytes)):
            raise ValueError("source_ids_invalid")
        receipt_source_ids = list(source_ids)
        if len(receipt_source_ids) > _MAX_BRIDGE_SOURCE_IDS:
            raise ValueError("source_ids_invalid")
    except (TypeError, ValueError):
        return {
            "ok": False,
            "status": "failed",
            "error": "checkpoint_v3_settlement_input_invalid",
            "receipt_recorded": False,
        }

    normalized: Dict[str, Any] | None = None
    structural_error = ""
    try:
        session_id = store._code(session_id, "session_id")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision_invalid")
        if not isinstance(checkpoint_candidate, Mapping):
            raise ValueError("checkpoint_candidate_invalid")
        normalized = normalize_thread_continuity_checkpoint_v3(
            dict(checkpoint_candidate)
        )
        if normalized != dict(checkpoint_candidate):
            raise ValueError("checkpoint_candidate_invalid")
    except (AttributeError, TypeError, ValueError):
        structural_error = "thread_continuity_checkpoint_invalid"

    safe_hashes = dict(hashes or {})
    safe_counts = dict(counts or {})
    if normalized is not None:
        bridge_ids = list(normalized["recent_bridge"]["source_group_ids"])
        if receipt_source_ids != bridge_ids or len(bridge_ids) > _MAX_BRIDGE_SOURCE_IDS:
            structural_error = "checkpoint_v3_receipt_source_ids_invalid"
        safe_hashes.update(
            checkpoint_revision_sha256=normalized["revision_id"].removeprefix(
                "tcr_"
            ),
            checkpoint_sha256=_sha256(normalized),
            source_proof_sha256=_sha256(normalized["source_proof"]),
        )
        safe_counts.update(
            checkpoint_revision=normalized["revision"],
            retired_group_count=normalized["retirement_cursor"]["group_count"],
            bridge_group_count=len(bridge_ids),
        )

    try:
        receipt = store._receipt_row(
            receipt_id=_namespaced_receipt_id(receipt_id),
            session_id=session_id,
            kind="delivery",
            status="delivered_checkpoint_failed",
            source_ids=receipt_source_ids,
            hashes=safe_hashes,
            counts=safe_counts,
            recorded_at=recorded_at,
        )
    except (AttributeError, TypeError, ValueError):
        return {
            "ok": False,
            "status": "failed",
            "error": "checkpoint_v3_settlement_input_invalid",
            "receipt_recorded": False,
        }

    validation_outcome = "failed" if structural_error else "stored_unvalidated"
    validation_error = structural_error
    if normalized is not None and not structural_error:
        try:
            _validated_checkpoint(normalized, validate_checkpoint_source)
        except ValueError:
            validation_outcome = "conflict"
            validation_error = "thread_continuity_checkpoint_source_conflict"
        except Exception:
            validation_outcome = "failed"
            validation_error = "checkpoint_v3_source_validation_failed"

    connection: sqlite3.Connection | None = None
    try:
        connection = store._connect()
        connection.execute("BEGIN IMMEDIATE")
        existing_row = connection.execute(
            "SELECT * FROM continuity_receipts WHERE receipt_id = ?",
            (receipt["receipt_id"],),
        ).fetchone()
        if existing_row is not None:
            existing = store._decode_receipt(existing_row)
            if existing is None or not _same_delivery(existing, receipt):
                connection.rollback()
                return {
                    "ok": False,
                    "status": "failed",
                    "error": "checkpoint_v3_settlement_receipt_conflict",
                    "receipt_recorded": False,
                }
            connection.commit()
            return _receipt_result(existing)

        outcome = validation_outcome
        error = validation_error
        encoded = ""
        encoded_sha256 = ""
        if outcome == "stored_unvalidated" and normalized is not None:
            row = _bounded_checkpoint_row(store, connection, session_id)
            state = _decode_checkpoint_row(row)
            if state.get("error"):
                outcome = "failed"
                error = state["error"]
            else:
                current_revision = int(state.get("revision") or 0)
                if current_revision != expected_revision:
                    outcome = "conflict"
                    error = "thread_continuity_revision_conflict"
                else:
                    previous = state.get("checkpoint")
                    try:
                        normalized = normalize_thread_continuity_checkpoint_v3(
                            normalized,
                            previous_state=(
                                previous if isinstance(previous, Mapping) else None
                            ),
                        )
                    except (TypeError, ValueError):
                        outcome = "failed"
                        error = "thread_continuity_checkpoint_invalid"
                    if (
                        outcome == "stored_unvalidated"
                        and normalized["revision"] != expected_revision + 1
                    ):
                        outcome = "failed"
                        error = "thread_continuity_checkpoint_invalid"
                    if outcome == "stored_unvalidated":
                        encoded = _json_text(normalized)
                        if len(encoded.encode("utf-8")) > _max_checkpoint_bytes(store):
                            outcome = "failed"
                            error = "checkpoint_v3_byte_limit_exceeded"
                        else:
                            encoded_sha256 = hashlib.sha256(
                                encoded.encode("utf-8")
                            ).hexdigest()

        if outcome == "stored_unvalidated" and normalized is not None:
            _write_checkpoint(
                store,
                connection,
                session_id,
                normalized,
                encoded,
                encoded_sha256,
                receipt["recorded_at"],
            )

        receipt["status"] = (
            "delivered_checkpoint_stored_unvalidated"
            if outcome == "stored_unvalidated"
            else "delivered_checkpoint_conflict"
            if outcome == "conflict"
            else "delivered_checkpoint_failed"
        )
        store._insert_receipt(connection, receipt)
        connection.commit()
        result = {
            "ok": outcome == "stored_unvalidated",
            "status": outcome,
            "error": error,
            "receipt_recorded": True,
            "idempotent": False,
        }
        if outcome == "stored_unvalidated" and normalized is not None:
            result.update(
                revision=normalized["revision"],
                revision_id=normalized["revision_id"],
            )
        return result
    except sqlite3.Error:
        if connection is not None:
            connection.rollback()
        return {
            "ok": False,
            "status": "failed",
            "error": "checkpoint_v3_storage_failed",
            "receipt_recorded": False,
        }
    finally:
        if connection is not None:
            connection.close()
