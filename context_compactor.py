from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping as MappingABC
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Tuple


_PHYSICAL_OWNER_SIDECAR_SCHEMA = "thread_continuity_physical_owner_sidecar.v1"
_PHYSICAL_OWNER_SIDECAR_KEYS = {
    "schema",
    "status",
    "plan_binding_sha256",
    "fixed_prompt_sha256",
    "physical_vector_sha256",
    "rows_sha256",
    "receipt_sha256",
    "physical_message_count",
    "rows",
    "body_included",
}
_PHYSICAL_OWNER_ROW_KEYS = {
    "physical_index",
    "carrier_kind",
    "checkpoint_kind",
    "role",
    "name",
    "body_sha256",
    "source_group_aliases",
    "source_message_aliases",
    "source_fingerprint",
    "relation",
}
_PHYSICAL_OWNER_CARRIERS = {"fixed", "checkpoint", "raw", "current", "postcurrent"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PHYSICAL_OWNER_AUTHORITY = object()
_PROMPT_PLAN_AUTHORITY = object()
_FIXED_PROMPT_SELECTION_AUTHORITY = object()


class _ThreadContinuityPhysicalOwnerSidecar(MappingABC):
    __slots__ = ("_payload_json", "_authority", "_generation")

    def __init__(
        self,
        payload: Mapping[str, Any],
        authority: object,
        generation: object,
    ) -> None:
        if authority is not _PHYSICAL_OWNER_AUTHORITY or generation is None:
            raise ValueError("thread_continuity_physical_owner_authority_invalid")
        object.__setattr__(
            self,
            "_payload_json",
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        object.__setattr__(self, "_authority", authority)
        object.__setattr__(self, "_generation", generation)

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("thread_continuity_physical_owner_sidecar_frozen")

    def __getitem__(self, key: str) -> Any:
        return self._snapshot()[key]

    def __iter__(self):
        return iter(self._snapshot())

    def __len__(self) -> int:
        return len(self._snapshot())

    def __copy__(self):
        return self._snapshot()

    def __deepcopy__(self, memo: Dict[int, Any]):
        return self._snapshot()

    def __repr__(self) -> str:
        return "<thread_continuity_physical_owner_sidecar body_included=False>"

    def _snapshot(self) -> Dict[str, Any]:
        return json.loads(self._payload_json)


class _ThreadContinuityPromptPlanOwner:
    __slots__ = ("_payload_json", "_authority")

    def __init__(self, payload: Mapping[str, Any], authority: object) -> None:
        if authority is not _PROMPT_PLAN_AUTHORITY:
            raise ValueError("thread_continuity_prompt_plan_authority_invalid")
        object.__setattr__(
            self,
            "_payload_json",
            json.dumps(
                dict(payload),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        object.__setattr__(self, "_authority", authority)

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("thread_continuity_prompt_plan_owner_frozen")

    def __copy__(self) -> Dict[str, Any]:
        return {}

    def __deepcopy__(self, memo: Dict[int, Any]) -> Dict[str, Any]:
        return {}

    def __repr__(self) -> str:
        return "<thread_continuity_prompt_plan_owner body_included=False>"

    def _snapshot(self) -> Dict[str, Any]:
        return json.loads(self._payload_json)


class _ThreadContinuityFixedPromptSelection:
    __slots__ = (
        "_authority",
        "_plan_owner",
        "_fixed_prompt_json",
        "_prompt_assembly",
    )

    def __init__(
        self,
        *,
        authority: object,
        plan_owner: _ThreadContinuityPromptPlanOwner,
        fixed_prompt_messages: List[Dict[str, Any]],
        prompt_assembly: Any,
    ) -> None:
        if (
            authority is not _FIXED_PROMPT_SELECTION_AUTHORITY
            or type(plan_owner) is not _ThreadContinuityPromptPlanOwner
            or plan_owner._authority is not _PROMPT_PLAN_AUTHORITY
        ):
            raise ValueError("thread_continuity_fixed_prompt_authority_invalid")
        object.__setattr__(self, "_authority", authority)
        object.__setattr__(self, "_plan_owner", plan_owner)
        object.__setattr__(
            self,
            "_fixed_prompt_json",
            json.dumps(
                fixed_prompt_messages,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        object.__setattr__(self, "_prompt_assembly", prompt_assembly)

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("thread_continuity_fixed_prompt_selection_frozen")

    def __copy__(self) -> Dict[str, Any]:
        return {}

    def __deepcopy__(self, memo: Dict[int, Any]) -> Dict[str, Any]:
        return {}

    def __repr__(self) -> str:
        return "<thread_continuity_fixed_prompt_selection body_included=False>"


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        image_count = 0
        for item in content:
            if not isinstance(item, Mapping):
                return ""
            item_type = str(item.get("type", "")).strip()
            if item_type in {"text", "input_text"}:
                text = item.get("text")
                if not isinstance(text, str):
                    return ""
                parts.append(text.strip())
            elif item_type in {"image_url", "input_image"}:
                image = item.get("image_url")
                image_url = image.get("url") if isinstance(image, Mapping) else image
                if not (
                    isinstance(image_url, str) and image_url.strip()
                    or isinstance(item.get("file_id"), str) and item["file_id"].strip()
                ):
                    return ""
                image_count += 1
            else:
                return ""
        cleaned = [p for p in parts if p]
        if image_count:
            cleaned.append(f"[图片 x{image_count}]")
        return "\n".join(cleaned).strip()
    return ""


def _normalize(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


THREAD_CONTINUITY_CHECKPOINT_SCHEMA = "thread_continuity_checkpoint.v1"
THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA = "thread_continuity_checkpoint.v2"
THREAD_CONTINUITY_RETIREMENT_CURSOR_SCHEMA = "thread_continuity_retirement_cursor.v1"
THREAD_CONTINUITY_RECENT_BRIDGE_SCHEMA = "thread_continuity_recent_bridge.v1"


def _group_fingerprint(group: Mapping[str, Any]) -> str:
    identity = [
        str(group.get("source_prefix_id") or "").strip(),
        str(group.get("group_kind") or "").strip(),
        str(group.get("logical_turn_id") or "").strip(),
        str(group.get("record_id") or "").strip(),
        str(group.get("effective_event_at") or "").strip(),
        [
            [
                str(message.get("role") or "").strip(),
                str(message.get("name") or "").strip(),
                str(message.get("message_id") or "").strip(),
                str(message.get("content_hash") or "").strip(),
            ]
            for message in list(group.get("messages") or [])
            if isinstance(message, Mapping)
        ],
    ]
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _content_hash(value: Any) -> str:
    try:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("thread_continuity_message_content_invalid") from exc
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_bridge_reference_at(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("thread_continuity_bridge_policy_invalid")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("thread_continuity_bridge_policy_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("thread_continuity_bridge_policy_invalid")
    return parsed.astimezone(timezone.utc)


def _bridge_reference_text(value: Any) -> str:
    return _parse_bridge_reference_at(value).isoformat()


def thread_continuity_retirement_source_group_ids(
    checkpoint: Mapping[str, Any] | None,
) -> List[str]:
    row = dict(checkpoint or {})
    if str(row.get("schema") or "") == THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA:
        cursor = row.get("retirement_cursor")
    else:
        cursor = row.get("covered_through")
    return [
        str(value or "").strip()
        for value in list(dict(cursor or {}).get("source_prefix_ids") or [])
        if str(value or "").strip()
    ]


def thread_continuity_bridge_projection(
    checkpoint: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    row = dict(checkpoint or {})
    if str(row.get("schema") or "") == THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA:
        bridge = dict(row.get("recent_bridge") or {})
        return {
            "status": str(bridge.get("status") or ""),
            "relation": str(bridge.get("relation") or ""),
            "body": str(bridge.get("body") or ""),
            "body_sha256": str(bridge.get("body_sha256") or ""),
            "represented_source_group_ids": list(
                bridge.get("source_group_ids") or []
            ),
            "source_group_fingerprints": list(
                bridge.get("source_group_fingerprints") or []
            ),
            "source_slice_fingerprint": str(
                bridge.get("source_slice_fingerprint") or ""
            ),
            "reference_at": str(bridge.get("reference_at") or ""),
            "recent_horizon_hours": bridge.get("recent_horizon_hours"),
            "source_token_limit": bridge.get("source_token_limit"),
            "output_token_limit": bridge.get("output_token_limit"),
        }
    body = str(row.get("summary_text") or "")
    return {
        "status": "legacy_unverified" if body else "empty",
        "relation": "legacy_unverified" if body else "no_visible_representation",
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "represented_source_group_ids": [],
        "source_group_fingerprints": [],
        "source_slice_fingerprint": "",
        "reference_at": "",
        "recent_horizon_hours": 0,
        "source_token_limit": 0,
        "output_token_limit": 0,
    }


def select_thread_continuity_recent_bridge(
    source_groups: List[Dict[str, Any]],
    *,
    retired_source_group_ids: List[str],
    reference_at: Any,
    recent_horizon_hours: Any,
    source_token_limit: Any,
    estimate_messages: Callable[[List[Dict[str, Any]]], int],
) -> Dict[str, Any]:
    normalized = normalize_complete_thread_groups(source_groups)
    if not normalized["complete"]:
        raise ValueError("thread_continuity_source_incomplete")
    if (
        type(recent_horizon_hours) is not int
        or not 1 <= recent_horizon_hours <= 24 * 365
        or type(source_token_limit) is not int
        or source_token_limit < 1
    ):
        raise ValueError("thread_continuity_bridge_policy_invalid")
    reference = _parse_bridge_reference_at(reference_at)
    groups = list(normalized["groups"])
    available_ids = [group["source_prefix_id"] for group in groups]
    retired_ids = [str(value or "").strip() for value in retired_source_group_ids]
    if not retired_ids or retired_ids != available_ids[: len(retired_ids)]:
        raise ValueError("thread_continuity_retirement_cursor_invalid")
    retired_groups = groups[: len(retired_ids)]
    cutoff = reference - timedelta(hours=recent_horizon_hours)
    suffix_start = len(retired_groups)
    for index in range(len(retired_groups) - 1, -1, -1):
        group = retired_groups[index]
        try:
            event_at = _parse_bridge_reference_at(group.get("effective_event_at"))
        except ValueError:
            break
        if event_at < cutoff or event_at > reference + timedelta(hours=24):
            break
        suffix_start = index
    eligible = retired_groups[suffix_start:]
    excluded_by_currentness = len(retired_groups) - len(eligible)
    selected_reversed: List[Dict[str, Any]] = []
    selected_tokens = 0
    excluded_by_token = 0
    for group in reversed(eligible):
        provider_messages = [
            {
                "role": message["role"],
                "content": message["content"],
                **({"name": message["name"]} if message.get("name") else {}),
            }
            for message in group["messages"]
        ]
        try:
            group_tokens = int(estimate_messages(provider_messages))
        except Exception as exc:
            raise ValueError("thread_continuity_bridge_estimator_invalid") from exc
        if group_tokens < 0:
            raise ValueError("thread_continuity_bridge_estimator_invalid")
        if selected_tokens + group_tokens > source_token_limit:
            excluded_by_token += len(eligible) - len(selected_reversed)
            break
        selected_reversed.append(group)
        selected_tokens += group_tokens
    selected = list(reversed(selected_reversed))
    return {
        "status": "ready" if selected else "empty",
        "source_group_ids": [group["source_prefix_id"] for group in selected],
        "source_group_fingerprints": [_group_fingerprint(group) for group in selected],
        "source_slice_fingerprint": (
            thread_continuity_prefix_fingerprint(selected) if selected else ""
        ),
        "reference_at": reference.isoformat(),
        "recent_horizon_hours": recent_horizon_hours,
        "source_token_limit": source_token_limit,
        "estimated_source_tokens": selected_tokens,
        "excluded_by_currentness_count": excluded_by_currentness,
        "excluded_by_token_count": excluded_by_token,
    }


def _attach_recent_bridge_plan(
    plan: Dict[str, Any],
    *,
    canonical: List[Dict[str, Any]],
    reference_at: Any,
    recent_horizon_hours: Any,
    source_token_limit: Any,
    output_token_limit: Any,
    estimate_messages: Callable[[List[Dict[str, Any]]], int],
) -> None:
    retired_ids = list(
        plan.get("retired_source_group_ids")
        or plan.get("covered_source_group_ids")
        or []
    )
    effective_reference = reference_at
    if effective_reference is None:
        effective_reference = next(
            (
                str(group.get("effective_event_at") or "").strip()
                for group in reversed(canonical)
                if str(group.get("effective_event_at") or "").strip()
            ),
            "",
        )
    selected = select_thread_continuity_recent_bridge(
        canonical,
        retired_source_group_ids=retired_ids,
        reference_at=effective_reference,
        recent_horizon_hours=recent_horizon_hours,
        source_token_limit=source_token_limit,
        estimate_messages=estimate_messages,
    )
    selected_ids = list(selected["source_group_ids"])
    selected_id_set = set(selected_ids)
    selected_groups = [
        group
        for group in canonical[: len(retired_ids)]
        if group["source_prefix_id"] in selected_id_set
    ]
    if (
        type(output_token_limit) is not int
        or output_token_limit < 1
    ):
        raise ValueError("thread_continuity_bridge_policy_invalid")
    plan.update(
        bridge_status=selected["status"],
        bridge_source_groups=selected_groups,
        bridge_source_group_ids=selected_ids,
        bridge_source_group_fingerprints=list(
            selected["source_group_fingerprints"]
        ),
        bridge_source_slice_fingerprint=selected["source_slice_fingerprint"],
        bridge_reference_at=selected["reference_at"],
        bridge_recent_horizon_hours=recent_horizon_hours,
        bridge_source_token_limit=source_token_limit,
        bridge_output_token_limit=output_token_limit,
        bridge_estimated_source_tokens=selected["estimated_source_tokens"],
        bridge_excluded_by_currentness_count=selected[
            "excluded_by_currentness_count"
        ],
        bridge_excluded_by_token_count=selected["excluded_by_token_count"],
        summary_output_token_limit=(
            min(int(plan.get("summary_output_token_limit") or 0), output_token_limit)
            if selected_ids else 0
        ),
    )


def _thread_continuity_currentness_plan(
    canonical: List[Dict[str, Any]],
    *,
    previous: Mapping[str, Any] | None,
    reference_at: Any,
    recent_horizon_hours: Any,
    source_token_limit: Any,
    estimate_messages: Callable[[List[Dict[str, Any]]], int],
) -> Dict[str, Any]:
    retired_ids = thread_continuity_retirement_source_group_ids(previous)
    if not canonical:
        return {
            "reference_at": "",
            "target_retired_source_group_ids": [],
            "expired_raw_count": 0,
            "bridge_refresh_required": False,
            "selected_bridge": {
                "status": "empty",
                "source_group_ids": [],
            },
        }
    effective_reference = reference_at
    if effective_reference is None:
        effective_reference = next(
            (
                str(group.get("effective_event_at") or "").strip()
                for group in reversed(canonical)
                if str(group.get("effective_event_at") or "").strip()
            ),
            "",
        )
    if not str(effective_reference or "").strip():
        previous_bridge = thread_continuity_bridge_projection(previous)
        return {
            "reference_at": "",
            "target_retired_source_group_ids": list(retired_ids),
            "expired_raw_count": 0,
            "bridge_refresh_required": False,
            "selected_bridge": {
                "status": previous_bridge["status"],
                "source_group_ids": list(
                    previous_bridge["represented_source_group_ids"]
                ),
            },
        }
    reference = _parse_bridge_reference_at(effective_reference)
    if (
        type(recent_horizon_hours) is not int
        or not 1 <= recent_horizon_hours <= 24 * 365
        or type(source_token_limit) is not int
        or source_token_limit < 1
    ):
        raise ValueError("thread_continuity_bridge_policy_invalid")
    cutoff = reference - timedelta(hours=recent_horizon_hours)
    target_ids = list(retired_ids)
    for group in canonical[len(retired_ids) :]:
        if str(group.get("group_kind") or "") != "dialogue_turn":
            break
        try:
            event_at = _parse_bridge_reference_at(group.get("effective_event_at"))
        except ValueError:
            break
        if event_at >= cutoff or event_at > reference + timedelta(hours=24):
            break
        target_ids.append(group["source_prefix_id"])
    if target_ids:
        selected = select_thread_continuity_recent_bridge(
            canonical,
            retired_source_group_ids=target_ids,
            reference_at=reference,
            recent_horizon_hours=recent_horizon_hours,
            source_token_limit=source_token_limit,
            estimate_messages=estimate_messages,
        )
    else:
        selected = {
            "status": "empty",
            "source_group_ids": [],
            "source_group_fingerprints": [],
            "source_slice_fingerprint": "",
            "reference_at": reference.isoformat(),
            "recent_horizon_hours": recent_horizon_hours,
            "source_token_limit": source_token_limit,
            "estimated_source_tokens": 0,
            "excluded_by_currentness_count": 0,
            "excluded_by_token_count": 0,
        }
    previous_bridge = thread_continuity_bridge_projection(previous)
    previous_schema = str(dict(previous or {}).get("schema") or "")
    bridge_refresh_required = bool(
        previous
        and (
            (
                reference_at is not None
                and previous_schema == THREAD_CONTINUITY_CHECKPOINT_SCHEMA
                and previous_bridge["status"] == "legacy_unverified"
            )
            or (
                previous_schema == THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA
                and (
                    previous_bridge["status"] != selected["status"]
                    or list(previous_bridge["represented_source_group_ids"])
                    != list(selected["source_group_ids"])
                )
            )
        )
    )
    return {
        "reference_at": reference.isoformat(),
        "target_retired_source_group_ids": target_ids,
        "expired_raw_count": len(target_ids) - len(retired_ids),
        "bridge_refresh_required": bridge_refresh_required,
        "selected_bridge": selected,
    }


def _canonical_owner_aliases(*values: Any) -> List[str]:
    aliases: List[str] = []
    for value in values:
        rows = value if isinstance(value, (list, tuple)) else [value]
        for raw in rows:
            alias = str(raw or "").strip()
            if alias and alias not in aliases:
                aliases.append(alias)
    return aliases


def _physical_owner_body_sha256(content: Any) -> str:
    text = _content_to_text(content).replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mint_thread_continuity_prompt_plan_owner(
    plan: Mapping[str, Any],
) -> _ThreadContinuityPromptPlanOwner:
    return _ThreadContinuityPromptPlanOwner(plan, _PROMPT_PLAN_AUTHORITY)


def read_thread_continuity_prompt_plan_carriers(
    plan_owner: Any,
) -> List[Dict[str, Any]]:
    """Read exact raw/current carrier authority from one private fold plan."""

    if (
        type(plan_owner) is not _ThreadContinuityPromptPlanOwner
        or plan_owner._authority is not _PROMPT_PLAN_AUTHORITY
    ):
        return []
    plan = plan_owner._snapshot()
    base_count = len(list(plan.get("base_messages") or []))
    continuity_count = int(
        bool(plan.get("previous_continuity_messages"))
        or str(plan.get("status") or "") in {"fold_required", "blocked"}
    )
    physical_index = base_count + continuity_count
    carriers: List[Dict[str, Any]] = []
    for group in list(plan.get("raw_suffix_groups") or []):
        if not isinstance(group, Mapping):
            return []
        group_aliases = _canonical_owner_aliases(
            group.get("source_prefix_id"),
            group.get("logical_turn_id"),
            group.get("record_id"),
            group.get("canonical_ids"),
        )
        for message in list(group.get("messages") or []):
            if not isinstance(message, Mapping):
                return []
            message_aliases = _canonical_owner_aliases(
                message.get("message_id"),
                message.get("canonical_ids"),
            )
            role = str(message.get("role") or "").strip()
            content = _content_to_text(message.get("content"))
            if role not in {"user", "assistant"} or not message_aliases or not content:
                return []
            carriers.append(
                {
                    "physical_index": physical_index,
                    "role": role,
                    "message_aliases": message_aliases,
                    "group_aliases": group_aliases,
                    "body_sha256": _physical_owner_body_sha256(
                        message.get("content")
                    ),
                    "carrier_kind": "final_raw_suffix",
                    "alias_source": "canonical_source_message",
                }
            )
            physical_index += 1
    current = dict(plan.get("current_ephemeral") or {})
    current_aliases = _canonical_owner_aliases(
        current.get("message_id"),
        current.get("canonical_ids"),
    )
    if current_aliases and _content_to_text(current.get("content")):
        carriers.append(
            {
                "physical_index": physical_index,
                "role": "user",
                "message_aliases": current_aliases,
                "group_aliases": [],
                "body_sha256": _physical_owner_body_sha256(
                    current.get("content")
                ),
                "carrier_kind": "current_ephemeral",
                "alias_source": "current_ephemeral_message",
            }
        )
    return carriers


def bind_thread_continuity_fixed_prompt_selection(
    plan_owner: Any,
    *,
    fixed_prompt_messages: Any,
    prompt_assembly: Any,
) -> _ThreadContinuityFixedPromptSelection:
    if (
        type(plan_owner) is not _ThreadContinuityPromptPlanOwner
        or plan_owner._authority is not _PROMPT_PLAN_AUTHORITY
        or prompt_assembly is None
    ):
        raise TypeError("thread_continuity_prompt_plan_owner_invalid")
    messages = _continuity_messages(fixed_prompt_messages)
    assembly_text = getattr(prompt_assembly, "text", None)
    if (
        not isinstance(assembly_text, str)
        or messages != [{"role": "system", "content": assembly_text}]
    ):
        raise ValueError("thread_continuity_fixed_prompt_messages_invalid")
    return _ThreadContinuityFixedPromptSelection(
        authority=_FIXED_PROMPT_SELECTION_AUTHORITY,
        plan_owner=plan_owner,
        fixed_prompt_messages=messages,
        prompt_assembly=prompt_assembly,
    )


def _read_thread_continuity_fixed_prompt_selection(
    value: Any,
    *,
    expected_plan_owner: _ThreadContinuityPromptPlanOwner,
) -> Dict[str, Any]:
    if (
        type(value) is not _ThreadContinuityFixedPromptSelection
        or value._authority is not _FIXED_PROMPT_SELECTION_AUTHORITY
        or value._plan_owner is not expected_plan_owner
    ):
        return {}
    messages = json.loads(value._fixed_prompt_json)
    if not messages or any(
        not isinstance(message, Mapping) or message.get("role") != "system"
        for message in messages
    ):
        return {}
    return {
        "fixed_prompt_messages": [dict(message) for message in messages],
        "prompt_assembly": value._prompt_assembly,
        "selection": value,
    }


def _physical_owner_message_vector(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "role": str(message.get("role") or ""),
            "name": str(message.get("name") or ""),
            "content": message.get("content"),
        }
        for message in messages
    ]


def _physical_owner_row(
    *,
    physical_index: int,
    carrier_kind: str,
    checkpoint_kind: str,
    message: Mapping[str, Any],
    source_group_aliases: List[str],
    source_message_aliases: List[str],
    source_fingerprint: str,
    relation: str,
) -> Dict[str, Any]:
    return {
        "physical_index": physical_index,
        "carrier_kind": carrier_kind,
        "checkpoint_kind": checkpoint_kind,
        "role": str(message.get("role") or ""),
        "name": str(message.get("name") or ""),
        "body_sha256": _physical_owner_body_sha256(message.get("content")),
        "source_group_aliases": list(source_group_aliases),
        "source_message_aliases": list(source_message_aliases),
        "source_fingerprint": source_fingerprint,
        "relation": relation,
    }


def _project_thread_continuity_physical_owner_sidecar(
    plan: Mapping[str, Any],
    *,
    checkpoint_messages: List[Dict[str, Any]],
    physical_messages: List[Dict[str, Any]],
) -> Mapping[str, Any]:
    rows: List[Dict[str, Any]] = []
    index = 0
    base_messages = [dict(message) for message in list(plan.get("base_messages") or [])]
    for message in base_messages:
        rows.append(
            _physical_owner_row(
                physical_index=index,
                carrier_kind="fixed",
                checkpoint_kind="none",
                message=message,
                source_group_aliases=[],
                source_message_aliases=[],
                source_fingerprint="",
                relation="fixed_prompt",
            )
        )
        index += 1
    checkpoint_kind = (
        "legacy_bridge"
        if (plan.get("status"), plan.get("reason")) == ("no_fold", "within_budget")
        and plan.get("previous_bridge_status") == "legacy_unverified"
        else "recent_bridge"
    )
    for message in checkpoint_messages:
        rows.append(
            _physical_owner_row(
                physical_index=index,
                carrier_kind="checkpoint",
                checkpoint_kind=checkpoint_kind,
                message=message,
                source_group_aliases=[],
                source_message_aliases=[],
                source_fingerprint=_content_hash(
                    {
                        "kind": checkpoint_kind,
                        "predecessor_revision_id": str(
                            plan.get("predecessor_revision_id") or ""
                        ),
                        "retired_source_group_ids": list(
                            plan.get("retired_source_group_ids")
                            or plan.get("covered_source_group_ids")
                            or []
                        ),
                        "represented_source_group_ids": list(
                            (
                                plan.get("previous_bridge_source_group_ids")
                                if (
                                    plan.get("status"), plan.get("reason")
                                ) == ("no_fold", "within_budget")
                                else plan.get("bridge_source_group_ids")
                            )
                            or []
                        ),
                        "body_sha256": _physical_owner_body_sha256(
                            message.get("content")
                        ),
                    }
                ),
                relation=(
                    "legacy_bridge_unverified"
                    if checkpoint_kind == "legacy_bridge"
                    else "represented_in_recent_bridge"
                ),
            )
        )
        index += 1
    for group in list(plan.get("raw_suffix_groups") or []):
        group_row = dict(group)
        group_aliases = _canonical_owner_aliases(
            group_row.get("source_prefix_id"),
            group_row.get("logical_turn_id"),
            group_row.get("record_id"),
        )
        group_fingerprint = _group_fingerprint(group_row)
        for raw_message in list(group_row.get("messages") or []):
            message = dict(raw_message)
            rows.append(
                _physical_owner_row(
                    physical_index=index,
                    carrier_kind="raw",
                    checkpoint_kind="none",
                    message=message,
                    source_group_aliases=group_aliases,
                    source_message_aliases=_canonical_owner_aliases(
                        message.get("message_id")
                    ),
                    source_fingerprint=group_fingerprint,
                    relation="same_canonical_body",
                )
            )
            index += 1
    current = dict(plan.get("current_ephemeral") or {})
    rows.append(
        _physical_owner_row(
            physical_index=index,
            carrier_kind="current",
            checkpoint_kind="none",
            message=current,
            source_group_aliases=[],
            source_message_aliases=_canonical_owner_aliases(current.get("message_id")),
            source_fingerprint=_content_hash(
                [
                    current.get("role"),
                    current.get("name", ""),
                    current.get("message_id"),
                    current.get("content_hash"),
                ]
            ),
            relation="same_canonical_body",
        )
    )
    index += 1
    for raw_message in list(plan.get("post_current_messages") or []):
        message = dict(raw_message)
        rows.append(
            _physical_owner_row(
                physical_index=index,
                carrier_kind="postcurrent",
                checkpoint_kind="none",
                message=message,
                source_group_aliases=[],
                source_message_aliases=_canonical_owner_aliases(
                    message.get("message_id")
                ),
                source_fingerprint=_content_hash(
                    [
                        message.get("role"),
                        message.get("name", ""),
                        message.get("message_id"),
                        message.get("content_hash"),
                    ]
                ),
                relation="post_current_tail",
            )
        )
        index += 1
    plan_binding = {
        "status": plan.get("status"),
        "reason": plan.get("reason"),
        "fold_plan_id": str(plan.get("fold_plan_id") or ""),
        "continuity_mode": str(plan.get("continuity_mode") or ""),
        "predecessor_revision_id": str(plan.get("predecessor_revision_id") or ""),
        "covered_source_group_ids": list(plan.get("covered_source_group_ids") or []),
        "retired_source_group_ids": list(plan.get("retired_source_group_ids") or []),
        "bridge_source_group_ids": list(plan.get("bridge_source_group_ids") or []),
        "previous_bridge_source_group_ids": list(
            plan.get("previous_bridge_source_group_ids") or []
        ),
        "fold_source_group_ids": list(plan.get("fold_source_group_ids") or []),
        "raw_suffix_group_ids": list(plan.get("raw_suffix_group_ids") or []),
        "current": [current.get("message_id"), current.get("content_hash")],
        "post_current": [
            [
                message.get("role"),
                message.get("name", ""),
                message.get("message_id"),
                message.get("content_hash"),
            ]
            for message in list(plan.get("post_current_messages") or [])
        ],
        "context_window_tokens": plan.get("context_window_tokens"),
        "reserved_output_tokens": plan.get("reserved_output_tokens"),
        "fixed_non_message_tokens": plan.get("fixed_non_message_tokens"),
    }
    sidecar = {
        "schema": _PHYSICAL_OWNER_SIDECAR_SCHEMA,
        "status": "ready",
        "plan_binding_sha256": _content_hash(plan_binding),
        "fixed_prompt_sha256": _content_hash(base_messages),
        "physical_vector_sha256": _content_hash(
            _physical_owner_message_vector(physical_messages)
        ),
        "rows_sha256": _content_hash(rows),
        "physical_message_count": len(physical_messages),
        "rows": rows,
        "body_included": False,
    }
    sidecar["receipt_sha256"] = _content_hash(sidecar)
    return sidecar


def _physical_owner_sidecar_payload_valid(
    sidecar: Mapping[str, Any],
    messages: List[Dict[str, Any]],
) -> bool:
    rows = list(sidecar.get("rows") or [])
    if (
        set(sidecar) != _PHYSICAL_OWNER_SIDECAR_KEYS
        or sidecar.get("schema") != _PHYSICAL_OWNER_SIDECAR_SCHEMA
        or sidecar.get("status") != "ready"
        or sidecar.get("body_included") is not False
        or type(sidecar.get("physical_message_count")) is not int
        or sidecar.get("physical_message_count") != len(messages)
        or len(rows) != len(messages)
        or not messages
        or any(
            not isinstance(sidecar.get(key), str)
            or not _SHA256_RE.fullmatch(sidecar.get(key))
            for key in (
                "plan_binding_sha256",
                "fixed_prompt_sha256",
                "physical_vector_sha256",
                "rows_sha256",
                "receipt_sha256",
            )
        )
        or sidecar.get("physical_vector_sha256")
        != _content_hash(_physical_owner_message_vector(messages))
        or sidecar.get("rows_sha256") != _content_hash(rows)
        or sidecar.get("receipt_sha256")
        != _content_hash({key: item for key, item in sidecar.items() if key != "receipt_sha256"})
    ):
        return False
    for index, (raw_row, message) in enumerate(zip(rows, messages)):
        row = dict(raw_row) if isinstance(raw_row, Mapping) else {}
        carrier = str(row.get("carrier_kind") or "")
        checkpoint_kind = str(row.get("checkpoint_kind") or "")
        group_aliases = row.get("source_group_aliases")
        message_aliases = row.get("source_message_aliases")
        if (
            set(row) != _PHYSICAL_OWNER_ROW_KEYS
            or row.get("physical_index") != index
            or carrier not in _PHYSICAL_OWNER_CARRIERS
            or row.get("role") != str(message.get("role") or "")
            or row.get("name") != str(message.get("name") or "")
            or row.get("body_sha256")
            != _physical_owner_body_sha256(message.get("content"))
            or not isinstance(group_aliases, list)
            or group_aliases != _canonical_owner_aliases(group_aliases)
            or not isinstance(message_aliases, list)
            or message_aliases != _canonical_owner_aliases(message_aliases)
        ):
            return False
        expected_shape = {
            "fixed": ("none", False, False, "", "fixed_prompt"),
            "checkpoint": (
                checkpoint_kind,
                False,
                False,
                row.get("source_fingerprint"),
                "legacy_bridge_unverified"
                if checkpoint_kind == "legacy_bridge"
                else "represented_in_recent_bridge",
            ),
            "raw": ("none", True, True, row.get("source_fingerprint"), "same_canonical_body"),
            "current": ("none", False, True, row.get("source_fingerprint"), "same_canonical_body"),
            "postcurrent": ("none", False, True, row.get("source_fingerprint"), "post_current_tail"),
        }[carrier]
        expected_checkpoint, requires_group, requires_message, fingerprint, relation = expected_shape
        if (
            checkpoint_kind != expected_checkpoint
            or (
                carrier == "checkpoint"
                and checkpoint_kind not in {"legacy_bridge", "recent_bridge"}
            )
            or bool(group_aliases) is not requires_group
            or bool(message_aliases) is not requires_message
            or row.get("source_fingerprint") != fingerprint
            or (
                carrier in {"checkpoint", "raw", "current", "postcurrent"}
                and not _SHA256_RE.fullmatch(str(fingerprint or ""))
            )
            or (carrier == "fixed" and fingerprint != "")
            or row.get("relation") != relation
        ):
            return False
    carriers = [str(dict(row).get("carrier_kind") or "") for row in rows]
    carrier_rank = {"fixed": 0, "checkpoint": 1, "raw": 2, "current": 3, "postcurrent": 4}
    fixed_messages = [
        {
            "role": messages[index]["role"],
            "content": messages[index]["content"],
            **(
                {"name": messages[index]["name"]}
                if str(messages[index].get("name") or "")
                else {}
            ),
        }
        for index, carrier in enumerate(carriers)
        if carrier == "fixed"
    ]
    if (
        not carriers
        or carriers[0] != "fixed"
        or any(
            carrier_rank[carriers[index]] > carrier_rank[carriers[index + 1]]
            for index in range(len(carriers) - 1)
        )
        or carriers.count("checkpoint") > 1
        or carriers.count("current") != 1
        or sidecar.get("fixed_prompt_sha256") != _content_hash(fixed_messages)
    ):
        return False
    return True


def _read_thread_continuity_physical_owner_sidecar(
    value: Any,
    *,
    physical_messages: Any,
    expected_generation: object,
) -> Mapping[str, Any]:
    if (
        type(value) is not _ThreadContinuityPhysicalOwnerSidecar
        or value._authority is not _PHYSICAL_OWNER_AUTHORITY
        or expected_generation is None
        or value._generation is not expected_generation
    ):
        return {}
    messages = (
        [dict(message) for message in physical_messages]
        if isinstance(physical_messages, list)
        and all(isinstance(message, Mapping) for message in physical_messages)
        else []
    )
    if not _physical_owner_sidecar_payload_valid(value._snapshot(), messages):
        return {}
    return value


def normalize_complete_thread_groups(
    groups: List[Dict[str, Any]],
    *,
    current_ephemeral: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Normalize durable canonical pairs while keeping the current user turn separate."""

    normalized: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}
    message_owners: Dict[str, str] = {}
    errors: List[str] = []
    for raw_group in list(groups or []):
        if not isinstance(raw_group, Mapping):
            errors.append("group_not_object")
            continue
        source_id = str(raw_group.get("source_prefix_id") or "").strip()
        group_kind = str(raw_group.get("group_kind") or "").strip()
        raw_messages = list(raw_group.get("messages") or [])
        expected_roles = {
            "dialogue_turn": ("user", "assistant"),
            "proactive_assistant_event": ("assistant",),
        }.get(group_kind)
        if not source_id or expected_roles is None or len(raw_messages) != len(expected_roles):
            errors.append("group_identity_or_pair_incomplete")
            continue
        messages: List[Dict[str, Any]] = []
        for expected_role, raw_message in zip(expected_roles, raw_messages):
            if not isinstance(raw_message, Mapping):
                messages = []
                break
            role = str(raw_message.get("role") or "").strip().lower()
            content = raw_message.get("content")
            if role != expected_role or not _content_to_text(content):
                messages = []
                break
            messages.append(
                {
                    "role": role,
                    **({"name": str(raw_message.get("name") or "").strip()} if str(raw_message.get("name") or "").strip() else {}),
                    "message_id": str(raw_message.get("message_id") or "").strip(),
                    "content": content,
                    "content_hash": _content_hash(content),
                }
            )
        if len(messages) != len(expected_roles):
            errors.append(f"group_pair_incomplete:{source_id or 'unknown'}")
            continue
        group = {
            "group_kind": group_kind,
            "source_prefix_id": source_id,
            "logical_turn_id": str(raw_group.get("logical_turn_id") or "").strip(),
            "record_id": str(raw_group.get("record_id") or "").strip(),
            "message_ids": [message["message_id"] for message in messages if message["message_id"]],
            "effective_event_at": str(raw_group.get("effective_event_at") or "").strip(),
            "messages": messages,
        }
        fingerprint = _group_fingerprint(group)
        previous = seen.get(source_id)
        if previous:
            if previous != fingerprint:
                errors.append(f"group_identity_conflict:{source_id}")
            continue
        for message_id in group["message_ids"]:
            owner = message_owners.get(message_id)
            if owner:
                errors.append(f"source_identity_conflict:{message_id}")
            message_owners[message_id] = source_id
        seen[source_id] = fingerprint
        normalized.append(group)
    current: Dict[str, Any] = {}
    if current_ephemeral is not None:
        role = str(current_ephemeral.get("role") or "user").strip().lower()
        content = current_ephemeral.get("content")
        if role != "user" or not _content_to_text(content):
            errors.append("current_ephemeral_invalid")
        else:
            current = {
                "role": "user",
                **({"name": str(current_ephemeral.get("name") or "").strip()} if str(current_ephemeral.get("name") or "").strip() else {}),
                "message_id": str(current_ephemeral.get("message_id") or "").strip(),
                "content": content,
                "content_hash": _content_hash(content),
                "ephemeral": True,
            }
    return {
        "complete": not errors,
        "groups": normalized,
        "current_ephemeral": current,
        "errors": errors,
    }


def thread_continuity_prefix_fingerprint(groups: List[Dict[str, Any]]) -> str:
    rows = [
        {
            "source_prefix_id": str(group.get("source_prefix_id") or "").strip(),
            "fingerprint": _group_fingerprint(group),
        }
        for group in groups
    ]
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _revision_id(
    predecessor_revision_id: str,
    covered_ids: List[str],
    covered_fingerprints: List[str],
    summary_sha256: str,
) -> str:
    binding = [
        predecessor_revision_id,
        [[source_id, fingerprint] for source_id, fingerprint in zip(covered_ids, covered_fingerprints)],
        summary_sha256,
    ]
    digest = hashlib.sha256(
        json.dumps(binding, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"tcr_{digest}"


def _state_revision_identity_valid(state: Mapping[str, Any]) -> bool:
    covered = state.get("covered_through") if isinstance(state.get("covered_through"), Mapping) else {}
    covered_ids = [str(value or "").strip() for value in list(covered.get("source_prefix_ids") or [])]
    covered_fingerprints = [
        str(value or "").strip() for value in list(covered.get("source_group_fingerprints") or [])
    ]
    expected = _revision_id(
        str(state.get("predecessor_revision_id") or "").strip(),
        covered_ids,
        covered_fingerprints,
        str(state.get("summary_sha256") or "").strip(),
    )
    return bool(
        covered_ids
        and len(covered_ids) == len(covered_fingerprints)
        and str(state.get("revision_id") or "").strip() == expected
    )


def _build_thread_continuity_checkpoint(
    *,
    previous_state: Mapping[str, Any] | None,
    source_groups: List[Dict[str, Any]],
    covered_source_group_ids: List[str],
    summary_text: Any,
    owner_rebuild: bool = False,
) -> Dict[str, Any]:
    normalized = normalize_complete_thread_groups(source_groups)
    if not normalized["complete"]:
        raise ValueError("thread_continuity_source_incomplete")
    groups = list(normalized["groups"])
    available_ids = [group["source_prefix_id"] for group in groups]
    covered_ids = [str(value or "").strip() for value in covered_source_group_ids]
    if not covered_ids or covered_ids != available_ids[: len(covered_ids)]:
        raise ValueError("thread_continuity_covered_prefix_invalid")
    if not isinstance(summary_text, str) or not _normalize(summary_text):
        raise ValueError("thread_continuity_summary_invalid")
    summary = _normalize(summary_text)
    try:
        previous_revision = int(dict(previous_state or {}).get("revision") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("thread_continuity_predecessor_invalid") from exc
    if previous_revision < 0:
        raise ValueError("thread_continuity_predecessor_invalid")
    previous = dict(previous_state or {})
    lineage_valid = False
    if previous:
        try:
            normalize_thread_continuity_checkpoint(previous, source_groups=groups)
            previous_source_ids = [str(value or "").strip() for value in list(previous.get("source_group_ids") or [])]
            lineage_valid = previous_source_ids == available_ids[: len(previous_source_ids)]
        except ValueError:
            lineage_valid = False
    previous_covered = [
        str(value or "").strip()
        for value in list(dict(previous.get("covered_through") or {}).get("source_prefix_ids") or [])
    ] if lineage_valid else []
    if lineage_valid and covered_ids[: len(previous_covered)] != previous_covered:
        raise ValueError("thread_continuity_covered_prefix_regression")
    lineage_status = "continued" if previous and lineage_valid else "rebuilt" if previous else "initial"
    if owner_rebuild and previous and lineage_valid:
        lineage_status = "rebuilt"
    summary_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    covered_groups = groups[: len(covered_ids)]
    covered_fingerprints = [_group_fingerprint(group) for group in covered_groups]
    prefix_fingerprint = thread_continuity_prefix_fingerprint(covered_groups)
    predecessor_revision_id = (
        str(previous.get("revision_id") or "").strip() if lineage_status == "continued" else ""
    )
    checkpoint = {
        "schema": THREAD_CONTINUITY_CHECKPOINT_SCHEMA,
        "revision": previous_revision + 1,
        "predecessor_revision": previous_revision,
        "source_group_ids": available_ids,
        "source_fingerprint": thread_continuity_prefix_fingerprint(groups),
        "revision_id": _revision_id(
            predecessor_revision_id, covered_ids, covered_fingerprints, summary_hash
        ),
        "predecessor_revision_id": predecessor_revision_id,
        "lineage_status": lineage_status,
        "summary_text": summary,
        "summary_sha256": summary_hash,
        "covered_through": {
            "source_prefix_ids": covered_ids,
            "source_group_fingerprints": covered_fingerprints,
            "prefix_fingerprint": prefix_fingerprint,
        },
    }
    return normalize_thread_continuity_checkpoint(
        checkpoint, source_groups=groups, previous_state=previous_state if lineage_valid else None
    )


def build_thread_continuity_checkpoint(
    *, previous_state: Mapping[str, Any] | None, source_groups: List[Dict[str, Any]],
    covered_source_group_ids: List[str], summary_text: Any,
) -> Dict[str, Any]:
    return _build_thread_continuity_checkpoint(
        previous_state=previous_state, source_groups=source_groups,
        covered_source_group_ids=covered_source_group_ids, summary_text=summary_text,
    )


def _normalize_thread_continuity_checkpoint_v1(
    state: Mapping[str, Any],
    *,
    source_groups: List[Dict[str, Any]],
    previous_state: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized = normalize_complete_thread_groups(source_groups)
    if not normalized["complete"]:
        raise ValueError("thread_continuity_source_incomplete")
    row = dict(state or {})
    if str(row.get("schema") or "") != THREAD_CONTINUITY_CHECKPOINT_SCHEMA:
        raise ValueError("thread_continuity_checkpoint_invalid")
    summary_value = row.get("summary_text")
    if not isinstance(summary_value, str) or not _normalize(summary_value):
        raise ValueError("thread_continuity_checkpoint_invalid")
    summary = _normalize(summary_value)
    summary_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    covered = dict(row.get("covered_through") or {}) if isinstance(row.get("covered_through"), Mapping) else {}
    covered_ids = [str(value or "").strip() for value in list(covered.get("source_prefix_ids") or [])]
    covered_fingerprints = [
        str(value or "").strip() for value in list(covered.get("source_group_fingerprints") or [])
    ]
    groups = list(normalized["groups"])
    available_ids = [group["source_prefix_id"] for group in groups]
    source_ids = [str(value or "").strip() for value in list(row.get("source_group_ids") or [])]
    source_groups = groups[: len(source_ids)]
    expected_covered_fingerprints = [_group_fingerprint(group) for group in groups[: len(covered_ids)]]
    if (
        type(row.get("revision")) is not int
        or type(row.get("predecessor_revision")) is not int
        or row["revision"] < 1
        or row["predecessor_revision"] != row["revision"] - 1
        or not source_ids
        or source_ids != available_ids[: len(source_ids)]
        or str(row.get("source_fingerprint") or "").strip()
        != thread_continuity_prefix_fingerprint(source_groups)
        or not covered_ids
        or covered_ids != source_ids[: len(covered_ids)]
        or covered_fingerprints != expected_covered_fingerprints
        or str(covered.get("prefix_fingerprint") or "").strip()
        != thread_continuity_prefix_fingerprint(groups[: len(covered_ids)])
        or str(row.get("summary_sha256") or "").strip() != summary_hash
        or not _state_revision_identity_valid(row)
    ):
        raise ValueError("thread_continuity_checkpoint_invalid")
    lineage_status = str(row.get("lineage_status") or "").strip()
    predecessor_id = str(row.get("predecessor_revision_id") or "").strip()
    if lineage_status == "continued":
        if not predecessor_id:
            raise ValueError("thread_continuity_lineage_invalid")
        if previous_state is not None:
            previous = _normalize_thread_continuity_checkpoint_v1(
                previous_state, source_groups=groups
            )
            previous_covered = dict(previous.get("covered_through") or {})
            previous_ids = [
                str(value or "").strip()
                for value in list(previous_covered.get("source_prefix_ids") or [])
            ]
            if (
                predecessor_id != str(previous.get("revision_id") or "").strip()
                or covered_ids[: len(previous_ids)] != previous_ids
                or row["predecessor_revision"] != previous["revision"]
            ):
                raise ValueError("thread_continuity_lineage_invalid")
    elif lineage_status not in {"initial", "rebuilt"} or predecessor_id:
        raise ValueError("thread_continuity_lineage_invalid")
    row["summary_text"] = summary
    return row


def _v2_revision_id(
    predecessor_revision_id: str,
    retirement_cursor: Mapping[str, Any],
    recent_bridge: Mapping[str, Any],
) -> str:
    return "tcr_" + _content_hash(
        {
            "predecessor_revision_id": predecessor_revision_id,
            "retirement_cursor": dict(retirement_cursor),
            "recent_bridge": dict(recent_bridge),
        }
    )


def _normalize_thread_continuity_checkpoint_v2(
    state: Mapping[str, Any],
    *,
    source_groups: List[Dict[str, Any]],
    previous_state: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized = normalize_complete_thread_groups(source_groups)
    if not normalized["complete"]:
        raise ValueError("thread_continuity_source_incomplete")
    row = dict(state or {})
    if str(row.get("schema") or "") != THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA:
        raise ValueError("thread_continuity_checkpoint_invalid")
    groups = list(normalized["groups"])
    available_ids = [group["source_prefix_id"] for group in groups]
    source_ids = [str(value or "").strip() for value in list(row.get("source_group_ids") or [])]
    source_owner_groups = groups[: len(source_ids)]
    cursor = dict(row.get("retirement_cursor") or {})
    retired_ids = [str(value or "").strip() for value in list(cursor.get("source_prefix_ids") or [])]
    retired_fingerprints = [
        str(value or "").strip()
        for value in list(cursor.get("source_group_fingerprints") or [])
    ]
    retired_groups = groups[: len(retired_ids)]
    bridge = dict(row.get("recent_bridge") or {})
    bridge_ids = [str(value or "").strip() for value in list(bridge.get("source_group_ids") or [])]
    bridge_fingerprints = [
        str(value or "").strip()
        for value in list(bridge.get("source_group_fingerprints") or [])
    ]
    body = bridge.get("body")
    bridge_status = str(bridge.get("status") or "")
    try:
        reference_at = _bridge_reference_text(bridge.get("reference_at"))
    except ValueError as exc:
        raise ValueError("thread_continuity_checkpoint_invalid") from exc
    if bridge_ids:
        start = retired_ids.index(bridge_ids[0]) if bridge_ids[0] in retired_ids else -1
        bridge_groups = retired_groups[start : start + len(bridge_ids)] if start >= 0 else []
    else:
        bridge_groups = []
    expected_bridge_fingerprints = [_group_fingerprint(group) for group in bridge_groups]
    expected_empty_sha = hashlib.sha256(b"").hexdigest()
    if (
        type(row.get("revision")) is not int
        or type(row.get("predecessor_revision")) is not int
        or row["revision"] < 1
        or row["predecessor_revision"] != row["revision"] - 1
        or not source_ids
        or source_ids != available_ids[: len(source_ids)]
        or str(row.get("source_fingerprint") or "").strip()
        != thread_continuity_prefix_fingerprint(source_owner_groups)
        or cursor.get("schema") != THREAD_CONTINUITY_RETIREMENT_CURSOR_SCHEMA
        or cursor.get("relation") != "retired_from_foreground"
        or not retired_ids
        or retired_ids != source_ids[: len(retired_ids)]
        or retired_fingerprints != [_group_fingerprint(group) for group in retired_groups]
        or str(cursor.get("prefix_fingerprint") or "")
        != thread_continuity_prefix_fingerprint(retired_groups)
        or bridge.get("schema") != THREAD_CONTINUITY_RECENT_BRIDGE_SCHEMA
        or bridge.get("relation")
        != (
            "represented_in_recent_bridge"
            if bridge_status == "ready"
            else "no_visible_representation"
        )
        or bridge_status not in {"ready", "empty"}
        or not isinstance(body, str)
        or bridge.get("body_sha256") != hashlib.sha256(body.encode("utf-8")).hexdigest()
        or bridge_ids != [group["source_prefix_id"] for group in bridge_groups]
        or bridge_fingerprints != expected_bridge_fingerprints
        or str(bridge.get("source_slice_fingerprint") or "")
        != (thread_continuity_prefix_fingerprint(bridge_groups) if bridge_groups else "")
        or reference_at != str(bridge.get("reference_at") or "")
        or type(bridge.get("recent_horizon_hours")) is not int
        or not 1 <= bridge["recent_horizon_hours"] <= 24 * 365
        or type(bridge.get("source_token_limit")) is not int
        or bridge["source_token_limit"] < 1
        or type(bridge.get("output_token_limit")) is not int
        or bridge["output_token_limit"] < 1
        or (bridge_status == "ready" and (not bridge_ids or not _normalize(body)))
        or (bridge_status == "empty" and (bridge_ids or body or bridge.get("body_sha256") != expected_empty_sha))
    ):
        raise ValueError("thread_continuity_checkpoint_invalid")
    predecessor_revision_id = str(row.get("predecessor_revision_id") or "").strip()
    if row.get("revision_id") != _v2_revision_id(
        predecessor_revision_id, cursor, bridge
    ):
        raise ValueError("thread_continuity_checkpoint_invalid")
    lineage_status = str(row.get("lineage_status") or "").strip()
    if lineage_status == "continued":
        if not predecessor_revision_id:
            raise ValueError("thread_continuity_lineage_invalid")
        if previous_state is not None:
            previous = normalize_thread_continuity_checkpoint(
                previous_state, source_groups=groups
            )
            previous_retired = thread_continuity_retirement_source_group_ids(previous)
            if (
                predecessor_revision_id != str(previous.get("revision_id") or "")
                or retired_ids[: len(previous_retired)] != previous_retired
                or row["predecessor_revision"] != previous["revision"]
            ):
                raise ValueError("thread_continuity_retirement_cursor_regression")
    elif lineage_status not in {"initial", "rebuilt"} or predecessor_revision_id:
        raise ValueError("thread_continuity_lineage_invalid")
    return row


def normalize_thread_continuity_checkpoint(
    state: Mapping[str, Any],
    *,
    source_groups: List[Dict[str, Any]],
    previous_state: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    schema = str(dict(state or {}).get("schema") or "")
    if schema == THREAD_CONTINUITY_CHECKPOINT_SCHEMA:
        return _normalize_thread_continuity_checkpoint_v1(
            state, source_groups=source_groups, previous_state=previous_state
        )
    if schema == THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA:
        return _normalize_thread_continuity_checkpoint_v2(
            state, source_groups=source_groups, previous_state=previous_state
        )
    raise ValueError("thread_continuity_checkpoint_invalid")


def build_thread_continuity_checkpoint_v2(
    *,
    previous_state: Mapping[str, Any] | None,
    source_groups: List[Dict[str, Any]],
    retired_source_group_ids: List[str],
    bridge_source_group_ids: List[str],
    bridge_text: Any,
    bridge_policy: Mapping[str, Any],
) -> Dict[str, Any]:
    normalized = normalize_complete_thread_groups(source_groups)
    if not normalized["complete"]:
        raise ValueError("thread_continuity_source_incomplete")
    groups = list(normalized["groups"])
    available_ids = [group["source_prefix_id"] for group in groups]
    retired_ids = [str(value or "").strip() for value in retired_source_group_ids]
    if not retired_ids or retired_ids != available_ids[: len(retired_ids)]:
        raise ValueError("thread_continuity_retirement_cursor_invalid")
    bridge_ids = [str(value or "").strip() for value in bridge_source_group_ids]
    if bridge_ids:
        start = retired_ids.index(bridge_ids[0]) if bridge_ids[0] in retired_ids else -1
        bridge_groups = groups[start : start + len(bridge_ids)] if start >= 0 else []
    else:
        bridge_groups = []
    if bridge_ids != [group["source_prefix_id"] for group in bridge_groups]:
        raise ValueError("thread_continuity_bridge_slice_invalid")
    if not isinstance(bridge_text, str):
        raise ValueError("thread_continuity_bridge_body_invalid")
    body = _normalize(bridge_text) if bridge_text else ""
    if bool(bridge_ids) != bool(body):
        raise ValueError("thread_continuity_bridge_body_invalid")
    policy = dict(bridge_policy or {})
    try:
        reference_at = _bridge_reference_text(policy.get("reference_at"))
    except ValueError as exc:
        raise ValueError("thread_continuity_bridge_policy_invalid") from exc
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
    lineage_valid = False
    if previous_state:
        try:
            previous = normalize_thread_continuity_checkpoint(
                previous_state, source_groups=groups
            )
            previous_source_ids = list(previous.get("source_group_ids") or [])
            lineage_valid = previous_source_ids == available_ids[: len(previous_source_ids)]
        except (TypeError, ValueError):
            previous = {}
    previous_retired = (
        thread_continuity_retirement_source_group_ids(previous)
        if lineage_valid else []
    )
    if previous_retired and retired_ids[: len(previous_retired)] != previous_retired:
        raise ValueError("thread_continuity_retirement_cursor_regression")
    previous_revision = int(previous.get("revision") or 0) if lineage_valid else 0
    predecessor_revision_id = (
        str(previous.get("revision_id") or "") if lineage_valid else ""
    )
    retirement_cursor = {
        "schema": THREAD_CONTINUITY_RETIREMENT_CURSOR_SCHEMA,
        "relation": "retired_from_foreground",
        "source_prefix_ids": retired_ids,
        "source_group_fingerprints": [
            _group_fingerprint(group) for group in groups[: len(retired_ids)]
        ],
        "prefix_fingerprint": thread_continuity_prefix_fingerprint(
            groups[: len(retired_ids)]
        ),
    }
    recent_bridge = {
        "schema": THREAD_CONTINUITY_RECENT_BRIDGE_SCHEMA,
        "status": "ready" if bridge_ids else "empty",
        "relation": (
            "represented_in_recent_bridge"
            if bridge_ids
            else "no_visible_representation"
        ),
        "source_group_ids": bridge_ids,
        "source_group_fingerprints": [
            _group_fingerprint(group) for group in bridge_groups
        ],
        "source_slice_fingerprint": (
            thread_continuity_prefix_fingerprint(bridge_groups)
            if bridge_groups else ""
        ),
        "reference_at": reference_at,
        "recent_horizon_hours": recent_horizon_hours,
        "source_token_limit": source_token_limit,
        "output_token_limit": output_token_limit,
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    checkpoint = {
        "schema": THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA,
        "revision": previous_revision + 1,
        "predecessor_revision": previous_revision,
        "source_group_ids": available_ids,
        "source_fingerprint": thread_continuity_prefix_fingerprint(groups),
        "revision_id": _v2_revision_id(
            predecessor_revision_id, retirement_cursor, recent_bridge
        ),
        "predecessor_revision_id": predecessor_revision_id,
        "lineage_status": "continued" if lineage_valid else "rebuilt" if previous_state else "initial",
        "retirement_cursor": retirement_cursor,
        "recent_bridge": recent_bridge,
    }
    return normalize_thread_continuity_checkpoint(
        checkpoint,
        source_groups=groups,
        previous_state=previous if lineage_valid else None,
    )


def _thread_continuity_checkpoint_marker(
    revision_id: str, revision: int, summary_sha256: str,
) -> str:
    return f"[Home Thread Continuity {revision_id} r{revision} sha256:{summary_sha256[:12]}]"


def render_thread_continuity_checkpoint_message(
    checkpoint: Mapping[str, Any], *, source_groups: List[Dict[str, Any]],
    previous_state: Mapping[str, Any] | None = None,
) -> Dict[str, str]:
    row = normalize_thread_continuity_checkpoint(
        checkpoint, source_groups=source_groups, previous_state=previous_state,
    )
    bridge = thread_continuity_bridge_projection(row)
    if not bridge["body"]:
        return {}
    marker = _thread_continuity_checkpoint_marker(
        row["revision_id"], row["revision"], bridge["body_sha256"],
    )
    if str(row.get("schema") or "") == THREAD_CONTINUITY_CHECKPOINT_V2_SCHEMA:
        marker = marker.replace("Home Thread Continuity", "Home Recent Continuity")
    return {"role": "system", "content": f"{marker}\n{bridge['body']}"}


MessageEstimator = Callable[[List[Dict[str, Any]]], int]


def _continuity_messages(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("thread_continuity_messages_invalid")
    out: List[Dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("thread_continuity_messages_invalid")
        role = str(row.get("role") or "").strip().lower()
        content = row.get("content")
        if role not in {"system", "developer", "user", "assistant", "tool"} or not _content_to_text(content):
            raise ValueError("thread_continuity_messages_invalid")
        name = str(row.get("name") or "").strip()
        out.append({"role": role, "content": content, **({"name": name} if name else {})})
    return out


def _normalize_post_current_messages(value: Any, *, unavailable_ids: set[str]) -> List[Dict[str, Any]]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError("thread_continuity_post_current_messages_invalid")
    seen = set(unavailable_ids)
    out: List[Dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) - {"role", "content", "name", "message_id"}:
            raise ValueError("thread_continuity_post_current_messages_invalid")
        role, message_id, content = (
            str(raw.get("role") or "").strip().lower(),
            str(raw.get("message_id") or "").strip(),
            raw.get("content"),
        )
        if role not in {"user", "assistant"} or not message_id or message_id in seen or not _content_to_text(content):
            raise ValueError("thread_continuity_post_current_messages_invalid")
        name = str(raw.get("name") or "").strip()
        seen.add(message_id)
        out.append({
            "role": role, "content": content, "message_id": message_id,
            "content_hash": _content_hash(content), **({"name": name} if name else {}),
        })
    return out


def _post_current_provider_messages(value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in list(value or []):
        if (
            not isinstance(raw, Mapping)
            or str(raw.get("role") or "") not in {"user", "assistant"}
            or not str(raw.get("message_id") or "").strip()
            or raw.get("content_hash") != _content_hash(raw.get("content"))
        ):
            raise ValueError("thread_continuity_post_current_messages_invalid")
        out.append({
            "role": raw["role"], "content": raw["content"],
            **({"name": raw["name"]} if raw.get("name") else {}),
        })
    return out


def _estimate(estimate_messages: MessageEstimator, messages: List[Dict[str, Any]]) -> int:
    try:
        value = estimate_messages(messages)
    except Exception as exc:
        raise ValueError("thread_continuity_estimator_failed") from exc
    if type(value) is not int or value < 0:
        raise ValueError("thread_continuity_estimator_invalid")
    return value


def _fold_plan_id(plan: Mapping[str, Any], groups: List[Dict[str, Any]]) -> str:
    current = dict(plan.get("current_ephemeral") or {})
    material = {
        "source": [[group["source_prefix_id"], _group_fingerprint(group)] for group in groups],
        "mode": plan.get("continuity_mode"),
        "predecessor_revision_id": plan.get("predecessor_revision_id"),
        "covered_source_group_ids": plan.get("covered_source_group_ids"),
        "fold_source_group_ids": plan.get("fold_source_group_ids"),
        "raw_suffix_group_ids": plan.get("raw_suffix_group_ids"),
        "current": [current.get("message_id"), current.get("content_hash")],
        "fixed_prompt_fingerprint": plan.get("fixed_prompt_fingerprint"),
        "post_current": [
            [row.get("role"), row.get("name", ""), row.get("message_id"), row.get("content_hash")]
            for row in list(plan.get("post_current_messages") or [])
        ],
        "context_window_tokens": plan.get("context_window_tokens"),
        "reserved_output_tokens": plan.get("reserved_output_tokens"),
        "fixed_non_message_tokens": plan.get("fixed_non_message_tokens"),
        "currentness_expiry_required": plan.get(
            "currentness_expiry_required"
        ),
        "currentness_expired_raw_count": plan.get(
            "currentness_expired_raw_count"
        ),
        "bridge_status": plan.get("bridge_status"),
        "bridge_source_group_ids": plan.get("bridge_source_group_ids"),
        "bridge_source_group_fingerprints": plan.get(
            "bridge_source_group_fingerprints"
        ),
        "bridge_source_slice_fingerprint": plan.get(
            "bridge_source_slice_fingerprint"
        ),
        "bridge_reference_at": plan.get("bridge_reference_at"),
        "bridge_recent_horizon_hours": plan.get(
            "bridge_recent_horizon_hours"
        ),
        "bridge_source_token_limit": plan.get("bridge_source_token_limit"),
        "bridge_output_token_limit": plan.get("bridge_output_token_limit"),
    }
    return "tcfp_" + _content_hash(material)


def normalize_thread_continuity_fold_plan(
    plan: Mapping[str, Any], *, source_groups: List[Dict[str, Any]],
    current_ephemeral: Mapping[str, Any], context_window_tokens: Any,
    reserved_output_tokens: Any, fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any, source_complete: bool,
    estimate_messages: MessageEstimator,
    previous_state: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    post_current_messages: Any = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    expected = _build_thread_continuity_fold_plan(
        source_groups,
        current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=fixed_non_message_tokens,
        fixed_prompt_messages=fixed_prompt_messages,
        source_complete=source_complete,
        estimate_messages=estimate_messages,
        previous_state=previous_state,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        post_current_messages=post_current_messages,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    eligible = expected.get("status") == "fold_required" or (
        expected.get("status") == "blocked"
        and expected.get("reason") == "rebuild_from_canonical_required"
    )
    if not eligible or dict(plan or {}) != expected:
        raise ValueError("thread_continuity_fold_plan_invalid")
    return expected


def _build_thread_continuity_fold_plan(
    groups: List[Dict[str, Any]],
    *,
    current_ephemeral: Mapping[str, Any],
    context_window_tokens: Any,
    reserved_output_tokens: Any,
    fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any,
    source_complete: bool,
    estimate_messages: MessageEstimator,
    previous_state: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    post_current_messages: Any = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    normalized = normalize_complete_thread_groups(groups, current_ephemeral=current_ephemeral)
    base = {
        "schema": "thread_continuity_fold_plan.v1",
        "status": "blocked",
        "reason": "",
        "fold_groups": [],
        "fold_source_group_ids": [],
        "raw_suffix_groups": list(normalized["groups"]),
        "raw_suffix_group_ids": [row["source_prefix_id"] for row in normalized["groups"]],
        "covered_source_group_ids": [],
        "current_user_raw": True,
        "source_complete": bool(source_complete and normalized["complete"]),
        "budget_status": "unknown",
        "rebuild_required": False,
        "summary_call_feasibility": "not_applicable",
    }
    if not source_complete or not normalized["complete"] or not normalized["current_ephemeral"]:
        base["reason"] = (
            "source_identity_conflict"
            if any(str(error).startswith("source_identity_conflict:") for error in normalized["errors"])
            else "source_incomplete"
        )
        return base
    if (
        type(context_window_tokens) is not int
        or type(reserved_output_tokens) is not int
        or type(fixed_non_message_tokens) is not int
        or context_window_tokens <= 0
        or reserved_output_tokens < 0
        or fixed_non_message_tokens < 0
        or reserved_output_tokens >= context_window_tokens
    ):
        base["reason"] = "budget_unknown"
        return base
    try:
        base_messages = _continuity_messages(fixed_prompt_messages)
        if any(message["role"] not in {"system", "developer"} for message in base_messages):
            raise ValueError("thread_continuity_fixed_prompt_contains_dialogue")
    except ValueError:
        base["reason"] = "base_prompt_invalid"
        return base
    canonical = list(normalized["groups"])
    current_id = str(normalized["current_ephemeral"].get("message_id") or "")
    if not current_id:
        base["reason"] = "identity_unresolved"
        return base
    if any(current_id in group.get("message_ids", []) for group in canonical):
        base["reason"] = "current_user_not_ephemeral"
        return base
    try:
        trailing_owner = _normalize_post_current_messages(
            post_current_messages,
            unavailable_ids={
                current_id,
                *(message_id for group in canonical for message_id in group.get("message_ids", [])),
            },
        )
        trailing_messages = _post_current_provider_messages(trailing_owner)
    except ValueError:
        base["reason"] = "post_current_messages_invalid"
        return base
    previous: Dict[str, Any] = {}
    previous_segment: List[Dict[str, Any]] = []
    retired_count = 0
    previous_bridge = thread_continuity_bridge_projection({})
    if previous_state:
        try:
            previous = normalize_thread_continuity_checkpoint(previous_state, source_groups=canonical)
            retired_count = len(
                thread_continuity_retirement_source_group_ids(previous)
            )
        except ValueError:
            previous = {}
        if previous:
            previous_bridge = thread_continuity_bridge_projection(previous)
            rendered_previous = render_thread_continuity_checkpoint_message(
                previous, source_groups=canonical,
            )
            if rendered_previous:
                previous_segment = [rendered_previous]
    candidates = canonical[retired_count:]
    canonical_ids = [row["source_prefix_id"] for row in canonical]
    minimum_source_ids = minimum_fold_source_group_ids if minimum_fold_source_group_ids is not None else canonical_ids[:retired_count]
    minimum_fold_ids = [
        str(value or "") for value in list(minimum_source_ids)
    ]
    if minimum_fold_ids != canonical_ids[: len(minimum_fold_ids)] or len(minimum_fold_ids) < retired_count:
        base["reason"] = "replan_prefix_invalid"
        return base
    try:
        currentness = _thread_continuity_currentness_plan(
            canonical,
            previous=previous,
            reference_at=bridge_reference_at,
            recent_horizon_hours=bridge_recent_horizon_hours,
            source_token_limit=bridge_source_token_limit,
            estimate_messages=estimate_messages,
        )
    except ValueError:
        base["reason"] = "bridge_currentness_invalid"
        return base
    currentness_target_ids = list(
        currentness["target_retired_source_group_ids"]
    )
    currentness_expiry_required = bool(
        currentness["expired_raw_count"]
        or currentness["bridge_refresh_required"]
    )
    current_name = str(normalized["current_ephemeral"].get("name") or "")
    current_message = {
        "role": "user",
        "content": normalized["current_ephemeral"]["content"],
        **({"name": current_name} if current_name else {}),
    }
    raw_messages = [
        {
            "role": message["role"],
            "content": message["content"],
            **({"name": message["name"]} if message.get("name") else {}),
        }
        for group in candidates
        for message in group["messages"]
    ]
    available_input = context_window_tokens - reserved_output_tokens - fixed_non_message_tokens
    carrier_marker = {
        "role": "system",
        "content": _thread_continuity_checkpoint_marker(
            "tcr_" + "0" * 64, int(previous.get("revision") or 0) + 1, "0" * 64,
        ) + "\n",
    }
    try:
        total = _estimate(estimate_messages, [*base_messages, *previous_segment, *raw_messages, current_message, *trailing_messages])
    except ValueError:
        base["reason"] = "estimator_invalid"
        return base
    base.update(
        {
            "budget_status": "known",
            "context_window_tokens": context_window_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "fixed_non_message_tokens": fixed_non_message_tokens,
            "available_input_tokens": available_input,
            "base_messages": base_messages,
            "previous_continuity_messages": previous_segment,
            "fixed_prompt_fingerprint": _content_hash(base_messages),
            "post_current_messages": trailing_owner,
            "current_ephemeral": normalized["current_ephemeral"],
            "continuity_mode": "incremental" if previous else "rebuild",
            "predecessor_revision_id": str(previous.get("revision_id") or ""),
            "covered_source_group_ids": [row["source_prefix_id"] for row in canonical[:retired_count]],
            "retired_source_group_ids": [row["source_prefix_id"] for row in canonical[:retired_count]],
            "previous_bridge_status": previous_bridge["status"] if previous else "absent",
            "previous_bridge_source_group_ids": list(
                previous_bridge.get("represented_source_group_ids") or []
            ),
            "raw_suffix_groups": candidates,
            "raw_suffix_group_ids": [row["source_prefix_id"] for row in candidates],
            "estimated_main_input_tokens": total,
            "currentness_expiry_required": currentness_expiry_required,
            "currentness_expired_raw_count": currentness[
                "expired_raw_count"
            ],
            "currentness_target_retired_source_group_ids": (
                currentness_target_ids
            ),
        }
    )
    required_prefix_fold = len(minimum_fold_ids) > retired_count
    if (
        total <= available_input
        and not required_prefix_fold
        and not currentness_expiry_required
    ):
        base["status"] = "no_fold"
        base["reason"] = "within_budget"
        return base

    def carrier_capacity(suffix_messages: List[Dict[str, Any]]) -> int:
        compacted_input = _estimate(
            estimate_messages,
            [*base_messages, carrier_marker, *suffix_messages, current_message, *trailing_messages],
        )
        return min(reserved_output_tokens, available_input - compacted_input)

    def provider_messages(owner_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {
                "role": message["role"], "content": message["content"],
                **({"name": message["name"]} if message.get("name") else {}),
            }
            for group in owner_groups for message in group["messages"]
        ]

    if total <= available_input and currentness_expiry_required:
        target_count = max(
            len(currentness_target_ids),
            len(minimum_fold_ids),
        )
        target_ids = canonical_ids[:target_count]
        fold_groups = canonical[retired_count:target_count]
        raw_suffix = canonical[target_count:]
        try:
            summary_output_token_limit = max(
                0,
                carrier_capacity(provider_messages(raw_suffix)),
            )
        except ValueError:
            base["reason"] = "estimator_invalid"
            return base
        base.update(
            {
                "status": "fold_required",
                "reason": "currentness_expiry",
                "summary_call_feasibility": "unverified",
                "summary_output_token_limit": summary_output_token_limit,
                "oversized_raw_group_ids": [],
                "fold_groups": fold_groups,
                "fold_source_group_ids": [
                    row["source_prefix_id"] for row in fold_groups
                ],
                "covered_source_group_ids": target_ids,
                "retired_source_group_ids": target_ids,
                "raw_suffix_groups": raw_suffix,
                "raw_suffix_group_ids": [
                    row["source_prefix_id"] for row in raw_suffix
                ],
            }
        )
        _attach_recent_bridge_plan(
            base,
            canonical=canonical,
            reference_at=currentness["reference_at"],
            recent_horizon_hours=bridge_recent_horizon_hours,
            source_token_limit=bridge_source_token_limit,
            output_token_limit=bridge_output_token_limit,
            estimate_messages=estimate_messages,
        )
        if (
            base.get("bridge_source_group_ids")
            and int(base.get("summary_output_token_limit") or 0) < 1
        ):
            base.update(
                status="blocked",
                reason="summary_output_budget_unavailable",
            )
            return base
        base["fold_plan_id"] = _fold_plan_id(base, canonical)
        return base

    if reserved_output_tokens == 0:
        base["reason"] = "summary_output_budget_unavailable"
        return base

    force_rebuild = False
    if previous:
        try:
            force_rebuild = not any(
                _estimate(
                    estimate_messages,
                    [
                        *base_messages, *previous_segment,
                        *provider_messages(candidates[index:]),
                        current_message, *trailing_messages,
                    ],
                ) <= available_input
                for index in range(1, len(candidates) + 1)
            )
        except ValueError:
            base["reason"] = "estimator_invalid"
            return base

    fold_count = 0
    summary_output_token_limit = 0
    try:
        if not force_rebuild:
            for index in range(max(1, len(minimum_fold_ids) - retired_count), len(candidates) + 1):
                if carrier_capacity(provider_messages(candidates[index:])) == reserved_output_tokens:
                    fold_count = index
                    summary_output_token_limit = reserved_output_tokens
                    break
        if not fold_count and candidates and not force_rebuild:
            summary_output_token_limit = carrier_capacity([])
            if summary_output_token_limit > 0:
                fold_count = len(candidates)
    except ValueError:
        base["reason"] = "estimator_invalid"
        return base
    if not fold_count:
        if previous:
            try:
                minimum_rebuild_count = max(retired_count, len(minimum_fold_ids))
                first_positive: Tuple[int, int] | None = None
                selected: Tuple[int, int] | None = None
                for rebuild_count in range(minimum_rebuild_count, len(canonical) + 1):
                    limit = carrier_capacity(provider_messages(canonical[rebuild_count:]))
                    if limit > 0 and first_positive is None:
                        first_positive = (rebuild_count, limit)
                    if limit == reserved_output_tokens:
                        selected = (rebuild_count, limit)
                        break
            except ValueError:
                base["reason"] = "estimator_invalid"
                return base
            selected = selected or first_positive
            if selected is None:
                base["reason"] = "summary_output_budget_unavailable"
                return base
            rebuild_count, rebuild_limit = selected
            rebuild_groups = canonical[:rebuild_count]
            rebuild_suffix = canonical[rebuild_count:]
            base.update(
                {
                    "rebuild_required": True,
                    "reason": "rebuild_from_canonical_required",
                    "summary_call_feasibility": "unverified",
                    "summary_output_token_limit": rebuild_limit,
                    "continuity_mode": "rebuild",
                    "predecessor_revision_id": "",
                    "fold_groups": rebuild_groups,
                    "fold_source_group_ids": [row["source_prefix_id"] for row in rebuild_groups],
                    "covered_source_group_ids": [row["source_prefix_id"] for row in rebuild_groups],
                    "retired_source_group_ids": [row["source_prefix_id"] for row in rebuild_groups],
                    "raw_suffix_groups": rebuild_suffix,
                    "raw_suffix_group_ids": [row["source_prefix_id"] for row in rebuild_suffix],
                }
            )
            _attach_recent_bridge_plan(
                base,
                canonical=canonical,
                reference_at=bridge_reference_at,
                recent_horizon_hours=bridge_recent_horizon_hours,
                source_token_limit=bridge_source_token_limit,
                output_token_limit=bridge_output_token_limit,
                estimate_messages=estimate_messages,
            )
            base["fold_plan_id"] = _fold_plan_id(base, canonical)
            return base
        base["reason"] = "fixed_context_exceeds_budget"
        return base
    fold_groups = candidates[:fold_count]
    oversized_group_ids: List[str] = []
    try:
        for fold_group in fold_groups:
            group_tokens = _estimate(
                estimate_messages,
                [
                    {
                        "role": message["role"],
                        "content": message["content"],
                        **({"name": message["name"]} if message.get("name") else {}),
                    }
                    for message in fold_group["messages"]
                ],
            )
            if group_tokens > available_input:
                oversized_group_ids.append(fold_group["source_prefix_id"])
    except ValueError:
        base["reason"] = "estimator_invalid"
        return base
    raw_suffix = candidates[fold_count:]
    base.update(
        {
            "status": "fold_required",
            "reason": (
                "required_prefix_fold"
                if required_prefix_fold and total <= available_input
                else "token_pressure"
            ),
            "summary_call_feasibility": "unverified",
            "summary_output_token_limit": summary_output_token_limit,
            "oversized_raw_group_ids": oversized_group_ids,
            "fold_groups": fold_groups,
            "fold_source_group_ids": [row["source_prefix_id"] for row in fold_groups],
            "covered_source_group_ids": base["covered_source_group_ids"]
            + [row["source_prefix_id"] for row in fold_groups],
            "retired_source_group_ids": base["covered_source_group_ids"]
            + [row["source_prefix_id"] for row in fold_groups],
            "raw_suffix_groups": raw_suffix,
            "raw_suffix_group_ids": [row["source_prefix_id"] for row in raw_suffix],
        }
    )
    _attach_recent_bridge_plan(
        base,
        canonical=canonical,
        reference_at=bridge_reference_at,
        recent_horizon_hours=bridge_recent_horizon_hours,
        source_token_limit=bridge_source_token_limit,
        output_token_limit=bridge_output_token_limit,
        estimate_messages=estimate_messages,
    )
    base["fold_plan_id"] = _fold_plan_id(base, canonical)
    return base


def plan_thread_continuity_fold(
    groups: List[Dict[str, Any]],
    *,
    current_ephemeral: Mapping[str, Any],
    context_window_tokens: Any,
    reserved_output_tokens: Any,
    fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any,
    source_complete: bool,
    estimate_messages: MessageEstimator,
    previous_state: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    post_current_messages: Any = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    return _build_thread_continuity_fold_plan(
        groups,
        current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=fixed_non_message_tokens,
        fixed_prompt_messages=fixed_prompt_messages,
        source_complete=source_complete,
        estimate_messages=estimate_messages,
        previous_state=previous_state,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        post_current_messages=post_current_messages,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )


def validate_thread_continuity_input(
    plan: Mapping[str, Any],
    proposed_summary_message: Mapping[str, Any] | None,
    *,
    fixed_non_message_tokens: Any,
    estimate_messages: MessageEstimator,
    physical_owner_generation: object,
) -> Dict[str, Any]:
    rebuild_owner = (
        plan.get("status"), plan.get("reason"), plan.get("rebuild_required"),
        plan.get("continuity_mode"), plan.get("predecessor_revision_id"),
    ) == ("blocked", "rebuild_from_canonical_required", True, "rebuild", "") and bool(plan.get("fold_plan_id"))
    no_fold = (plan.get("status"), plan.get("reason")) == ("no_fold", "within_budget")
    if str(plan.get("status") or "") != "fold_required" and not rebuild_owner and not no_fold:
        return {"status": "not_applicable", "reason": "fold_not_required"}
    segments: List[Dict[str, Any]] = []
    if no_fold:
        if proposed_summary_message is not None:
            return {"status": "invalid", "reason": "summary_message_unexpected"}
        if plan.get("previous_continuity_messages"):
            try:
                segments = _continuity_messages(plan["previous_continuity_messages"])
            except ValueError:
                return {"status": "invalid", "reason": "summary_message_invalid"}
    else:
        if proposed_summary_message is None and not plan.get(
            "bridge_source_group_ids"
        ):
            segments = []
        else:
            try:
                segments = _continuity_messages(
                    [dict(proposed_summary_message or {})]
                )
            except ValueError:
                return {"status": "invalid", "reason": "summary_message_invalid"}
    if any(segment["role"] != "system" for segment in segments):
        return {"status": "invalid", "reason": "summary_message_invalid"}
    raw_messages = [
        {
            "role": message["role"],
            "content": message["content"],
            **({"name": message["name"]} if message.get("name") else {}),
        }
        for group in plan.get("raw_suffix_groups") or []
        for message in group["messages"]
    ]
    current_row = dict(plan.get("current_ephemeral") or {})
    current = {
        "role": "user",
        "content": current_row.get("content"),
        **({"name": current_row["name"]} if current_row.get("name") else {}),
    }
    try:
        trailing_messages = _post_current_provider_messages(plan.get("post_current_messages"))
    except ValueError:
        return {"status": "invalid", "reason": "post_current_messages_invalid"}
    messages = [*list(plan.get("base_messages") or []), *segments, *raw_messages, current, *trailing_messages]
    try:
        estimated = _estimate(estimate_messages, messages)
    except ValueError:
        return {"status": "invalid", "reason": "estimator_invalid"}
    window = int(plan.get("context_window_tokens") or 0)
    reserve = int(plan.get("reserved_output_tokens") or 0)
    fixed_non_message = plan.get("fixed_non_message_tokens")
    if (
        type(fixed_non_message_tokens) is not int
        or fixed_non_message_tokens < 0
        or fixed_non_message != fixed_non_message_tokens
    ):
        return {"status": "invalid", "reason": "fixed_non_message_tokens_invalid"}
    if estimated + fixed_non_message + reserve > window:
        raw_ids = list(plan.get("raw_suffix_group_ids") or [])
        if not raw_ids:
            return {
                "status": "blocked",
                "reason": "summary_too_large_all_groups_folded",
                "estimated_input_tokens": estimated,
            }
        return {
            "status": "replan_required",
            "reason": "summary_too_large",
            "next_oldest_group_to_fold": str(raw_ids[0] or ""),
            "required_covered_source_group_ids": [
                *list(plan.get("covered_source_group_ids") or []),
                str(raw_ids[0] or ""),
            ],
            "required_fold_source_group_ids": [
                *list(plan.get("covered_source_group_ids") or []),
                str(raw_ids[0] or ""),
            ],
            "estimated_input_tokens": estimated,
        }
    physical_owner_payload = _project_thread_continuity_physical_owner_sidecar(
        plan,
        checkpoint_messages=segments,
        physical_messages=messages,
    )
    if not _physical_owner_sidecar_payload_valid(
        physical_owner_payload,
        messages,
    ):
        return {"status": "invalid", "reason": "physical_owner_sidecar_invalid"}
    physical_owner_sidecar = _ThreadContinuityPhysicalOwnerSidecar(
        physical_owner_payload,
        _PHYSICAL_OWNER_AUTHORITY,
        physical_owner_generation,
    )
    if not _read_thread_continuity_physical_owner_sidecar(
        physical_owner_sidecar,
        physical_messages=messages,
        expected_generation=physical_owner_generation,
    ):
        return {"status": "invalid", "reason": "physical_owner_sidecar_invalid"}
    return {
        "status": "ready",
        "provider_messages": messages,
        "estimated_input_tokens": estimated,
        "physical_owner_sidecar": physical_owner_sidecar,
    }


SUMMARY_ATTEMPT_SCHEMA = "thread_continuity_summary_attempt.v1"
SUMMARY_RECEIPT_SCHEMA = "thread_continuity_summary_receipt.v1"
RECENT_BRIDGE_COMPLETION_SCHEMA = "thread_continuity_recent_bridge_completion.v1"
SUMMARY_CONSTRUCTION_TOKEN_LIMIT = 30_000
SUMMARY_INSTRUCTION = """Build one bounded recent continuity bridge from only the supplied exact canonical source groups.
Preserve concrete people, events, decisions, emotions, causes, promises, open loops, and uncertainty.
Do not invent or infer a profile, persona, memory, diagnosis, preference, relationship, or action authority beyond the source.
Do not reconstruct older history and do not treat any previous bridge or summary as source.
Source IDs are structural metadata only and need not appear in the prose. Return only the visible summary text."""


def _summary_prompt(carry: str, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SUMMARY_INSTRUCTION}]
    if carry:
        messages.append({"role": "system", "name": "continuity_carry", "content": carry})
    messages.append(
        {
            "role": "system",
            "name": "continuity_source_metadata",
            "content": "Ordered canonical source group IDs: "
            + json.dumps([group["source_prefix_id"] for group in groups], ensure_ascii=False),
        }
    )
    for group in groups:
        for message in group["messages"]:
            name = str(message.get("name") or "")
            messages.append(
                {"role": message["role"], "content": message["content"], **({"name": name} if name else {})}
            )
    return messages


def _normalize_summary_receipt(
    receipt: Mapping[str, Any], *, attempt_descriptor: Mapping[str, Any], provider_result: Any,
) -> Dict[str, Any]:
    row = dict(receipt or {})
    descriptor = dict(attempt_descriptor or {})
    prior = [str(value or "") for value in list(descriptor.get("processed_source_group_ids") or [])]
    batch = [str(value or "") for value in list(descriptor.get("batch_source_group_ids") or [])]
    processed = [*prior, *batch]
    if _provider_summary_result_incomplete(provider_result):
        raise ValueError("thread_continuity_summary_receipt_invalid")
    summary = _visible_summary_text(provider_result)
    if not batch or not _normalize(summary):
        raise ValueError("thread_continuity_summary_receipt_invalid")
    body = {
        "schema": SUMMARY_RECEIPT_SCHEMA,
        "descriptor_id": descriptor["descriptor_id"],
        "processed_source_group_ids": processed,
        "accepted_summary_sha256": _content_hash(summary),
        "result_sha256": _content_hash(provider_result),
    }
    expected = {**body, "receipt_id": "tcsr_" + _content_hash(body)}
    if row != expected:
        raise ValueError("thread_continuity_summary_receipt_invalid")
    return {**expected, "accepted_summary": summary}


def plan_next_summary_attempt(
    groups: List[Dict[str, Any]], *, fold_plan: Mapping[str, Any],
    current_ephemeral: Mapping[str, Any], context_window_tokens: Any,
    reserved_output_tokens: Any, fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any, source_complete: bool,
    estimate_messages: MessageEstimator,
    previous_checkpoint: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    accepted_attempts: List[Mapping[str, Any]] | None = None,
    accepted_chunk_completions: List[List[Mapping[str, Any]]] | None = None,
    post_current_messages: Any = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    blocked = {"status": "blocked", "progress_source_group_count": 0}
    try:
        owner_plan = normalize_thread_continuity_fold_plan(
            fold_plan,
            source_groups=groups,
            current_ephemeral=current_ephemeral,
            context_window_tokens=context_window_tokens,
            reserved_output_tokens=reserved_output_tokens,
            fixed_non_message_tokens=fixed_non_message_tokens,
            fixed_prompt_messages=fixed_prompt_messages,
            source_complete=source_complete,
            estimate_messages=estimate_messages,
            previous_state=previous_checkpoint,
            minimum_fold_source_group_ids=minimum_fold_source_group_ids,
            post_current_messages=post_current_messages,
            bridge_reference_at=bridge_reference_at,
            bridge_recent_horizon_hours=bridge_recent_horizon_hours,
            bridge_source_token_limit=bridge_source_token_limit,
            bridge_output_token_limit=bridge_output_token_limit,
        )
        canonical = list(normalize_complete_thread_groups(groups)["groups"])
    except (TypeError, ValueError):
        return {**blocked, "reason": "fold_plan_invalid"}
    try:
        checkpoint = (
            normalize_thread_continuity_checkpoint(previous_checkpoint, source_groups=canonical)
            if previous_checkpoint else {}
        )
    except (TypeError, ValueError):
        checkpoint = {}
    retired_ids = list(
        owner_plan.get("retired_source_group_ids")
        or owner_plan.get("covered_source_group_ids")
        or []
    )
    target_ids = list(owner_plan.get("bridge_source_group_ids") or [])
    target_id_set = set(target_ids)
    target_groups = [
        group for group in canonical if group["source_prefix_id"] in target_id_set
    ]
    if [group["source_prefix_id"] for group in target_groups] != target_ids:
        return {**blocked, "reason": "bridge_source_invalid"}
    checkpoint_revision_id = str(checkpoint.get("revision_id") or "")
    mode = "bridge_rebuild"
    predecessor = checkpoint_revision_id
    summary_output_token_limit = owner_plan.get("summary_output_token_limit")
    summary_construction_token_limit = min(
        context_window_tokens,
        SUMMARY_CONSTRUCTION_TOKEN_LIMIT,
    )
    if (
        type(summary_output_token_limit) is not int
        or summary_output_token_limit < 0
        or summary_output_token_limit > reserved_output_tokens
        or summary_output_token_limit
        > int(owner_plan.get("bridge_output_token_limit") or 0)
    ):
        return {**blocked, "reason": "summary_output_budget_unavailable"}

    def make_plan_id(attempt_mode: str, attempt_predecessor: str) -> str:
        return "tcsp_" + _content_hash(
            {
                "fold_plan_id": owner_plan["fold_plan_id"],
                "mode": attempt_mode,
                "predecessor_revision_id": attempt_predecessor,
                "retirement_source_group_ids": retired_ids,
                "target_inventory": [
                    [group["source_prefix_id"], _group_fingerprint(group)] for group in target_groups
                ],
                "context_window_tokens": context_window_tokens,
                "reserved_output_tokens": reserved_output_tokens,
                "fixed_non_message_tokens": fixed_non_message_tokens,
                "summary_construction_token_limit": summary_construction_token_limit,
            }
        )

    def fit_batch(start: int, summary: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        batch: List[Dict[str, Any]] = []
        prompt: List[Dict[str, Any]] = []
        for end in range(start + 1, len(target_groups) + 1):
            candidate = target_groups[start:end]
            candidate_prompt = _summary_prompt(summary, candidate)
            if (
                _estimate(estimate_messages, candidate_prompt)
                + summary_output_token_limit
                > summary_construction_token_limit
            ):
                break
            batch, prompt = candidate, candidate_prompt
        return batch, prompt

    def next_attempt(
        attempt_mode: str, attempt_predecessor: str, carry: str, processed: List[str],
    ) -> Dict[str, Any]:
        if processed == target_ids:
            completion = {
                "schema": RECENT_BRIDGE_COMPLETION_SCHEMA,
                "fold_plan_id": owner_plan["fold_plan_id"],
                "continuity_mode": attempt_mode,
                "predecessor_revision_id": attempt_predecessor,
                "retired_source_group_ids": retired_ids,
                "bridge_source_group_ids": processed,
                "summary_sha256": hashlib.sha256(carry.encode("utf-8")).hexdigest(),
            }
            completion["completion_id"] = "tcscomp_" + _content_hash(completion)
            return {
                "status": "complete",
                "accepted_summary": carry,
                "retired_source_group_ids": retired_ids,
                "bridge_source_group_ids": processed,
                "owner_completion": completion,
                "progress_source_group_count": 0,
            }
        if reserved_output_tokens == 0 or summary_output_token_limit == 0:
            return {**blocked, "reason": "summary_output_budget_unavailable"}
        try:
            batch, provider_messages = fit_batch(len(processed), carry)
        except ValueError:
            return {**blocked, "reason": "estimator_invalid"}
        if not batch:
            try:
                group_fits_empty = bool(fit_batch(len(processed), "")[0])
            except ValueError:
                return {**blocked, "reason": "estimator_invalid"}
            reason = "summary_input_too_large" if carry and group_fits_empty else "chunk_required"
            result = {
                **blocked,
                "reason": reason,
                "blocked_source_group_id": target_ids[len(processed)],
            }
            if reason == "chunk_required":
                owner = {
                    "fold_plan_id": owner_plan["fold_plan_id"],
                    "mode": attempt_mode,
                    "predecessor_revision_id": attempt_predecessor,
                    "processed_source_group_ids": processed,
                    "carry_sha256": _content_hash(carry),
                    "fixed_non_message_tokens": fixed_non_message_tokens,
                    "blocked_source_group_id": result["blocked_source_group_id"],
                }
                result.update(owner, chunk_owner_id="tcsc_" + _content_hash(owner))
            return result
        descriptor = {
            "schema": SUMMARY_ATTEMPT_SCHEMA,
            "fold_plan_id": owner_plan["fold_plan_id"],
            "plan_id": make_plan_id(attempt_mode, attempt_predecessor),
            "mode": attempt_mode,
            "predecessor_revision_id": attempt_predecessor,
            "target_source_group_ids": target_ids,
            "target_group_fingerprints": [_group_fingerprint(group) for group in target_groups],
            "processed_source_group_ids": processed,
            "batch_source_group_ids": [group["source_prefix_id"] for group in batch],
            "batch_group_fingerprints": [_group_fingerprint(group) for group in batch],
            "carry_sha256": _content_hash(carry),
            "input_sha256": _content_hash(provider_messages),
            "context_window_tokens": context_window_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "summary_output_token_limit": summary_output_token_limit,
            "fixed_non_message_tokens": fixed_non_message_tokens,
            "summary_construction_token_limit": summary_construction_token_limit,
        }
        descriptor["descriptor_id"] = "tcsd_" + _content_hash(descriptor)
        return {"status": "ready", "descriptor": descriptor, "provider_messages": provider_messages}

    carry = ""
    processed: List[str] = []
    chunk_completions = list(accepted_chunk_completions or [])
    chunk_index = 0

    def consume_completed_chunks(planned: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal mode, predecessor, carry, processed, chunk_index
        while (
            planned.get("status") == "blocked"
            and planned.get("reason") == "chunk_required"
            and chunk_index < len(chunk_completions)
        ):
            completion = _plan_summary_chunk_from_owner(
                planned,
                groups=groups,
                carry_candidates=[carry],
                context_window_tokens=context_window_tokens,
                reserved_output_tokens=reserved_output_tokens,
                estimate_messages=estimate_messages,
                accepted_chunk_attempts=chunk_completions[chunk_index],
            )
            if completion.get("status") != "complete":
                return {**blocked, "reason": "accepted_chunk_completion_invalid"}
            mode, predecessor = str(planned["mode"]), str(planned["predecessor_revision_id"])
            carry, processed = str(completion["accepted_summary"]), list(completion["covered_source_group_ids"])
            chunk_index += 1
            planned = next_attempt(mode, predecessor, carry, processed)
        return planned

    for accepted in list(accepted_attempts or []):
        expected = consume_completed_chunks(next_attempt(mode, predecessor, carry, processed))
        descriptor = dict(accepted.get("descriptor") or {}) if isinstance(accepted, Mapping) else {}
        if expected.get("status") != "ready" or descriptor != expected.get("descriptor"):
            return {**blocked, "reason": "accepted_receipt_invalid"}
        try:
            receipt = _normalize_summary_receipt(
                accepted.get("receipt") or {},
                attempt_descriptor=descriptor,
                provider_result=accepted.get("provider_result"),
            )
        except (TypeError, ValueError):
            return {**blocked, "reason": "accepted_receipt_invalid"}
        mode = str(descriptor["mode"])
        predecessor = str(descriptor["predecessor_revision_id"])
        carry = receipt["accepted_summary"]
        processed = list(receipt["processed_source_group_ids"])
    planned = consume_completed_chunks(next_attempt(mode, predecessor, carry, processed))
    return planned if chunk_index == len(chunk_completions) else {
        **blocked, "reason": "accepted_chunk_completion_invalid"
    }


def _visible_summary_text(result: Any) -> str:
    parts: List[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and _normalize(value):
            parts.append(_normalize(value))

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, Mapping):
            return
        kind = str(value.get("type") or "").strip().lower()
        role = str(value.get("role") or "").strip().lower()
        if role and role != "assistant":
            return
        if kind in {"text", "output_text"}:
            if role in {"", "assistant"}:
                add(value.get("text") if isinstance(value.get("text"), str) else value.get("content"))
            return
        if kind in {"message", "assistant_message"}:
            if role not in {"", "assistant"}:
                return
            add(value.get("content"))
            if isinstance(value.get("content"), list):
                visit(value["content"])
            return
        if kind or role:
            return
        if isinstance(value.get("output"), list):
            visit(value["output"])
        if isinstance(value.get("choices"), list):
            for choice in value["choices"]:
                if isinstance(choice, Mapping):
                    message = choice.get("message")
                    if (
                        isinstance(message, Mapping)
                        and str(message.get("role") or "").strip().lower() in {"", "assistant"}
                    ):
                        content = message.get("content")
                        add(content)
                        if isinstance(content, list):
                            visit(content)

    if isinstance(result, str):
        add(result)
    elif (
        isinstance(result, Mapping)
        and isinstance(result.get("output_text"), str)
        and not str(result.get("role") or "").strip()
        and not str(result.get("type") or "").strip()
    ):
        add(result["output_text"])
    else:
        visit(result)
    return _normalize("\n".join(parts))


def _provider_summary_result_incomplete(result: Any) -> bool:
    if not isinstance(result, Mapping):
        return False
    if str(result.get("status") or "").strip().lower() == "incomplete":
        return True

    def truncated_reason(row: Mapping[str, Any]) -> bool:
        reason = str(row.get("finish_reason") or row.get("finishReason") or "").strip()
        return reason.replace("-", "_").upper() in {"LENGTH", "MAX_TOKENS"}

    if truncated_reason(result):
        return True
    return any(
        truncated_reason(row)
        for key in ("choices", "candidates")
        for row in list(result.get(key) or [])
        if isinstance(row, Mapping)
    )


def accept_summary_attempt(
    descriptor: Mapping[str, Any], result: Any, *, groups: List[Dict[str, Any]],
    fold_plan: Mapping[str, Any], current_ephemeral: Mapping[str, Any],
    context_window_tokens: Any, reserved_output_tokens: Any,
    fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any, source_complete: bool, estimate_messages: MessageEstimator,
    previous_checkpoint: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    accepted_attempts: List[Mapping[str, Any]] | None = None,
    accepted_chunk_completions: List[List[Mapping[str, Any]]] | None = None,
    post_current_messages: Any = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    rejected = {"status": "rejected", "progress_source_group_count": 0}
    expected = plan_next_summary_attempt(
        groups,
        fold_plan=fold_plan,
        current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=fixed_non_message_tokens,
        fixed_prompt_messages=fixed_prompt_messages,
        source_complete=source_complete,
        estimate_messages=estimate_messages,
        previous_checkpoint=previous_checkpoint,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        accepted_attempts=accepted_attempts,
        accepted_chunk_completions=accepted_chunk_completions,
        post_current_messages=post_current_messages,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    row = dict(descriptor or {})
    if expected.get("status") != "ready" or row != expected.get("descriptor"):
        return {**rejected, "reason": "attempt_descriptor_invalid"}
    if _provider_summary_result_incomplete(result):
        return {**rejected, "reason": "summary_result_incomplete"}
    summary = _visible_summary_text(result)
    if not summary:
        return {**rejected, "reason": "summary_result_invalid"}
    try:
        summary_tokens = _estimate(
            estimate_messages,
            [{"role": "assistant", "content": summary}],
        )
    except ValueError:
        return {**rejected, "reason": "estimator_invalid"}
    if summary_tokens > int(fold_plan.get("bridge_output_token_limit") or 0):
        return {**rejected, "reason": "bridge_output_too_large"}
    prior = list(row["processed_source_group_ids"])
    batch = list(row["batch_source_group_ids"])
    body = {
        "schema": SUMMARY_RECEIPT_SCHEMA,
        "descriptor_id": row["descriptor_id"],
        "processed_source_group_ids": [*prior, *batch],
        "accepted_summary_sha256": _content_hash(summary),
        "result_sha256": _content_hash(result),
    }
    receipt = {**body, "receipt_id": "tcsr_" + _content_hash(body)}
    return {
        "status": "accepted",
        "progress_source_group_count": len(batch),
        "accepted_summary": summary,
        "covered_source_group_ids": body["processed_source_group_ids"],
        "receipt": receipt,
    }


def build_thread_continuity_checkpoint_from_attempts(
    *, source_groups: List[Dict[str, Any]], fold_plan: Mapping[str, Any],
    current_ephemeral: Mapping[str, Any], context_window_tokens: Any,
    reserved_output_tokens: Any, fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any, source_complete: bool, estimate_messages: MessageEstimator,
    previous_checkpoint: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    accepted_summary_attempts: List[Mapping[str, Any]] | None = None, accepted_chunk_completions: List[List[Mapping[str, Any]]] | None = None,
    post_current_messages: Any = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    complete = plan_next_summary_attempt(
        source_groups, fold_plan=fold_plan, current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens, reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=fixed_non_message_tokens, fixed_prompt_messages=fixed_prompt_messages,
        source_complete=source_complete, estimate_messages=estimate_messages,
        previous_checkpoint=previous_checkpoint,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        accepted_attempts=accepted_summary_attempts,
        accepted_chunk_completions=accepted_chunk_completions,
        post_current_messages=post_current_messages,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    if complete.get("status") != "complete":
        raise ValueError("thread_continuity_summary_incomplete")
    summary = str(complete.get("accepted_summary") or "")
    retired = list(complete.get("retired_source_group_ids") or [])
    bridge_source_ids = list(complete.get("bridge_source_group_ids") or [])
    completion = dict(complete.get("owner_completion") or {})
    mode, predecessor = completion.get("continuity_mode"), completion.get("predecessor_revision_id")
    body = {
        "schema": RECENT_BRIDGE_COMPLETION_SCHEMA,
        "fold_plan_id": fold_plan.get("fold_plan_id"),
        "continuity_mode": mode,
        "predecessor_revision_id": predecessor,
        "retired_source_group_ids": retired,
        "bridge_source_group_ids": bridge_source_ids,
        "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
    }
    expected = {**body, "completion_id": "tcscomp_" + _content_hash(body)}
    if mode != "bridge_rebuild":
        raise ValueError("thread_continuity_summary_completion_invalid")
    if completion != expected:
        raise ValueError("thread_continuity_summary_completion_invalid")
    return build_thread_continuity_checkpoint_v2(
        previous_state=previous_checkpoint,
        source_groups=source_groups,
        retired_source_group_ids=retired,
        bridge_source_group_ids=bridge_source_ids,
        bridge_text=summary,
        bridge_policy={
            "reference_at": fold_plan.get("bridge_reference_at"),
            "recent_horizon_hours": fold_plan.get(
                "bridge_recent_horizon_hours"
            ),
            "source_token_limit": fold_plan.get("bridge_source_token_limit"),
            "output_token_limit": fold_plan.get("bridge_output_token_limit"),
        },
    )


SUMMARY_CHUNK_INSTRUCTION = SUMMARY_INSTRUCTION + """
The source below is one exact contiguous fragment of a larger canonical group. Update the carried summary using only this fragment; preserve uncertainty and partial boundaries without guessing missing text."""


def _chunk_atoms(group: Mapping[str, Any]) -> List[Dict[str, Any]]:
    atoms: List[Dict[str, Any]] = []
    cursor = 0
    for message_index, message in enumerate(group["messages"]):
        content = message["content"]
        parts = content if isinstance(content, list) else [content]
        for part in parts:
            if isinstance(part, str):
                kind, length = "string", len(part)
            elif isinstance(part, Mapping) and str(part.get("type") or "") in {"text", "input_text"}:
                kind, length = str(part["type"]), max(1, len(part["text"]))
            elif isinstance(part, Mapping) and str(part.get("type") or "") in {"image_url", "input_image"}:
                kind, length = str(part["type"]), 1
            else:
                raise ValueError("thread_continuity_chunk_source_invalid")
            if length:
                atoms.append(
                    {
                        "message_index": message_index,
                        "kind": kind,
                        "value": part,
                        "start": cursor,
                        "end": cursor + length,
                    }
                )
                cursor += length
    return atoms


def _chunk_fragment_messages(
    group: Mapping[str, Any], atoms: List[Dict[str, Any]], start: int, end: int,
) -> List[Dict[str, Any]]:
    pieces: Dict[int, Any] = {}
    for atom in atoms:
        left, right = max(start, atom["start"]), min(end, atom["end"])
        if left >= right:
            continue
        message_index = atom["message_index"]
        if atom["kind"] == "string":
            pieces[message_index] = atom["value"][left - atom["start"] : right - atom["start"]]
        else:
            part = dict(atom["value"])
            if atom["kind"] in {"text", "input_text"}:
                part["text"] = part["text"][left - atom["start"] : right - atom["start"]]
            pieces.setdefault(message_index, []).append(part)
    out: List[Dict[str, Any]] = []
    for message_index, message in enumerate(group["messages"]):
        if message_index not in pieces:
            continue
        name = str(message.get("name") or "")
        out.append(
            {
                "role": message["role"],
                "content": pieces[message_index],
                **({"name": name} if name else {}),
            }
        )
    return out


def _chunk_prompt(
    carry: str, group: Mapping[str, Any], atoms: List[Dict[str, Any]], start: int, end: int,
) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SUMMARY_CHUNK_INSTRUCTION}]
    if carry:
        messages.append({"role": "system", "name": "continuity_carry", "content": carry})
    metadata = {"source_group_id": group["source_prefix_id"], "fragment": [start, end, atoms[-1]["end"]]}
    messages.append(
        {
            "role": "system",
            "name": "continuity_fragment_metadata",
            "content": json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        }
    )
    return [*messages, *_chunk_fragment_messages(group, atoms, start, end)]


def _chunk_receipt(descriptor: Mapping[str, Any], provider_result: Any) -> Tuple[str, Dict[str, Any]]:
    if _provider_summary_result_incomplete(provider_result):
        raise ValueError("thread_continuity_chunk_receipt_invalid")
    summary = _visible_summary_text(provider_result)
    if not summary:
        raise ValueError("thread_continuity_chunk_receipt_invalid")
    body = {
        "schema": "thread_continuity_summary_chunk_receipt.v1",
        "descriptor_id": descriptor["descriptor_id"],
        "source_group_id": descriptor["source_group_id"],
        "fragment_end": descriptor["fragment_end"],
        "phase": descriptor["phase"],
        "accepted_summary_sha256": _content_hash(summary),
        "result_sha256": _content_hash(provider_result),
    }
    return summary, {**body, "receipt_id": "tccr_" + _content_hash(body)}


def _bounded_chunk_end(
    build_prompt: Callable[[int], List[Dict[str, Any]]], estimate_messages: MessageEstimator,
    *, start: int, total: int, window: int, reserve: int,
) -> Tuple[int, int, bool]:
    samples: Dict[int, int] = {}

    def sample(end: int) -> int:
        if end not in samples:
            samples[end] = _estimate(estimate_messages, build_prompt(end)) + reserve
            ordered = sorted(samples.items())
            if any(left[1] > right[1] for left, right in zip(ordered, ordered[1:])):
                raise ValueError("thread_continuity_estimator_nonmonotonic")
        return samples[end]

    best, first = start, start + 1
    try:
        sample(first)
        if first < total:
            sample(first + 1)
        low, high = first, total
        while low <= high:
            end = (low + high) // 2
            if sample(end) <= window:
                best, low = end, end + 1
            else:
                high = end - 1
        if best < total:
            sample(best + 1)
    except ValueError:
        return start, len(samples), True
    return best, len(samples), False


def _plan_summary_chunk_from_owner(
    owner: Mapping[str, Any], *, groups: List[Dict[str, Any]], carry_candidates: List[str],
    context_window_tokens: int, reserved_output_tokens: int,
    estimate_messages: MessageEstimator,
    accepted_chunk_attempts: List[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    blocked = {"status": "blocked", "progress_source_group_count": 0}
    if owner.get("status") != "blocked" or owner.get("reason") != "chunk_required":
        return {**blocked, "reason": "chunk_owner_invalid"}
    try:
        canonical = normalize_complete_thread_groups(groups)["groups"]
        group = next(row for row in canonical if row["source_prefix_id"] == owner["blocked_source_group_id"])
        atoms = _chunk_atoms(group)
        carry = next(value for value in carry_candidates if _content_hash(value) == owner["carry_sha256"])
    except (StopIteration, TypeError, ValueError):
        return {**blocked, "reason": "chunk_owner_invalid"}

    total = atoms[-1]["end"]
    summary_construction_token_limit = min(
        context_window_tokens,
        SUMMARY_CONSTRUCTION_TOKEN_LIMIT,
    )

    def next_attempt(cursor: int, summary: str) -> Dict[str, Any]:
        if cursor == total:
            return {
                "status": "complete",
                "progress_source_group_count": 0,
                "accepted_summary": summary,
                "covered_source_group_ids": [
                    *owner["processed_source_group_ids"],
                    group["source_prefix_id"],
                ],
            }
        best, estimator_calls, observed_violation = _bounded_chunk_end(
            lambda end: _chunk_prompt(summary, group, atoms, cursor, end),
            estimate_messages,
            start=cursor,
            total=total,
            window=summary_construction_token_limit,
            reserve=reserved_output_tokens,
        )
        if observed_violation:
            return {
                **blocked,
                "reason": "estimator_invalid",
                "monotonicity_contract": "deterministic_monotonic",
                "observed_violation": True,
                "estimator_call_count": estimator_calls,
            }
        if best == cursor:
            return {
                **blocked,
                "reason": "atomic_fragment_too_large",
                "monotonicity_contract": "deterministic_monotonic",
                "observed_violation": False,
                "estimator_call_count": estimator_calls,
                "blocked_atom_kind": next(atom["kind"] for atom in atoms if atom["start"] <= cursor < atom["end"]),
            }
        provider_messages = _chunk_prompt(summary, group, atoms, cursor, best)
        descriptor = {
            "schema": "thread_continuity_summary_chunk_attempt.v1",
            "chunk_owner_id": owner["chunk_owner_id"],
            "source_group_id": group["source_prefix_id"],
            "source_group_fingerprint": _group_fingerprint(group),
            "message_lineage": [
                [message["role"], message.get("name", ""), message["message_id"], message["content_hash"]]
                for message in group["messages"]
            ],
            "processed_source_group_ids": owner["processed_source_group_ids"],
            "fragment_start": cursor,
            "fragment_end": best,
            "fragment_total": total,
            "fragment_fingerprint": _content_hash(provider_messages[3 if summary else 2 :]),
            "phase": "group_finalize" if best == total else "fragment_update",
            "carry_sha256": _content_hash(summary),
            "input_sha256": _content_hash(provider_messages),
            "context_window_tokens": context_window_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "fixed_non_message_tokens": owner.get("fixed_non_message_tokens"),
            "summary_construction_token_limit": summary_construction_token_limit,
            "monotonicity_contract": "deterministic_monotonic",
            "observed_violation": False,
            "estimator_call_count": estimator_calls,
        }
        descriptor["descriptor_id"] = "tccd_" + _content_hash(descriptor)
        return {"status": "ready", "descriptor": descriptor, "provider_messages": provider_messages}

    cursor = 0
    for accepted in list(accepted_chunk_attempts or []):
        expected = next_attempt(cursor, carry)
        descriptor = dict(accepted.get("descriptor") or {}) if isinstance(accepted, Mapping) else {}
        if expected.get("status") != "ready" or descriptor != expected.get("descriptor"):
            return {**blocked, "reason": "accepted_chunk_receipt_invalid"}
        try:
            summary, receipt = _chunk_receipt(descriptor, accepted.get("provider_result"))
            if dict(accepted.get("receipt") or {}) != receipt:
                raise ValueError("thread_continuity_chunk_receipt_invalid")
        except (TypeError, ValueError):
            return {**blocked, "reason": "accepted_chunk_receipt_invalid"}
        cursor, carry = descriptor["fragment_end"], summary
    return next_attempt(cursor, carry)


def plan_next_summary_chunk_attempt(
    groups: List[Dict[str, Any]], *, accepted_summary_attempts: List[Mapping[str, Any]] | None = None,
    accepted_chunk_completions: List[List[Mapping[str, Any]]] | None = None,
    accepted_chunk_attempts: List[Mapping[str, Any]] | None = None, **owner_inputs: Any,
) -> Dict[str, Any]:
    owner = plan_next_summary_attempt(
        groups, accepted_attempts=accepted_summary_attempts,
        accepted_chunk_completions=accepted_chunk_completions, **owner_inputs,
    )
    candidates = [""]
    for attempts in (accepted_summary_attempts, (accepted_chunk_completions or [None])[-1]):
        if isinstance(attempts, list) and attempts and isinstance(attempts[-1], Mapping):
            candidates.insert(0, _visible_summary_text(attempts[-1].get("provider_result")))
    return _plan_summary_chunk_from_owner(
        owner, groups=groups, carry_candidates=candidates,
        context_window_tokens=owner_inputs["context_window_tokens"],
        reserved_output_tokens=owner_inputs["reserved_output_tokens"],
        estimate_messages=owner_inputs["estimate_messages"],
        accepted_chunk_attempts=accepted_chunk_attempts,
    )


def accept_summary_chunk_attempt(
    descriptor: Mapping[str, Any], result: Any, **owner_inputs: Any,
) -> Dict[str, Any]:
    rejected = {"status": "rejected", "progress_source_group_count": 0}
    expected = plan_next_summary_chunk_attempt(**owner_inputs)
    row = dict(descriptor or {})
    if expected.get("status") != "ready" or row != expected.get("descriptor"):
        return {**rejected, "reason": "chunk_descriptor_invalid"}
    if _provider_summary_result_incomplete(result):
        return {**rejected, "reason": "summary_chunk_result_incomplete"}
    try:
        summary, receipt = _chunk_receipt(row, result)
    except (TypeError, ValueError):
        return {**rejected, "reason": "chunk_result_invalid"}
    finalized = row["phase"] == "group_finalize"
    return {
        "status": "accepted",
        "progress_source_group_count": 1 if finalized else 0,
        "accepted_summary": summary,
        "covered_source_group_ids": [
            *row["processed_source_group_ids"],
            *([row["source_group_id"]] if finalized else []),
        ],
        "receipt": receipt,
    }
