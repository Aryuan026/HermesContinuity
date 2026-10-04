from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Dict, List


THREAD_CONTINUITY_CHECKPOINT_V3_SCHEMA = "thread_continuity_checkpoint.v3"
THREAD_CONTINUITY_COMPACT_SOURCE_SCHEMA = "thread_continuity_compact_source.v1"
THREAD_CONTINUITY_PREFIX_DESCRIPTOR_SCHEMA = (
    "thread_continuity_prefix_descriptor.v1"
)
THREAD_CONTINUITY_RETIREMENT_CURSOR_V2_SCHEMA = (
    "thread_continuity_retirement_cursor.v2"
)
THREAD_CONTINUITY_RETIREMENT_ELIGIBILITY_SCHEMA = (
    "thread_continuity_retirement_eligibility.v1"
)
THREAD_CONTINUITY_CHECKPOINT_VALIDATION_SCHEMA = (
    "thread_continuity_checkpoint_validation.v1"
)
THREAD_CONTINUITY_RECENT_BRIDGE_SCHEMA = "thread_continuity_recent_bridge.v1"
CANONICAL_HISTORY_PREFIX_SCHEMA = "hermes.canonical_history_prefix.v1"


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_ID_RE = re.compile(r"^tcr_[0-9a-f]{64}$")
_HOST_TOKEN_KEYS = {
    "schema",
    "realm_id",
    "incarnation",
    "activation_epoch",
    "domain_id",
    "topology_revision",
    "canonical_rule_version",
    "indexed_change_seq",
    "end_anchor",
    "canonical_count",
    "prefix_hash",
}
_PREFIX_KEYS = {
    "schema",
    "through_anchor",
    "canonical_count",
    "group_count",
    "prefix_hash",
    "group_root",
}
_SOURCE_PROOF_KEYS = {
    "host_token",
    "grouping_rule_version",
    "group_count",
    "group_root",
}
_GROUP_PREFIX_KEYS = {
    "source_prefix_id",
    "source_group_fingerprint",
    "prefix",
}
_ELIGIBILITY_KEYS = {
    "schema",
    "status",
    "prefix",
    "physical_ownership_sha256",
}
_SOURCE_KEYS = {
    "schema",
    "status",
    "scan_complete",
    "source_snapshot",
    "source_proof",
    "prefix_before_groups",
    "groups",
    "group_prefixes",
    "retirement_eligibility",
    "stats",
}
_SOURCE_STATS_KEYS = {
    "full_prefix",
    "canonical_message_count",
    "returned_groups",
    "workset_rows",
    "workset_bytes",
    "compacted_prefix_group_ids",
}
_CHECKPOINT_KEYS = {
    "schema",
    "revision",
    "predecessor_revision",
    "revision_id",
    "predecessor_revision_id",
    "lineage_status",
    "source_proof",
    "retirement_cursor",
    "recent_bridge",
    "storage_state",
}
_CURSOR_KEYS = {
    "schema",
    "relation",
    "through_anchor",
    "canonical_count",
    "group_count",
    "prefix_hash",
    "group_root",
}
_BRIDGE_KEYS = {
    "schema",
    "status",
    "relation",
    "source_group_ids",
    "source_group_fingerprints",
    "source_slice_fingerprint",
    "reference_at",
    "recent_horizon_hours",
    "source_token_limit",
    "output_token_limit",
    "body",
    "body_sha256",
}
_VALIDATION_KEYS = {
    "schema",
    "status",
    "checkpoint_revision_id",
    "checkpoint_source_proof_sha256",
    "checkpoint_retirement_cursor_sha256",
    "current_source_snapshot",
    "current_retirement_eligibility_sha256",
    "body_included",
}


