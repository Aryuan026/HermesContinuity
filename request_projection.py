"""Pure request-only Continuity projection and execution-stage proof."""

from __future__ import annotations

import copy
import hashlib
import struct
from collections.abc import Mapping
from typing import Any


PROJECTION_PROOF_SCHEMA = "thread_continuity_request_projection_proof.v1"
DEFAULT_MAX_PROJECTION_CHARS = 24_000
CONTINUITY_MARKER_NAMESPACE = "[THREAD CONTINUITY QUOTED REFERENCE"
CONTINUITY_END_BOUNDARY = "[END THREAD CONTINUITY QUOTED REFERENCE]"
_TEXT_BLOCK_TYPES = {"text", "input_text"}
_STANDARD_VISIBLE_BLOCK_TYPES = {"image", "image_url", "document"}
_RESPONSES_VISIBLE_BLOCK_TYPES = {"input_image", "input_file"}
_BEDROCK_VISIBLE_BLOCK_KEYS = {"image", "document"}
_BEDROCK_TEXT_BLOCK = "bedrock_text"
_PROOF_KEYS = {
    "schema",
    "status",
    "reason",
    "carrier_index",
    "carrier_kind",
    "request_sha256",
    "bridge_body_sha256",
    "message_count",
    "body_included",
}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _frame(kind: bytes, payload: bytes) -> bytes:
    return kind + len(payload).to_bytes(8, "big") + payload


def _canonical_bytes(value: Any) -> bytes:
    if value is None:
        return _frame(b"n", b"")
    if type(value) is bool:
        return _frame(b"b", b"1" if value else b"0")
    if type(value) is int:
        return _frame(b"i", str(value).encode("ascii"))
    if type(value) is float:
        return _frame(b"f", struct.pack("!d", value))
    if isinstance(value, str):
        return _frame(b"s", value.encode("utf-8"))
    if isinstance(value, bytes):
        return _frame(b"y", value)
    if isinstance(value, (list, tuple)):
        return _frame(b"l", b"".join(_canonical_bytes(item) for item in value))
    if isinstance(value, Mapping):
        pairs = sorted(
            (_canonical_bytes(key), _canonical_bytes(item))
            for key, item in value.items()
        )
        return _frame(
            b"d",
            b"".join(_frame(b"k", key) + _frame(b"v", item) for key, item in pairs),
        )
    raise TypeError(f"unsupported request value: {type(value).__name__}")


def _request_sha256(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(request)).hexdigest()


