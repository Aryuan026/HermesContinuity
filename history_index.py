"""Body-free group positions over the host's bounded canonical history index.

The canonical database remains the only transcript. Preparation may walk its
history, but neither this database nor a Python cache keeps those bodies.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import json
import threading
import time
import uuid

from .hermes_adapter import _json_text, _sha256, _project_canonical_source
from .context_compactor import _group_fingerprint
from .resource_budget import PREPARATION_LOCK, PREPARATION_WORKSETS


GROUP_RULE = "hermes_continuity_group_index.v1"


class _Occurrences:
    """Only one page of counter changes lives in Python; history lives in SQL."""

    def __init__(self, connection, session_id, kind, before_position):
        self.connection = connection
        self.session_id = session_id
        self.kind = kind
        self.before_position = before_position
        self.values = {}
        self.changes = []

    def __getitem__(self, key):
        key = _sha256(key)
        if key not in self.values:
            row = self.connection.execute(
                "SELECT occurrence FROM continuity_group_occurrences "
                "WHERE session_id=? AND kind=? AND identity_hash=? AND position<=? "
                "ORDER BY position DESC LIMIT 1",
                (self.session_id, self.kind, key, self.before_position),
            ).fetchone()
            self.values[key] = row[0] if row else 0
        return self.values[key]

    def __setitem__(self, key, value):
        key = _sha256(key)
        self.values[key] = value
        self.changes.append((key, value))

    def commit(self, positions):
        if len(positions) != len(self.changes):
            raise ValueError("group_occurrence_boundary_invalid")
        self.connection.executemany(
            "INSERT INTO continuity_group_occurrences VALUES (?,?,?,?,?)",
            [(self.session_id, self.kind, position, key, value)
             for position, (key, value) in zip(positions, self.changes)],
        )


class ContinuityHistoryIndex:
    def __init__(self, session_db, metadata_store):
        self.db = session_db
        self.store = metadata_store
        self.owner_id = "continuity-" + uuid.uuid4().hex
        self.activation_epoch = None
        self._closed = False
        self._wake = threading.Condition()
        self._pending = dict()
        self._worker = None
        self._last_status = {}
        self._completed = 0
        self._listeners = {}
        self._pending_group = None
        with closing(self.store._connect()) as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS continuity_group_progress (
                    session_id TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    group_count INTEGER NOT NULL,
                    prefix_json TEXT NOT NULL,
                    head_json TEXT NOT NULL,
                    invalid_from INTEGER,
                    ready INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS continuity_group_index (
                    session_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    group_id TEXT NOT NULL,
                    start_position INTEGER NOT NULL,
                    end_position INTEGER NOT NULL,
                    event_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    prefix_json TEXT NOT NULL,
                    compacted INTEGER NOT NULL,
                    stored_bytes INTEGER NOT NULL,
                    PRIMARY KEY(session_id,ordinal),
                    UNIQUE(session_id,group_id)
                );
                CREATE INDEX IF NOT EXISTS continuity_group_end
                    ON continuity_group_index(session_id,end_position);
                CREATE INDEX IF NOT EXISTS continuity_group_uncompacted
                    ON continuity_group_index(session_id,compacted,ordinal);
                CREATE TABLE IF NOT EXISTS continuity_group_occurrences (
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    identity_hash TEXT NOT NULL,
                    occurrence INTEGER NOT NULL,
                    PRIMARY KEY(session_id,kind,position)
                );
                CREATE INDEX IF NOT EXISTS continuity_group_occurrence_lookup
                    ON continuity_group_occurrences(session_id,kind,identity_hash,position);
                CREATE INDEX IF NOT EXISTS continuity_group_occurrence_position
                    ON continuity_group_occurrences(session_id,position);
            """)

    def close(self):
        with self._wake:
            self._closed = True
            self._pending.clear()
            listeners = list(self._listeners.values())
            self._listeners.clear()
            self._wake.notify_all()
        for listener in listeners:
            listener.close()
        if self._worker is not None:
            self._worker.join()
        self._pending_group = None
        PREPARATION_WORKSETS.release(self.owner_id)

    def request(self, session_id):
        with self._wake:
            if self._closed:
                return "closed"
            if session_id not in self._pending and len(self._pending) >= 32:
                return "busy"
            register = getattr(self.db, "register_history_listener", None)
            if callable(register) and session_id not in self._listeners:
                if len(self._listeners) == 32:
                    self._listeners.pop(next(iter(self._listeners))).close()
                self._listeners[session_id] = register(
                    session_id, lambda domain, _tail: self.request(domain))
            self._pending[session_id] = None
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True,
                                                name="continuity-history-prepare")
                self._worker.start()
            self._wake.notify()
        return "pending"

    def status(self, session_id=""):
        with self._wake:
            result = self._last_status.get(session_id, {})
            return {"status": result.get("status", "idle"),
                    "reason": result.get("reason", ""),
                    "queued_domains": len(self._pending), "closed": self._closed,
                    "body_included": False}

    def _run(self):
        while True:
            with self._wake:
                while not self._pending and not self._closed:
                    self._wake.wait()
                if self._closed:
                    return
                session_id = (self._pending_group["session_id"]
                              if self._pending_group is not None
                              and self._pending_group["session_id"] in self._pending
                              else next(iter(self._pending)))
                self._pending.pop(session_id)
            try:
                with PREPARATION_LOCK:
                    result = self.prepare_step(session_id)
            except Exception:
                result = {"status": "fault", "reason": "history_preparation_failed"}
            with self._wake:
                self._last_status[session_id] = result
                # Bound diagnostics as well as wakeups. No transcript is retained.
                if len(self._last_status) > 32:
                    self._last_status.pop(next(iter(self._last_status)))
                if (result.get("status") == "progress" and not self._closed
                        and (session_id in self._pending or len(self._pending) < 32)):
                    self._pending[session_id] = None
                self._completed += 1
                self._wake.notify_all()

    @staticmethod
    def _cursor(target, after_position):
        from hermes_state_history import make_history_cursor
        return make_history_cursor(target, after_position=after_position)

    def _page(self, session_id, target, position, max_rows=256, max_bytes=4*1024*1024):
        return self.db.read_history_page(
            session_id, target=target, cursor=self._cursor(target, position),
            max_rows=max_rows, max_bytes=max_bytes,
        )

    def _prefix(self, target, descriptor):
        return {**target, "end_anchor": descriptor["through_anchor"],
                "canonical_count": descriptor["canonical_count"],
                "prefix_hash": descriptor["prefix_hash"]}

    def _discard_suffix(self, connection, session_id, position):
        """Delete only bounded index chunks; canonical rows are never touched."""
        remaining = False
        for table, column in (("continuity_group_index", "end_position"),
                              ("continuity_group_occurrences", "position")):
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} "
                f"WHERE session_id=? AND {column}>? LIMIT 256)", (session_id, position))
            remaining |= cursor.rowcount == 256
        return remaining

    def prepare_step(self, session_id):
        """A finite preparation quantum, also callable by isolated tests."""
        if self._closed:
            return {"status": "closed"}
        if not PREPARATION_WORKSETS.acquire(self.owner_id, 8*1024*1024):
            return {"status": "busy", "reason": "preparation_workset_busy"}
        try:
            result = self._prepare_step(session_id)
            if result.get("status") != "progress":
                self._pending_group = None
            return result
        except BaseException:
            self._pending_group = None
            raise
        finally:
            if self._pending_group is None:
                PREPARATION_WORKSETS.release(self.owner_id)

    def _prepare_step(self, session_id):
        prepared = self.db.prepare_history_step(
            session_id, owner_id=self.owner_id, activation_epoch=self.activation_epoch,
            max_pages=8, deadline_ms=50,
        )
        if prepared.get("activation_epoch"):
            self.activation_epoch = prepared["activation_epoch"]
        if prepared.get("status") != "ready":
            return prepared
        page_allowance = 8 - prepared.get("pages_processed", 0)
        if page_allowance <= 0:
            return {"status": "progress", "reason": "canonical_history_prepared"}
        target = prepared["head_token"]
        from .checkpoint_v3 import (
            thread_continuity_group_root_seed,
            extend_thread_continuity_group_root,
        )
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            progress = connection.execute(
                "SELECT * FROM continuity_group_progress WHERE session_id=?", (session_id,)
            ).fetchone()
            empty = self.db.seal_history_prefix(
                session_id, activation_epoch=self.activation_epoch, end_anchor=None)
            if empty.get("status") != "valid":
                return {"status": "progress", "reason": "history_seal_pending"}
            empty_token = empty["token"]
            empty_prefix = {
                "schema": "thread_continuity_prefix_descriptor.v1", "through_anchor": "",
                "canonical_count": 0, "group_count": 0, "prefix_hash": empty_token["prefix_hash"],
                "group_root": thread_continuity_group_root_seed(
                    domain_id=target["domain_id"], grouping_rule_version=GROUP_RULE),
            }
            if progress is None:
                connection.execute("INSERT INTO continuity_group_progress VALUES (?,?,?,?,?,NULL,0)",
                                   (session_id, 0, 0, _json_text(empty_prefix), "{}"))
                progress = connection.execute(
                    "SELECT * FROM continuity_group_progress WHERE session_id=?", (session_id,)
                ).fetchone()
            prefix = json.loads(progress["prefix_json"])
            old_head = json.loads(progress["head_json"])
            invalid_from = progress["invalid_from"]
            if old_head and invalid_from is None:
                validation = self.db.validate_history_prefix(old_head)
                if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
                    if validation.get("status") == "pending":
                        return {"status": "progress", "reason": "history_validation_pending"}
                    changed_at = validation.get("invalidated_from_position") or 1
                    before = connection.execute(
                        "SELECT prefix_json,end_position,ordinal FROM continuity_group_index "
                        "WHERE session_id=? AND end_position<? ORDER BY end_position DESC LIMIT 1",
                        (session_id, changed_at),
                    ).fetchone()
                    prefix = json.loads(before["prefix_json"]) if before else empty_prefix
                    invalid_from = before["end_position"] if before else 0
                    connection.execute(
                        "UPDATE continuity_group_progress SET position=?,group_count=?,prefix_json=?,"
                        "head_json='{}',invalid_from=?,ready=0 WHERE session_id=?",
                        (invalid_from, prefix["group_count"], _json_text(prefix), invalid_from, session_id))
            if invalid_from is not None:
                if self._discard_suffix(connection, session_id, invalid_from):
                    connection.commit()
                    return {"status": "progress", "reason": "group_suffix_invalidating"}
                connection.execute("UPDATE continuity_group_progress SET invalid_from=NULL WHERE session_id=?",
                                   (session_id,))
            position = invalid_from if invalid_from is not None else progress["position"]
            if position >= target["canonical_count"]:
                connection.execute("UPDATE continuity_group_progress SET head_json=?,ready=1 WHERE session_id=?",
                                   (_json_text(target), session_id))
                connection.commit()
                return {"status": "ready"}
            expected_progress = tuple(connection.execute(
                "SELECT * FROM continuity_group_progress WHERE session_id=?", (session_id,)
            ).fetchone())
            connection.commit()
            # Host payload reads and projection must not hold the receipt writer
            # lock. Publish this bounded page only if its index predecessor is
            # still the same after taking the short write transaction below.
            rows, entries, stored_bytes = [], [], 0
            pending = self._pending_group
            self._pending_group = None
            if pending is not None and pending["session_id"] == session_id and pending["position"] == position:
                validity = self.db.validate_history_prefix(pending["target"])
                if validity.get("status") == "valid" and not validity.get("invalidated_from_position"):
                    rows, entries, stored_bytes = pending["rows"], pending["entries"], pending["stored_bytes"]
            del pending
            for _ in range(page_allowance):
                page = self._page(session_id, target, position + len(rows),
                                  max_rows=min(256, 2048-len(rows)),
                                  max_bytes=4*1024*1024-stored_bytes)
                if page.get("status") not in {"ready", "valid"}:
                    return {"status": page.get("status", "fault"),
                            "reason": page.get("reason", "history_page_failed")}
                rows.extend(page["rows"])
                entries.extend(page["entries"])
                stored_bytes += page["stored_bytes"]
                identities = _Occurrences(connection, session_id, "message", position)
                groups = _Occurrences(connection, session_id, "group", position)
                projected = _project_canonical_source(
                    session_id, rows, full_prefix=False, identity_occurrences=identities,
                    group_occurrences=groups, prior_group_count=prefix["group_count"],
                    include_group_boundaries=True,
                )
                if projected.get("status") != "ready":
                    return {"status": "fault", "reason": projected.get("error", "group_projection_failed")}
                if len(_json_text({"rows": rows, "entries": entries,
                                   "projection": projected,
                                   "message_occurrences": identities.changes,
                                   "group_occurrences": groups.changes}).encode("utf-8")) > 8*1024*1024:
                    return {"status": "overflow", "reason": "preparation_workset_limit_exceeded"}
                consumed = projected["_consumed_rows"]
                if consumed or page["scan_complete"]:
                    break
                if len(rows) >= 2048 or stored_bytes >= 4*1024*1024:
                    return {"status": "overflow", "reason": "complete_group_limit_exceeded"}
            else:
                # The host and group reader share eight pages. Retain only the
                # bounded unfinished group, under the process-wide 8 MiB lease,
                # so continuous small appends cannot starve its eighth page.
                self._pending_group = {"session_id": session_id, "position": position,
                    "target": target, "rows": rows, "entries": entries, "stored_bytes": stored_bytes}
                return {"status": "progress", "reason": "complete_group_pending_page"}
            # Only committed complete boundaries advance occurrence counters.
            del projected
            identities = _Occurrences(connection, session_id, "message", position)
            groups = _Occurrences(connection, session_id, "group", position)
            projected = _project_canonical_source(
                session_id, rows[:consumed], full_prefix=False, identity_occurrences=identities,
                group_occurrences=groups, prior_group_count=prefix["group_count"],
                include_group_boundaries=True,
            )
            records = []
            for group, start, end, compacted in zip(projected["groups"], projected["_group_starts"], projected["_group_ends"],
                                              projected["_group_compacted"]):
                if len(_json_text(group).encode("utf-8")) > 4*1024*1024:
                    return {"status": "overflow", "reason": "complete_group_byte_limit_exceeded"}
                entry = entries[end-1]
                fingerprint = _group_fingerprint(group)
                prefix = {
                    "schema": "thread_continuity_prefix_descriptor.v1",
                    "through_anchor": entry["anchor"], "canonical_count": entry["position"],
                    "group_count": prefix["group_count"]+1, "prefix_hash": entry["prefix_hash"],
                    "group_root": extend_thread_continuity_group_root(
                        prefix["group_root"], group_count=prefix["group_count"]+1,
                        source_prefix_id=group["source_prefix_id"], source_group_fingerprint=fingerprint,
                        through_anchor=entry["anchor"], canonical_count=entry["position"],
                        prefix_hash=entry["prefix_hash"]),
                }
                records.append((session_id, prefix["group_count"], group["source_prefix_id"],
                                    entries[start]["position"], entry["position"], group["effective_event_at"], fingerprint,
                                    _json_text(prefix), int(compacted),
                                    sum(item["stored_bytes"] for item in entries[start:end])))
            full = bool(page["scan_complete"])
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM continuity_group_progress WHERE session_id=?", (session_id,)
            ).fetchone()
            validation = self.db.validate_history_prefix(target)
            if (current is None or tuple(current) != expected_progress
                    or validation.get("status") != "valid" or validation.get("invalidated_from_position")):
                return {"status": "progress", "reason": "group_predecessor_changed"}
            identities.commit([entry["position"] for entry in entries[:consumed]])
            groups.commit([entries[end-1]["position"] for end in projected["_group_ends"]])
            connection.executemany("INSERT INTO continuity_group_index VALUES (?,?,?,?,?,?,?,?,?,?)", records)
            connection.execute(
                "UPDATE continuity_group_progress SET position=?,group_count=?,prefix_json=?,head_json=?,ready=? "
                "WHERE session_id=?",
                (position+consumed, prefix["group_count"], _json_text(prefix),
                 _json_text(target), int(full), session_id),
            )
            if self._closed:
                connection.rollback()
                return {"status": "closed"}
            connection.commit()
            return {"status": "ready" if full else "progress"}

    def read_source(self, session_id, *, reference_at, recent_horizon_hours=72,
                    max_rows=2048, max_bytes=4*1024*1024):
        # The host persists this turn's user before request middleware. Give the
        # existing background worker a bounded chance to audit that small delta;
        # otherwise every turn would encounter a fresh pending journal forever.
        # Bootstrap/overload still return native without a foreground scan.
        deadline = time.monotonic() + 0.1
        while True:
            with self._wake:
                completed = self._completed
            result = self._read_source_once(
                session_id, reference_at=reference_at, recent_horizon_hours=recent_horizon_hours,
                max_rows=max_rows, max_bytes=max_bytes)
            if result.get("status") != "pending":
                return result
            with self._wake:
                if self._closed or not self._wake.wait_for(
                        lambda: self._closed or self._completed != completed,
                        timeout=max(0, deadline-time.monotonic())):
                    return result
                if time.monotonic() >= deadline:
                    return result

    def _hydrate_groups(self, connection, session_id, target, records, max_rows, max_bytes):
        """Hydrate complete indexed groups; the same proof checks serve both paths."""
        rows, entries, actual_bytes = [], [], 0
        position = records[0]["start_position"]-1 if records else 0
        start_position = position
        end_position = records[-1]["end_position"] if records else position
        while position < end_position:
            page = self._page(session_id, target, position,
                              min(256, end_position-position, max_rows-len(rows)),
                              max_bytes-actual_bytes)
            if page.get("status") not in {"ready", "valid"} or not page.get("rows"):
                raise ValueError("history_page_unavailable")
            rows.extend(page["rows"])
            entries.extend(page["entries"])
            actual_bytes += page["stored_bytes"]
            position = entries[-1]["position"]
        projected = _project_canonical_source(
            session_id, rows, full_prefix=False,
            identity_occurrences=_Occurrences(connection, session_id, "message", start_position),
            group_occurrences=_Occurrences(connection, session_id, "group", start_position),
            prior_group_count=records[0]["ordinal"]-1 if records else 0,
            include_group_boundaries=True,
        )
        if projected.get("status") != "ready" or len(projected["groups"]) != len(records):
            raise ValueError("group_index_projection_mismatch")
        for group, record in zip(projected["groups"], records):
            if group["source_prefix_id"] != record["group_id"] or _group_fingerprint(group) != record["fingerprint"]:
                raise ValueError("group_index_projection_mismatch")
        return projected["groups"], len(rows), actual_bytes

    def read_recall(self, session_id, queries, *, max_groups=24, max_rows=2048,
                    max_bytes=4*1024*1024, start_at=None, end_at=None):
        """Question-selected complete groups, never retirement eligibility."""
        from .hermes_adapter import _failed_source
        search = getattr(self.db, "search_history_matches", None)
        if not callable(search):
            return _failed_source("unavailable", "bounded_native_search_missing")
        if (not isinstance(queries, list) or not 1 <= len(queries) <= 3
                or any(not isinstance(q, str) or not 1 <= len(q) <= 80 for q in queries)):
            raise ValueError("recall_queries_invalid")
        if any(type(value) is not int or not 1 <= value <= limit for value, limit in
               ((max_groups, 24), (max_rows, 2048), (max_bytes, 4*1024*1024))):
            raise ValueError("recall_workset_budget_invalid")
        start = datetime.fromisoformat(start_at) if start_at else None
        end = datetime.fromisoformat(end_at) if end_at else None
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            progress = connection.execute(
                "SELECT * FROM continuity_group_progress WHERE session_id=?", (session_id,)
            ).fetchone()
            if progress is None or not progress["ready"] or progress["invalid_from"] is not None:
                self.request(session_id)
                return _failed_source("pending", "history_preparation_pending")
            target = self._prefix(json.loads(progress["head_json"]), json.loads(progress["prefix_json"]))
            validation = self.db.validate_history_prefix(target)
            if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
                self.request(session_id)
                return _failed_source("pending", "history_source_changed")
            ranked = {}
            records = {}
            for query in queries:
                hits = search(session_id, target=target, query=query, max_matches=64, deadline_ms=50)
                if hits.get("status") != "ready":
                    return _failed_source("unavailable", str(hits.get("reason") or "recall_search_unavailable"))
                seen = set()
                for rank, position in enumerate(hits["matches"], 1):
                    record = connection.execute(
                        "SELECT * FROM continuity_group_index WHERE session_id=? AND end_position>=? "
                        "ORDER BY end_position LIMIT 1", (session_id, position)
                    ).fetchone()
                    if record is None or record["start_position"] > position:
                        continue
                    key = record["group_id"]
                    event = datetime.fromisoformat(record["event_at"])
                    if key in seen or (start and event < start) or (end and event > end):
                        continue
                    seen.add(key)
                    records[key] = record
                    ranked[key] = ranked.get(key, 0) + 1/(60+rank)
            selected, groups, rows_used, bytes_used = [], [], 0, 0
            for key in sorted(ranked, key=lambda key: (ranked[key], records[key]["ordinal"]), reverse=True):
                record = records[key]
                count = record["end_position"]-record["start_position"]+1
                if count+rows_used > max_rows or record["stored_bytes"]+bytes_used > max_bytes:
                    continue
                try:
                    hydrated, count, size = self._hydrate_groups(
                        connection, session_id, target, [record], max_rows-rows_used, max_bytes-bytes_used)
                except ValueError as error:
                    return _failed_source("unavailable", str(error))
                selected.append({"group_id": key, "fingerprint": record["fingerprint"]})
                groups.extend(hydrated)
                rows_used += count
                bytes_used += size
                if len(groups) >= max_groups:
                    break
            proof = {"host_token": target, "grouping_rule_version": GROUP_RULE, "groups": selected}
            self.validate_recall(proof, session_id=session_id)
            return {"status": "ready", "groups": groups, "source_proof": proof,
                    "source_snapshot": _sha256(proof),
                    "stats": {"workset_rows": rows_used, "workset_bytes": bytes_used,
                              "returned_groups": len(groups), "retirement_authority": False}}

    def validate_recall(self, proof, *, session_id):
        target = proof["host_token"]
        if target["domain_id"] != session_id or proof["grouping_rule_version"] != GROUP_RULE:
            raise ValueError("recall_domain_or_group_rule_changed")
        validation = self.db.validate_history_prefix(target)
        if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
            raise ValueError("recall_source_changed")
        with closing(self.store._connect()) as connection:
            for group in proof["groups"]:
                row = connection.execute(
                    "SELECT fingerprint,end_position FROM continuity_group_index WHERE session_id=? AND group_id=?",
                    (session_id, group["group_id"])).fetchone()
                if row is None or row["fingerprint"] != group["fingerprint"] or row["end_position"] > target["canonical_count"]:
                    raise ValueError("recall_group_changed")
        return proof

    def _read_source_once(self, session_id, *, reference_at, recent_horizon_hours=72,
                          max_rows=2048, max_bytes=4*1024*1024):
        from .hermes_adapter import _failed_source
        from .checkpoint_v3 import (canonical_proof_sha256,
                                    thread_continuity_group_root_seed)
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            progress = connection.execute(
                "SELECT * FROM continuity_group_progress WHERE session_id=?", (session_id,)
            ).fetchone()
            if progress is None or not progress["ready"] or progress["invalid_from"] is not None:
                last = self.status(session_id)
                self.request(session_id)
                if last["status"] == "overflow":
                    return _failed_source("overflow", last["reason"] or "history_preparation_overflow")
                return _failed_source("pending", "history_preparation_pending")
            target = json.loads(progress["head_json"])
            validation = self.db.validate_history_prefix(target)
            if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
                self.request(session_id)
                return _failed_source("pending", "history_source_" + validation.get("status", "invalid"))
            if validation.get("current_indexed_change_seq", target["indexed_change_seq"]) > target["indexed_change_seq"]:
                # A verified old prefix remains usable while the worker catches
                # up to newer, already audited tail rows.
                self.request(session_id)
            empty = self.db.seal_history_prefix(
                session_id, activation_epoch=target["activation_epoch"], end_anchor=None)
            if empty.get("status") != "valid":
                return _failed_source("pending", "history_source_pending")
            empty_prefix = {
                "schema": "thread_continuity_prefix_descriptor.v1", "through_anchor": "",
                "canonical_count": 0, "group_count": 0,
                "prefix_hash": empty["token"]["prefix_hash"],
                "group_root": thread_continuity_group_root_seed(
                    domain_id=target["domain_id"], grouping_rule_version=GROUP_RULE),
            }
            first_live = connection.execute(
                "SELECT ordinal FROM continuity_group_index WHERE session_id=? AND compacted=0 "
                "ORDER BY ordinal LIMIT 1", (session_id,)
            ).fetchone()
            eligible_count = first_live[0]-1 if first_live else progress["group_count"]
            eligible_row = connection.execute(
                "SELECT prefix_json FROM continuity_group_index WHERE session_id=? AND ordinal=?",
                (session_id, eligible_count),
            ).fetchone()
            eligible = json.loads(eligible_row[0]) if eligible_row else empty_prefix
            # Select a bounded contiguous suffix. A full active suffix must fit;
            # older compacted groups remain represented by their prefix proof.
            records = connection.execute(
                "SELECT * FROM continuity_group_index WHERE session_id=? ORDER BY ordinal DESC LIMIT ?",
                (session_id, max_rows+1),
            )
            selected = []
            bytes_used = 0
            last_position = None
            cutoff = datetime.fromisoformat(reference_at.replace("Z", "+00:00")) - timedelta(hours=recent_horizon_hours)
            for record in records:
                if last_position is None:
                    last_position = record["end_position"]
                row_count = last_position-record["start_position"]+1
                if row_count > max_rows or bytes_used+record["stored_bytes"] > max_bytes:
                    break
                # Older history does not become summary input simply because
                # preparation finished. The proof, not its body, survives.
                if record["ordinal"] <= eligible_count and datetime.fromisoformat(record["event_at"]) < cutoff:
                    break
                selected.append(record)
                bytes_used += record["stored_bytes"]
            selected.reverse()
            start_ordinal = selected[0]["ordinal"] if selected else progress["group_count"]+1
            if start_ordinal > eligible_count+1:
                return _failed_source("overflow", "foreground_group_limit_exceeded")
            before = connection.execute(
                "SELECT prefix_json FROM continuity_group_index WHERE session_id=? AND ordinal=?",
                (session_id, start_ordinal-1),
            ).fetchone()
            prefix_before = json.loads(before[0]) if before else empty_prefix
            try:
                groups, row_count, actual_bytes = self._hydrate_groups(
                    connection, session_id, target, selected, max_rows, max_bytes)
            except ValueError as error:
                return _failed_source("pending" if str(error) == "history_page_unavailable"
                                      else "ambiguous", str(error))
            prefixes = []
            for record in selected:
                prefixes.append({"source_prefix_id": record["group_id"],
                                 "source_group_fingerprint": record["fingerprint"],
                                 "prefix": json.loads(record["prefix_json"])})
            validation = self.db.validate_history_prefix(target)
            if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
                self.request(session_id)
                return _failed_source("pending", "history_source_changed")
            last_prefix = json.loads(progress["prefix_json"])
            # A pending user (or trailing non-dialogue row) is not part of a
            # complete group. Its later provider sidecar must not rewrite the
            # proof of the preceding complete dialogue prefix.
            complete_target = self._prefix(target, last_prefix)
            proof = {"host_token": complete_target, "grouping_rule_version": GROUP_RULE,
                     "group_count": progress["group_count"], "group_root": last_prefix["group_root"]}
            eligibility = {
                "schema": "thread_continuity_retirement_eligibility.v1", "status": "eligible",
                "prefix": eligible,
                "physical_ownership_sha256": canonical_proof_sha256(
                    {"host_token": target, "compacted_prefix": eligible}),
            }
            result = {
                "schema": "thread_continuity_compact_source.v1", "status": "ready", "scan_complete": True,
                "source_snapshot": canonical_proof_sha256(proof), "source_proof": proof,
                "prefix_before_groups": prefix_before, "groups": groups,
                "group_prefixes": prefixes, "retirement_eligibility": eligibility,
                "stats": {"full_prefix": False, "canonical_message_count": complete_target["canonical_count"],
                          "returned_groups": len(selected), "workset_rows": row_count,
                          "workset_bytes": actual_bytes,
                          "compacted_prefix_group_ids": [record["group_id"] for record in selected
                                                         if record["ordinal"] <= eligible_count]},
            }
            return result

    def validate_checkpoint(self, checkpoint, *, session_id):
        deadline = time.monotonic() + 0.1
        while True:
            with self._wake:
                completed = self._completed
            try:
                return self._validate_checkpoint_once(checkpoint, session_id=session_id)
            except ValueError as error:
                if str(error) not in {"checkpoint_source_pending", "checkpoint_index_pending"}:
                    raise
                self.request(session_id)
                with self._wake:
                    if (self._closed or not self._wake.wait_for(
                            lambda: self._closed or self._completed != completed,
                            timeout=max(0, deadline-time.monotonic()))
                            or time.monotonic() >= deadline):
                        raise

    def _validate_checkpoint_once(self, checkpoint, *, session_id):
        """Every consumer checks the old proof against current host and group state."""
        from .checkpoint_v3 import (normalize_thread_continuity_checkpoint_v3,
                                    thread_continuity_group_root_seed)
        checkpoint = normalize_thread_continuity_checkpoint_v3(checkpoint)
        proof = checkpoint["source_proof"]
        if proof["grouping_rule_version"] != GROUP_RULE:
            raise ValueError("checkpoint_grouping_rule_changed")
        target = proof["host_token"]
        if target["domain_id"] != session_id:
            raise ValueError("checkpoint_domain_mismatch")
        validation = self.db.validate_history_prefix(target)
        if validation.get("status") == "pending":
            raise ValueError("checkpoint_source_pending")
        if validation.get("status") != "valid":
            raise ValueError("checkpoint_source_changed")
        with closing(self.store._connect()) as connection:
            connection.execute("BEGIN")
            progress = connection.execute(
                "SELECT head_json,ready,invalid_from FROM continuity_group_progress WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if progress is None or not progress["ready"] or progress["invalid_from"] is not None:
                raise ValueError("checkpoint_index_pending")
            current_target = json.loads(progress["head_json"])
            validation = self.db.validate_history_prefix(current_target)
            if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
                raise ValueError("checkpoint_index_pending")
            def descriptor_at(count):
                if count == 0:
                    empty = self.db.seal_history_prefix(
                        session_id, activation_epoch=current_target["activation_epoch"], end_anchor=None)
                    if empty.get("status") != "valid":
                        raise ValueError("checkpoint_index_pending")
                    return {"through_anchor": "", "canonical_count": 0, "group_count": 0,
                            "prefix_hash": empty["token"]["prefix_hash"],
                            "group_root": thread_continuity_group_root_seed(
                                domain_id=session_id, grouping_rule_version=GROUP_RULE)}
                row = connection.execute(
                    "SELECT prefix_json FROM continuity_group_index WHERE session_id=? AND ordinal=?",
                    (session_id, count),
                ).fetchone()
                return json.loads(row[0]) if row else None

            group = descriptor_at(proof["group_count"])
            if group is None or group["group_root"] != proof["group_root"]:
                raise ValueError("checkpoint_group_changed")
            cursor = checkpoint["retirement_cursor"]
            descriptor = descriptor_at(cursor["group_count"])
            if descriptor is None:
                raise ValueError("checkpoint_retirement_changed")
            if any(cursor[key] != descriptor[key] for key in
                   ("through_anchor", "canonical_count", "group_count", "prefix_hash", "group_root")):
                raise ValueError("checkpoint_retirement_changed")
            live = connection.execute(
                "SELECT ordinal FROM continuity_group_index WHERE session_id=? AND compacted=0 "
                "AND ordinal<=? ORDER BY ordinal LIMIT 1", (session_id, cursor["group_count"])
            ).fetchone()
            validation = self.db.validate_history_prefix(target)
            if validation.get("status") == "pending":
                raise ValueError("checkpoint_source_pending")
            if live is not None or validation.get("status") != "valid":
                raise ValueError("checkpoint_retirement_changed")
            bridge = checkpoint["recent_bridge"]
            prior_ordinal = None
            for group_id, fingerprint in zip(bridge["source_group_ids"], bridge["source_group_fingerprints"]):
                record = connection.execute(
                    "SELECT ordinal,fingerprint FROM continuity_group_index WHERE session_id=? AND group_id=?",
                    (session_id, group_id),
                ).fetchone()
                if (record is None or record["fingerprint"] != fingerprint
                        or record["ordinal"] > cursor["group_count"]
                        or (prior_ordinal is not None and record["ordinal"] != prior_ordinal+1)):
                    raise ValueError("checkpoint_bridge_changed")
                prior_ordinal = record["ordinal"]
            validation = self.db.validate_history_prefix(current_target)
            if validation.get("status") != "valid" or validation.get("invalidated_from_position"):
                raise ValueError("checkpoint_index_pending")
        return checkpoint
