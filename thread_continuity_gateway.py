"""Body-free linker and capture-boundary projections for thread continuity."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Sequence

from .context_compactor import (
    thread_continuity_bridge_projection,
    thread_continuity_retirement_source_group_ids,
)
from .identity import canonical_aliases


_CAPTURE_TRACE_KEYS = {
    "schema",
    "append_disposition",
    "canonical_winner_record_id",
    "pre_source_match",
    "post_source_snapshot",
    "post_source_group_count",
    "publish_status",
    "publish_error",
    "published_revision",
    "body_included",
}
_LINKER_PROJECTION_KEYS = {
    "schema",
    "projection_phase",
    "candidate_unretired_basis",
    "canonical_source_aliases",
    "candidate_unretired_group_ids",
    "candidate_unretired_aliases",
    "retired_group_ids",
    "retired_aliases",
    "bridge_represented_group_ids",
    "bridge_represented_aliases",
    "bridge_status",
    "bridge_body_sha256",
    "current_ephemeral_aliases",
    "continuity_revision",
    "continuity_revision_id",
    "source_snapshot",
    "body_included",
}
_LINKER_IDENTITY_FIELDS = (
    "canonical_source_aliases",
    "candidate_unretired_group_ids",
    "candidate_unretired_aliases",
    "retired_group_ids",
    "retired_aliases",
    "bridge_represented_group_ids",
    "bridge_represented_aliases",
    "current_ephemeral_aliases",
)


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_revision_id(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith("tcr_")
        and _is_sha256(value[4:])
    )


def _is_canonical_identity_list(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and value == canonical_aliases(value)
    )


def _valid_linker_projection(row: Mapping[str, Any]) -> bool:
    if (
        set(row) != _LINKER_PROJECTION_KEYS
        or row.get("schema") != "thread_continuity_linker_projection.v2"
        or row.get("projection_phase") != "pre_fold"
        or row.get("candidate_unretired_basis")
        != "retirement_cursor_complement"
        or row.get("body_included") is not False
        or any(
            not _is_canonical_identity_list(row.get(field))
            for field in _LINKER_IDENTITY_FIELDS
        )
        or not row.get("canonical_source_aliases")
        or not row.get("current_ephemeral_aliases")
        or not _is_sha256(row.get("source_snapshot"))
    ):
        return False
    revision = row.get("continuity_revision")
    if type(revision) is not int or not 0 <= revision <= 2**63 - 1:
        return False
    revision_id = row.get("continuity_revision_id")
    bridge_sha256 = row.get("bridge_body_sha256")
    bridge_status = row.get("bridge_status")
    if revision == 0:
        if revision_id != "" or bridge_sha256 != "" or bridge_status != "absent":
            return False
        if row.get("retired_group_ids") or row.get("retired_aliases"):
            return False
    elif (
        not _is_revision_id(revision_id)
        or not _is_sha256(bridge_sha256)
        or bridge_status not in {"ready", "empty", "legacy_unverified"}
    ):
        return False
    retired_group_ids = set(row.get("retired_group_ids") or [])
    candidate_group_ids = set(row.get("candidate_unretired_group_ids") or [])
    bridge_group_ids = set(row.get("bridge_represented_group_ids") or [])
    if retired_group_ids & candidate_group_ids or not bridge_group_ids.issubset(
        retired_group_ids
    ):
        return False
    canonical_source_aliases = set(row.get("canonical_source_aliases") or [])
    if not set(row.get("retired_aliases") or []).issubset(
        canonical_source_aliases
    ) or not set(row.get("candidate_unretired_aliases") or []).issubset(
        canonical_source_aliases
    ) or not set(row.get("bridge_represented_aliases") or []).issubset(
        canonical_source_aliases
    ):
        return False
    return True


def _source_group_aliases(group: Mapping[str, Any]) -> List[str]:
    aliases = canonical_aliases(
        group.get("source_prefix_id"),
        group.get("logical_turn_id"),
        group.get("record_id"),
        group.get("canonical_ids"),
        group.get("canonical_aliases"),
        group.get("message_ids"),
    )
    for message in list(group.get("messages") or []):
        if isinstance(message, Mapping):
            aliases = canonical_aliases(
                aliases,
                message.get("message_id"),
                message.get("canonical_ids"),
                message.get("canonical_aliases"),
            )
    return aliases


def build_thread_continuity_linker_projection(
    *,
    source_groups: Sequence[Mapping[str, Any]],
    checkpoint: Mapping[str, Any] | None,
    source_snapshot: str,
    current_ephemeral: Mapping[str, Any],
) -> Dict[str, Any]:
    """Link the current canonical prefix without conflating summary coverage with raw body."""

    groups = [dict(group) for group in source_groups if isinstance(group, Mapping)]
    group_ids = [str(group.get("source_prefix_id") or "").strip() for group in groups]
    if (
        len(groups) != len(source_groups)
        or not group_ids
        or any(not group_id for group_id in group_ids)
        or len(set(group_ids)) != len(group_ids)
    ):
        raise ValueError("thread_continuity_linker_source_invalid")
    snapshot = str(source_snapshot or "").strip()
    if not _is_sha256(snapshot):
        raise ValueError("thread_continuity_linker_snapshot_invalid")

    active_checkpoint = dict(checkpoint or {})
    retired_ids = thread_continuity_retirement_source_group_ids(active_checkpoint)
    if retired_ids != group_ids[: len(retired_ids)]:
        raise ValueError("thread_continuity_linker_retirement_prefix_invalid")
    bridge = thread_continuity_bridge_projection(active_checkpoint)
    bridge_ids = list(bridge["represented_source_group_ids"])
    if bridge_ids:
        start = retired_ids.index(bridge_ids[0]) if bridge_ids[0] in retired_ids else -1
        if start < 0 or bridge_ids != retired_ids[start : start + len(bridge_ids)]:
            raise ValueError("thread_continuity_linker_bridge_slice_invalid")
    revision = active_checkpoint.get("revision", 0)
    revision_id = str(active_checkpoint.get("revision_id") or "").strip()
    bridge_sha256 = str(bridge.get("body_sha256") or "").strip()
    bridge_status = str(bridge.get("status") or "")
    if active_checkpoint and (
        type(revision) is not int
        or not 1 <= revision <= 2**63 - 1
        or not _is_revision_id(revision_id)
        or not _is_sha256(bridge_sha256)
        or bridge_status not in {"ready", "empty", "legacy_unverified"}
    ):
        raise ValueError("thread_continuity_linker_checkpoint_invalid")
    if not active_checkpoint:
        revision, revision_id, bridge_sha256, bridge_status = 0, "", "", "absent"

    retired_groups = groups[: len(retired_ids)]
    candidate_unretired_groups = groups[len(retired_ids) :]
    bridge_id_set = set(bridge_ids)
    bridge_groups = [
        group
        for group in retired_groups
        if str(group.get("source_prefix_id") or "") in bridge_id_set
    ]
    canonical_source_aliases: List[str] = []
    retired_aliases: List[str] = []
    candidate_unretired_aliases: List[str] = []
    bridge_represented_aliases: List[str] = []
    for group in groups:
        canonical_source_aliases = canonical_aliases(
            canonical_source_aliases, _source_group_aliases(group)
        )
    for group in retired_groups:
        retired_aliases = canonical_aliases(
            retired_aliases, _source_group_aliases(group)
        )
    for group in candidate_unretired_groups:
        candidate_unretired_aliases = canonical_aliases(
            candidate_unretired_aliases, _source_group_aliases(group)
        )
    for group in bridge_groups:
        bridge_represented_aliases = canonical_aliases(
            bridge_represented_aliases, _source_group_aliases(group)
        )
    current_aliases = canonical_aliases(
        current_ephemeral.get("message_id"),
        current_ephemeral.get("canonical_ids"),
        current_ephemeral.get("canonical_aliases"),
    )
    if not current_aliases:
        raise ValueError("thread_continuity_linker_current_invalid")
    return {
        "schema": "thread_continuity_linker_projection.v2",
        "projection_phase": "pre_fold",
        "candidate_unretired_basis": "retirement_cursor_complement",
        "canonical_source_aliases": canonical_source_aliases,
        "candidate_unretired_group_ids": [
            str(group.get("source_prefix_id") or "")
            for group in candidate_unretired_groups
        ],
        "candidate_unretired_aliases": candidate_unretired_aliases,
        "retired_group_ids": retired_ids,
        "retired_aliases": retired_aliases,
        "bridge_represented_group_ids": bridge_ids,
        "bridge_represented_aliases": bridge_represented_aliases,
        "bridge_status": bridge_status,
        "bridge_body_sha256": bridge_sha256,
        "current_ephemeral_aliases": current_aliases,
        "continuity_revision": revision,
        "continuity_revision_id": revision_id,
        "source_snapshot": snapshot,
        "body_included": False,
    }


def _linker_identity_trace(field: str, values: Sequence[str]) -> Dict[str, Any]:
    rows = canonical_aliases(values)
    return {
        f"{field}_count": len(rows),
        f"{field}_sha256": hashlib.sha256(
            "\0".join(rows).encode("utf-8")
        ).hexdigest(),
    }


def project_thread_continuity_linker_trace(value: Mapping[str, Any]) -> Dict[str, Any]:
    """Bound the internal exact linker before it enters run metadata or capture."""

    row = dict(value or {})
    if not _valid_linker_projection(row):
        return {}
    candidate_group_trace = _linker_identity_trace(
        "candidate_unretired_group",
        row.get("candidate_unretired_group_ids") or [],
    )
    retired_group_trace = _linker_identity_trace(
        "retired_group",
        row.get("retired_group_ids") or [],
    )
    bridge_group_trace = _linker_identity_trace(
        "bridge_represented_group",
        row.get("bridge_represented_group_ids") or [],
    )
    return {
        "schema": "thread_continuity_linker_trace.v2",
        "projection_phase": "pre_fold",
        "candidate_unretired_basis": "retirement_cursor_complement",
        **_linker_identity_trace(
            "canonical_source_alias", row.get("canonical_source_aliases") or []
        ),
        **candidate_group_trace,
        **_linker_identity_trace(
            "candidate_unretired_alias",
            row.get("candidate_unretired_aliases") or [],
        ),
        **retired_group_trace,
        **_linker_identity_trace(
            "retired_alias",
            row.get("retired_aliases") or [],
        ),
        **bridge_group_trace,
        **_linker_identity_trace(
            "bridge_represented_alias",
            row.get("bridge_represented_aliases") or [],
        ),
        **_linker_identity_trace(
            "current_ephemeral_alias",
            row.get("current_ephemeral_aliases") or [],
        ),
        "continuity_revision": row.get("continuity_revision"),
        "continuity_revision_id": str(row.get("continuity_revision_id") or ""),
        "source_snapshot": str(row.get("source_snapshot") or ""),
        "bridge_status": str(row.get("bridge_status") or ""),
        "bridge_body_sha256": str(row.get("bridge_body_sha256") or ""),
        "body_included": False,
    }


def publish_thread_continuity_handoff(
    sink: Dict[str, Any] | None,
    result: Mapping[str, Any],
) -> None:
    """Move only checkpoint authority fields across the capture boundary."""

    if not isinstance(sink, dict):
        return
    sink.clear()
    sink.update(
        expected_revision=result.get("expected_revision"),
        expected_pre_turn_source_snapshot=result.get(
            "expected_pre_turn_source_snapshot"
        ),
        checkpoint_candidate=result.get("checkpoint_candidate"),
    )


def project_thread_continuity_capture_trace(value: Any) -> Dict[str, Any]:
    """Keep the public capture receipt causal and body-free."""

    row = dict(value) if isinstance(value, Mapping) else {}
    trace = {key: row[key] for key in _CAPTURE_TRACE_KEYS if key in row}
    trace["body_included"] = False
    return trace
