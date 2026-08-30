from __future__ import annotations

import hashlib, json
from typing import Any, Callable, Dict, List, Mapping

from .context_compactor import (
    _mint_thread_continuity_prompt_plan_owner,
    _read_thread_continuity_fixed_prompt_selection,
    accept_summary_attempt,
    accept_summary_chunk_attempt,
    build_thread_continuity_checkpoint_from_attempts,
    plan_next_summary_attempt,
    plan_next_summary_chunk_attempt,
    plan_thread_continuity_fold,
    render_thread_continuity_checkpoint_message,
    SUMMARY_CONSTRUCTION_TOKEN_LIMIT,
    thread_continuity_bridge_projection,
    thread_continuity_retirement_source_group_ids,
    validate_thread_continuity_input,
)


_SCHEMA = "thread_continuity_turn_compilation.v1"
_TRACE_SAMPLE_LIMIT, _ID_SAMPLE_LIMIT = 17, 8


def _result(trace: Dict[str, Any], status: str, *, reason: str, revision: int, snapshot: str,
            mode: str = "raw", messages: List[Dict[str, Any]] | None = None,
            checkpoint: Mapping[str, Any] | None = None,
            physical_owner_sidecar: Mapping[str, Any] | None = None,
            selected_prompt_assembly: Any = None,
            fixed_prompt_selection: Any = None) -> Dict[str, Any]:
    trace.update(final_status=status, reason=reason)
    return {
        "schema": _SCHEMA, "status": status, "mode": mode,
        "physical_provider_messages": list(messages or []) if status == "ready" else [],
        "private_physical_owner_sidecar": (
            physical_owner_sidecar if status == "ready" and physical_owner_sidecar else None
        ),
        "private_selected_prompt_assembly": (
            selected_prompt_assembly if status == "ready" else None
        ),
        "private_fixed_prompt_selection": (
            fixed_prompt_selection if status == "ready" else None
        ),
        "checkpoint_candidate": dict(checkpoint) if status == "ready" and checkpoint else None,
        "expected_revision": revision, "expected_pre_turn_source_snapshot": snapshot, "trace": trace,
    }


def _ids_trace(values: List[str]) -> Dict[str, Any]:
    return {"count": len(values), "sample": values[:_ID_SAMPLE_LIMIT], "sha256": hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()}


def _note_call(trace: Dict[str, Any], kind: str, generation: int,
               descriptor: Mapping[str, Any]) -> Dict[str, Any] | None:
    descriptor_id = str(descriptor.get("descriptor_id") or "")
    if not descriptor_id or descriptor_id in trace["seen_descriptor_ids"]:
        return None
    trace["seen_descriptor_ids"].add(descriptor_id)
    trace["summary_call_count"] += 1
    trace[f"{kind}_attempt_count"] += 1
    if len(trace["attempt_samples"]) == _TRACE_SAMPLE_LIMIT:
        trace["attempt_sample_truncated"] = True
        return {}
    sample = {
        "kind": kind, "plan_generation": generation, "descriptor_id": descriptor_id,
        "provider_returned": False, "accepted": False,
    }
    trace["attempt_samples"].append(sample)
    return sample


def _note_result(trace: Dict[str, Any], sample: Dict[str, Any] | None, kind: str,
                 descriptor: Mapping[str, Any], accepted: Mapping[str, Any]) -> None:
    trace["provider_returned_count"] += 1
    accepted_ok = accepted.get("status") == "accepted"
    if accepted_ok:
        trace["accepted_receipt_count"] += 1
        trace[f"accepted_{kind}_receipt_count"] += 1
    if sample:
        sample.update(provider_returned=True, accepted=accepted_ok)
        if accepted_ok:
            receipt = dict(accepted.get("receipt") or {})
            sample.update(
                receipt_id=receipt.get("receipt_id"), result_sha256=receipt.get("result_sha256"),
                progress_source_group_count=int(accepted.get("progress_source_group_count") or 0),
                progress_fragment_count=(int(descriptor.get("fragment_end") or 0) - int(descriptor.get("fragment_start") or 0)) if kind == "chunk" else 0,
            )


def _public_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: value for key, value in trace.items() if key != "seen_descriptor_ids"}
    out.update(attempt_sample_omitted_count=trace["summary_call_count"] - len(trace["attempt_samples"]),
               projected_cache_attempt_count=trace["summary_call_count"],
               cache_observation_complete=trace["cache_unknown_attempt_count"] == 0)
    return out


