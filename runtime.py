"""Hermes request-only runtime for the extracted continuity bridge.

Hermes keeps ownership of its transcript and native context compression.  This
module only compiles a bounded bridge from canonical SessionDB rows, projects
that bridge into the current provider request, and publishes a checkpoint after
the projected request has actually reached a provider successfully.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from hermes_cli.request_overlay import (
    OVERLAY_KEPT,
    RequestOverlay,
    canonical_request_sha256,
    last_real_user_index,
    project_request_overlay,
    request_messages,
)

from .context_compactor import thread_continuity_bridge_projection
from .thread_continuity_runtime import compile_thread_continuity_turn


_request_sha256 = canonical_request_sha256
CONTINUITY_MARKER_NAMESPACE = "[THREAD CONTINUITY QUOTED REFERENCE"
CONTINUITY_END_BOUNDARY = "[END THREAD CONTINUITY QUOTED REFERENCE]"
CONTINUITY_MARKER = CONTINUITY_MARKER_NAMESPACE + " marker=continuity_static]"
_SUMMARY_PREFIXES = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]",
    "[CONTEXT SUMMARY]:",
    "[CONTEXT COMPACTION]",
)
_TRANSPORT_SCHEMA_VERSION = "hermes.transport.v3"
_SUMMARY_END_PREFIX = "[END THREAD CONTINUITY SUMMARY "
_TRUSTED_CONTEXT_CONFIDENCE = frozenset({"authoritative", "catalog", "cached"})
_LOWER_CONFIDENCE_CONTEXT_MARGIN = 0.90


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    attachments = 0
    for item in value:
        if not isinstance(item, Mapping):
            return ""
        kind = str(item.get("type") or "")
        if kind in {"text", "input_text"} or (
            not kind and set(item) == {"text"}
        ):
            text = item.get("text")
            if not isinstance(text, str):
                return ""
            if text.strip():
                parts.append(text.strip())
        elif kind in {
            "image",
            "image_url",
            "input_image",
            "document",
            "input_file",
        } or (not kind and ({"image", "document"} & set(item))):
            attachments += 1
        elif kind in {"tool_result", "tool_use"} or "toolResult" in item:
            continue
        else:
            return ""
    if attachments:
        parts.append(f"[attachment x{attachments}]")
    return "\n".join(parts).strip()


def _attachment_payload(item: Mapping[str, Any], kind: str) -> Any:
    """Extract provider-neutral attachment content, not wrapper syntax."""

    candidates = (
        ("image_url", "image", "source", "data")
        if kind == "image"
        else (
            "file_data",
            "file_id",
            "document",
            "source",
            "data",
        )
    )
    payload: Any = None
    found = False
    for key in candidates:
        if key in item:
            payload = item[key]
            found = True
            break
    if not found:
        return None
    while isinstance(payload, Mapping):
        for key in ("url", "bytes", "file_data", "file_id", "source", "data"):
            if key in payload:
                payload = payload[key]
                break
        else:
            break
    return payload


def _attachment_identity(item: Mapping[str, Any]) -> dict[str, str] | None:
    block_type = str(item.get("type") or "").strip().lower()
    if block_type in {"image", "image_url", "input_image"} or (
        not block_type and "image" in item
    ):
        kind = "image"
    elif block_type == "input_file":
        kind = "file"
    elif block_type == "document" or (not block_type and "document" in item):
        kind = "document"
    else:
        return None
    payload = _attachment_payload(item, kind)
    if payload is None:
        return None
    try:
        digest = canonical_request_sha256({"content": payload})
    except (TypeError, ValueError):
        return None
    return {"kind": kind, "content_sha256": digest}


def _current_identity_content(value: Any) -> Any:
    """Normalize equivalent provider carriers while binding attachment data."""

    if isinstance(value, str):
        return [{"kind": "text", "text": value.strip()}]
    if not isinstance(value, list):
        return {"kind": "invalid", "value": value}
    normalized: list[Any] = []
    for item in value:
        if not isinstance(item, Mapping):
            normalized.append({"kind": "invalid", "value": item})
            continue
        kind = str(item.get("type") or "")
        if kind in {"text", "input_text"} or (
            not kind and set(item) == {"text"}
        ):
            text = item.get("text")
            normalized.append(
                {"kind": "text", "text": text.strip()}
                if isinstance(text, str)
                else {"kind": "invalid", "value": dict(item)}
            )
        else:
            attachment = _attachment_identity(item)
            normalized.append(
                attachment
                if attachment is not None
                else {"kind": "payload", "value": dict(item)}
            )
    return normalized


def _current_message_sha256(message: Mapping[str, Any]) -> str:
    try:
        return canonical_request_sha256(
            {
                "role": "user",
                "content": _current_identity_content(message.get("content")),
            }
        )
    except (TypeError, ValueError):
        return ""


def _text_anchor_present(candidate: str, anchor: str) -> bool:
    return bool(
        candidate == anchor
        or candidate.startswith(anchor + "\n")
        or candidate.endswith("\n" + anchor)
        or f"\n{anchor}\n" in candidate
    )


def _identity_anchor_present(candidate: Any, anchor: Any) -> bool:
    if candidate == anchor:
        return True
    if not isinstance(candidate, list) or not isinstance(anchor, list) or not anchor:
        return False
    for start in range(0, len(candidate) - len(anchor) + 1):
        window = candidate[start : start + len(anchor)]
        if window == anchor:
            return True
        if len(window) == len(anchor) == 1:
            candidate_part = window[0]
            anchor_part = anchor[0]
            if (
                isinstance(candidate_part, Mapping)
                and isinstance(anchor_part, Mapping)
                and candidate_part.get("kind") == "text"
                and anchor_part.get("kind") == "text"
                and isinstance(candidate_part.get("text"), str)
                and isinstance(anchor_part.get("text"), str)
                and _text_anchor_present(
                    candidate_part["text"], anchor_part["text"]
                )
            ):
                return True
    return False


def _request_has_user_anchor(
    request: Mapping[str, Any],
    anchor_sha256: str,
    anchor_identity: Any = None,
) -> bool:
    shape = request_messages(request)
    if not anchor_sha256 or shape is None:
        return False
    for message in shape[1]:
        if (
            not isinstance(message, Mapping)
            or str(message.get("role") or "").strip().lower() != "user"
            or not _text(message.get("content"))
        ):
            continue
        if _current_message_sha256(message) == anchor_sha256:
            return True
        if anchor_identity is not None and _identity_anchor_present(
            _current_identity_content(message.get("content")),
            anchor_identity,
        ):
            return True
    return False


def _is_native_compaction_message(message: Mapping[str, Any]) -> bool:
    text = _text(message.get("content")).lstrip()
    return any(text.startswith(prefix) for prefix in _SUMMARY_PREFIXES)


def _safe_fixed_prompt(request: Mapping[str, Any], messages: list[Any]) -> list[dict[str, Any]]:
    """Extract prompt bytes for donor budgeting without changing the request."""

    leading: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            raise ValueError("request_message_invalid")
        role = str(message.get("role") or "").strip().lower()
        if role not in {"system", "developer"}:
            break
        if _is_native_compaction_message(message):
            continue
        content = message.get("content")
        if not _text(content):
            raise ValueError("fixed_prompt_invalid")
        leading.append({"role": role, "content": content})

    top_values = [
        value
        for value in (request.get("system"), request.get("instructions"))
        if value is not None and value != ""
    ]
    if len(top_values) > 1 and _text(top_values[0]) != _text(top_values[1]):
        raise ValueError("fixed_prompt_ambiguous")
    if top_values:
        top_text = _text(top_values[0])
        if not top_text:
            raise ValueError("fixed_prompt_invalid")
        leading_text = [_text(row["content"]) for row in leading]
        if leading_text and top_text not in leading_text:
            raise ValueError("fixed_prompt_ambiguous")
        if not leading_text:
            leading.append({"role": "system", "content": top_text})
    return leading


def _fixed_non_message_tokens(
    request: Mapping[str, Any],
    messages: list[Any],
    current_index: int,
) -> int:
    """Conservatively charge provider-only fields and unowned message bytes."""

    shadow = {
        key: value
        for key, value in request.items()
        if key not in {"messages", "input", "system", "instructions"}
    }
    shadow["provider_owned_message_bytes"] = [
        message
        for index, message in enumerate(messages)
        if index > current_index
        or (
            isinstance(message, Mapping)
            and _is_native_compaction_message(message)
        )
    ]
    return (len(_json_bytes(shadow)) + 3) // 4


def _reserved_output_tokens(request: Mapping[str, Any], window: int) -> int:
    for key in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
        value = request.get(key)
        if type(value) is int and 0 < value < window:
            return value
    return min(4096, max(1, window // 8))


def _default_estimator(messages: list[dict[str, Any]]) -> int:
    from agent.model_metadata import estimate_messages_tokens_rough

    return int(estimate_messages_tokens_rough(messages))


def _usable_context_window(
    tokens: Any,
    source: Any,
    confidence: Any,
) -> int | None:
    """Accept only host-resolved windows with explicit non-fallback provenance."""

    if type(tokens) is not int or tokens <= 0:
        return None
    source_value = str(source or "").strip().lower()
    confidence_value = str(confidence or "").strip().lower()
    if (
        not source_value
        or source_value in {"unknown", "fallback", "fallback_unknown"}
        or confidence_value not in _TRUSTED_CONTEXT_CONFIDENCE
    ):
        return None
    if confidence_value == "authoritative":
        return tokens
    return max(1, int(tokens * _LOWER_CONFIDENCE_CONTEXT_MARGIN))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _TurnPlan:
    current_sha256: str
    current_identity: Any = None
    marker: str = ""
    bridge_body: str = ""
    checkpoint_candidate: dict[str, Any] | None = None
    expected_revision: int = 0
    expected_source_snapshot: str = ""
    source_ids: tuple[str, ...] = ()
    reason: str = ""
    context_window_tokens: int = 0
    usable_context_window_tokens: int = 0
    context_window_source: str = "unknown"
    context_window_confidence: str = "unknown"
    reserved_output_tokens: int = 0
    provider_key: tuple[str, str, str] = ("", "", "")
    publish_status: str = ""


@dataclass
class _Projection:
    turn_key: tuple[str, str]
    attempt_seq: int
    overlay: RequestOverlay | None
    provider_key: tuple[str, str, str] = ("", "", "")
    request_model_sha256: str = ""
    context_window_tokens: int = 0
    usable_context_window_tokens: int = 0
    context_window_source: str = "unknown"
    context_window_confidence: str = "unknown"
    reserved_output_tokens: int = 0
    last_touch: float = 0.0


@dataclass
class _TransportStage:
    turn_key: tuple[str, str]
    attempt_seq: int
    request_sha256: str
    transport_record: Any = field(repr=False, compare=False)
    last_touch: float = 0.0


class ContinuityRuntime:
    """Compile once per turn, project per request, settle per physical success."""

    def __init__(
        self,
        adapter: Any,
        plugin_llm: Any,
        *,
        compiler: Callable[..., Any] = compile_thread_continuity_turn,
        projector: Callable[..., RequestOverlay] = project_request_overlay,
        estimator: Callable[[list[dict[str, Any]]], int] | None = None,
        clock: Callable[[], str] | None = None,
        marker: str = CONTINUITY_MARKER,
        recent_horizon_hours: int = 72,
        source_token_limit: int = 24_000,
        output_token_limit: int = 2_048,
        max_projection_chars: int = 24_000,
        max_cached_turns: int = 128,
        attempt_ttl_seconds: float = 600.0,
        summary_timeout_seconds: float = 120.0,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.adapter = adapter
        self.plugin_llm = plugin_llm
        self.compiler = compiler
        self.projector = projector
        self.estimator = estimator or _default_estimator
        self.clock = clock or _utc_now
        self.marker = str(marker)
        self.recent_horizon_hours = int(recent_horizon_hours)
        self.source_token_limit = int(source_token_limit)
        self.output_token_limit = int(output_token_limit)
        self.max_projection_chars = int(max_projection_chars)
        self.max_cached_turns = max(1, int(max_cached_turns))
        self.attempt_ttl_seconds = max(1.0, float(attempt_ttl_seconds))
        self.summary_timeout_seconds = float(summary_timeout_seconds)
        self.monotonic = monotonic or time.monotonic
        self._lock = threading.RLock()
        self._publish_condition = threading.Condition(self._lock)
        self._turns: "OrderedDict[tuple[str, str], _TurnPlan]" = OrderedDict()
        self._compiling: set[tuple[str, str]] = set()
        self._projections: dict[tuple[str, str, str], _Projection] = {}
        self._transport: dict[tuple[str, str, str], _TransportStage] = {}
        self._executing: set[tuple[str, str, str]] = set()
        self._attempt_seq = 0

    def _trim_locked(
        self,
        *,
        protected_turns: tuple[tuple[str, str], ...] = (),
    ) -> bool:
        self._sweep_expired_locked()
        while len(self._turns) > self.max_cached_turns:
            active = {
                value.turn_key
                for value in (*self._projections.values(), *self._transport.values())
            }
            expired = next(
                (
                    turn_key
                    for turn_key in self._turns
                    if turn_key not in active and turn_key not in protected_turns
                ),
                None,
            )
            if expired is None:
                return False
            self._turns.pop(expired, None)
            self._projections = {
                key: value
                for key, value in self._projections.items()
                if value.turn_key != expired
            }
            self._transport = {
                key: value
                for key, value in self._transport.items()
                if value.turn_key != expired
            }
        return True

    def _sweep_expired_locked(self) -> None:
        cutoff = self.monotonic() - self.attempt_ttl_seconds
        expired = {
            key
            for key, value in self._projections.items()
            if value.last_touch <= cutoff and key not in self._executing
        } | {
            key
            for key, value in self._transport.items()
            if value.last_touch <= cutoff and key not in self._executing
        }
        for key in expired:
            self._projections.pop(key, None)
            self._transport.pop(key, None)

    def _attempt_capacity_available_locked(
        self,
        attempt_key: tuple[str, str, str],
    ) -> bool:
        self._sweep_expired_locked()
        return bool(
            attempt_key in self._projections
            or len(self._projections) < self.max_cached_turns
        )

    @staticmethod
    def _old_checkpoint(bundle: Mapping[str, Any]) -> Mapping[str, Any] | None:
        continuity = bundle.get("continuity")
        if not isinstance(continuity, Mapping) or continuity.get("status") != "ready":
            return None
        state = continuity.get("state")
        checkpoint = state.get("checkpoint") if isinstance(state, Mapping) else None
        return checkpoint if isinstance(checkpoint, Mapping) else None

    async def _summary_call(
        self,
        descriptor: Mapping[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.plugin_llm is None or not callable(
            getattr(self.plugin_llm, "acomplete", None)
        ):
            raise RuntimeError("plugin_llm_unavailable")
        marker = (
            f"{_SUMMARY_END_PREFIX}"
            f"{canonical_request_sha256({'descriptor': dict(descriptor), 'messages': messages})}]"
        )
        summary_messages = copy.deepcopy(messages)
        terminal_instruction = (
            "End the response with this exact completion marker, exactly once, "
            "as the final non-whitespace text. Do not quote or explain it:\n"
            + marker
        )
        for index in range(len(summary_messages) - 1, -1, -1):
            row = summary_messages[index]
            if row.get("role") == "user" and isinstance(row.get("content"), str):
                row["content"] = row["content"].rstrip() + "\n\n" + terminal_instruction
                break
        else:
            summary_messages.append({"role": "user", "content": terminal_instruction})
        result = await self.plugin_llm.acomplete(
            summary_messages,
            max_tokens=int(descriptor.get("max_output_tokens") or 0),
            timeout=self.summary_timeout_seconds,
            purpose="thread_continuity_summary",
        )
        finish_reason = getattr(result, "finish_reason", None)
        raw_text = str(getattr(result, "text", "") or "")
        normalized = str(finish_reason or "").strip().replace("-", "_").lower()
        marker_complete = bool(
            raw_text.rstrip().endswith(marker) and raw_text.count(marker) == 1
        )
        content = raw_text.rstrip()
        if marker_complete:
            content = content[: -len(marker)].rstrip()
        completed = bool(normalized == "stop" and marker_complete and content)
        row: dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "content": content,
            "finish_reason": finish_reason,
        }
        if not completed:
            row["status"] = "incomplete"
        usage = getattr(result, "usage", None)
        if usage is not None:
            row["usage"] = {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
                "cache_read_input_tokens": int(
                    getattr(usage, "cache_read_tokens", 0) or 0
                ),
                "cache_creation_input_tokens": int(
                    getattr(usage, "cache_write_tokens", 0) or 0
                ),
            }
        return row

    @staticmethod
    def _project_cache(
        _kind: str,
        result: Any,
        *,
        provider_returned: bool,
    ) -> dict[str, Any]:
        usage = result.get("usage") if isinstance(result, Mapping) else None
        if not provider_returned or not isinstance(usage, Mapping):
            return {"status": "unknown", "provider_returned": provider_returned}
        return {
            "status": "observed",
            "provider_returned": True,
            "cache_read_input_tokens": int(
                usage.get("cache_read_input_tokens") or 0
            ),
            "cache_creation_input_tokens": int(
                usage.get("cache_creation_input_tokens") or 0
            ),
        }

    def _compile_plan(
        self,
        request: Mapping[str, Any],
        *,
        session_id: str,
        turn_id: str,
        model: str,
        provider: str,
        base_url: str,
        context_window_tokens: Any,
        context_window_source: Any,
        context_window_confidence: Any,
    ) -> _TurnPlan:
        shape = request_messages(request)
        if shape is None:
            return _TurnPlan("", reason="request_carrier_ambiguous")
        _request_key, messages = shape
        current_index = last_real_user_index(messages)
        if current_index < 0:
            return _TurnPlan("", reason="real_user_carrier_missing")
        # A first sighting during a tool continuation has provider-owned tail
        # that the extracted donor does not understand. A plan prepared on the
        # first API request is safely reusable for later tool calls.
        if current_index != len(messages) - 1:
            return _TurnPlan("", reason="first_request_has_provider_tail")
        current_message = messages[current_index]
        if not isinstance(current_message, Mapping):
            return _TurnPlan("", reason="current_message_invalid")
        current_text = _text(current_message.get("content"))
        if not current_text:
            return _TurnPlan("", reason="current_content_invalid")
        current_sha = _current_message_sha256(current_message)
        if not current_sha:
            return _TurnPlan("", reason="current_identity_invalid")
        usable_window = _usable_context_window(
            context_window_tokens,
            context_window_source,
            context_window_confidence,
        )
        if usable_window is None:
            return _TurnPlan(current_sha, reason="context_window_untrusted")
        window = int(context_window_tokens)
        source_label = str(context_window_source or "unknown")
        confidence_label = str(context_window_confidence or "unknown")
        try:
            fixed_prompt = _safe_fixed_prompt(request, messages)
            fixed_tokens = _fixed_non_message_tokens(
                request, messages, current_index
            )
            reserve = _reserved_output_tokens(request, usable_window)
            bundle = self.adapter.read_bundle(session_id)
            source = bundle.get("source") if isinstance(bundle, Mapping) else None
            if not isinstance(source, Mapping):
                raise ValueError("source_unavailable")
            compacted_ids = list(
                dict(source.get("stats") or {}).get(
                    "compacted_prefix_group_ids"
                )
                or []
            )
        except Exception as exc:
            return _TurnPlan(current_sha, reason=str(exc) or "compile_input_invalid")

        async def drive() -> dict[str, Any]:
            result = self.compiler(
                bundle,
                current_ephemeral={
                    "role": "user",
                    "message_id": "hcu_" + _sha256(
                        [session_id, turn_id, current_sha]
                    ),
                    "content": current_text,
                },
                fixed_prompt_messages=fixed_prompt,
                context_window_tokens=usable_window,
                reserved_output_tokens=reserve,
                fixed_non_message_tokens=fixed_tokens,
                estimate_messages=self.estimator,
                summary_call=self._summary_call,
                project_provider_attempt=self._project_cache,
                physical_owner_generation=object(),
                post_current_messages=[],
                minimum_fold_source_group_ids=compacted_ids,
                bridge_reference_at=self.clock(),
                bridge_recent_horizon_hours=self.recent_horizon_hours,
                bridge_source_token_limit=self.source_token_limit,
                bridge_output_token_limit=self.output_token_limit,
            )
            if inspect.isawaitable(result):
                result = await result
            return dict(result or {})

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                compiled = asyncio.run(drive())
            except Exception:
                return _TurnPlan(current_sha, reason="continuity_compile_failed")
        else:
            return _TurnPlan(current_sha, reason="async_middleware_unsupported")

        if compiled.get("status") != "ready":
            return _TurnPlan(
                current_sha,
                reason=str(compiled.get("reason") or "continuity_compile_fallback"),
            )
        candidate_value = compiled.get("checkpoint_candidate")
        candidate = dict(candidate_value) if isinstance(candidate_value, Mapping) else None
        selected = candidate if candidate is not None else self._old_checkpoint(bundle)
        bridge = thread_continuity_bridge_projection(selected)
        raw_bridge_body = str(bridge.get("body") or "")
        if str(bridge.get("status") or "") != "ready":
            raw_bridge_body = ""
        bridge_body = (
            f"{raw_bridge_body.rstrip()}\n{CONTINUITY_END_BOUNDARY}"
            if raw_bridge_body.strip()
            else ""
        )
        marker = (
            f"{CONTINUITY_MARKER_NAMESPACE} "
            f"checkpoint_revision={int(dict(selected or {}).get('revision') or 0)} "
            f"source_snapshot={str(compiled.get('expected_pre_turn_source_snapshot') or '')} "
            f"bridge_sha256={hashlib.sha256(bridge_body.encode('utf-8')).hexdigest()}]"
            if bridge_body
            else ""
        )
        source_ids = tuple(
            str(value)
            for value in list(bridge.get("represented_source_group_ids") or [])
            if str(value)
        )
        return _TurnPlan(
            current_sha256=current_sha,
            marker=marker,
            bridge_body=bridge_body,
            checkpoint_candidate=candidate,
            expected_revision=int(compiled.get("expected_revision") or 0),
            expected_source_snapshot=str(
                compiled.get("expected_pre_turn_source_snapshot") or ""
            ),
            source_ids=source_ids,
            context_window_tokens=window,
            usable_context_window_tokens=usable_window,
            context_window_source=source_label,
            context_window_confidence=confidence_label,
            reserved_output_tokens=reserve,
            provider_key=(model, provider, base_url),
        )

    def _plan_for_request(
        self,
        request: Mapping[str, Any],
        *,
        session_id: str,
        turn_id: str,
        model: str,
        provider: str,
        base_url: str,
        context_window_tokens: Any,
        context_window_source: Any,
        context_window_confidence: Any,
    ) -> _TurnPlan:
        turn_key = (session_id, turn_id)
        shape = request_messages(request)
        current_sha = ""
        if shape is not None:
            index = last_real_user_index(shape[1])
            if index >= 0 and isinstance(shape[1][index], Mapping):
                current_sha = _current_message_sha256(shape[1][index])
        with self._lock:
            existing = self._turns.get(turn_key)
            if existing is not None:
                self._turns.move_to_end(turn_key)
                if not _request_has_user_anchor(
                    request,
                    existing.current_sha256,
                    existing.current_identity,
                ):
                    return _TurnPlan(current_sha, reason="current_identity_drift")
                return existing
            if turn_key in self._compiling:
                return _TurnPlan(current_sha, reason="turn_compile_in_progress")
            self._compiling.add(turn_key)
        try:
            plan = self._compile_plan(
                request,
                session_id=session_id,
                turn_id=turn_id,
                model=model,
                provider=provider,
                base_url=base_url,
                context_window_tokens=context_window_tokens,
                context_window_source=context_window_source,
                context_window_confidence=context_window_confidence,
            )
            if plan.current_sha256 and current_sha == plan.current_sha256:
                plan.current_identity = _current_identity_content(
                    shape[1][last_real_user_index(shape[1])].get("content")
                )
        finally:
            with self._lock:
                self._compiling.discard(turn_key)
        with self._lock:
            self._turns[turn_key] = plan
            self._turns.move_to_end(turn_key)
            if not self._trim_locked(protected_turns=(turn_key,)):
                if self._turns.get(turn_key) is plan:
                    self._turns.pop(turn_key, None)
                return _TurnPlan(current_sha, reason="turn_capacity_exceeded")
        return plan

    def _attempt_budget(
        self,
        request: Mapping[str, Any],
        plan: _TurnPlan,
        provider_key: tuple[str, str, str],
        *,
        context_window_tokens: Any,
        context_window_source: Any,
        context_window_confidence: Any,
    ) -> tuple[int, int, int, str, str] | None:
        usable_window = _usable_context_window(
            context_window_tokens,
            context_window_source,
            context_window_confidence,
        )
        if usable_window is None:
            return None
        window = int(context_window_tokens)
        source = str(context_window_source or "unknown")
        confidence = str(context_window_confidence or "unknown")
        reserve = _reserved_output_tokens(request, usable_window)
        if (
            usable_window - reserve
            < plan.usable_context_window_tokens - plan.reserved_output_tokens
        ):
            return None
        return window, usable_window, reserve, source, confidence

    @staticmethod
    def _request_model_sha256(request: Mapping[str, Any]) -> str:
        try:
            return canonical_request_sha256(
                {
                    "present": "model" in request,
                    "model": request.get("model"),
                }
            )
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _native_request(
        request: Mapping[str, Any], projection: _Projection
    ) -> dict[str, Any] | None:
        return (
            projection.overlay.native_request(request)
            if projection.overlay is not None
            else None
        )

    def _scoped_projection_exact(
        self,
        request: Mapping[str, Any],
        projection: _Projection,
        plan: _TurnPlan,
        *,
        provider_key: tuple[str, str, str],
    ) -> bool:
        native_request = self._native_request(request, projection)
        if (
            provider_key != projection.provider_key
            or self._request_model_sha256(request)
            != projection.request_model_sha256
            or native_request is None
        ):
            return False
        return _request_has_user_anchor(
            native_request,
            plan.current_sha256,
            plan.current_identity,
        )

    def _provider_projection_exact(
        self,
        request: Mapping[str, Any],
        projection: _Projection,
        plan: _TurnPlan,
        *,
        provider_key: tuple[str, str, str],
    ) -> bool:
        """Verify the bridge on the captured provider-bound request."""

        if (
            provider_key != projection.provider_key
            or self._request_model_sha256(request)
            != projection.request_model_sha256
        ):
            return False
        if projection.overlay is None:
            return _request_has_user_anchor(
                request,
                plan.current_sha256,
                plan.current_identity,
            )
        native_request = projection.overlay.native_request(
            request,
            require_original_material=False,
        )
        return bool(
            native_request is not None
            and _request_has_user_anchor(
                native_request,
                plan.current_sha256,
                plan.current_identity,
            )
        )

    def _register_provider_budget_filter(
        self,
        transport_record: Any,
        projection: _Projection,
        plan: _TurnPlan,
        provider_key: tuple[str, str, str],
    ) -> bool:
        """Delegate the one final-body budget decision to the host overlay."""

        overlay = projection.overlay
        if overlay is None:
            return False
        return overlay.register_final_budget_guard(
            transport_record,
            context_window_tokens=projection.usable_context_window_tokens,
            reserve_tokens=_reserved_output_tokens,
            validator=lambda body, native: bool(
                provider_key == projection.provider_key
                and self._request_model_sha256(body) == projection.request_model_sha256
                and _request_has_user_anchor(
                    native,
                    plan.current_sha256,
                    plan.current_identity,
                )
            ),
        )

    def _stage_provider_transport(
        self,
        attempt_key: tuple[str, str, str],
        projection: _Projection,
        plan: _TurnPlan,
        provider_key: tuple[str, str, str],
        transport_record: Any,
        transport_schema_version: str,
    ) -> None:
        try:
            if (
                transport_schema_version != _TRANSPORT_SCHEMA_VERSION
                or transport_record is None
                or getattr(transport_record, "schema_version", None)
                != _TRANSPORT_SCHEMA_VERSION
                or bool(getattr(transport_record, "ambiguous"))
                or getattr(transport_record, "capture_count") != 1
                or (
                    projection.overlay is not None
                    and projection.overlay.disposition != OVERLAY_KEPT
                )
            ):
                return
            provider_body = getattr(transport_record, "provider_body")
            estimated_tokens = getattr(
                transport_record, "provider_body_estimated_tokens"
            )
            estimate_source = getattr(
                transport_record, "provider_body_estimate_source"
            )
            estimate_confidence = getattr(
                transport_record, "provider_body_estimate_confidence"
            )
            reserve = _reserved_output_tokens(
                provider_body, projection.usable_context_window_tokens
            ) if isinstance(provider_body, Mapping) else 0
            if (
                not isinstance(provider_body, Mapping)
                or not self._provider_projection_exact(
                    provider_body,
                    projection,
                    plan,
                    provider_key=provider_key,
                )
                or type(estimated_tokens) is not int
                or estimated_tokens < 0
                or estimate_source != "hermes.provider_body.rough.v1"
                or estimate_confidence != "heuristic_with_margin"
                or estimated_tokens + reserve
                > projection.usable_context_window_tokens
            ):
                return
            request_digest = canonical_request_sha256(provider_body)
        except Exception:
            return
        with self._lock:
            current = self._projections.get(attempt_key)
            if current is not projection:
                return
            now = self.monotonic()
            projection.last_touch = now
            self._transport[attempt_key] = _TransportStage(
                turn_key=projection.turn_key,
                attempt_seq=projection.attempt_seq,
                request_sha256=request_digest,
                transport_record=transport_record,
                last_touch=now,
            )

    def llm_request(
        self,
        *,
        request: Mapping[str, Any],
        original_request: Mapping[str, Any] | None = None,
        session_id: str,
        turn_id: str,
        api_request_id: str,
        model: str = "",
        provider: str = "",
        base_url: str = "",
        api_mode: str = "",
        context_window_tokens: Any = None,
        context_window_source: str = "unknown",
        context_window_confidence: str = "unknown",
        **_kwargs: Any,
    ) -> dict[str, Any] | None:
        session_id = str(session_id or "").strip()
        turn_id = str(turn_id or "").strip()
        api_request_id = str(api_request_id or "").strip()
        if (
            not session_id
            or not turn_id
            or not api_request_id
            or api_mode == "codex_app_server"
            or not isinstance(request, Mapping)
        ):
            return None
        attempt_key = (session_id, turn_id, api_request_id)
        with self._lock:
            self._projections.pop(attempt_key, None)
            self._transport.pop(attempt_key, None)
        plan_request = (
            original_request if isinstance(original_request, Mapping) else request
        )
        plan = self._plan_for_request(
            plan_request,
            session_id=session_id,
            turn_id=turn_id,
            model=str(model or ""),
            provider=str(provider or ""),
            base_url=str(base_url or ""),
            context_window_tokens=context_window_tokens,
            context_window_source=context_window_source,
            context_window_confidence=context_window_confidence,
        )
        if plan.reason:
            return None
        provider_key = (
            str(model or ""),
            str(provider or ""),
            str(base_url or ""),
        )
        budget = self._attempt_budget(
            request,
            plan,
            provider_key,
            context_window_tokens=context_window_tokens,
            context_window_source=context_window_source,
            context_window_confidence=context_window_confidence,
        )
        if budget is None:
            return None
        window, usable_window, reserve, source, confidence = budget
        if not plan.bridge_body:
            if plan.checkpoint_candidate is None:
                return None
            with self._lock:
                if self._turns.get((session_id, turn_id)) is not plan:
                    return None
                if not self._attempt_capacity_available_locked(attempt_key):
                    return None
                self._attempt_seq += 1
                self._projections[attempt_key] = _Projection(
                    turn_key=(session_id, turn_id),
                    attempt_seq=self._attempt_seq,
                    overlay=None,
                    provider_key=provider_key,
                    request_model_sha256=self._request_model_sha256(request),
                    context_window_tokens=window,
                    usable_context_window_tokens=usable_window,
                    context_window_source=source,
                    context_window_confidence=confidence,
                    reserved_output_tokens=reserve,
                    last_touch=self.monotonic(),
                )
            return None
        overlay = self.projector(
            request,
            marker_namespace=CONTINUITY_MARKER_NAMESPACE,
            end_boundary=CONTINUITY_END_BOUNDARY,
            marker=plan.marker,
            body=plan.bridge_body,
            max_projection_chars=self.max_projection_chars,
        )
        if (
            not isinstance(overlay, RequestOverlay)
            or overlay.status != "projected"
            or not isinstance(overlay.request, dict)
            or not overlay.verify_exact(overlay.request)
        ):
            return None
        next_request = overlay.request
        with self._lock:
            if self._turns.get((session_id, turn_id)) is not plan:
                return None
            if not self._attempt_capacity_available_locked(attempt_key):
                return None
            self._attempt_seq += 1
            self._projections[attempt_key] = _Projection(
                turn_key=(session_id, turn_id),
                attempt_seq=self._attempt_seq,
                overlay=overlay,
                provider_key=provider_key,
                request_model_sha256=self._request_model_sha256(next_request),
                context_window_tokens=window,
                usable_context_window_tokens=usable_window,
                context_window_source=source,
                context_window_confidence=confidence,
                reserved_output_tokens=reserve,
                last_touch=self.monotonic(),
            )
        return {
            "request": next_request,
            "source": "hermes-continuity",
            "reason": "bridge_projected",
        }

    def llm_execution(
        self,
        *,
        request: Mapping[str, Any],
        original_request: Mapping[str, Any],
        next_call: Callable[[dict[str, Any]], Any],
        session_id: str,
        turn_id: str,
        api_request_id: str,
        model: str = "",
        provider: str = "",
        base_url: str = "",
        transport_record: Any = None,
        transport_schema_version: str = "",
        context_window_tokens: Any = None,
        context_window_source: str = "unknown",
        context_window_confidence: str = "unknown",
        **_kwargs: Any,
    ) -> Any:
        del original_request
        attempt_key = (
            str(session_id or "").strip(),
            str(turn_id or "").strip(),
            str(api_request_id or "").strip(),
        )
        with self._lock:
            projection = self._projections.get(attempt_key)
            plan = self._turns.get(projection.turn_key) if projection else None
            self._sweep_expired_locked()
            projection_active = bool(
                projection is not None
                and plan is not None
                and self._projections.get(attempt_key) is projection
            )
            if projection_active:
                self._executing.add(attempt_key)
        if projection is None or plan is None:
            return next_call(request)
        if not projection_active:
            native_request = self._native_request(request, projection)
            return next_call(native_request if native_request is not None else request)
        supplied_provider_key = (
            str(model or ""),
            str(provider or ""),
            str(base_url or ""),
        )
        provider_key = (
            supplied_provider_key
            if any(supplied_provider_key)
            else projection.provider_key
        )
        usable_window = _usable_context_window(
            context_window_tokens,
            context_window_source,
            context_window_confidence,
        )
        context_matches = bool(
            usable_window == projection.usable_context_window_tokens
            and context_window_tokens == projection.context_window_tokens
            and str(context_window_source or "unknown")
            == projection.context_window_source
            and str(context_window_confidence or "unknown")
            == projection.context_window_confidence
        )
        transport_ready = bool(
            str(transport_schema_version or "") == _TRANSPORT_SCHEMA_VERSION
            and transport_record is not None
            and context_matches
            and (
                projection.overlay is None
                or self._register_provider_budget_filter(
                    transport_record,
                    projection,
                    plan,
                    provider_key,
                )
            )
        )
        if not transport_ready:
            native_request = (
                self._native_request(request, projection)
                if projection.overlay is not None
                else request
            )
            with self._lock:
                self._executing.discard(attempt_key)
                self._projections.pop(attempt_key, None)
                self._transport.pop(attempt_key, None)
            return next_call(native_request if native_request is not None else request)
        if projection.overlay is None:
            candidate_bound = bool(
                provider_key == projection.provider_key
                and self._request_model_sha256(request)
                == projection.request_model_sha256
                and _request_has_user_anchor(
                    request,
                    plan.current_sha256,
                    plan.current_identity,
                )
            )
            try:
                response = next_call(request)
            except Exception:
                with self._lock:
                    self._executing.discard(attempt_key)
                    self._projections.pop(attempt_key, None)
                    self._transport.pop(attempt_key, None)
                raise
            if candidate_bound:
                self._stage_provider_transport(
                    attempt_key,
                    projection,
                    plan,
                    provider_key,
                    transport_record,
                    str(transport_schema_version or ""),
                )
            with self._lock:
                self._executing.discard(attempt_key)
            return response

        if not self._scoped_projection_exact(
            request,
            projection,
            plan,
            provider_key=provider_key,
        ):
            native_request = self._native_request(request, projection)
            with self._lock:
                self._executing.discard(attempt_key)
                self._projections.pop(attempt_key, None)
                self._transport.pop(attempt_key, None)
            return next_call(native_request if native_request is not None else request)

        try:
            response = next_call(request)
        except Exception:
            with self._lock:
                self._executing.discard(attempt_key)
                self._projections.pop(attempt_key, None)
                self._transport.pop(attempt_key, None)
            raise
        self._stage_provider_transport(
            attempt_key,
            projection,
            plan,
            provider_key,
            transport_record,
            str(transport_schema_version or ""),
        )
        with self._lock:
            self._executing.discard(attempt_key)
        return response

    def _record_receipt(
        self,
        attempt_key: tuple[str, str, str],
        stage: _TransportStage,
        plan: _TurnPlan,
        status: str,
    ) -> None:
        store = getattr(self.adapter, "metadata_store", None)
        writer = getattr(store, "record_receipt", None)
        if not callable(writer):
            return
        receipt_id, hashes, counts = self._receipt_material(
            attempt_key,
            stage,
            plan,
        )
        try:
            writer(
                receipt_id=receipt_id,
                session_id=attempt_key[0],
                kind="delivery",
                status=status,
                source_ids=plan.source_ids,
                hashes=hashes,
                counts=counts,
            )
        except Exception:
            return

    @staticmethod
    def _receipt_material(
        attempt_key: tuple[str, str, str],
        stage: _TransportStage,
        plan: _TurnPlan,
    ) -> tuple[str, dict[str, str], dict[str, int]]:
        receipt_id = "hcr_" + _sha256(
            [*attempt_key, stage.attempt_seq, stage.request_sha256]
        )
        return (
            receipt_id,
            {
                "request_sha256": stage.request_sha256,
                "bridge_body_sha256": hashlib.sha256(
                    plan.bridge_body.encode("utf-8")
                ).hexdigest(),
                "source_snapshot": plan.expected_source_snapshot,
            },
            {"represented_source_group_count": len(plan.source_ids)},
        )

    def post_api_request(
        self,
        *,
        session_id: str,
        turn_id: str,
        api_request_id: str,
        transport_record: Any = None,
        transport_schema_version: str = "",
        **_kwargs: Any,
    ) -> None:
        attempt_key = (
            str(session_id or "").strip(),
            str(turn_id or "").strip(),
            str(api_request_id or "").strip(),
        )
        with self._lock:
            self._executing.discard(attempt_key)
            stage = self._transport.pop(attempt_key, None)
            projection = self._projections.pop(attempt_key, None)
            plan = self._turns.get(stage.turn_key) if stage else None
            protected_turn = (
                stage.turn_key
                if stage is not None
                else projection.turn_key
                if projection is not None
                else None
            )
            self._trim_locked(
                protected_turns=(protected_turn,) if protected_turn else ()
            )
        if stage is None or plan is None:
            return None
        try:
            provider_body = getattr(transport_record, "provider_body")
            transport_verified = bool(
                transport_schema_version == _TRANSPORT_SCHEMA_VERSION
                and transport_record is stage.transport_record
                and getattr(transport_record, "schema_version", None)
                == _TRANSPORT_SCHEMA_VERSION
                and not bool(getattr(transport_record, "ambiguous"))
                and getattr(transport_record, "capture_count") == 1
                and bool(getattr(transport_record, "settled"))
                and isinstance(provider_body, Mapping)
                and canonical_request_sha256(provider_body) == stage.request_sha256
            )
        except Exception:
            transport_verified = False
        if not transport_verified:
            return None

        candidate = plan.checkpoint_candidate
        cached = ""
        if candidate is not None:
            with self._publish_condition:
                while plan.publish_status == "in_progress":
                    self._publish_condition.wait()
                cached = plan.publish_status
                if not cached:
                    plan.publish_status = "in_progress"
        if cached:
            status = {
                "applied": "delivered_checkpoint_unchanged",
                "conflict": "delivered_checkpoint_conflict",
                "failed": "delivered_checkpoint_failed",
            }.get(cached, "delivered_checkpoint_failed")
            self._record_receipt(attempt_key, stage, plan, status)
            return None

        receipt_id, hashes, counts = self._receipt_material(
            attempt_key,
            stage,
            plan,
        )
        settler = getattr(self.adapter, "settle_checkpoint_delivery", None)
        if not callable(settler):
            settled: Mapping[str, Any] = {
                "ok": False,
                "status": "failed",
                "receipt_recorded": False,
            }
        else:
            try:
                value = settler(
                    attempt_key[0],
                    expected_revision=plan.expected_revision,
                    expected_source_snapshot=plan.expected_source_snapshot,
                    checkpoint_candidate=candidate,
                    receipt_id=receipt_id,
                    source_ids=plan.source_ids,
                    hashes=hashes,
                    counts=counts,
                )
            except Exception:
                value = {"ok": False, "status": "failed", "receipt_recorded": False}
            settled = value if isinstance(value, Mapping) else {
                "ok": False,
                "status": "failed",
                "receipt_recorded": False,
            }
        outcome = str(settled.get("status") or "failed")
        if outcome not in {"applied", "unchanged", "conflict", "failed"}:
            outcome = "failed"
        if candidate is not None:
            terminal = outcome if outcome in {"applied", "conflict"} else "failed"
            with self._publish_condition:
                plan.publish_status = terminal
                self._publish_condition.notify_all()
        return None

    def api_request_error(
        self,
        *,
        session_id: str,
        turn_id: str,
        api_request_id: str,
        **_kwargs: Any,
    ) -> None:
        attempt_key = (
            str(session_id or "").strip(),
            str(turn_id or "").strip(),
            str(api_request_id or "").strip(),
        )
        with self._lock:
            self._executing.discard(attempt_key)
            projection = self._projections.pop(attempt_key, None)
            self._transport.pop(attempt_key, None)
            self._trim_locked(
                protected_turns=(projection.turn_key,) if projection else ()
            )
        return None

    def status_command(self, raw_args: str = "") -> str:
        """Return body-free process state for the owner-visible slash command."""

        session_filter = str(raw_args or "").strip()
        with self._lock:
            self._sweep_expired_locked()
            plans = [
                (turn_key, plan)
                for turn_key, plan in self._turns.items()
                if not session_filter or turn_key[0] == session_filter
            ]
            reason_counts: dict[str, int] = {}
            for _turn_key, plan in plans:
                if plan.reason:
                    reason_counts[plan.reason] = reason_counts.get(plan.reason, 0) + 1
            context_source_counts: dict[str, int] = {}
            context_confidence_counts: dict[str, int] = {}
            for _turn_key, plan in plans:
                if plan.context_window_tokens > 0:
                    context_source_counts[plan.context_window_source] = (
                        context_source_counts.get(plan.context_window_source, 0) + 1
                    )
                    context_confidence_counts[plan.context_window_confidence] = (
                        context_confidence_counts.get(
                            plan.context_window_confidence, 0
                        )
                        + 1
                    )
            payload = {
                "schema": "hermes_continuity_status.v1",
                "session_filter": session_filter,
                "cached_turn_count": len(plans),
                "active_projection_count": sum(
                    1
                    for value in self._projections.values()
                    if not session_filter or value.turn_key[0] == session_filter
                ),
                "provider_transport_count": sum(
                    1
                    for value in self._transport.values()
                    if not session_filter or value.turn_key[0] == session_filter
                ),
                "executing_attempt_count": sum(
                    1
                    for key in self._executing
                    if not session_filter or key[0] == session_filter
                ),
                "checkpoint_publish_status_counts": {
                    status: sum(
                        1 for _key, plan in plans if plan.publish_status == status
                    )
                    for status in ("applied", "conflict", "failed", "in_progress")
                },
                "reason_counts": reason_counts,
                "context_window_source_counts": context_source_counts,
                "context_window_confidence_counts": context_confidence_counts,
                "final_provider_estimate": {
                    "source": "hermes.provider_body.rough.v1",
                    "confidence": "heuristic_with_margin",
                    "is_exact_tokenizer_bound": False,
                },
                "attempt_limit": self.max_cached_turns,
                "attempt_ttl_seconds": self.attempt_ttl_seconds,
                "stores_canonical_message_bodies": False,
                "checkpoint_contains_generated_bridge_body": True,
                "codex_app_server_supported": False,
                "moa_delivery_supported": False,
            }
        store = getattr(self.adapter, "metadata_store", None)
        durable_reader = getattr(store, "status_summary", None)
        if callable(durable_reader):
            try:
                payload["durable"] = durable_reader(session_filter)
            except Exception:
                payload["durable"] = {
                    "schema": "hermes_continuity_durable_status.v1",
                    "status": "unavailable",
                    "body_included": False,
                }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def clear(self) -> None:
        """Drop process-private frozen plans; durable checkpoints stay intact."""

        with self._lock:
            self._turns.clear()
            self._compiling.clear()
            self._projections.clear()
            self._transport.clear()
            self._executing.clear()