def _json_clone(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("thread_continuity_v3_json_invalid") from exc


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("thread_continuity_v3_json_invalid") from exc


def canonical_proof_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _domain_sha256(domain: str, value: Any) -> str:
    material = domain.encode("utf-8") + b"\x00" + _canonical_json(value)
    return hashlib.sha256(material).hexdigest()


def _closed_mapping(value: Any, keys: set[str], error: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(error)
    row = dict(value)
    if set(row) != keys:
        raise ValueError(error)
    return row


def _closed_text(value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or value != value.strip() or (not value and not allow_empty):
        raise ValueError("thread_continuity_v3_text_invalid")
    if len(value) > 1024:
        raise ValueError("thread_continuity_v3_text_invalid")
    return value


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("thread_continuity_v3_count_invalid")
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError("thread_continuity_v3_hash_invalid")
    return value


def normalize_thread_continuity_revision_id(
    value: Any, *, allow_empty: bool = False
) -> str:
    revision_id = _closed_text(value, allow_empty=allow_empty)
    if revision_id and not _REVISION_ID_RE.fullmatch(revision_id):
        raise ValueError("thread_continuity_checkpoint_invalid")
    return revision_id


def _reference_at(value: Any) -> str:
    text = _closed_text(value)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("thread_continuity_bridge_policy_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("thread_continuity_bridge_policy_invalid")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_canonical_history_prefix_token(value: Mapping[str, Any]) -> Dict[str, Any]:
    row = _closed_mapping(value, _HOST_TOKEN_KEYS, "thread_continuity_host_token_invalid")
    if row["schema"] != CANONICAL_HISTORY_PREFIX_SCHEMA:
        raise ValueError("thread_continuity_host_token_invalid")
    for key in (
        "realm_id",
        "incarnation",
        "activation_epoch",
        "domain_id",
        "topology_revision",
        "canonical_rule_version",
    ):
        row[key] = _closed_text(row[key])
    row["indexed_change_seq"] = _count(row["indexed_change_seq"])
    row["canonical_count"] = _count(row["canonical_count"])
    row["end_anchor"] = _closed_text(
        row["end_anchor"], allow_empty=row["canonical_count"] == 0
    )
    if row["canonical_count"] == 0 and row["end_anchor"]:
        raise ValueError("thread_continuity_host_token_invalid")
    if row["canonical_count"] and not row["end_anchor"]:
        raise ValueError("thread_continuity_host_token_invalid")
    row["prefix_hash"] = _sha256(row["prefix_hash"])
    return row


def normalize_thread_continuity_prefix_descriptor(
    value: Mapping[str, Any],
) -> Dict[str, Any]:
    row = _closed_mapping(value, _PREFIX_KEYS, "thread_continuity_prefix_invalid")
    if row["schema"] != THREAD_CONTINUITY_PREFIX_DESCRIPTOR_SCHEMA:
        raise ValueError("thread_continuity_prefix_invalid")
    row["canonical_count"] = _count(row["canonical_count"])
    row["group_count"] = _count(row["group_count"])
    row["through_anchor"] = _closed_text(
        row["through_anchor"], allow_empty=row["canonical_count"] == 0
    )
    if row["canonical_count"] == 0:
        if row["through_anchor"] or row["group_count"]:
            raise ValueError("thread_continuity_prefix_invalid")
    elif not row["through_anchor"] or row["group_count"] > row["canonical_count"]:
        raise ValueError("thread_continuity_prefix_invalid")
    row["prefix_hash"] = _sha256(row["prefix_hash"])
    row["group_root"] = _sha256(row["group_root"])
    return row


def normalize_thread_continuity_source_proof(
    value: Mapping[str, Any],
) -> Dict[str, Any]:
    row = _closed_mapping(value, _SOURCE_PROOF_KEYS, "thread_continuity_source_proof_invalid")
    row["host_token"] = normalize_canonical_history_prefix_token(row["host_token"])
    row["grouping_rule_version"] = _closed_text(row["grouping_rule_version"])
    row["group_count"] = _count(row["group_count"])
    row["group_root"] = _sha256(row["group_root"])
    return row


def thread_continuity_group_root_seed(
    *, domain_id: str, grouping_rule_version: str
) -> str:
    return _domain_sha256(
        "thread_continuity_group_root.seed.v1",
        {
            "domain_id": _closed_text(domain_id),
            "grouping_rule_version": _closed_text(grouping_rule_version),
        },
    )


def extend_thread_continuity_group_root(
    previous_group_root: str,
    *,
    group_count: int,
    source_prefix_id: str,
    source_group_fingerprint: str,
    through_anchor: str,
    canonical_count: int,
    prefix_hash: str,
) -> str:
    return _domain_sha256(
        "thread_continuity_group_root.step.v1",
        {
            "previous_group_root": _sha256(previous_group_root),
            "group_count": _count(group_count),
            "source_prefix_id": _closed_text(source_prefix_id),
            "source_group_fingerprint": _sha256(source_group_fingerprint),
            "through_anchor": _closed_text(through_anchor),
            "canonical_count": _count(canonical_count),
            "prefix_hash": _sha256(prefix_hash),
        },
    )


def _normalize_groups(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("thread_continuity_compact_groups_invalid")
    # The donor normalizer owns visible-content, duplicate-ID, multimodal and
    # complete-pair semantics.  Import lazily so context_compactor can in turn
    # dispatch v3 checkpoints here without a module-import cycle.
    from .context_compactor import normalize_complete_thread_groups

    normalized = normalize_complete_thread_groups(value)
    groups = list(normalized["groups"])
    if not normalized["complete"] or len(groups) != len(value):
        raise ValueError("thread_continuity_compact_groups_invalid")
    return groups


def thread_continuity_group_fingerprint(group: Mapping[str, Any]) -> str:
    from .context_compactor import _group_fingerprint

    return _group_fingerprint(group)


def _source_slice_fingerprint(groups: List[Dict[str, Any]]) -> str:
    from .context_compactor import thread_continuity_prefix_fingerprint

    return thread_continuity_prefix_fingerprint(groups)


def _normalize_eligibility(value: Any) -> Dict[str, Any]:
    row = _closed_mapping(
        value, _ELIGIBILITY_KEYS, "thread_continuity_retirement_eligibility_invalid"
    )
    if (
        row["schema"] != THREAD_CONTINUITY_RETIREMENT_ELIGIBILITY_SCHEMA
        or row["status"] != "eligible"
    ):
        raise ValueError("thread_continuity_retirement_eligibility_invalid")
    row["prefix"] = normalize_thread_continuity_prefix_descriptor(row["prefix"])
    row["physical_ownership_sha256"] = _sha256(row["physical_ownership_sha256"])
    return row


def normalize_thread_continuity_compact_source(
    value: Mapping[str, Any],
) -> Dict[str, Any]:
    row = _closed_mapping(value, _SOURCE_KEYS, "thread_continuity_compact_source_invalid")
    if (
        row["schema"] != THREAD_CONTINUITY_COMPACT_SOURCE_SCHEMA
        or row["status"] != "ready"
        or row["scan_complete"] is not True
    ):
        raise ValueError("thread_continuity_compact_source_invalid")
    source_proof = normalize_thread_continuity_source_proof(row["source_proof"])
    prefix_before = normalize_thread_continuity_prefix_descriptor(
        row["prefix_before_groups"]
    )
    groups = _normalize_groups(row["groups"])
    raw_prefixes = row["group_prefixes"]
    if not isinstance(raw_prefixes, list) or len(raw_prefixes) != len(groups):
        raise ValueError("thread_continuity_compact_source_invalid")
    group_prefixes: List[Dict[str, Any]] = []
    previous = prefix_before
    for group, raw_prefix in zip(groups, raw_prefixes):
        item = _closed_mapping(
            raw_prefix, _GROUP_PREFIX_KEYS, "thread_continuity_group_prefix_invalid"
        )
        item["source_prefix_id"] = _closed_text(item["source_prefix_id"])
        item["source_group_fingerprint"] = _sha256(
            item["source_group_fingerprint"]
        )
        item["prefix"] = normalize_thread_continuity_prefix_descriptor(item["prefix"])
        expected_fingerprint = thread_continuity_group_fingerprint(group)
        expected_root = extend_thread_continuity_group_root(
            previous["group_root"],
            group_count=previous["group_count"] + 1,
            source_prefix_id=group["source_prefix_id"],
            source_group_fingerprint=expected_fingerprint,
            through_anchor=item["prefix"]["through_anchor"],
            canonical_count=item["prefix"]["canonical_count"],
            prefix_hash=item["prefix"]["prefix_hash"],
        )
        if (
            item["source_prefix_id"] != group["source_prefix_id"]
            or item["source_group_fingerprint"] != expected_fingerprint
            or item["prefix"]["group_count"] != previous["group_count"] + 1
            or item["prefix"]["canonical_count"] <= previous["canonical_count"]
            or item["prefix"]["group_root"] != expected_root
        ):
            raise ValueError("thread_continuity_group_prefix_invalid")
        group_prefixes.append(item)
        previous = item["prefix"]
    host = source_proof["host_token"]
    if (
        source_proof["group_count"] != previous["group_count"]
        or source_proof["group_root"] != previous["group_root"]
        or previous["canonical_count"] > host["canonical_count"]
        or (
            previous["canonical_count"] == host["canonical_count"]
            and (
                previous["through_anchor"] != host["end_anchor"]
                or previous["prefix_hash"] != host["prefix_hash"]
            )
        )
    ):
        raise ValueError("thread_continuity_source_proof_invalid")
    eligibility = _normalize_eligibility(row["retirement_eligibility"])
    available_prefixes = [prefix_before, *[item["prefix"] for item in group_prefixes]]
    if eligibility["prefix"] not in available_prefixes:
        raise ValueError("thread_continuity_retirement_eligibility_invalid")
    stats = _closed_mapping(
        row["stats"], _SOURCE_STATS_KEYS, "thread_continuity_compact_source_invalid"
    )
    for key in (
        "canonical_message_count",
        "returned_groups",
        "workset_rows",
        "workset_bytes",
    ):
        stats[key] = _count(stats[key])
    compacted_ids = stats["compacted_prefix_group_ids"]
    if not isinstance(compacted_ids, list):
        raise ValueError("thread_continuity_compact_source_invalid")
    compacted_ids = [_closed_text(value) for value in compacted_ids]
    eligible_count = available_prefixes.index(eligibility["prefix"])
    if (
        stats["full_prefix"] is not False
        or stats["canonical_message_count"] != host["canonical_count"]
        or stats["returned_groups"] != len(groups)
        or stats["workset_rows"] > 2_048
        or stats["workset_bytes"] > 4 * 1024 * 1024
        or compacted_ids
        != [group["source_prefix_id"] for group in groups[:eligible_count]]
    ):
        raise ValueError("thread_continuity_compact_source_invalid")
    stats["compacted_prefix_group_ids"] = compacted_ids
    normalized = {
        "schema": THREAD_CONTINUITY_COMPACT_SOURCE_SCHEMA,
        "status": "ready",
        "scan_complete": True,
        "source_snapshot": _sha256(row["source_snapshot"]),
        "source_proof": source_proof,
        "prefix_before_groups": prefix_before,
        "groups": groups,
        "group_prefixes": group_prefixes,
        "retirement_eligibility": eligibility,
        "stats": stats,
    }
    if normalized["source_snapshot"] != canonical_proof_sha256(source_proof):
        raise ValueError("thread_continuity_compact_source_snapshot_invalid")
    return normalized


def _normalize_retirement_cursor(value: Any) -> Dict[str, Any]:
    row = _closed_mapping(value, _CURSOR_KEYS, "thread_continuity_retirement_cursor_invalid")
    if (
        row["schema"] != THREAD_CONTINUITY_RETIREMENT_CURSOR_V2_SCHEMA
        or row["relation"] != "retired_from_foreground"
    ):
        raise ValueError("thread_continuity_retirement_cursor_invalid")
    prefix = normalize_thread_continuity_prefix_descriptor(
        {
            "schema": THREAD_CONTINUITY_PREFIX_DESCRIPTOR_SCHEMA,
            "through_anchor": row["through_anchor"],
            "canonical_count": row["canonical_count"],
            "group_count": row["group_count"],
            "prefix_hash": row["prefix_hash"],
            "group_root": row["group_root"],
        }
    )
    return {
        "schema": THREAD_CONTINUITY_RETIREMENT_CURSOR_V2_SCHEMA,
        "relation": "retired_from_foreground",
        **{key: prefix[key] for key in _PREFIX_KEYS if key != "schema"},
    }


def _normalize_recent_bridge(value: Any) -> Dict[str, Any]:
    row = _closed_mapping(value, _BRIDGE_KEYS, "thread_continuity_recent_bridge_invalid")
    if row["schema"] != THREAD_CONTINUITY_RECENT_BRIDGE_SCHEMA:
        raise ValueError("thread_continuity_recent_bridge_invalid")
    status = row["status"]
    if status not in {"ready", "empty"}:
        raise ValueError("thread_continuity_recent_bridge_invalid")
    expected_relation = (
        "represented_in_recent_bridge" if status == "ready" else "no_visible_representation"
    )
    ids = row["source_group_ids"]
    fingerprints = row["source_group_fingerprints"]
    body = row["body"]
    if (
        row["relation"] != expected_relation
        or not isinstance(ids, list)
        or not isinstance(fingerprints, list)
        or len(ids) != len(fingerprints)
        or not isinstance(body, str)
    ):
        raise ValueError("thread_continuity_recent_bridge_invalid")
    ids = [_closed_text(value) for value in ids]
    fingerprints = [_sha256(value) for value in fingerprints]
    if len(ids) != len(set(ids)):
        raise ValueError("thread_continuity_recent_bridge_invalid")
    source_slice_fingerprint = str(row["source_slice_fingerprint"])
    body_sha256 = _sha256(row["body_sha256"])
    if (
        body_sha256 != hashlib.sha256(body.encode("utf-8")).hexdigest()
        or (status == "ready" and (not ids or not body.strip()))
        or (
            status == "empty"
            and (
                ids
                or fingerprints
                or body
                or source_slice_fingerprint
                or body_sha256 != hashlib.sha256(b"").hexdigest()
            )
        )
        or (status == "ready" and not _SHA256_RE.fullmatch(source_slice_fingerprint))
    ):
        raise ValueError("thread_continuity_recent_bridge_invalid")
    reference_at = _reference_at(row["reference_at"])
    for key, maximum in (
        ("recent_horizon_hours", 24 * 365),
        ("source_token_limit", None),
        ("output_token_limit", None),
    ):
        value = row[key]
        if type(value) is not int or value < 1 or (maximum and value > maximum):
            raise ValueError("thread_continuity_bridge_policy_invalid")
    return {
        **row,
        "source_group_ids": ids,
        "source_group_fingerprints": fingerprints,
        "source_slice_fingerprint": source_slice_fingerprint,
        "reference_at": reference_at,
        "body_sha256": body_sha256,
    }


def _checkpoint_revision_id(value: Mapping[str, Any]) -> str:
    material = {key: _json_clone(item) for key, item in value.items() if key != "revision_id"}
    return "tcr_" + _domain_sha256(THREAD_CONTINUITY_CHECKPOINT_V3_SCHEMA, material)


def normalize_thread_continuity_checkpoint_v3(
    state: Mapping[str, Any],
    *,
    previous_state: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    row = _closed_mapping(state, _CHECKPOINT_KEYS, "thread_continuity_checkpoint_invalid")
    if row["schema"] != THREAD_CONTINUITY_CHECKPOINT_V3_SCHEMA:
        raise ValueError("thread_continuity_checkpoint_invalid")
    row["revision"] = _count(row["revision"])
    row["predecessor_revision"] = _count(row["predecessor_revision"])
    if row["revision"] < 1 or row["predecessor_revision"] != row["revision"] - 1:
        raise ValueError("thread_continuity_checkpoint_invalid")
    row["revision_id"] = normalize_thread_continuity_revision_id(
        row["revision_id"]
    )
    row["predecessor_revision_id"] = normalize_thread_continuity_revision_id(
        row["predecessor_revision_id"], allow_empty=True
    )
    row["source_proof"] = normalize_thread_continuity_source_proof(row["source_proof"])
    row["retirement_cursor"] = _normalize_retirement_cursor(row["retirement_cursor"])
    row["recent_bridge"] = _normalize_recent_bridge(row["recent_bridge"])
    if row["storage_state"] != "stored_unvalidated":
        raise ValueError("thread_continuity_checkpoint_invalid")
    lineage = row["lineage_status"]
    if lineage == "continued":
        if row["revision"] < 2 or not row["predecessor_revision_id"]:
            raise ValueError("thread_continuity_lineage_invalid")
    elif lineage == "initial":
        if row["revision"] != 1 or row["predecessor_revision"] or row["predecessor_revision_id"]:
            raise ValueError("thread_continuity_lineage_invalid")
    elif lineage == "rebuilt":
        if (row["revision"] == 1) != (not row["predecessor_revision_id"]):
            raise ValueError("thread_continuity_lineage_invalid")
    else:
        raise ValueError("thread_continuity_lineage_invalid")
    if row["revision_id"] != _checkpoint_revision_id(row):
        raise ValueError("thread_continuity_checkpoint_invalid")
    if previous_state is not None:
        previous = normalize_thread_continuity_checkpoint_v3(previous_state)
        if lineage in {"continued", "rebuilt"}:
            old_cursor = previous["retirement_cursor"]
            cursor = row["retirement_cursor"]
            if (
                row["predecessor_revision"] != previous["revision"]
                or row["predecessor_revision_id"] != previous["revision_id"]
            ):
                raise ValueError("thread_continuity_lineage_invalid")
            if lineage == "continued" and (
                cursor["canonical_count"] < old_cursor["canonical_count"]
                or cursor["group_count"] < old_cursor["group_count"]
            ):
                raise ValueError("thread_continuity_retirement_cursor_regression")
        else:
            raise ValueError("thread_continuity_lineage_invalid")
    return _json_clone(row)


def normalize_thread_continuity_checkpoint_validation(
    value: Mapping[str, Any],
) -> Dict[str, Any]:
    row = _closed_mapping(
        value, _VALIDATION_KEYS, "thread_continuity_checkpoint_validation_invalid"
    )
    if (
        row["schema"] != THREAD_CONTINUITY_CHECKPOINT_VALIDATION_SCHEMA
        or row["status"] != "valid"
        or row["body_included"] is not False
    ):
        raise ValueError("thread_continuity_checkpoint_validation_invalid")
    try:
        row["checkpoint_revision_id"] = normalize_thread_continuity_revision_id(
            row["checkpoint_revision_id"]
        )
    except ValueError as exc:
        raise ValueError("thread_continuity_checkpoint_validation_invalid") from exc
    for key in (
        "checkpoint_source_proof_sha256",
        "checkpoint_retirement_cursor_sha256",
        "current_source_snapshot",
        "current_retirement_eligibility_sha256",
    ):
        row[key] = _sha256(row[key])
    return row


def _prefix_from_cursor(cursor: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema": THREAD_CONTINUITY_PREFIX_DESCRIPTOR_SCHEMA,
        "through_anchor": cursor["through_anchor"],
        "canonical_count": cursor["canonical_count"],
        "group_count": cursor["group_count"],
        "prefix_hash": cursor["prefix_hash"],
        "group_root": cursor["group_root"],
    }


def validate_thread_continuity_checkpoint_v3_source(
    state: Mapping[str, Any],
    *,
    compact_source: Mapping[str, Any],
    previous_state: Mapping[str, Any] | None = None,
    checkpoint_validation: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    checkpoint = normalize_thread_continuity_checkpoint_v3(
        state, previous_state=previous_state
    )
    source = normalize_thread_continuity_compact_source(compact_source)
    eligibility = source["retirement_eligibility"]
    cursor_prefix = _prefix_from_cursor(checkpoint["retirement_cursor"])
    bridge = checkpoint["recent_bridge"]
    inventory = [
        (group["source_prefix_id"], item["source_group_fingerprint"])
        for group, item in zip(source["groups"], source["group_prefixes"])
    ]
    bridge_inventory = list(
        zip(bridge["source_group_ids"], bridge["source_group_fingerprints"])
    )
    contiguous = not bridge_inventory
    if bridge_inventory:
        starts = [index for index, item in enumerate(inventory) if item == bridge_inventory[0]]
        contiguous = any(
            inventory[index : index + len(bridge_inventory)] == bridge_inventory
            for index in starts
        )
    bridge_groups = [
        group
        for group, item in zip(source["groups"], inventory)
        if item in bridge_inventory
    ]
    if (
        not contiguous
        or bridge["source_slice_fingerprint"]
        != (_source_slice_fingerprint(bridge_groups) if bridge_groups else "")
    ):
        raise ValueError("thread_continuity_checkpoint_source_invalid")
    if bridge_inventory:
        last_index = inventory.index(bridge_inventory[-1])
        if source["group_prefixes"][last_index]["prefix"]["group_count"] > cursor_prefix["group_count"]:
            raise ValueError("thread_continuity_checkpoint_source_invalid")
    if checkpoint_validation is None:
        # A freshly built candidate belongs to this exact frozen source and may
        # retire only the host-audited physical-ownership boundary.
        if (
            checkpoint["source_proof"] != source["source_proof"]
            or cursor_prefix != eligibility["prefix"]
        ):
            raise ValueError("thread_continuity_checkpoint_source_invalid")
    else:
        # A stored checkpoint may precede newly appended history.  The adapter
        # proves that old token against the current host snapshot and binds the
        # result in this body-free validation carrier; do not require equality
        # with the newer head token or rebuild every time the user speaks.
        validation = normalize_thread_continuity_checkpoint_validation(
            checkpoint_validation
        )
        if (
            validation["checkpoint_revision_id"] != checkpoint["revision_id"]
            or validation["checkpoint_source_proof_sha256"]
            != canonical_proof_sha256(checkpoint["source_proof"])
            or validation["checkpoint_retirement_cursor_sha256"]
            != canonical_proof_sha256(checkpoint["retirement_cursor"])
            or validation["current_source_snapshot"] != source["source_snapshot"]
            or validation["current_retirement_eligibility_sha256"]
            != canonical_proof_sha256(eligibility)
        ):
            raise ValueError("thread_continuity_checkpoint_validation_invalid")
        if (
            cursor_prefix["canonical_count"]
            > eligibility["prefix"]["canonical_count"]
            or cursor_prefix["group_count"]
            > eligibility["prefix"]["group_count"]
        ):
            raise ValueError("thread_continuity_checkpoint_source_invalid")
    return checkpoint


def build_thread_continuity_checkpoint_v3(
    *,
    previous_state: Mapping[str, Any] | None,
    source_proof: Mapping[str, Any],
    retirement_prefix: Mapping[str, Any],
    bridge_source_groups: List[Mapping[str, Any]],
    bridge_text: Any,
    bridge_policy: Mapping[str, Any],
    continue_lineage: bool,
    predecessor_revision: int | None = None,
    predecessor_revision_id: str | None = None,
) -> Dict[str, Any]:
    source = normalize_thread_continuity_source_proof(source_proof)
    prefix = normalize_thread_continuity_prefix_descriptor(retirement_prefix)
    groups = _normalize_groups(bridge_source_groups)
    body = bridge_text.strip() if isinstance(bridge_text, str) else None
    if body is None or bool(groups) != bool(body):
        raise ValueError("thread_continuity_bridge_body_invalid")
    policy = dict(bridge_policy or {})
    reference_at = _reference_at(policy.get("reference_at"))
    recent_horizon_hours = policy.get("recent_horizon_hours")
    source_token_limit = policy.get("source_token_limit")
    output_token_limit = policy.get("output_token_limit")
    if (
        type(recent_horizon_hours) is not int
        or not 1 <= recent_horizon_hours <= 24 * 365
        or type(source_token_limit) is not int
        or source_token_limit < 1
        or type(output_token_limit) is not int
        or output_token_limit < 1
    ):
        raise ValueError("thread_continuity_bridge_policy_invalid")
    previous: Dict[str, Any] = {}
    if previous_state is not None and str(previous_state.get("schema") or "") == THREAD_CONTINUITY_CHECKPOINT_V3_SCHEMA:
        previous = normalize_thread_continuity_checkpoint_v3(previous_state)
    if continue_lineage and not previous:
        raise ValueError("thread_continuity_lineage_invalid")
    if previous:
        prior_revision = previous["revision"]
        prior_revision_id = previous["revision_id"]
        if predecessor_revision is not None and predecessor_revision != prior_revision:
            raise ValueError("thread_continuity_lineage_invalid")
        if predecessor_revision_id is not None and predecessor_revision_id != prior_revision_id:
            raise ValueError("thread_continuity_lineage_invalid")
    elif predecessor_revision is not None or predecessor_revision_id is not None:
        prior_revision = _count(predecessor_revision)
        prior_revision_id = normalize_thread_continuity_revision_id(
            predecessor_revision_id
        )
        if prior_revision < 1:
            raise ValueError("thread_continuity_lineage_invalid")
    else:
        prior_revision, prior_revision_id = 0, ""
    revision = prior_revision + 1
    bridge_ids = [group["source_prefix_id"] for group in groups]
    bridge_fingerprints = [thread_continuity_group_fingerprint(group) for group in groups]
    bridge = {
        "schema": THREAD_CONTINUITY_RECENT_BRIDGE_SCHEMA,
        "status": "ready" if groups else "empty",
        "relation": (
            "represented_in_recent_bridge" if groups else "no_visible_representation"
        ),
        "source_group_ids": bridge_ids,
        "source_group_fingerprints": bridge_fingerprints,
        "source_slice_fingerprint": _source_slice_fingerprint(groups) if groups else "",
        "reference_at": reference_at,
        "recent_horizon_hours": recent_horizon_hours,
        "source_token_limit": source_token_limit,
        "output_token_limit": output_token_limit,
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    cursor = {
        "schema": THREAD_CONTINUITY_RETIREMENT_CURSOR_V2_SCHEMA,
        "relation": "retired_from_foreground",
        **{key: prefix[key] for key in _PREFIX_KEYS if key != "schema"},
    }
    checkpoint = {
        "schema": THREAD_CONTINUITY_CHECKPOINT_V3_SCHEMA,
        "revision": revision,
        "predecessor_revision": revision - 1,
        "revision_id": "",
        "predecessor_revision_id": prior_revision_id,
        "lineage_status": (
            "continued"
            if continue_lineage
            else "rebuilt"
            if previous_state is not None or prior_revision
            else "initial"
        ),
        "source_proof": source,
        "retirement_cursor": cursor,
        "recent_bridge": bridge,
        "storage_state": "stored_unvalidated",
    }
    checkpoint["revision_id"] = _checkpoint_revision_id(checkpoint)
    return normalize_thread_continuity_checkpoint_v3(
        checkpoint, previous_state=previous if previous else None
    )


def make_thread_continuity_checkpoint_validation(
    checkpoint: Mapping[str, Any], compact_source: Mapping[str, Any]
) -> Dict[str, Any]:
    normalized = normalize_thread_continuity_checkpoint_v3(checkpoint)
    source = normalize_thread_continuity_compact_source(compact_source)
    return {
        "schema": THREAD_CONTINUITY_CHECKPOINT_VALIDATION_SCHEMA,
        "status": "valid",
        "checkpoint_revision_id": normalized["revision_id"],
        "checkpoint_source_proof_sha256": canonical_proof_sha256(
            normalized["source_proof"]
        ),
        "checkpoint_retirement_cursor_sha256": canonical_proof_sha256(
            normalized["retirement_cursor"]
        ),
        "current_source_snapshot": source["source_snapshot"],
        "current_retirement_eligibility_sha256": canonical_proof_sha256(
            source["retirement_eligibility"]
        ),
        "body_included": False,
    }