def _project_cache(trace: Dict[str, Any], sample: Dict[str, Any] | None, projector: Callable[..., Any], kind: str, result: Any, returned: bool) -> None:
    try:
        isolated = json.loads(json.dumps(result, ensure_ascii=False))
        raw = projector(kind, isolated, provider_returned=returned)
        row, error = (dict(raw) if isinstance(raw, Mapping) else {}), False
    except Exception:
        row, error = {}, True
    status, values = str(row.get("status") or ""), {
        "cache_read_input_tokens": row.get("cache_read_input_tokens", row.get("cache_read_tokens")),
        "cache_creation_input_tokens": row.get("cache_creation_input_tokens", row.get("cache_creation_tokens")),
    }
    if status == "observed":
        error = error or any(type(value) is not int or value < 0 for value in values.values())
    if error or status not in {"observed", "unknown"} or row.get("provider_returned") is not returned or (not returned and status == "observed"):
        status, error = "unknown", True
    projected: Dict[str, Any] = {"status": status, "provider_returned": returned, **(values if status == "observed" else {})}
    trace[f"cache_{status}_attempt_count"] += 1
    trace["cache_projection_error_count"] += int(error)
    if status == "observed":
        trace["cache_read_input_tokens_total"] += values["cache_read_input_tokens"]
        trace["cache_creation_input_tokens_total"] += values["cache_creation_input_tokens"]
    if sample: sample["cache"] = projected


def resolve_thread_continuity_fixed_prompt_plan(
    groups: List[Dict[str, Any]],
    *,
    current_ephemeral: Mapping[str, Any],
    context_window_tokens: Any,
    reserved_output_tokens: Any,
    fixed_non_message_tokens: Any,
    fixed_prompt_messages: Any,
    post_current_messages: Any = None,
    previous_state: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
    estimate_messages: Callable[[List[Dict[str, Any]]], int],
    fixed_prompt_finalizer: Callable[[Any], Any] | None = None,
    plan_fold: Callable[..., Dict[str, Any]] = plan_thread_continuity_fold,
) -> Dict[str, Any]:
    """Resolve one pure fixed-prompt/fold fixed point without provider work."""

    original_fixed_prompt_messages = fixed_prompt_messages
    resolved_fixed_prompt_messages = fixed_prompt_messages
    selected_prompt_assembly: Any = None
    fixed_prompt_selection: Any = None
    prepared_fold_plan: Dict[str, Any] | None = None
    status = "absent" if fixed_prompt_finalizer is None else "candidate"
    pass_count = 0
    if fixed_prompt_finalizer is not None:
        converged = False
        for _pass_index in range(4):
            pass_count += 1
            prepared_fold_plan = plan_fold(
                groups,
                current_ephemeral=current_ephemeral,
                context_window_tokens=context_window_tokens,
                reserved_output_tokens=reserved_output_tokens,
                fixed_non_message_tokens=fixed_non_message_tokens,
                fixed_prompt_messages=resolved_fixed_prompt_messages,
                post_current_messages=post_current_messages,
                source_complete=True,
                estimate_messages=estimate_messages,
                previous_state=previous_state,
                minimum_fold_source_group_ids=minimum_fold_source_group_ids,
                bridge_reference_at=bridge_reference_at,
                bridge_recent_horizon_hours=bridge_recent_horizon_hours,
                bridge_source_token_limit=bridge_source_token_limit,
                bridge_output_token_limit=bridge_output_token_limit,
            )
            plan_owner = _mint_thread_continuity_prompt_plan_owner(
                prepared_fold_plan
            )
            try:
                selected = _read_thread_continuity_fixed_prompt_selection(
                    fixed_prompt_finalizer(plan_owner),
                    expected_plan_owner=plan_owner,
                )
            except Exception:
                selected = {}
            if not selected:
                status = "legacy_fallback_invalid"
                resolved_fixed_prompt_messages = original_fixed_prompt_messages
                selected_prompt_assembly = None
                fixed_prompt_selection = None
                prepared_fold_plan = None
                converged = True
                break
            next_fixed_prompt_messages = selected["fixed_prompt_messages"]
            selected_prompt_assembly = selected["prompt_assembly"]
            fixed_prompt_selection = selected["selection"]
            if next_fixed_prompt_messages == resolved_fixed_prompt_messages:
                status = "selected"
                converged = True
                break
            resolved_fixed_prompt_messages = next_fixed_prompt_messages
        if not converged:
            status = "legacy_fallback_nonconvergent"
            resolved_fixed_prompt_messages = original_fixed_prompt_messages
            selected_prompt_assembly = None
            fixed_prompt_selection = None
            prepared_fold_plan = None
    if prepared_fold_plan is None:
        prepared_fold_plan = plan_fold(
            groups,
            current_ephemeral=current_ephemeral,
            context_window_tokens=context_window_tokens,
            reserved_output_tokens=reserved_output_tokens,
            fixed_non_message_tokens=fixed_non_message_tokens,
            fixed_prompt_messages=resolved_fixed_prompt_messages,
            post_current_messages=post_current_messages,
            source_complete=True,
            estimate_messages=estimate_messages,
            previous_state=previous_state,
            minimum_fold_source_group_ids=minimum_fold_source_group_ids,
            bridge_reference_at=bridge_reference_at,
            bridge_recent_horizon_hours=bridge_recent_horizon_hours,
            bridge_source_token_limit=bridge_source_token_limit,
            bridge_output_token_limit=bridge_output_token_limit,
        )
    return {
        "fold_plan": prepared_fold_plan,
        "resolved_fixed_prompt_messages": resolved_fixed_prompt_messages,
        "private_selected_prompt_assembly": selected_prompt_assembly,
        "private_fixed_prompt_selection": fixed_prompt_selection,
        "status": status,
        "pass_count": pass_count,
    }


