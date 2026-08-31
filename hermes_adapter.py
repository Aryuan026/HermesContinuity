"""Hermes SessionDB projection, derived checkpoints, and receipt state."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Sequence

from .context_compactor import (
    _content_hash,
    _content_to_text,
    normalize_complete_thread_groups,
    normalize_thread_continuity_checkpoint,
)


_SUMMARY_PREFIXES = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]",
    "[CONTEXT SUMMARY]:",
    "[CONTEXT COMPACTION]",
)
_MERGED_SUMMARY_DELIMITER = "[END OF PRIOR CONTEXT — COMPACTION SUMMARY BELOW]"
_INTERIM_ASSISTANT_FINISH_REASONS = {
    "incomplete",
    "verification_required",
    "verify_hook_continue",
}
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+~=-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_WINDOW_REQUEST_SCHEMA = "continuity_canonical_window_request.v2"
_CANONICAL_WINDOW_RESPONSE_SCHEMA = "continuity_canonical_window_response.v2"
_CANONICAL_WINDOW_TRACE_SCHEMA = "continuity_canonical_window_trace.v2"
_CANONICAL_WINDOW_REQUEST_KEYS = {
    "schema",
    "current_session_id",
    "reference_at",
    "horizon_seconds",
    "max_sessions",
    "max_groups",
    "excluded_sources",
    "allowed_source_classes",
}
_CANONICAL_WINDOW_REQUIRED_REQUEST_KEYS = {
    "schema",
    "current_session_id",
    "reference_at",
}
_CANONICAL_WINDOW_DEFAULT_EXCLUDED_SOURCES = ("subagent", "tool")
_CANONICAL_WINDOW_SOURCE_CLASSES = frozenset(
    {"human", "scheduled", "internal", "delegated", "tool", "unknown"}
)
_CANONICAL_WINDOW_FUTURE_TOLERANCE_SECONDS = 300
_CANONICAL_WINDOW_MAX_PHYSICAL_ROWS = 2_048
_CANONICAL_WINDOW_MAX_LINEAGE_SESSIONS = 64
_HUMAN_SESSION_SOURCES = frozenset(
    {
        "api_server",
        "bluebubbles",
        "dingtalk",
        "desktop",
        "discord",
        "email",
        "feishu",
        "hermes_browser",
        "local",
        "matrix",
        "mattermost",
        "qqbot",
        "signal",
        "slack",
        "sms",
        "telegram",
        "cli",
        "tui",
        "dashboard",
        "wecom",
        "wecom_callback",
        "weixin",
        "whatsapp",
        "whatsapp_cloud",
        "yuanbao",
    }
)
_INTERNAL_SESSION_SOURCES = frozenset(
    {"agent_state", "background", "maintenance", "session", "system_turn"}
)
_TOOL_SESSION_SOURCES = frozenset({"provider", "reader", "tool"})


class _ProjectionError(ValueError):
    pass


def _json_text(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise _ProjectionError("source_row_not_json") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            _content_text(item.get("text"))
            for item in value
            if isinstance(item, Mapping) and item.get("type") in {"text", "input_text"}
        )
    if isinstance(value, Mapping):
        return _content_text(value.get("text"))
    return ""


def _is_compaction_summary(row: Mapping[str, Any]) -> bool:
    metadata = row.get("display_metadata")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    if row.get("_compressed_summary") or metadata.get("_compressed_summary"):
        return True
    if str(row.get("display_kind") or "") in {
        "compaction_summary",
        "context_compaction_summary",
    }:
        return True
    text = _content_text(row.get("content")).lstrip()
    if _MERGED_SUMMARY_DELIMITER in text:
        text = text.split(_MERGED_SUMMARY_DELIMITER, 1)[1].lstrip()
    return text.startswith(_SUMMARY_PREFIXES)


def _is_nonvisible_provider_scaffold(row: Mapping[str, Any], role: str) -> bool:
    """Recognize host-owned API-only rows that never entered the transcript."""

    api_content = row.get("api_content")
    if (
        _content_to_text(row.get("content"))
        or not isinstance(api_content, str)
        or not api_content.strip()
        or row.get("platform_message_id")
    ):
        return False
    return str(row.get("display_kind") or "").strip() == "hidden" or role == "user"


def _source_evidence(row: Mapping[str, Any]) -> Dict[str, str]:
    metadata = row.get("display_metadata")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    return {
        "display_kind": str(row.get("display_kind") or "").strip(),
        "internal_kind": str(metadata.get("internal_kind") or "").strip(),
    }


def _source_class(
    source: str,
    evidence: Mapping[str, Any],
    human_sources: frozenset[str] = _HUMAN_SESSION_SOURCES,
) -> str:
    source = str(source or "").strip().lower()
    display_kind = str(evidence.get("display_kind") or "").strip().lower()
    internal_kind = str(evidence.get("internal_kind") or "").strip().lower()
    if source == "cron" or (
        display_kind == "internal_notification" and internal_kind == "wakeup"
    ):
        return "scheduled"
    if display_kind == "internal_notification" or source in _INTERNAL_SESSION_SOURCES:
        return "internal"
    if source == "subagent":
        return "delegated"
    if source in _TOOL_SESSION_SOURCES:
        return "tool"
    if source in human_sources:
        return "human"
    return "unknown"


def _dedupe_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(row.get("role") or ""),
        _json_text(row.get("content")),
        _json_text(row.get("timestamp")),
        _json_text(row.get("tool_call_id")),
        _json_text(row.get("tool_calls")),
        _json_text(row.get("tool_name")),
    )


def _signature(row: Mapping[str, Any], *, lifecycle: bool) -> str:
    omitted = {"id"} if lifecycle else {"id", "active", "compacted"}
    return _json_text(
        {str(key): value for key, value in row.items() if str(key) not in omitted}
    )


def _active(row: Mapping[str, Any]) -> bool:
    return row.get("active") in {1, True}


def _compacted(row: Mapping[str, Any]) -> bool:
    return row.get("compacted") in {1, True}


def _row_id(row: Mapping[str, Any]) -> int:
    value = row.get("id")
    if type(value) is not int or value < 1:
        raise _ProjectionError("source_row_id_invalid")
    return value


def _audit_canonical_view(
    session_id: str,
    canonical_rows: Sequence[Mapping[str, Any]],
    raw_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    if not all(isinstance(row, Mapping) for row in (*canonical_rows, *raw_rows)):
        raise _ProjectionError("source_row_invalid")
    for row in (*canonical_rows, *raw_rows):
        if row.get("active") not in {0, 1, False, True} or row.get("compacted") not in {
            0,
            1,
            False,
            True,
        }:
            raise _ProjectionError("source_lifecycle_invalid")
        if row.get("session_id") not in {None, session_id}:
            raise _ProjectionError("source_session_mismatch")

    raw_ids = [_row_id(row) for row in raw_rows]
    canonical_ids = [_row_id(row) for row in canonical_rows]
    if len(raw_ids) != len(set(raw_ids)) or len(canonical_ids) != len(
        set(canonical_ids)
    ):
        raise _ProjectionError("source_origin_collision")
    if raw_ids != sorted(raw_ids):
        raise _ProjectionError("source_order_invalid")

    relevant = [dict(row) for row in raw_rows if _active(row) or _compacted(row)]
    raw_buckets: Dict[tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for row in relevant:
        raw_buckets[_dedupe_key(row)].append(row)

    canonical_buckets: Dict[tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    for row in canonical_rows:
        canonical_buckets[_dedupe_key(row)].append(dict(row))
    if set(raw_buckets) != set(canonical_buckets) or any(
        len(rows) != 1 for rows in canonical_buckets.values()
    ):
        raise _ProjectionError("canonical_view_unexplained")

    # SessionDB has already decoded content/tool_calls/display_metadata on both
    # reads. This is therefore a persisted-field *semantic* audit, not a claim
    # that legacy JSON TEXT encodings were byte-identical. Platform IDs,
    # api_content and decoded display sidecars still participate and differing
    # values fail closed.
    winners: Dict[tuple[str, ...], tuple[int, Dict[str, Any]]] = {}
    for key, entries in raw_buckets.items():
        entries = sorted(entries, key=_row_id)
        active_entries = [row for row in entries if _active(row)]
        if len(active_entries) > 1:
            raise _ProjectionError("canonical_active_collision")
        if len(entries) == 1:
            winner = entries[0]
            if not ((_active(winner) and not _compacted(winner)) or (
                not _active(winner) and _compacted(winner)
            )):
                raise _ProjectionError("source_lifecycle_invalid")
        else:
            winner = active_entries[0] if active_entries else entries[-1]
            clone_signature = _signature(winner, lifecycle=False)
            if any(
                _signature(row, lifecycle=False) != clone_signature
                for row in entries
            ):
                raise _ProjectionError("canonical_clone_sidecar_collision")
            if active_entries:
                if (
                    winner is not entries[-1]
                    or _compacted(winner)
                    or any(_active(row) or not _compacted(row) for row in entries[:-1])
                ):
                    raise _ProjectionError("canonical_clone_order_invalid")
            elif any(_active(row) or not _compacted(row) for row in entries):
                raise _ProjectionError("canonical_clone_ambiguous")

            # Hermes' schema has no durable generation/origin carrier. It
            # cannot distinguish a manually inserted duplicate whose complete
            # persisted fields and timestamp are identical from a compaction
            # clone. Match SessionDB's canonical dedupe semantics and use the
            # earliest member only as the logical ordering origin.
        canonical = canonical_buckets[key][0]
        if (
            _row_id(canonical) != _row_id(winner)
            or _signature(canonical, lifecycle=True)
            != _signature(winner, lifecycle=True)
        ):
            raise _ProjectionError("canonical_view_winner_mismatch")
        winners[key] = (_row_id(entries[0]), canonical)

    if any(
        winners.get(_dedupe_key(row), (None, None))[1] != row
        for row in canonical_rows
    ):
        raise _ProjectionError("canonical_view_winner_mismatch")
    ordered_origins = [origin for origin, _row in winners.values()]
    if len(ordered_origins) != len(set(ordered_origins)):
        raise _ProjectionError("source_origin_collision")
    return [
        dict(row)
        for _origin, row in sorted(winners.values(), key=lambda value: value[0])
    ]


def _timestamp_text(value: Any) -> str:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = datetime.fromtimestamp(float(value), timezone.utc)
        elif isinstance(value, str) and value.strip():
            text = value.strip()
            try:
                parsed = datetime.fromtimestamp(float(text), timezone.utc)
            except ValueError:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
                parsed = parsed.astimezone(timezone.utc)
        else:
            raise ValueError
    except (OverflowError, OSError, TypeError, ValueError) as exc:
        raise _ProjectionError("source_timestamp_invalid") from exc
    return parsed.isoformat()


def _message_identity(
    session_id: str,
    row: Mapping[str, Any],
    occurrence: int,
) -> str:
    role = str(row.get("role") or "").strip().lower()
    content_hash = _content_hash(row.get("content"))
    material = {
        "schema": "hermes_continuity_message_identity.v1",
        "session_id": session_id,
        "platform_message_id": str(row.get("platform_message_id") or ""),
        "role": role,
        "content_sha256": content_hash,
        "timestamp": row.get("timestamp"),
        "tool_tuple": [
            row.get("tool_call_id"),
            row.get("tool_calls"),
            row.get("tool_name"),
        ],
        "occurrence": occurrence,
    }
    return "hcm_" + _sha256(material)


def _snapshot_rows(groups: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "source_prefix_id": group["source_prefix_id"],
            "group_kind": group.get("group_kind", ""),
            "logical_turn_id": group["logical_turn_id"],
            "record_id": group["record_id"],
            "message_ids": list(group["message_ids"]),
            "effective_event_at": group["effective_event_at"],
            "content_hashes": [message["content_hash"] for message in group["messages"]],
        }
        for group in groups
    ]


def _source_snapshot(groups: Sequence[Mapping[str, Any]]) -> str:
    return _sha256(_snapshot_rows(groups))


def _failed_source(status: str, error: str) -> Dict[str, Any]:
    return {
        "status": status,
        "groups": [],
        "source_prefix_ids": [],
        "source_snapshot": "",
        "scan_complete": False,
        "error": error,
        "stats": {
            "full_prefix": False,
            "returned_groups": 0,
            "compacted_prefix_group_ids": [],
        },
    }


def _lineage_row_signature(row: Mapping[str, Any]) -> str:
    """Compare decoded persisted clone fields without physical ownership."""

    omitted = {"id", "session_id", "active", "compacted"}
    return _json_text(
        {
            str(key): value
            for key, value in row.items()
            if str(key) not in omitted and not str(key).startswith("_continuity_")
        }
    )


def _project_canonical_source(
    session_id: str,
    canonical: Sequence[Mapping[str, Any]],
    *,
    full_prefix: bool,
    max_groups: int | None = None,
    include_lineage_proofs: bool = False,
) -> Dict[str, Any]:
    """Run the retained canonical-row grouping algorithm."""

    occurrences: Dict[str, int] = defaultdict(int)
    prepared: List[Dict[str, Any]] = []
    try:
        for row in canonical:
            role = str(row.get("role") or "").strip().lower()
            identity_base = _json_text(
                [
                    session_id,
                    str(row.get("platform_message_id") or ""),
                    role,
                    _content_hash(row.get("content")),
                    row.get("timestamp"),
                    row.get("tool_call_id"),
                    row.get("tool_calls"),
                    row.get("tool_name"),
                ]
            )
            occurrence = occurrences[identity_base]
            occurrences[identity_base] += 1
            prepared.append(
                {
                    **row,
                    "_continuity_role": role,
                    "_continuity_message_id": _message_identity(
                        session_id, row, occurrence
                    ),
                }
            )
    except (TypeError, ValueError, _ProjectionError):
        return _failed_source("ambiguous", "source_identity_invalid")

    groups: List[Dict[str, Any]] = []
    group_compacted: List[bool] = []
    lineage_proofs: List[Dict[str, str]] = []
    pending_users: List[Dict[str, Any]] = []
    group_occurrences: Dict[str, int] = defaultdict(int)
    for row in prepared:
        role = row["_continuity_role"]
        if _is_compaction_summary(row) or role in {
            "system",
            "developer",
            "tool",
            "session_meta",
        }:
            continue
        if role not in {"user", "assistant"}:
            return _failed_source("ambiguous", "source_role_invalid")
        if _is_nonvisible_provider_scaffold(row, role):
            continue
        if role == "assistant":
            finish_reason = str(row.get("finish_reason") or "").strip().lower()
            if (
                row.get("tool_calls")
                or finish_reason == "tool_calls"
                or finish_reason in _INTERIM_ASSISTANT_FINISH_REASONS
            ):
                continue
        if not _content_to_text(row.get("content")):
            return _failed_source("ambiguous", "source_visible_content_invalid")
        if role == "user":
            pending_users.append(row)
            continue
        if not pending_users and not groups:
            return _failed_source("ambiguous", "proactive_event_unverified")

        assistant_id = row["_continuity_message_id"]
        assistant_hash = _content_hash(row.get("content"))
        effective_event_at = _timestamp_text(row.get("timestamp"))
        persisted_rows = [*pending_users, row]
        if pending_users:
            user_contents = [pending.get("content") for pending in pending_users]
            if len(user_contents) == 1:
                user_content = user_contents[0]
                user_id = pending_users[0]["_continuity_message_id"]
            elif all(isinstance(content, str) for content in user_contents):
                user_content = "\n\n".join(user_contents)
                user_id = "hcm_" + _sha256(
                    {
                        "schema": "hermes_continuity_merged_user_identity.v1",
                        "session_id": session_id,
                        "message_ids": [
                            pending["_continuity_message_id"]
                            for pending in pending_users
                        ],
                        "content_hash": _content_hash(user_content),
                    }
                )
            else:
                return _failed_source(
                    "ambiguous", "consecutive_user_content_unmergeable"
                )
            evidence = _source_evidence(pending_users[-1])
            if any(_source_evidence(pending) != evidence for pending in pending_users):
                return _failed_source("ambiguous", "source_evidence_ambiguous")
            user_hash = _content_hash(user_content)
            group_kind = "dialogue_turn"
            message_ids = [user_id, assistant_id]
            messages = [
                {
                    "role": "user",
                    "message_id": user_id,
                    "content": user_content,
                    "content_hash": user_hash,
                },
                {
                    "role": "assistant",
                    "message_id": assistant_id,
                    "content": row.get("content"),
                    "content_hash": assistant_hash,
                },
            ]
            visible_key = [
                effective_event_at,
                ["user", user_hash],
                ["assistant", assistant_hash],
            ]
        else:
            evidence = _source_evidence(row)
            group_kind = "proactive_assistant_event"
            message_ids = [assistant_id]
            messages = [
                {
                    "role": "assistant",
                    "message_id": assistant_id,
                    "content": row.get("content"),
                    "content_hash": assistant_hash,
                }
            ]
            visible_key = [effective_event_at, ["assistant", assistant_hash]]

        group_base = _json_text([session_id, group_kind, message_ids])
        group_occurrence = group_occurrences[group_base]
        group_occurrences[group_base] += 1
        group_id = "hcg_" + _sha256(
            {
                "schema": "hermes_continuity_group_identity.v1",
                "session_id": session_id,
                "group_kind": group_kind,
                "message_ids": message_ids,
                "occurrence": group_occurrence,
            }
        )
        group = {
            "group_kind": group_kind,
            "source_prefix_id": group_id,
            "logical_turn_id": group_id,
            "record_id": group_id,
            "effective_event_at": effective_event_at,
            "message_ids": message_ids,
            "messages": messages,
        }
        groups.append(group)
        group_compacted.append(
            all(not _active(message) and _compacted(message) for message in persisted_rows)
        )
        if include_lineage_proofs:
            lineage_proofs.append(
                {
                    "visible_key": _sha256(visible_key),
                    "persisted_signature": _sha256(
                        [_lineage_row_signature(message) for message in persisted_rows]
                    ),
                    "source_evidence": evidence,
                }
            )
        pending_users = []
        if max_groups is not None and len(groups) > max_groups:
            return _failed_source("overflow", "source_group_limit_exceeded")

    normalized = normalize_complete_thread_groups(groups)
    if not normalized["complete"] or normalized["groups"] != groups:
        return _failed_source("ambiguous", "source_groups_invalid")
    compacted_prefix_ids: List[str] = []
    if full_prefix:
        for group, is_compacted in zip(groups, group_compacted):
            if not is_compacted:
                break
            compacted_prefix_ids.append(group["source_prefix_id"])
    snapshot_rows = _snapshot_rows(groups)
    result = {
        "status": "ready",
        "groups": groups,
        "source_prefix_ids": [group["source_prefix_id"] for group in groups],
        "_snapshot_rows": snapshot_rows,
        "source_snapshot": _sha256(snapshot_rows),
        "scan_complete": True,
        "stats": {
            "full_prefix": full_prefix,
            "canonical_message_count": len(canonical),
            "returned_groups": len(groups),
            "tail_user_incomplete": bool(pending_users),
            "compacted_prefix_group_ids": compacted_prefix_ids,
        },
    }
    if include_lineage_proofs:
        result["_lineage_group_proofs"] = lineage_proofs
    return result


class HermesSessionAdapter:
    """Project one Hermes session without owning or searching its transcript."""

    def __init__(
        self,
        session_db: Any,
        metadata_store: "ContinuityMetadataStore | None" = None,
    ) -> None:
        self.session_db = session_db
        self.metadata_store = metadata_store

    def read_source(self, session_id: str) -> Dict[str, Any]:
        session_id = str(session_id or "").strip()
        if not session_id:
            return _failed_source("unavailable", "session_id_invalid")
        try:
            canonical_rows = self.session_db.get_messages(
                session_id, include_compacted=True
            )
            raw_rows = self.session_db.get_messages(
                session_id, include_inactive=True
            )
            if not isinstance(canonical_rows, list) or not isinstance(raw_rows, list):
                raise _ProjectionError("source_view_invalid")
            canonical = _audit_canonical_view(session_id, canonical_rows, raw_rows)
        except _ProjectionError as exc:
            return _failed_source("ambiguous", str(exc))
        except Exception:
            return _failed_source("unavailable", "sessiondb_read_failed")

        return _project_canonical_source(
            session_id,
            canonical,
            full_prefix=True,
        )

    def _read_recent_session_source(
        self,
        session_id: str,
        *,
        start_timestamp: float,
        end_timestamp: float,
        max_physical_rows: int,
        max_groups: int,
    ) -> Dict[str, Any]:
        reader = getattr(self.session_db, "get_messages_time_window", None)
        if not callable(reader):
            return _failed_source("unavailable", "recent_source_host_incompatible")

        def read_view(**lifecycle: bool) -> tuple[List[Dict[str, Any]], int]:
            result = reader(
                session_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                max_physical_rows=max_physical_rows,
                **lifecycle,
            )
            if not isinstance(result, Mapping):
                raise _ProjectionError("recent_source_view_invalid")
            messages = result.get("messages")
            scan_complete = result.get("scan_complete")
            overflow = result.get("overflow")
            physical_count = result.get("physical_row_count")
            reported_limit = result.get("max_physical_rows")
            if (
                not isinstance(messages, list)
                or type(scan_complete) is not bool
                or type(overflow) is not bool
                or type(physical_count) is not int
                or physical_count < 0
                or reported_limit != max_physical_rows
            ):
                raise _ProjectionError("recent_source_view_invalid")
            if overflow:
                if messages or scan_complete:
                    raise _ProjectionError("recent_source_overflow_invalid")
                raise OverflowError
            if not scan_complete or physical_count > max_physical_rows:
                raise _ProjectionError("recent_source_scan_incomplete")
            if any(not isinstance(row, Mapping) for row in messages):
                raise _ProjectionError("recent_source_row_invalid")
            return [dict(row) for row in messages], physical_count

        try:
            canonical_rows, canonical_physical_count = read_view(
                include_inactive=False,
                include_compacted=True,
            )
            raw_rows, raw_physical_count = read_view(
                include_inactive=True,
                include_compacted=False,
            )
            canonical = _audit_canonical_view(session_id, canonical_rows, raw_rows)
        except OverflowError:
            return _failed_source("overflow", "source_physical_row_limit_exceeded")
        except _ProjectionError as exc:
            return _failed_source("ambiguous", str(exc))
        except Exception:
            return _failed_source("unavailable", "recent_source_read_failed")

        source = _project_canonical_source(
            session_id,
            canonical,
            full_prefix=False,
            max_groups=max_groups,
            include_lineage_proofs=True,
        )
        if source.get("status") == "ready":
            source["stats"] = {
                **dict(source.get("stats") or {}),
                "physical_row_count": raw_physical_count,
                "canonical_physical_row_count": canonical_physical_count,
                "max_physical_rows": max_physical_rows,
            }
        return source

    def read_recent_lineage_source(
        self,
        lineage_session_ids: Sequence[str],
        *,
        start_timestamp: float,
        end_timestamp: float,
        max_physical_rows: int,
        max_groups: int,
    ) -> Dict[str, Any]:
        """Read one bounded ancestor-to-tip window and collapse exact clones."""

        lineage = [str(value or "").strip() for value in lineage_session_ids]
        if (
            not lineage
            or len(lineage) > _CANONICAL_WINDOW_MAX_LINEAGE_SESSIONS
            or len(lineage) != len(set(lineage))
            or any(not _CODE_RE.fullmatch(value) for value in lineage)
            or not isinstance(start_timestamp, (int, float))
            or isinstance(start_timestamp, bool)
            or not isinstance(end_timestamp, (int, float))
            or isinstance(end_timestamp, bool)
            or float(start_timestamp) > float(end_timestamp)
            or type(max_physical_rows) is not int
            or max_physical_rows < 1
            or type(max_groups) is not int
            or max_groups < 0
        ):
            return _failed_source("ambiguous", "recent_lineage_request_invalid")

        groups: List[Dict[str, Any]] = []
        signatures: Dict[str, str] = {}
        selected_evidence: List[Dict[str, str]] = []
        prior_counts: Dict[str, int] = defaultdict(int)
        physical_row_count = 0
        canonical_physical_row_count = 0
        for session_id in lineage:
            remaining_physical_rows = max_physical_rows - physical_row_count
            if remaining_physical_rows < 1:
                return _failed_source(
                    "overflow", "source_physical_row_limit_exceeded"
                )
            source = self._read_recent_session_source(
                session_id,
                start_timestamp=float(start_timestamp),
                end_timestamp=float(end_timestamp),
                max_physical_rows=remaining_physical_rows,
                max_groups=max_groups,
            )
            if source.get("status") != "ready" or source.get("scan_complete") is not True:
                return source
            source_groups = source.get("groups")
            proofs = source.get("_lineage_group_proofs")
            if (
                not isinstance(source_groups, list)
                or not isinstance(proofs, list)
                or len(source_groups) != len(proofs)
            ):
                return _failed_source("ambiguous", "recent_lineage_proof_invalid")
            stats = dict(source.get("stats") or {})
            physical_row_count += int(stats.get("physical_row_count") or 0)
            canonical_physical_row_count += int(
                stats.get("canonical_physical_row_count") or 0
            )
            session_counts: Dict[str, int] = defaultdict(int)
            for group, proof in zip(source_groups, proofs):
                if not isinstance(group, Mapping) or not isinstance(proof, Mapping):
                    return _failed_source("ambiguous", "recent_lineage_proof_invalid")
                visible_key = str(proof.get("visible_key") or "")
                persisted_signature = str(proof.get("persisted_signature") or "")
                evidence = proof.get("source_evidence")
                if not _SHA256_RE.fullmatch(visible_key) or not _SHA256_RE.fullmatch(
                    persisted_signature
                ) or not isinstance(evidence, Mapping) or set(evidence) != {
                    "display_kind",
                    "internal_kind",
                } or any(not isinstance(value, str) for value in evidence.values()):
                    return _failed_source("ambiguous", "recent_lineage_proof_invalid")
                known_signature = signatures.get(visible_key)
                if known_signature is not None and known_signature != persisted_signature:
                    return _failed_source("ambiguous", "lineage_clone_sidecar_collision")
                signatures[visible_key] = persisted_signature
                occurrence = session_counts[visible_key]
                session_counts[visible_key] += 1
                if occurrence < prior_counts[visible_key]:
                    continue
                groups.append(dict(group))
                selected_evidence.append(dict(evidence))
                if len(groups) > max_groups:
                    return _failed_source("overflow", "source_group_limit_exceeded")
            for visible_key, count in session_counts.items():
                prior_counts[visible_key] = max(prior_counts[visible_key], count)

        normalized = normalize_complete_thread_groups(groups)
        if not normalized["complete"] or normalized["groups"] != groups:
            return _failed_source("ambiguous", "recent_lineage_groups_invalid")
        snapshot_rows = _snapshot_rows(groups)
        return {
            "status": "ready",
            "groups": groups,
            "_group_source_evidence": selected_evidence,
            "source_prefix_ids": [group["source_prefix_id"] for group in groups],
            "_snapshot_rows": snapshot_rows,
            "source_snapshot": _sha256(snapshot_rows),
            "scan_complete": True,
            "stats": {
                "full_prefix": False,
                "returned_groups": len(groups),
                "lineage_session_count": len(lineage),
                "physical_row_count": physical_row_count,
                "canonical_physical_row_count": canonical_physical_row_count,
                "max_physical_rows": max_physical_rows,
                "compacted_prefix_group_ids": [],
            },
        }

    def read_bundle(self, session_id: str) -> Dict[str, Any]:
        source = self.read_source(session_id)
        continuity = (
            self.metadata_store.read_continuity(session_id, source)
            if self.metadata_store is not None
            else {"status": "absent", "state": {}, "error": ""}
        )
        return {"source": source, "continuity": continuity}

    def settle_checkpoint_delivery(
        self,
        session_id: str,
        *,
        expected_revision: int,
        expected_source_snapshot: str,
        checkpoint_candidate: Mapping[str, Any] | None,
        receipt_id: str,
        source_ids: Sequence[str] = (),
        hashes: Mapping[str, str] | None = None,
        counts: Mapping[str, int] | None = None,
        recorded_at: str | None = None,
    ) -> Dict[str, Any]:
        if self.metadata_store is None:
            return {"ok": False, "status": "failed", "error": "metadata_store_unavailable"}
        return self.metadata_store.settle_checkpoint_delivery(
            session_id,
            expected_revision=expected_revision,
            expected_source_snapshot=expected_source_snapshot,
            checkpoint_candidate=checkpoint_candidate,
            receipt_id=receipt_id,
            source_ids=source_ids,
            hashes=hashes,
            counts=counts,
            recorded_at=recorded_at,
            source_reread=self.read_source,
        )


class ContinuityCanonicalSourceService:
    """Expose one frozen, profile-local canonical near-field window.

    The active profile's SessionDB is the hard agent/realm boundary. This
    service does not accept a user-id filter, does not search transcripts, and
    never writes Continuity metadata. It only projects sources already audited
    by :class:`HermesSessionAdapter`.
    """

    def __init__(
        self,
        adapter: HermesSessionAdapter,
        *,
        max_physical_rows: int = _CANONICAL_WINDOW_MAX_PHYSICAL_ROWS,
        additional_human_sources: Sequence[str] = (),
    ) -> None:
        if type(max_physical_rows) is not int or max_physical_rows < 1:
            raise ValueError("canonical_window_physical_row_limit_invalid")
        self.adapter = adapter
        self.session_db = adapter.session_db
        self.max_physical_rows = max_physical_rows
        self.max_lineage_sessions = _CANONICAL_WINDOW_MAX_LINEAGE_SESSIONS
        normalized_human_sources = set(_HUMAN_SESSION_SOURCES)
        for value in additional_human_sources:
            source = str(value or "").strip().lower()
            if not _CODE_RE.fullmatch(source):
                raise ValueError("canonical_window_human_source_invalid")
            normalized_human_sources.add(source)
        self.human_session_sources = frozenset(normalized_human_sources)

    @staticmethod
    def _parse_request(request: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(request, Mapping):
            raise _ProjectionError("canonical_window_request_invalid")
        row = dict(request)
        if (
            not _CANONICAL_WINDOW_REQUIRED_REQUEST_KEYS.issubset(row)
            or not set(row).issubset(_CANONICAL_WINDOW_REQUEST_KEYS)
            or row.get("schema") != _CANONICAL_WINDOW_REQUEST_SCHEMA
        ):
            raise _ProjectionError("canonical_window_request_invalid")

        current_session_id = str(row.get("current_session_id") or "").strip()
        if not _CODE_RE.fullmatch(current_session_id):
            raise _ProjectionError("canonical_window_session_invalid")

        reference_raw = row.get("reference_at")
        if not isinstance(reference_raw, str) or not reference_raw.strip():
            raise _ProjectionError("canonical_window_reference_invalid")
        try:
            reference = datetime.fromisoformat(
                reference_raw.strip().replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise _ProjectionError("canonical_window_reference_invalid") from exc
        if reference.tzinfo is None or reference.utcoffset() != timedelta(0):
            raise _ProjectionError("canonical_window_reference_invalid")
        reference = reference.astimezone(timezone.utc)

        horizon_seconds = row.get("horizon_seconds", 7_200)
        max_sessions = row.get("max_sessions", 16)
        max_groups = row.get("max_groups", 64)
        if (
            type(horizon_seconds) is not int
            or not 1 <= horizon_seconds <= 86_400
            or type(max_sessions) is not int
            or not 1 <= max_sessions <= 64
            or type(max_groups) is not int
            or not 1 <= max_groups <= 128
        ):
            raise _ProjectionError("canonical_window_bounds_invalid")

        excluded_raw = row.get(
            "excluded_sources",
            list(_CANONICAL_WINDOW_DEFAULT_EXCLUDED_SOURCES),
        )
        if not isinstance(excluded_raw, list) or len(excluded_raw) > 64:
            raise _ProjectionError("canonical_window_sources_invalid")
        excluded_sources: List[str] = []
        for value in excluded_raw:
            if not isinstance(value, str):
                raise _ProjectionError("canonical_window_sources_invalid")
            source = value.strip()
            if not _CODE_RE.fullmatch(source):
                raise _ProjectionError("canonical_window_sources_invalid")
            if source not in excluded_sources:
                excluded_sources.append(source)
        excluded_sources.sort()
        allowed_raw = row.get(
            "allowed_source_classes",
            sorted(_CANONICAL_WINDOW_SOURCE_CLASSES),
        )
        if not isinstance(allowed_raw, list) or not 1 <= len(allowed_raw) <= 6:
            raise _ProjectionError("canonical_window_source_classes_invalid")
        allowed_source_classes: List[str] = []
        for value in allowed_raw:
            source_class = str(value or "").strip().lower()
            if source_class not in _CANONICAL_WINDOW_SOURCE_CLASSES:
                raise _ProjectionError("canonical_window_source_classes_invalid")
            if source_class not in allowed_source_classes:
                allowed_source_classes.append(source_class)
        allowed_source_classes.sort()
        return {
            "schema": _CANONICAL_WINDOW_REQUEST_SCHEMA,
            "current_session_id": current_session_id,
            "reference_at": reference.isoformat(),
            "reference": reference,
            "horizon_seconds": horizon_seconds,
            "max_sessions": max_sessions,
            "max_groups": max_groups,
            "excluded_sources": excluded_sources,
            "allowed_source_classes": allowed_source_classes,
        }

    @staticmethod
    def _event_time(value: Any) -> datetime:
        try:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parsed = datetime.fromtimestamp(float(value), timezone.utc)
            elif isinstance(value, str) and value.strip():
                text = value.strip()
                try:
                    parsed = datetime.fromtimestamp(float(text), timezone.utc)
                except ValueError:
                    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError
            else:
                raise ValueError
        except (OverflowError, OSError, TypeError, ValueError) as exc:
            raise _ProjectionError("canonical_window_event_time_invalid") from exc
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _trace(
        *,
        listed_session_count: int = 0,
        candidate_session_count: int = 0,
        source_session_count: int = 0,
        returned_group_count: int = 0,
        outside_horizon_session_count: int = 0,
        outside_horizon_group_count: int = 0,
        current_lineage_excluded_count: int = 0,
        policy_excluded_group_count: int = 0,
        session_proofs: Sequence[Mapping[str, Any]] = (),
        group_proofs: Sequence[Mapping[str, Any]] = (),
    ) -> Dict[str, Any]:
        return {
            "schema": _CANONICAL_WINDOW_TRACE_SCHEMA,
            "listed_session_count": int(listed_session_count),
            "candidate_session_count": int(candidate_session_count),
            "source_session_count": int(source_session_count),
            "returned_group_count": int(returned_group_count),
            "outside_horizon_session_count": int(outside_horizon_session_count),
            "outside_horizon_group_count": int(outside_horizon_group_count),
            "current_lineage_excluded_count": int(current_lineage_excluded_count),
            "policy_excluded_group_count": int(policy_excluded_group_count),
            "session_proofs_sha256": _sha256(list(session_proofs)),
            "group_proofs_sha256": _sha256(list(group_proofs)),
            "body_included": False,
        }

    @staticmethod
    def _response(
        *,
        status: str,
        reason: str,
        request: Mapping[str, Any] | None,
        groups: Sequence[Mapping[str, Any]] = (),
        revision_material: Mapping[str, Any] | None = None,
        trace: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        request_row = dict(request or {})
        public_groups = [copy.deepcopy(dict(group)) for group in groups]
        return {
            "schema": _CANONICAL_WINDOW_RESPONSE_SCHEMA,
            "status": status,
            "reason": reason,
            "reference_at": str(request_row.get("reference_at") or ""),
            "horizon_seconds": int(request_row.get("horizon_seconds") or 7_200),
            "source_revision": _sha256(
                {
                    "status": status,
                    "reason": reason,
                    "material": dict(revision_material or {}),
                }
            ),
            "scan_complete": status in {"ready", "empty"},
            "groups": public_groups,
            "trace": dict(trace or ContinuityCanonicalSourceService._trace()),
        }

    @staticmethod
    def _request_revision_fields(request: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "schema": request["schema"],
            "current_session_id": request["current_session_id"],
            "reference_at": request["reference_at"],
            "horizon_seconds": request["horizon_seconds"],
            "max_sessions": request["max_sessions"],
            "max_groups": request["max_groups"],
            "excluded_sources": list(request["excluded_sources"]),
            "allowed_source_classes": list(request["allowed_source_classes"]),
            "future_tolerance_seconds": _CANONICAL_WINDOW_FUTURE_TOLERANCE_SECONDS,
        }

    @staticmethod
    def _neutral_group(
        *,
        source_session_id: str,
        source: str,
        source_class: str,
        source_snapshot: str,
        group: Mapping[str, Any],
    ) -> Dict[str, Any]:
        group_id = str(group.get("source_prefix_id") or "").strip()
        if not _CODE_RE.fullmatch(group_id):
            raise _ProjectionError("canonical_window_group_id_invalid")
        occurred = ContinuityCanonicalSourceService._event_time(
            group.get("effective_event_at")
        ).isoformat()
        raw_messages = group.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            raise _ProjectionError("canonical_window_messages_invalid")
        messages: List[Dict[str, Any]] = []
        seen_message_ids: set[str] = set()
        for raw in raw_messages:
            if not isinstance(raw, Mapping):
                raise _ProjectionError("canonical_window_messages_invalid")
            message_id = str(raw.get("message_id") or "").strip()
            role = str(raw.get("role") or "").strip().lower()
            content_hash = str(raw.get("content_hash") or "").strip()
            content = raw.get("content")
            if (
                not _CODE_RE.fullmatch(message_id)
                or message_id in seen_message_ids
                or role not in {"user", "assistant"}
                or not _SHA256_RE.fullmatch(content_hash)
                or content_hash != _content_hash(content)
            ):
                raise _ProjectionError("canonical_window_messages_invalid")
            seen_message_ids.add(message_id)
            messages.append(
                {
                    "message_id": message_id,
                    "role": role,
                    "content": copy.deepcopy(content),
                    "content_hash": content_hash,
                }
            )
        return {
            "source_session_id": source_session_id,
            "source": source,
            "source_class": source_class,
            "source_snapshot": source_snapshot,
            "group_id": group_id,
            "effective_event_at": occurred,
            "messages": messages,
        }

    def read_window(self, request: Mapping[str, Any]) -> Dict[str, Any]:
        """Synchronously read one complete frozen window without side effects."""

        try:
            parsed = self._parse_request(request)
        except _ProjectionError:
            return self._response(
                status="failed",
                reason="request_invalid",
                request=None,
                revision_material={"schema": _CANONICAL_WINDOW_REQUEST_SCHEMA},
            )

        request_revision = self._request_revision_fields(parsed)
        list_sessions = getattr(self.session_db, "list_sessions_rich", None)
        get_lineage = getattr(self.session_db, "get_compression_lineage", None)
        recent_reader = getattr(self.session_db, "get_messages_time_window", None)
        read_recent_lineage = getattr(
            self.adapter, "read_recent_lineage_source", None
        )
        if (
            not callable(list_sessions)
            or not callable(get_lineage)
            or not callable(recent_reader)
            or not callable(read_recent_lineage)
        ):
            return self._response(
                status="failed",
                reason="host_incompatible",
                request=parsed,
                revision_material={"request": request_revision, "host": "incompatible"},
            )

        try:
            lineage_values = get_lineage(parsed["current_session_id"])
            if not isinstance(lineage_values, list) or not lineage_values:
                raise _ProjectionError("canonical_window_lineage_invalid")
            if len(lineage_values) > self.max_lineage_sessions:
                raise _ProjectionError("canonical_window_lineage_invalid")
            current_lineage: set[str] = set()
            for value in lineage_values:
                lineage_id = str(value).strip() if isinstance(value, str) else ""
                if not _CODE_RE.fullmatch(lineage_id):
                    raise _ProjectionError("canonical_window_lineage_invalid")
                current_lineage.add(lineage_id)
            if (
                len(current_lineage) != len(lineage_values)
                or parsed["current_session_id"] not in current_lineage
            ):
                raise _ProjectionError("canonical_window_lineage_invalid")
        except Exception:
            return self._response(
                status="failed",
                reason="session_list_failed",
                request=parsed,
                revision_material={"request": request_revision, "list": "failed"},
            )

        reference = parsed["reference"]
        cutoff = reference - timedelta(seconds=parsed["horizon_seconds"])
        upper_bound = reference + timedelta(
            seconds=_CANONICAL_WINDOW_FUTURE_TOLERANCE_SECONDS
        )
        candidates: List[Dict[str, Any]] = []
        listed_session_count = 0
        outside_horizon_session_count = 0
        current_lineage_excluded_count = 0
        seen_session_ids: set[str] = set()
        prior_last_active: datetime | None = None
        # One extra row is the completeness sentinel. Current-lineage tips may
        # consume list rows without being candidates, so they receive their
        # own bounded allowance; future-skew rows consume the same finite
        # budget and therefore block instead of causing an unbounded scan.
        session_scan_budget = (
            parsed["max_sessions"] + len(current_lineage) + 1
        )
        session_scan_exhausted = False
        offset = 0
        try:
            while True:
                remaining_session_rows = session_scan_budget - listed_session_count
                if remaining_session_rows < 1:
                    session_scan_exhausted = True
                    break
                page_size = min(64, remaining_session_rows)
                page = list_sessions(
                    exclude_sources=list(parsed["excluded_sources"]),
                    limit=page_size,
                    offset=offset,
                    include_children=False,
                    project_compression_tips=True,
                    order_by_last_active=True,
                    compact_rows=True,
                )
                if not isinstance(page, list) or len(page) > page_size or any(
                    not isinstance(row, Mapping) for row in page
                ):
                    raise _ProjectionError("canonical_window_session_list_invalid")
                reached_cutoff = False
                for raw in page:
                    row = dict(raw)
                    session_id = str(row.get("id") or "").strip()
                    source = str(row.get("source") or "").strip()
                    lineage_root = str(row.get("_lineage_root_id") or "").strip()
                    if (
                        not _CODE_RE.fullmatch(session_id)
                        or session_id in seen_session_ids
                        or not _CODE_RE.fullmatch(source)
                        or source in parsed["excluded_sources"]
                        or (lineage_root and not _CODE_RE.fullmatch(lineage_root))
                    ):
                        raise _ProjectionError("canonical_window_session_row_invalid")
                    seen_session_ids.add(session_id)
                    listed_session_count += 1
                    last_active = self._event_time(row.get("last_active"))
                    if prior_last_active is not None and last_active > prior_last_active:
                        raise _ProjectionError("canonical_window_session_order_invalid")
                    prior_last_active = last_active
                    if last_active < cutoff:
                        outside_horizon_session_count += 1
                        reached_cutoff = True
                        break
                    if last_active > upper_bound:
                        outside_horizon_session_count += 1
                        continue
                    if session_id in current_lineage or lineage_root in current_lineage:
                        current_lineage_excluded_count += 1
                        continue
                    candidates.append(
                        {
                            "source_session_id": session_id,
                            "source": source,
                            "last_active": last_active.isoformat(),
                        }
                    )
                    if len(candidates) > parsed["max_sessions"]:
                        break
                if len(candidates) > parsed["max_sessions"] or reached_cutoff:
                    break
                if len(page) < page_size:
                    break
                offset += len(page)
                if listed_session_count >= session_scan_budget:
                    session_scan_exhausted = True
                    break
        except _ProjectionError:
            trace = self._trace(
                listed_session_count=listed_session_count,
                outside_horizon_session_count=outside_horizon_session_count,
                current_lineage_excluded_count=current_lineage_excluded_count,
            )
            return self._response(
                status="blocked",
                reason="session_listing_ambiguous",
                request=parsed,
                revision_material={"request": request_revision, "list": "ambiguous"},
                trace=trace,
            )
        except Exception:
            return self._response(
                status="failed",
                reason="session_list_failed",
                request=parsed,
                revision_material={"request": request_revision, "list": "failed"},
                trace=self._trace(
                    listed_session_count=listed_session_count,
                    outside_horizon_session_count=outside_horizon_session_count,
                    current_lineage_excluded_count=current_lineage_excluded_count,
                ),
            )

        candidate_proofs = [
            {
                "source_session_id_sha256": _sha256(row["source_session_id"]),
                "source_sha256": _sha256(row["source"]),
                "last_active": row["last_active"],
            }
            for row in candidates
        ]
        base_trace_values = {
            "listed_session_count": listed_session_count,
            "candidate_session_count": len(candidates),
            "outside_horizon_session_count": outside_horizon_session_count,
            "current_lineage_excluded_count": current_lineage_excluded_count,
        }
        if len(candidates) > parsed["max_sessions"] or session_scan_exhausted:
            return self._response(
                status="blocked",
                reason="session_limit_exceeded",
                request=parsed,
                revision_material={
                    "request": request_revision,
                    "candidates": candidate_proofs,
                },
                trace=self._trace(
                    **base_trace_values,
                    session_proofs=candidate_proofs,
                ),
            )

        neutral_groups: List[Dict[str, Any]] = []
        session_proofs: List[Dict[str, Any]] = []
        outside_horizon_group_count = 0
        policy_excluded_group_count = 0
        audited_group_count = 0
        seen_candidate_lineage_sessions: set[str] = set()
        for candidate in candidates:
            session_id = candidate["source_session_id"]
            source = candidate["source"]
            try:
                lineage_values = get_lineage(session_id)
                if not isinstance(lineage_values, list) or not lineage_values:
                    raise _ProjectionError("candidate_lineage_invalid")
                if len(lineage_values) > self.max_lineage_sessions:
                    raise OverflowError("candidate_lineage_limit_exceeded")
                candidate_lineage: List[str] = []
                for value in lineage_values:
                    lineage_id = str(value).strip() if isinstance(value, str) else ""
                    if not _CODE_RE.fullmatch(lineage_id):
                        raise _ProjectionError("candidate_lineage_invalid")
                    candidate_lineage.append(lineage_id)
                if (
                    len(candidate_lineage) != len(set(candidate_lineage))
                    or candidate_lineage[-1] != session_id
                    or set(candidate_lineage).intersection(current_lineage)
                    or set(candidate_lineage).intersection(
                        seen_candidate_lineage_sessions
                    )
                ):
                    raise _ProjectionError("candidate_lineage_invalid")
                seen_candidate_lineage_sessions.update(candidate_lineage)
                source_result = read_recent_lineage(
                    candidate_lineage,
                    start_timestamp=cutoff.timestamp(),
                    end_timestamp=upper_bound.timestamp(),
                    max_physical_rows=self.max_physical_rows,
                    max_groups=parsed["max_groups"] - audited_group_count,
                )
            except Exception:
                source_result = None
            if (
                not isinstance(source_result, Mapping)
                or source_result.get("status") != "ready"
                or source_result.get("scan_complete") is not True
                or not _SHA256_RE.fullmatch(
                    str(source_result.get("source_snapshot") or "")
                )
                or not isinstance(source_result.get("groups"), list)
                or not isinstance(
                    source_result.get("_group_source_evidence"), list
                )
                or len(source_result["groups"])
                != len(source_result["_group_source_evidence"])
            ):
                source_status = (
                    str(source_result.get("status") or "")
                    if isinstance(source_result, Mapping)
                    else ""
                )
                return self._response(
                    status="blocked",
                    reason=(
                        "group_limit_exceeded"
                        if source_status == "overflow"
                        and isinstance(source_result, Mapping)
                        and source_result.get("error")
                        == "source_group_limit_exceeded"
                        else (
                            "candidate_source_ambiguous"
                            if source_status == "ambiguous"
                            else "candidate_source_unavailable"
                        )
                    ),
                    request=parsed,
                    revision_material={
                        "request": request_revision,
                        "candidates": candidate_proofs,
                        "accepted_sessions": session_proofs,
                    },
                    trace=self._trace(
                        **base_trace_values,
                        source_session_count=len(session_proofs),
                        session_proofs=session_proofs,
                    ),
                )
            source_snapshot = str(source_result["source_snapshot"])
            audited_group_count += len(source_result["groups"])
            if audited_group_count > parsed["max_groups"]:
                return self._response(
                    status="blocked",
                    reason="group_limit_exceeded",
                    request=parsed,
                    revision_material={
                        "request": request_revision,
                        "candidates": candidate_proofs,
                        "accepted_sessions": session_proofs,
                    },
                    trace=self._trace(
                        **base_trace_values,
                        source_session_count=len(session_proofs),
                        outside_horizon_group_count=outside_horizon_group_count,
                        policy_excluded_group_count=policy_excluded_group_count,
                        session_proofs=session_proofs,
                    ),
                )
            session_group_proofs: List[Dict[str, Any]] = []
            try:
                for group, evidence in zip(
                    source_result["groups"],
                    source_result["_group_source_evidence"],
                ):
                    if not isinstance(group, Mapping):
                        raise _ProjectionError("canonical_window_group_invalid")
                    if not isinstance(evidence, Mapping):
                        raise _ProjectionError("canonical_window_source_evidence_invalid")
                    classification = _source_class(
                        source,
                        evidence,
                        self.human_session_sources,
                    )
                    neutral = self._neutral_group(
                        source_session_id=session_id,
                        source=source,
                        source_class=classification,
                        source_snapshot=source_snapshot,
                        group=group,
                    )
                    occurred = self._event_time(neutral["effective_event_at"])
                    group_proof = {
                        "group_id": neutral["group_id"],
                        "source_class": neutral["source_class"],
                        "effective_event_at": neutral["effective_event_at"],
                        "messages": [
                            {
                                "message_id": message["message_id"],
                                "role": message["role"],
                                "content_hash": message["content_hash"],
                            }
                            for message in neutral["messages"]
                        ],
                    }
                    session_group_proofs.append(group_proof)
                    if occurred < cutoff or occurred > upper_bound:
                        outside_horizon_group_count += 1
                        continue
                    if classification not in parsed["allowed_source_classes"]:
                        policy_excluded_group_count += 1
                        continue
                    neutral_groups.append(neutral)
            except (_ProjectionError, TypeError, ValueError):
                return self._response(
                    status="blocked",
                    reason="candidate_source_ambiguous",
                    request=parsed,
                    revision_material={
                        "request": request_revision,
                        "candidates": candidate_proofs,
                        "accepted_sessions": session_proofs,
                    },
                    trace=self._trace(
                        **base_trace_values,
                        source_session_count=len(session_proofs),
                        outside_horizon_group_count=outside_horizon_group_count,
                        session_proofs=session_proofs,
                    ),
                )
            session_proofs.append(
                {
                    "source_session_id": session_id,
                    "source": source,
                    "source_snapshot": source_snapshot,
                    "lineage_session_ids": candidate_lineage,
                    "groups": session_group_proofs,
                }
            )

        neutral_groups.sort(
            key=lambda group: (group["effective_event_at"], group["group_id"])
        )
        group_proofs = [
            {
                "source_session_id": group["source_session_id"],
                "source": group["source"],
                "source_class": group["source_class"],
                "source_snapshot": group["source_snapshot"],
                "group_id": group["group_id"],
                "effective_event_at": group["effective_event_at"],
                "messages": [
                    {
                        "message_id": message["message_id"],
                        "role": message["role"],
                        "content_hash": message["content_hash"],
                    }
                    for message in group["messages"]
                ],
            }
            for group in neutral_groups
        ]
        trace = self._trace(
            **base_trace_values,
            source_session_count=len(session_proofs),
            returned_group_count=len(neutral_groups),
            outside_horizon_group_count=outside_horizon_group_count,
            policy_excluded_group_count=policy_excluded_group_count,
            session_proofs=session_proofs,
            group_proofs=group_proofs,
        )
        revision_material = {
            "schema": _CANONICAL_WINDOW_RESPONSE_SCHEMA,
            "request": request_revision,
            "policy": {
                "max_physical_rows": self.max_physical_rows,
                "max_lineage_sessions": self.max_lineage_sessions,
            },
            "sessions": sorted(
                session_proofs,
                key=lambda row: (row["source_session_id"], row["source_snapshot"]),
            ),
            "groups": group_proofs,
        }
        if len(neutral_groups) > parsed["max_groups"]:
            return self._response(
                status="blocked",
                reason="group_limit_exceeded",
                request=parsed,
                revision_material=revision_material,
                trace=trace,
            )
        status = "ready" if neutral_groups else "empty"
        empty_reason = (
            "no_allowed_groups_in_window"
            if policy_excluded_group_count
            else "no_complete_groups_in_window"
        )
        return self._response(
            status=status,
            reason="" if neutral_groups else empty_reason,
            request=parsed,
            groups=neutral_groups,
            revision_material=revision_material,
            trace=trace,
        )


class ContinuityMetadataStore:
    """Own generated checkpoints and body-free receipts, never Hermes messages."""

    _OWNER_ID = "hermes-continuity.v1"
    _HERMES_CANONICAL_TABLES = frozenset(
        {
            "schema_version",
            "system_prompts",
            "sessions",
            "messages",
            "session_model_usage",
            "state_meta",
            "gateway_routing",
            "gateway_hygiene_state",
            "compression_locks",
            "session_turn_leases",
            "async_delegations",
        }
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            schema_objects = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    "SELECT name, type FROM sqlite_master"
                )
                if not str(row[0]).startswith("sqlite_")
            }
            tables = {
                name
                for name, object_type in schema_objects.items()
                if object_type == "table"
            }
            if tables & self._HERMES_CANONICAL_TABLES:
                raise ValueError("plugin_metadata_store_canonical_conflict")
            if "hermes_plugin_store_owner" in tables:
                try:
                    owner = connection.execute(
                        "SELECT owner_id FROM hermes_plugin_store_owner "
                        "WHERE singleton = 1"
                    ).fetchone()
                except sqlite3.Error as exc:
                    raise ValueError(
                        "plugin_metadata_store_owner_conflict"
                    ) from exc
                if owner is None or owner["owner_id"] != self._OWNER_ID:
                    raise ValueError("plugin_metadata_store_owner_conflict")
            elif schema_objects:
                raise ValueError("plugin_metadata_store_unclaimed")
            else:
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
                    (self._OWNER_ID,),
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS continuity_checkpoints (
                    session_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    source_snapshot TEXT NOT NULL,
                    source_prefix_ids_json TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    checkpoint_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS continuity_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    receipt_kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    hashes_json TEXT NOT NULL,
                    counts_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """,
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS continuity_receipts_session "
                "ON continuity_receipts(session_id, recorded_at, receipt_id)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode_checkpoint(row: sqlite3.Row | None) -> Dict[str, Any]:
        if row is None:
            return {}
        try:
            checkpoint = json.loads(row["checkpoint_json"])
            source_ids = json.loads(row["source_prefix_ids_json"])
        except (json.JSONDecodeError, TypeError):
            return {"error": "checkpoint_state_corrupt"}
        if (
            not isinstance(checkpoint, dict)
            or not isinstance(source_ids, list)
            or row["checkpoint_sha256"] != _sha256(checkpoint)
        ):
            return {"error": "checkpoint_state_corrupt"}
        return {
            "revision": int(row["revision"]),
            "source_snapshot": str(row["source_snapshot"]),
            "source_prefix_ids": [str(value) for value in source_ids],
            "checkpoint": checkpoint,
            "checkpoint_sha256": str(row["checkpoint_sha256"]),
            "updated_at": str(row["updated_at"]),
        }

    def read_continuity(
        self, session_id: str, source: Mapping[str, Any]
    ) -> Dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM continuity_checkpoints WHERE session_id = ?",
                (str(session_id),),
            ).fetchone()
        if row is None:
            return {"status": "absent", "state": {}, "error": ""}
        state = self._decode_checkpoint(row)
        if state.get("error"):
            return {"status": "unavailable", "state": {}, "error": state["error"]}
        if source.get("status") != "ready" or source.get("scan_complete") is not True:
            return {"status": "unavailable", "state": {}, "error": "source_unavailable"}
        groups = list(source.get("groups") or [])
        current_ids = [str(group.get("source_prefix_id") or "") for group in groups]
        stored_ids = list(state["source_prefix_ids"])
        if (
            stored_ids != current_ids[: len(stored_ids)]
            or state["source_snapshot"] != _source_snapshot(groups[: len(stored_ids)])
        ):
            return {
                "status": "unavailable",
                "state": {},
                "error": "thread_continuity_source_conflict",
            }
        try:
            checkpoint = normalize_thread_continuity_checkpoint(
                state["checkpoint"], source_groups=groups
            )
        except (TypeError, ValueError):
            return {
                "status": "unavailable",
                "state": {},
                "error": "thread_continuity_checkpoint_invalid",
            }
        if checkpoint != state["checkpoint"]:
            return {
                "status": "unavailable",
                "state": {},
                "error": "thread_continuity_checkpoint_invalid",
            }
        return {
            "status": "ready",
            "state": {
                **state,
                "checkpoint": checkpoint,
                "source_advanced": len(current_ids) > len(stored_ids),
            },
            "error": "",
        }

    def _checkpoint_outcome(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        expected_revision: int,
        expected_snapshot: str,
        candidate: Mapping[str, Any],
        source: Mapping[str, Any],
    ) -> Dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM continuity_checkpoints WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        state = self._decode_checkpoint(row)
        if state.get("error"):
            return {"status": "failed", "error": state["error"]}
        current_revision = int(state.get("revision") or 0)
        if current_revision != expected_revision:
            return {
                "status": "conflict",
                "error": "thread_continuity_revision_conflict",
                "current_revision": current_revision,
            }
        if source.get("status") != "ready" or source.get("scan_complete") is not True:
            return {
                "status": "failed",
                "error": (
                    "thread_continuity_source_ambiguous"
                    if source.get("status") == "ambiguous"
                    else "thread_continuity_source_incomplete"
                ),
            }
        groups = list(source.get("groups") or [])
        current_ids = [str(group.get("source_prefix_id") or "") for group in groups]
        candidate_ids = [
            str(value or "") for value in list(candidate.get("source_group_ids") or [])
        ]
        if (
            not candidate_ids
            or candidate_ids != current_ids[: len(candidate_ids)]
            or expected_snapshot != _source_snapshot(groups[: len(candidate_ids)])
            or source.get("source_snapshot") != _source_snapshot(groups)
        ):
            return {
                "status": "conflict",
                "error": "thread_continuity_source_conflict",
            }
        previous = state.get("checkpoint") if state else None
        try:
            checkpoint = normalize_thread_continuity_checkpoint(
                candidate,
                source_groups=groups,
                previous_state=previous if isinstance(previous, Mapping) else None,
            )
        except (TypeError, ValueError):
            return {
                "status": "failed",
                "error": "thread_continuity_checkpoint_invalid",
            }
        if checkpoint != candidate or checkpoint.get("revision") != expected_revision + 1:
            return {
                "status": "failed",
                "error": "thread_continuity_checkpoint_invalid",
            }
        return {
            "status": "applied",
            "error": "",
            "checkpoint": checkpoint,
            "source_ids": candidate_ids,
        }

    @staticmethod
    def _write_checkpoint(
        connection: sqlite3.Connection,
        session_id: str,
        source_snapshot: str,
        checkpoint: Mapping[str, Any],
        source_ids: Sequence[str],
    ) -> None:
        connection.execute(
            """
            INSERT INTO continuity_checkpoints (
                session_id, revision, source_snapshot,
                source_prefix_ids_json, checkpoint_json,
                checkpoint_sha256, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                revision = excluded.revision,
                source_snapshot = excluded.source_snapshot,
                source_prefix_ids_json = excluded.source_prefix_ids_json,
                checkpoint_json = excluded.checkpoint_json,
                checkpoint_sha256 = excluded.checkpoint_sha256,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                checkpoint["revision"],
                source_snapshot,
                _json_text(source_ids),
                _json_text(checkpoint),
                _sha256(checkpoint),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    @staticmethod
    def _code(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not _CODE_RE.fullmatch(text):
            raise ValueError(f"{field}_invalid")
        return text

    def _receipt_row(
        self,
        *,
        receipt_id: str,
        session_id: str,
        kind: str,
        status: str,
        source_ids: Sequence[str] = (),
        hashes: Mapping[str, str] | None = None,
        counts: Mapping[str, int] | None = None,
        recorded_at: str | None = None,
    ) -> Dict[str, Any]:
        receipt_id = self._code(receipt_id, "receipt_id")
        session_id = self._code(session_id, "session_id")
        kind = self._code(kind, "receipt_kind")
        status = self._code(status, "receipt_status")
        if kind not in {"delivery", "failure"}:
            raise ValueError("receipt_kind_invalid")
        ids = [self._code(value, "source_id") for value in source_ids]
        if len(ids) != len(set(ids)):
            raise ValueError("source_id_invalid")
        safe_hashes = {
            self._code(key, "hash_name"): str(value or "").strip()
            for key, value in dict(hashes or {}).items()
        }
        if any(not _SHA256_RE.fullmatch(value) for value in safe_hashes.values()):
            raise ValueError("receipt_hash_invalid")
        safe_counts = {
            self._code(key, "count_name"): value
            for key, value in dict(counts or {}).items()
        }
        if any(type(value) is not int or value < 0 for value in safe_counts.values()):
            raise ValueError("receipt_count_invalid")
        if recorded_at is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        else:
            try:
                parsed = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError
                timestamp = parsed.astimezone(timezone.utc).isoformat()
            except ValueError as exc:
                raise ValueError("receipt_time_invalid") from exc
        return {
            "receipt_id": receipt_id,
            "session_id": session_id,
            "kind": kind,
            "status": status,
            "source_ids": ids,
            "hashes": safe_hashes,
            "counts": safe_counts,
            "recorded_at": timestamp,
        }

    @staticmethod
    def _insert_receipt(connection: sqlite3.Connection, receipt: Mapping[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO continuity_receipts (
                receipt_id, session_id, receipt_kind, status,
                source_ids_json, hashes_json, counts_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt["receipt_id"],
                receipt["session_id"],
                receipt["kind"],
                receipt["status"],
                _json_text(receipt["source_ids"]),
                _json_text(receipt["hashes"]),
                _json_text(receipt["counts"]),
                receipt["recorded_at"],
            ),
        )

    @staticmethod
    def _decode_receipt(row: sqlite3.Row) -> Dict[str, Any] | None:
        try:
            source_ids = json.loads(row["source_ids_json"])
            hashes = json.loads(row["hashes_json"])
            counts = json.loads(row["counts_json"])
        except (json.JSONDecodeError, TypeError):
            return None
        if (
            not isinstance(source_ids, list)
            or not isinstance(hashes, dict)
            or not isinstance(counts, dict)
        ):
            return None
        return {
            "receipt_id": row["receipt_id"],
            "session_id": row["session_id"],
            "kind": row["receipt_kind"],
            "status": row["status"],
            "source_ids": source_ids,
            "hashes": hashes,
            "counts": counts,
            "recorded_at": row["recorded_at"],
        }

    def settle_checkpoint_delivery(
        self,
        session_id: str,
        *,
        expected_revision: int,
        expected_source_snapshot: str,
        checkpoint_candidate: Mapping[str, Any] | None,
        receipt_id: str,
        source_ids: Sequence[str] = (),
        hashes: Mapping[str, str] | None = None,
        counts: Mapping[str, int] | None = None,
        recorded_at: str | None = None,
        source_reread: Callable[[str], Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Settle one delivered request without splitting checkpoint and receipt."""

        try:
            session_id = self._code(session_id, "session_id")
            candidate = (
                None if checkpoint_candidate is None else dict(checkpoint_candidate)
            )
            expected_snapshot = str(expected_source_snapshot or "").strip()
            if candidate is not None and (
                type(expected_revision) is not int
                or expected_revision < 0
                or not _SHA256_RE.fullmatch(expected_snapshot)
            ):
                raise ValueError("checkpoint_settlement_input_invalid")
            receipt = self._receipt_row(
                receipt_id=receipt_id,
                session_id=session_id,
                kind="delivery",
                status="delivered_checkpoint_unchanged",
                source_ids=source_ids,
                hashes=hashes,
                counts=counts,
                recorded_at=recorded_at,
            )
        except (TypeError, ValueError):
            return {
                "ok": False,
                "status": "failed",
                "error": "checkpoint_settlement_input_invalid",
                "receipt_recorded": False,
            }

        source: Dict[str, Any] = {}
        source_error = ""
        if candidate is not None:
            try:
                source = dict(source_reread(session_id) or {})
            except Exception:
                source_error = "checkpoint_source_reread_failed"
            if not source_error and (
                source.get("status") != "ready"
                or source.get("scan_complete") is not True
            ):
                source_error = (
                    "thread_continuity_source_ambiguous"
                    if source.get("status") == "ambiguous"
                    else "thread_continuity_source_incomplete"
                )

        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                "SELECT * FROM continuity_receipts WHERE receipt_id = ?",
                (receipt["receipt_id"],),
            ).fetchone()
            if existing_row is not None:
                existing = self._decode_receipt(existing_row)
                same_delivery = bool(
                    existing is not None
                    and existing["session_id"] == receipt["session_id"]
                    and existing["kind"] == receipt["kind"]
                    and existing["source_ids"] == receipt["source_ids"]
                    and existing["hashes"] == receipt["hashes"]
                    and existing["counts"] == receipt["counts"]
                )
                outcomes = {
                    "delivered_checkpoint_applied": "applied",
                    "delivered_checkpoint_unchanged": "unchanged",
                    "delivered_checkpoint_conflict": "conflict",
                    "delivered_checkpoint_failed": "failed",
                }
                outcome = outcomes.get(existing["status"] if existing else "")
                if not same_delivery or outcome is None:
                    connection.rollback()
                    return {
                        "ok": False,
                        "status": "failed",
                        "error": "checkpoint_settlement_receipt_conflict",
                        "receipt_recorded": False,
                    }
                connection.commit()
                return {
                    "ok": outcome in {"applied", "unchanged"},
                    "status": outcome,
                    "error": (
                        ""
                        if outcome in {"applied", "unchanged"}
                        else "thread_continuity_settlement_conflict"
                        if outcome == "conflict"
                        else "checkpoint_settlement_failed"
                    ),
                    "receipt_recorded": True,
                    "idempotent": True,
                }

            outcome = "unchanged"
            error = ""
            checkpoint: Dict[str, Any] | None = None
            candidate_ids: List[str] = []
            if candidate is not None:
                checkpoint_outcome = self._checkpoint_outcome(
                    connection,
                    session_id,
                    expected_revision,
                    expected_snapshot,
                    candidate,
                    source,
                )
                outcome = checkpoint_outcome["status"]
                error = checkpoint_outcome["error"]
                if source_error and error == "thread_continuity_source_incomplete":
                    error = source_error
                checkpoint = checkpoint_outcome.get("checkpoint")
                candidate_ids = checkpoint_outcome.get("source_ids", [])

            if outcome == "applied" and checkpoint is not None:
                self._write_checkpoint(
                    connection,
                    session_id,
                    expected_snapshot,
                    checkpoint,
                    candidate_ids,
                )

            receipt["status"] = f"delivered_checkpoint_{outcome}"
            self._insert_receipt(connection, receipt)
            connection.commit()
            result = {
                "ok": outcome in {"applied", "unchanged"},
                "status": outcome,
                "error": error,
                "receipt_recorded": True,
                "idempotent": False,
            }
            if checkpoint is not None and outcome == "applied":
                result.update(
                    revision=checkpoint["revision"],
                    source_snapshot=expected_snapshot,
                )
            return result
        except sqlite3.Error:
            if connection is not None:
                connection.rollback()
            return {
                "ok": False,
                "status": "failed",
                "error": "checkpoint_storage_failed",
                "receipt_recorded": False,
            }
        finally:
            if connection is not None:
                connection.close()

    def record_receipt(
        self,
        *,
        receipt_id: str,
        session_id: str,
        kind: str,
        status: str,
        source_ids: Sequence[str] = (),
        hashes: Mapping[str, str] | None = None,
        counts: Mapping[str, int] | None = None,
        recorded_at: str | None = None,
    ) -> Dict[str, Any]:
        row = self._receipt_row(
            receipt_id=receipt_id,
            session_id=session_id,
            kind=kind,
            status=status,
            source_ids=source_ids,
            hashes=hashes,
            counts=counts,
            recorded_at=recorded_at,
        )
        with self._connect() as connection:
            self._insert_receipt(connection, row)
        return row

    def status_summary(self, session_id: str = "") -> Dict[str, Any]:
        """Return restart-safe checkpoint/receipt health without any body."""

        session_id = str(session_id or "").strip()
        with self._connect() as connection:
            checkpoint_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuity_checkpoints"
                ).fetchone()[0]
            )
            receipt_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM continuity_receipts"
                ).fetchone()[0]
            )
            checkpoint_row = None
            receipt_row = None
            if session_id:
                session_id = self._code(session_id, "session_id")
                checkpoint_row = connection.execute(
                    "SELECT * FROM continuity_checkpoints WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                receipt_row = connection.execute(
                    """
                    SELECT * FROM continuity_receipts
                    WHERE session_id = ?
                    ORDER BY recorded_at DESC, receipt_id DESC LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
        checkpoint = self._decode_checkpoint(checkpoint_row)
        recent_bridge = (
            checkpoint.get("checkpoint", {}).get("recent_bridge", {})
            if isinstance(checkpoint.get("checkpoint"), Mapping)
            else {}
        )
        receipt = self._decode_receipt(receipt_row) if receipt_row is not None else None
        return {
            "schema": "hermes_continuity_durable_status.v1",
            "session_filter": session_id,
            "checkpoint_count": checkpoint_count,
            "receipt_count": receipt_count,
            "checkpoint": {
                "status": (
                    "ready"
                    if checkpoint and not checkpoint.get("error")
                    else "corrupt"
                    if checkpoint.get("error")
                    else "absent"
                ),
                "revision": int(checkpoint.get("revision") or 0),
                "source_snapshot": str(checkpoint.get("source_snapshot") or ""),
                "source_prefix_count": len(checkpoint.get("source_prefix_ids") or []),
                "recent_bridge_status": str(recent_bridge.get("status") or ""),
                "recent_bridge_body_sha256": str(
                    recent_bridge.get("body_sha256") or ""
                ),
                "represented_source_group_count": len(
                    recent_bridge.get("source_group_ids") or []
                ),
            },
            "last_delivery": (
                {
                    "status": receipt["status"],
                    "recorded_at": receipt["recorded_at"],
                    "hashes": receipt["hashes"],
                    "counts": receipt["counts"],
                }
                if receipt is not None
                else None
            ),
            "body_included": False,
        }