def _request_messages(request: Mapping[str, Any]) -> tuple[str, list[Any]] | None:
    candidates = [
        (key, request.get(key))
        for key in ("messages", "input")
        if isinstance(request.get(key), list)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _clone_request(provider_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-clone ordinary provider JSON, with a safe copy-on-write fallback."""

    try:
        return copy.deepcopy(dict(provider_kwargs))
    except Exception:
        request = dict(provider_kwargs)
    for key in ("messages", "input"):
        if isinstance(request.get(key), list):
            request[key] = list(request[key])
    return request


def _has_visible_non_tool_content(content: Any) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, Mapping):
            continue
        part_type = part.get("type")
        if part_type in _TEXT_BLOCK_TYPES:
            text = part.get("text")
        elif "type" not in part and set(part) == {"text"}:
            text = part.get("text")
        elif part_type in _STANDARD_VISIBLE_BLOCK_TYPES | _RESPONSES_VISIBLE_BLOCK_TYPES:
            return True
        elif "type" not in part and _BEDROCK_VISIBLE_BLOCK_KEYS.intersection(part):
            return True
        else:
            continue
        if isinstance(text, str) and text.strip():
            return True
    return False


def _last_real_user_index(messages: list[Any]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if (
            isinstance(message, Mapping)
            and message.get("role") == "user"
            and _has_visible_non_tool_content(message.get("content"))
        ):
            return index
    return -1


def _list_block_type(content: list[Any]) -> str:
    kinds: set[str] = set()
    for part in content:
        if not isinstance(part, Mapping):
            continue
        if (
            part.get("type") in _TEXT_BLOCK_TYPES
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        ):
            kinds.add(str(part["type"]))
        elif (
            "type" not in part
            and set(part) == {"text"}
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        ):
            kinds.add(_BEDROCK_TEXT_BLOCK)
        elif part.get("type") in _STANDARD_VISIBLE_BLOCK_TYPES:
            kinds.add("text")
        elif part.get("type") in _RESPONSES_VISIBLE_BLOCK_TYPES:
            kinds.add("input_text")
        elif "type" not in part and _BEDROCK_VISIBLE_BLOCK_KEYS.intersection(part):
            kinds.add(_BEDROCK_TEXT_BLOCK)
    return next(iter(kinds)) if len(kinds) == 1 else ""


def _projection_block(block_type: str, text: str) -> dict[str, str]:
    return (
        {"text": text}
        if block_type == _BEDROCK_TEXT_BLOCK
        else {"type": block_type, "text": text}
    )


def _carrier_kind(request_key: str, content: Any) -> str:
    if isinstance(content, str):
        return f"{request_key}:string"
    if isinstance(content, list):
        block_type = _list_block_type(content)
        return f"{request_key}:{block_type}" if block_type else ""
    return ""


def _request_text_occurrences(value: Any, needle: str) -> int:
    if isinstance(value, str):
        return value.count(needle)
    if isinstance(value, Mapping):
        return sum(
            _request_text_occurrences(item, needle) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return sum(_request_text_occurrences(item, needle) for item in value)
    return 0


def _proof(
    request: Mapping[str, Any],
    *,
    status: str,
    reason: str,
    carrier_index: int,
    carrier_kind: str,
    bridge_body: str,
    message_count: int,
) -> dict[str, Any]:
    try:
        request_digest = _request_sha256(request)
    except (TypeError, ValueError):
        request_digest = ""
    return {
        "schema": PROJECTION_PROOF_SCHEMA,
        "status": status,
        "reason": reason,
        "carrier_index": carrier_index,
        "carrier_kind": carrier_kind,
        "request_sha256": request_digest,
        "bridge_body_sha256": _sha256_text(bridge_body),
        "message_count": message_count,
        "body_included": False,
    }


def _blocked(
    request: Mapping[str, Any],
    *,
    reason: str,
    bridge_body: str,
    message_count: int = 0,
) -> dict[str, Any]:
    return {
        "request": request,
        "proof": _proof(
            request,
            status="blocked",
            reason=reason,
            carrier_index=-1,
            carrier_kind="",
            bridge_body=bridge_body,
            message_count=message_count,
        ),
    }


def _projection_is_exact(
    request: Mapping[str, Any],
    messages: list[Any],
    *,
    carrier_index: int,
    carrier_kind: str,
    marker: str,
    bridge_body: str,
) -> bool:
    if not 0 <= carrier_index < len(messages):
        return False
    message = messages[carrier_index]
    if not isinstance(message, Mapping) or message.get("role") != "user":
        return False
    block = f"{marker}\n{bridge_body}"
    content = message.get("content")
    if carrier_kind.endswith(":string"):
        carrier_exact = isinstance(content, str) and content.startswith(f"{block}\n\n")
    else:
        block_type = carrier_kind.rsplit(":", 1)[-1]
        carrier_exact = bool(
            isinstance(content, list)
            and content
            and content[0] == _projection_block(block_type, block)
        )
    return bool(
        carrier_exact
        and _request_text_occurrences(request, CONTINUITY_MARKER_NAMESPACE) == 1
        and _request_text_occurrences(request, CONTINUITY_END_BOUNDARY) == 1
        and _request_text_occurrences(request, marker) == 1
        and _request_text_occurrences(request, bridge_body) == 1
        and _request_text_occurrences(request, block) == 1
    )


def project_continuity_request(
    provider_kwargs: Mapping[str, Any],
    *,
    marker: str,
    bridge_body: str,
    max_projection_chars: int = DEFAULT_MAX_PROJECTION_CHARS,
) -> dict[str, Any]:
    """Return a cloned provider request with one exact Continuity carrier."""

    if not isinstance(provider_kwargs, Mapping):
        raise TypeError("provider_kwargs must be a mapping")
    request = _clone_request(provider_kwargs)

    marker_text = marker if isinstance(marker, str) else ""
    bridge_text = bridge_body if isinstance(bridge_body, str) else ""
    shape = _request_messages(request)
    message_count = len(shape[1]) if shape else 0
    try:
        _request_sha256(request)
    except (TypeError, ValueError):
        return _blocked(
            request,
            reason="request_hash_unavailable",
            bridge_body=bridge_text,
            message_count=message_count,
        )
    if (
        not marker_text.startswith(CONTINUITY_MARKER_NAMESPACE)
        or marker_text.count(CONTINUITY_MARKER_NAMESPACE) != 1
        or not bridge_text.strip()
        or not bridge_text.endswith(CONTINUITY_END_BOUNDARY)
        or bridge_text.count(CONTINUITY_END_BOUNDARY) != 1
        or CONTINUITY_MARKER_NAMESPACE in bridge_text
        or marker_text in bridge_text
        or bridge_text in marker_text
        or CONTINUITY_END_BOUNDARY in marker_text
    ):
        return _blocked(
            request,
            reason="projection_material_invalid",
            bridge_body=bridge_text,
            message_count=message_count,
        )
    block = f"{marker_text}\n{bridge_text}"
    if (
        type(max_projection_chars) is not int
        or max_projection_chars < 1
        or len(block) > max_projection_chars
    ):
        return _blocked(
            request,
            reason="projection_too_large",
            bridge_body=bridge_text,
            message_count=message_count,
        )
    if shape is None:
        return _blocked(
            request,
            reason="request_carrier_ambiguous",
            bridge_body=bridge_text,
        )
    request_key, messages = shape
    carrier_index = _last_real_user_index(messages)
    if carrier_index < 0:
        return _blocked(
            request,
            reason="real_user_carrier_missing",
            bridge_body=bridge_text,
            message_count=len(messages),
        )
    message = messages[carrier_index]
    content = message.get("content")
    carrier_kind = _carrier_kind(request_key, content)
    if not carrier_kind:
        return _blocked(
            request,
            reason="real_user_carrier_ambiguous",
            bridge_body=bridge_text,
            message_count=len(messages),
        )

    namespace_count = _request_text_occurrences(
        request, CONTINUITY_MARKER_NAMESPACE
    )
    end_boundary_count = _request_text_occurrences(
        request, CONTINUITY_END_BOUNDARY
    )
    marker_count = _request_text_occurrences(request, marker_text)
    bridge_count = _request_text_occurrences(request, bridge_text)
    if (namespace_count or end_boundary_count) and not (
        namespace_count == 1
        and end_boundary_count == 1
        and marker_count == 1
    ):
        return _blocked(
            request,
            reason="projection_namespace_conflict",
            bridge_body=bridge_text,
            message_count=len(messages),
        )
    if marker_count:
        if _projection_is_exact(
            request,
            messages,
            carrier_index=carrier_index,
            carrier_kind=carrier_kind,
            marker=marker_text,
            bridge_body=bridge_text,
        ):
            return {
                "request": request,
                "proof": _proof(
                    request,
                    status="projected",
                    reason="",
                    carrier_index=carrier_index,
                    carrier_kind=carrier_kind,
                    bridge_body=bridge_text,
                    message_count=len(messages),
                ),
            }
        return _blocked(
            request,
            reason="projection_marker_conflict",
            bridge_body=bridge_text,
            message_count=len(messages),
        )
    if bridge_count:
        return _blocked(
            request,
            reason="bridge_body_conflict",
            bridge_body=bridge_text,
            message_count=len(messages),
        )

    projected_message = dict(message)
    if isinstance(content, str):
        projected_message["content"] = f"{block}\n\n{content}"
    else:
        block_type = carrier_kind.rsplit(":", 1)[-1]
        projected_message["content"] = [
            _projection_block(block_type, block),
            *content,
        ]
    messages[carrier_index] = projected_message
    return {
        "request": request,
        "proof": _proof(
            request,
            status="projected",
            reason="",
            carrier_index=carrier_index,
            carrier_kind=carrier_kind,
            bridge_body=bridge_text,
            message_count=len(messages),
        ),
    }


def verify_continuity_request_projection(
    provider_kwargs: Mapping[str, Any],
    proof: Mapping[str, Any],
    *,
    marker: str,
    bridge_body: str,
) -> dict[str, Any]:
    """Recompute the execution-stage proof against the request sent downstream."""

    marker_text = marker if isinstance(marker, str) else ""
    bridge_text = bridge_body if isinstance(bridge_body, str) else ""
    if not isinstance(provider_kwargs, Mapping) or not isinstance(proof, Mapping):
        return _proof(
            {},
            status="blocked",
            reason="proof_invalid",
            carrier_index=-1,
            carrier_kind="",
            bridge_body=bridge_text,
            message_count=0,
        )
    shape = _request_messages(provider_kwargs)
    if shape is None:
        return _proof(
            provider_kwargs,
            status="blocked",
            reason="request_carrier_ambiguous",
            carrier_index=-1,
            carrier_kind="",
            bridge_body=bridge_text,
            message_count=0,
        )
    request_key, messages = shape
    carrier_index = _last_real_user_index(messages)
    carrier_kind = (
        _carrier_kind(request_key, messages[carrier_index].get("content"))
        if carrier_index >= 0 and isinstance(messages[carrier_index], Mapping)
        else ""
    )
    try:
        request_digest = _request_sha256(provider_kwargs)
    except (TypeError, ValueError):
        request_digest = ""
    expected = {
        "schema": PROJECTION_PROOF_SCHEMA,
        "status": "projected",
        "reason": "",
        "carrier_index": carrier_index,
        "carrier_kind": carrier_kind,
        "request_sha256": request_digest,
        "bridge_body_sha256": _sha256_text(bridge_text),
        "message_count": len(messages),
        "body_included": False,
    }
    proof_valid = bool(
        request_digest
        and set(proof) == _PROOF_KEYS
        and proof.get("status") == "projected"
        and dict(proof) == expected
    )
    projection_valid = bool(
        marker_text.startswith(CONTINUITY_MARKER_NAMESPACE)
        and marker_text.count(CONTINUITY_MARKER_NAMESPACE) == 1
        and bridge_text.strip()
        and bridge_text.endswith(CONTINUITY_END_BOUNDARY)
        and bridge_text.count(CONTINUITY_END_BOUNDARY) == 1
        and CONTINUITY_MARKER_NAMESPACE not in bridge_text
        and marker_text not in bridge_text
        and bridge_text not in marker_text
        and CONTINUITY_END_BOUNDARY not in marker_text
        and carrier_kind
        and _projection_is_exact(
            provider_kwargs,
            messages,
            carrier_index=carrier_index,
            carrier_kind=carrier_kind,
            marker=marker_text,
            bridge_body=bridge_text,
        )
    )
    status = "verified" if proof_valid and projection_valid else "blocked"
    reason = "" if status == "verified" else (
        "projection_drift" if proof_valid else "proof_mismatch"
    )
    return _proof(
        provider_kwargs,
        status=status,
        reason=reason,
        carrier_index=carrier_index if status == "verified" else -1,
        carrier_kind=carrier_kind if status == "verified" else "",
        bridge_body=bridge_text,
        message_count=len(messages),
    )