def resolve_thread_continuity_context_epoch_plan(
    groups: List[Dict[str, Any]],
    *,
    current_ephemeral: Mapping[str, Any],
    context_window_tokens: Any,
    reserved_output_tokens: Any,
    soft_high_input_tokens: Any,
    soft_low_input_tokens: Any,
    context_epoch_policy: Any,
    fixed_prompt_messages: Any,
    estimate_messages: Callable[[List[Dict[str, Any]]], int],
    post_current_messages: Any = None,
    previous_state: Mapping[str, Any] | None = None,
    minimum_fold_source_group_ids: List[str] | None = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
    fixed_prompt_finalizer: Callable[[Any], Any] | None = None,
    plan_fold: Callable[..., Dict[str, Any]] = plan_thread_continuity_fold,
) -> Dict[str, Any]:
    """Plan one API-owned token-watermark epoch without provider work."""

    trace: Dict[str, Any] = {
        "schema": "thread_continuity_context_epoch_plan.v1",
        "status": "blocked",
        "rollover_reason": "budget_unknown",
        "context_epoch_policy": str(context_epoch_policy or ""),
        "hard_context_window_tokens": context_window_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "soft_high_input_tokens": soft_high_input_tokens,
        "soft_low_input_tokens": soft_low_input_tokens,
        "estimated_pre_input_tokens": 0,
        "estimated_target_input_tokens": 0,
        "soft_low_reached": False,
        "irreducible_input_tokens": 0,
        "eligible_retired_count": 0,
        "minimum_fold_source_group_ids": [],
        "maintenance_call_count": 0,
        "body_included": False,
    }
    if (
        context_epoch_policy != "token_watermark_v1"
        or type(context_window_tokens) is not int
        or type(reserved_output_tokens) is not int
        or type(soft_high_input_tokens) is not int
        or type(soft_low_input_tokens) is not int
        or context_window_tokens <= 0
        or reserved_output_tokens < 0
        or reserved_output_tokens >= context_window_tokens
        or not 0
        <= soft_low_input_tokens
        < soft_high_input_tokens
        <= context_window_tokens - reserved_output_tokens
    ):
        return trace

    hard_resolution = resolve_thread_continuity_fixed_prompt_plan(
        groups,
        current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=0,
        fixed_prompt_messages=fixed_prompt_messages,
        post_current_messages=post_current_messages,
        previous_state=previous_state,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        estimate_messages=estimate_messages,
        fixed_prompt_finalizer=fixed_prompt_finalizer,
        plan_fold=plan_fold,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    hard_plan = dict(hard_resolution.get("fold_plan") or {})
    pre_tokens = int(hard_plan.get("estimated_main_input_tokens") or 0)
    current_name = str(current_ephemeral.get("name") or "")
    irreducible_messages = [
        *list(hard_plan.get("base_messages") or []),
        *list(hard_plan.get("previous_continuity_messages") or []),
        {
            "role": "user",
            "content": current_ephemeral.get("content"),
            **({"name": current_name} if current_name else {}),
        },
        *list(hard_plan.get("post_current_messages") or []),
    ]
    try:
        irreducible_tokens = int(estimate_messages(irreducible_messages))
    except Exception:
        irreducible_tokens = 0
    trace.update(
        estimated_pre_input_tokens=pre_tokens,
        irreducible_input_tokens=irreducible_tokens,
        hard_plan_status=str(hard_plan.get("status") or ""),
        hard_plan_reason=str(hard_plan.get("reason") or ""),
    )
    if hard_plan.get("status") == "blocked":
        trace["rollover_reason"] = str(
            hard_plan.get("reason") or "hard_plan_blocked"
        )
        return trace
    hard_requires_fold = hard_plan.get("status") == "fold_required"
    if (
        hard_requires_fold
        and hard_plan.get("reason") == "currentness_expiry"
        and pre_tokens <= soft_high_input_tokens
    ):
        target_ids = list(
            hard_plan.get("covered_source_group_ids") or []
        )
        trace.update(
            status="rollover_required",
            rollover_reason="currentness_expiry",
            estimated_target_input_tokens=pre_tokens,
            soft_low_reached=pre_tokens <= soft_low_input_tokens,
            eligible_retired_count=int(
                hard_plan.get("currentness_expired_raw_count") or 0
            ),
            minimum_fold_source_group_ids=target_ids,
            target_plan_status="fold_required",
            target_plan_reason="currentness_expiry",
        )
        return trace
    if (
        not hard_requires_fold
        and pre_tokens <= soft_high_input_tokens
    ):
        trace.update(
            status="append_only",
            rollover_reason="below_soft_high",
            estimated_target_input_tokens=pre_tokens,
            soft_low_reached=pre_tokens <= soft_low_input_tokens,
        )
        return trace

    target_headroom = (
        context_window_tokens
        - reserved_output_tokens
        - soft_low_input_tokens
    )
    target_resolution = resolve_thread_continuity_fixed_prompt_plan(
        groups,
        current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=target_headroom,
        fixed_prompt_messages=fixed_prompt_messages,
        post_current_messages=post_current_messages,
        previous_state=previous_state,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        estimate_messages=estimate_messages,
        fixed_prompt_finalizer=fixed_prompt_finalizer,
        plan_fold=plan_fold,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    target_plan = dict(target_resolution.get("fold_plan") or {})
    covered_ids = [
        str(value or "")
        for value in list(hard_plan.get("covered_source_group_ids") or [])
    ]
    raw_suffix_ids = [
        str(value or "")
        for value in list(hard_plan.get("raw_suffix_group_ids") or [])
    ]
    all_ids = [*covered_ids, *raw_suffix_ids]
    previous_ids = thread_continuity_retirement_source_group_ids(previous_state)
    accepted_previous_ids = (
        previous_ids
        if previous_ids == all_ids[: len(previous_ids)]
        else []
    )
    eligible_ids = all_ids[len(accepted_previous_ids):]
    if target_plan.get("status") != "fold_required":
        hard_safe_plan = hard_plan
        if eligible_ids:
            hard_safe_resolution = resolve_thread_continuity_fixed_prompt_plan(
                groups,
                current_ephemeral=current_ephemeral,
                context_window_tokens=context_window_tokens,
                reserved_output_tokens=reserved_output_tokens,
                fixed_non_message_tokens=0,
                fixed_prompt_messages=fixed_prompt_messages,
                post_current_messages=post_current_messages,
                previous_state=previous_state,
                minimum_fold_source_group_ids=all_ids,
                estimate_messages=estimate_messages,
                fixed_prompt_finalizer=fixed_prompt_finalizer,
                plan_fold=plan_fold,
                bridge_reference_at=bridge_reference_at,
                bridge_recent_horizon_hours=bridge_recent_horizon_hours,
                bridge_source_token_limit=bridge_source_token_limit,
                bridge_output_token_limit=bridge_output_token_limit,
            )
            candidate = dict(hard_safe_resolution.get("fold_plan") or {})
            if candidate.get("status") == "fold_required":
                hard_safe_plan = candidate
        hard_safe_target_ids = list(
            hard_safe_plan.get("covered_source_group_ids") or []
        )
        hard_safe_target_id_set = set(hard_safe_target_ids)
        hard_safe_retired_count = sum(
            source_id in hard_safe_target_id_set
            for source_id in eligible_ids
        )
        hard_safe_requires_rollover = (
            hard_safe_plan.get("status") == "fold_required"
        )
        trace.update(
            status=(
                "rollover_required"
                if hard_safe_requires_rollover
                else "append_only"
            ),
            rollover_reason="hard_safe_above_soft_low",
            estimated_target_input_tokens=irreducible_tokens,
            soft_low_reached=False,
            eligible_retired_count=hard_safe_retired_count,
            minimum_fold_source_group_ids=(
                hard_safe_target_ids if hard_safe_requires_rollover else []
            ),
            target_plan_status=str(target_plan.get("status") or ""),
            target_plan_reason=str(target_plan.get("reason") or ""),
        )
        return trace
    target_ids = list(target_plan.get("covered_source_group_ids") or [])
    target_id_set = set(target_ids)
    trace.update(
        status="rollover_required",
        rollover_reason=(
            "hard_ceiling_pressure"
            if hard_requires_fold
            else "soft_high_exceeded"
        ),
        estimated_target_input_tokens=soft_low_input_tokens,
        soft_low_reached=True,
        eligible_retired_count=sum(
            source_id in target_id_set for source_id in eligible_ids
        ),
        minimum_fold_source_group_ids=target_ids,
        target_plan_status="fold_required",
        target_plan_reason=str(target_plan.get("reason") or ""),
    )
    return trace


async def compile_thread_continuity_turn(
    bundle: Mapping[str, Any], *, current_ephemeral: Mapping[str, Any],
    fixed_prompt_messages: Any, context_window_tokens: Any, reserved_output_tokens: Any,
    fixed_non_message_tokens: Any, estimate_messages: Callable[[List[Dict[str, Any]]], int],
    summary_call: Callable[[Mapping[str, Any], List[Dict[str, Any]]], Any],
    project_provider_attempt: Callable[..., Any],
    physical_owner_generation: object,
    post_current_messages: Any = None,
    minimum_fold_source_group_ids: Any = None,
    fixed_prompt_finalizer: Callable[[Any], Any] | None = None,
    bridge_reference_at: Any = None,
    bridge_recent_horizon_hours: Any = 72,
    bridge_source_token_limit: Any = 24_000,
    bridge_output_token_limit: Any = 2_048,
) -> Dict[str, Any]:
    trace: Dict[str, Any] = {
        **{key: 0 for key in (
            "summary_call_count", "summary_attempt_count", "chunk_attempt_count",
            "provider_returned_count", "accepted_receipt_count", "accepted_summary_receipt_count",
            "accepted_chunk_receipt_count", "replan_count", "source_group_count",
            "cache_observed_attempt_count", "cache_unknown_attempt_count", "cache_projection_error_count",
            "cache_read_input_tokens_total", "cache_creation_input_tokens_total",
        )},
        "schema": "thread_continuity_compilation_trace.v1", "body_included": False,
        "summary_construction_token_limit": min(
            context_window_tokens,
            SUMMARY_CONSTRUCTION_TOKEN_LIMIT,
        ) if type(context_window_tokens) is int and context_window_tokens > 0 else 0,
        "attempt_samples": [], "attempt_sample_truncated": False,
        "plan_generations": [], "seen_descriptor_ids": set(),
        "fixed_prompt_finalizer_status": (
            "candidate" if fixed_prompt_finalizer is not None else "absent"
        ),
        "fixed_prompt_finalizer_pass_count": 0,
    }
    source_row = bundle.get("source") if isinstance(bundle, Mapping) else None
    continuity_row = bundle.get("continuity") if isinstance(bundle, Mapping) else None
    source = dict(source_row) if isinstance(source_row, Mapping) else {}
    continuity = dict(continuity_row) if isinstance(continuity_row, Mapping) else {}
    snapshot = str(source.get("source_snapshot") or "")
    revision = 0
    trace.update(
        source_status=source.get("status"), source_scan_complete=source.get("scan_complete"),
        source_snapshot=snapshot,
        source_group_count=len(source.get("groups") or []) if isinstance(source.get("groups"), list) else 0,
        continuity_status=continuity.get("status"), continuity_revision=0, continuity_revision_id="",
    )

    def fail(reason: str) -> Dict[str, Any]:
        if trace["plan_generations"]:
            trace["plan_generations"][-1].update(final_disposition="fallback", failure_reason=reason)
        return _result(_public_trace(trace), "fallback", reason=reason, revision=revision, snapshot=snapshot)

    if (
        source.get("status") != "ready"
        or source.get("scan_complete") is not True
        or not isinstance(source.get("stats"), Mapping)
        or source["stats"].get("full_prefix") is not True
        or not snapshot
        or not isinstance(source.get("groups"), list)
    ):
        return fail("source_unavailable")
    groups = list(source["groups"])
    continuity_status = str(continuity.get("status") or "")
    previous: Mapping[str, Any] | None = None
    if continuity_status == "ready":
        state = continuity.get("state") if isinstance(continuity.get("state"), Mapping) else {}
        previous = state.get("checkpoint") if isinstance(state.get("checkpoint"), Mapping) else None
        if previous is None or type(state.get("revision")) is not int or state["revision"] < 1:
            return fail("continuity_state_unavailable")
        revision = state["revision"]
    elif continuity_status != "absent":
        return fail("continuity_state_unavailable")
    trace.update(
        continuity_revision=revision,
        continuity_revision_id=str(dict(previous or {}).get("revision_id") or ""),
    )
    current_row = current_ephemeral if isinstance(current_ephemeral, Mapping) else {}
    current_id = str(current_row.get("message_id") or "")
    if not current_id:
        return fail("current_identity_invalid")
    canonical_ids = [str(group.get("source_prefix_id") or "") for group in groups]
    requested_minimum = [
        str(value or "") for value in list(minimum_fold_source_group_ids or [])
    ]
    if requested_minimum != canonical_ids[: len(requested_minimum)]:
        return fail("minimum_fold_prefix_invalid")
    previous_covered = thread_continuity_retirement_source_group_ids(previous)
    minimum_fold_ids = canonical_ids[
        : max(len(requested_minimum), len(previous_covered))
    ]

    fixed_resolution = resolve_thread_continuity_fixed_prompt_plan(
        groups,
        current_ephemeral=current_ephemeral,
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=fixed_non_message_tokens,
        fixed_prompt_messages=fixed_prompt_messages,
        post_current_messages=post_current_messages,
        previous_state=previous,
        minimum_fold_source_group_ids=minimum_fold_ids,
        estimate_messages=estimate_messages,
        fixed_prompt_finalizer=fixed_prompt_finalizer,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    prepared_fold_plan = dict(fixed_resolution["fold_plan"])
    resolved_fixed_prompt_messages = fixed_resolution[
        "resolved_fixed_prompt_messages"
    ]
    selected_prompt_assembly = fixed_resolution[
        "private_selected_prompt_assembly"
    ]
    fixed_prompt_selection = fixed_resolution["private_fixed_prompt_selection"]
    trace["fixed_prompt_finalizer_status"] = fixed_resolution["status"]
    trace["fixed_prompt_finalizer_pass_count"] = fixed_resolution["pass_count"]

    owner = {
        "current_ephemeral": current_ephemeral,
        "context_window_tokens": context_window_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "fixed_non_message_tokens": fixed_non_message_tokens,
        "fixed_prompt_messages": resolved_fixed_prompt_messages,
        "post_current_messages": post_current_messages,
        "source_complete": True,
        "estimate_messages": estimate_messages,
        "previous_state": previous,
        "minimum_fold_source_group_ids": minimum_fold_ids,
        "bridge_reference_at": bridge_reference_at,
        "bridge_recent_horizon_hours": bridge_recent_horizon_hours,
        "bridge_source_token_limit": bridge_source_token_limit,
        "bridge_output_token_limit": bridge_output_token_limit,
    }
    for generation in (1,):
        fold_plan = prepared_fold_plan or plan_thread_continuity_fold(groups, **owner)
        target_ids = [str(value or "") for value in list(fold_plan.get("covered_source_group_ids") or [])]
        generation_trace = {
            "generation": generation, "fold_plan_id": str(fold_plan.get("fold_plan_id") or ""),
            "mode": str(fold_plan.get("continuity_mode") or "raw"),
            "target": _ids_trace(target_ids), "accepted_receipt_count": 0,
            "discarded_on_replan": False, "final_disposition": "planning",
        }
        trace["plan_generations"].append(generation_trace)
        if fold_plan.get("status") == "no_fold":
            physical = validate_thread_continuity_input(
                fold_plan, None, fixed_non_message_tokens=fixed_non_message_tokens,
                estimate_messages=estimate_messages,
                physical_owner_generation=physical_owner_generation,
            )
            if physical.get("status") != "ready":
                return fail("final_input_invalid")
            generation_trace["final_disposition"] = "ready"
            previous_bridge = thread_continuity_bridge_projection(previous)
            trace.update(
                final_retired=_ids_trace(target_ids),
                final_bridge_represented=_ids_trace(
                    list(previous_bridge["represented_source_group_ids"])
                ),
                final_raw_suffix=_ids_trace(list(fold_plan.get("raw_suffix_group_ids") or [])),
                checkpoint_bridge_status=previous_bridge["status"] if previous else "absent",
                checkpoint_bridge_body_sha256=previous_bridge["body_sha256"] if previous else "",
            )
            return _result(
                _public_trace(trace), "ready", reason="", mode="raw",
                messages=list(physical["provider_messages"]),
                physical_owner_sidecar=physical["physical_owner_sidecar"],
                selected_prompt_assembly=selected_prompt_assembly,
                fixed_prompt_selection=fixed_prompt_selection,
                revision=revision, snapshot=snapshot,
            )
        if fold_plan.get("status") not in {"fold_required", "blocked"} or not fold_plan.get("fold_plan_id"):
            return fail(str(fold_plan.get("reason") or "fold_plan_invalid"))

        attempt_owner = {
            "fold_plan": fold_plan,
            "current_ephemeral": current_ephemeral,
            "context_window_tokens": context_window_tokens,
            "reserved_output_tokens": reserved_output_tokens,
            "fixed_non_message_tokens": fixed_non_message_tokens,
            "fixed_prompt_messages": resolved_fixed_prompt_messages,
            "post_current_messages": post_current_messages,
            "source_complete": True,
            "estimate_messages": estimate_messages,
            "previous_checkpoint": previous,
            "minimum_fold_source_group_ids": minimum_fold_ids,
            "bridge_reference_at": bridge_reference_at,
            "bridge_recent_horizon_hours": bridge_recent_horizon_hours,
            "bridge_source_token_limit": bridge_source_token_limit,
            "bridge_output_token_limit": bridge_output_token_limit,
        }
        accepted: List[Mapping[str, Any]] = []
        chunk_completions: List[List[Mapping[str, Any]]] = []
        while True:
            planned = plan_next_summary_attempt(
                groups, accepted_attempts=accepted,
                accepted_chunk_completions=chunk_completions, **attempt_owner,
            )
            if planned.get("status") == "ready":
                descriptor = dict(planned.get("descriptor") or {})
                sample = _note_call(trace, "summary", generation, descriptor)
                if sample is None:
                    return fail("summary_descriptor_repeated")
                try:
                    provider_result = await summary_call(
                        {
                            "kind": "summary", "descriptor_id": descriptor["descriptor_id"],
                            "plan_generation": generation,
                            "max_output_tokens": descriptor["summary_output_token_limit"],
                        },
                        list(planned["provider_messages"]),
                    )
                except Exception:
                    _project_cache(trace, sample, project_provider_attempt, "summary", None, False)
                    return fail("summary_call_failed")
                _project_cache(trace, sample, project_provider_attempt, "summary", provider_result, True)
                try:
                    accepted_result = accept_summary_attempt(
                        descriptor, provider_result, groups=groups,
                        accepted_attempts=accepted, accepted_chunk_completions=chunk_completions,
                        **attempt_owner,
                    )
                except (TypeError, ValueError): accepted_result = {"status": "rejected"}
                _note_result(trace, sample, "summary", descriptor, accepted_result)
                if accepted_result.get("status") != "accepted" or int(accepted_result.get("progress_source_group_count") or 0) < 1:
                    return fail(str(accepted_result.get("reason") or "summary_result_invalid"))
                generation_trace["accepted_receipt_count"] += 1
                accepted.append({
                    "descriptor": descriptor, "provider_result": provider_result,
                    "receipt": accepted_result["receipt"],
                })
                continue
            if planned.get("status") == "blocked" and planned.get("reason") == "chunk_required":
                chunk_attempts: List[Mapping[str, Any]] = []
                while True:
                    chunk = plan_next_summary_chunk_attempt(
                        groups=groups, accepted_summary_attempts=accepted,
                        accepted_chunk_completions=chunk_completions,
                        accepted_chunk_attempts=chunk_attempts, **attempt_owner,
                    )
                    if chunk.get("status") == "complete":
                        chunk_completions.append(chunk_attempts)
                        break
                    if chunk.get("status") != "ready":
                        return fail(str(chunk.get("reason") or "chunk_plan_invalid"))
                    descriptor = dict(chunk.get("descriptor") or {})
                    sample = _note_call(trace, "chunk", generation, descriptor)
                    if sample is None:
                        return fail("chunk_descriptor_repeated")
                    try:
                        provider_result = await summary_call(
                            {
                                "kind": "chunk", "descriptor_id": descriptor["descriptor_id"],
                                "plan_generation": generation,
                                "max_output_tokens": fold_plan["summary_output_token_limit"],
                            },
                            list(chunk["provider_messages"]),
                        )
                    except Exception:
                        _project_cache(trace, sample, project_provider_attempt, "chunk", None, False)
                        return fail("summary_call_failed")
                    _project_cache(trace, sample, project_provider_attempt, "chunk", provider_result, True)
                    try:
                        accepted_chunk = accept_summary_chunk_attempt(
                            descriptor, provider_result,
                            groups=groups, accepted_summary_attempts=accepted,
                            accepted_chunk_completions=chunk_completions,
                            accepted_chunk_attempts=chunk_attempts, **attempt_owner,
                        )
                    except (TypeError, ValueError): accepted_chunk = {"status": "rejected"}
                    _note_result(trace, sample, "chunk", descriptor, accepted_chunk)
                    if accepted_chunk.get("status") != "accepted":
                        return fail(str(accepted_chunk.get("reason") or "chunk_result_invalid"))
                    generation_trace["accepted_receipt_count"] += 1
                    chunk_attempts.append({
                        "descriptor": descriptor, "provider_result": provider_result,
                        "receipt": accepted_chunk["receipt"],
                    })
                continue
            if planned.get("status") != "complete":
                return fail(str(planned.get("reason") or "summary_incomplete"))
            try:
                checkpoint = build_thread_continuity_checkpoint_from_attempts(
                    source_groups=groups, accepted_summary_attempts=accepted,
                    accepted_chunk_completions=chunk_completions, **attempt_owner,
                )
                segment = render_thread_continuity_checkpoint_message(
                    checkpoint, source_groups=groups, previous_state=previous,
                )
            except (TypeError, ValueError):
                return fail("checkpoint_invalid")
            physical = validate_thread_continuity_input(
                fold_plan, segment or None, fixed_non_message_tokens=fixed_non_message_tokens,
                estimate_messages=estimate_messages,
                physical_owner_generation=physical_owner_generation,
            )
            if physical.get("status") == "ready":
                retired = thread_continuity_retirement_source_group_ids(checkpoint)
                bridge = thread_continuity_bridge_projection(checkpoint)
                generation_trace["final_disposition"] = "ready"
                trace.update(
                    final_retired=_ids_trace(retired),
                    final_bridge_represented=_ids_trace(
                        list(bridge["represented_source_group_ids"])
                    ),
                    final_raw_suffix=_ids_trace(list(fold_plan.get("raw_suffix_group_ids") or [])),
                    checkpoint_revision_id=checkpoint.get("revision_id"),
                    checkpoint_bridge_status=bridge["status"],
                    checkpoint_bridge_body_sha256=bridge["body_sha256"],
                )
                return _result(
                    _public_trace(trace), "ready", reason="", mode="compacted",
                    messages=list(physical["provider_messages"]), checkpoint=checkpoint,
                    physical_owner_sidecar=physical["physical_owner_sidecar"],
                    selected_prompt_assembly=selected_prompt_assembly,
                    fixed_prompt_selection=fixed_prompt_selection,
                    revision=revision, snapshot=snapshot,
                )
            return fail(
                "frozen_plan_input_overflow"
                if physical.get("status") == "replan_required"
                else str(physical.get("reason") or "final_input_invalid")
            )
