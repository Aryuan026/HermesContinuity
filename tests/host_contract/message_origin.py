"""Minimal H13 classifier contract for host-independent unit CI.

Exact-host behavior is exercised separately against the accepted Hermes 0.21
tree. This fixture only keeps pure plugin tests importable while the public
0.21 host replay remains owned by the later assembly landing wave.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


MESSAGE_ORIGIN_SCHEMA = "hermes.message_origin.v1"
HUMAN = "human"
SCHEDULED = "scheduled"
INTERNAL = "internal"
DELEGATED = "delegated"
CLI_USER = "cli.user"
CRON_AGENT = "cron.agent"
GATEWAY_INTERNAL = "gateway.internal"
SUBAGENT = "subagent"

_WRITER_KINDS = {
    CLI_USER: HUMAN,
    CRON_AGENT: SCHEDULED,
    GATEWAY_INTERNAL: INTERNAL,
    SUBAGENT: DELEGATED,
}


def build_message_origin_proof(writer: str) -> dict[str, str]:
    kind = _WRITER_KINDS.get(writer)
    if kind is None:
        raise ValueError("unknown message origin writer")
    return {"schema": MESSAGE_ORIGIN_SCHEMA, "kind": kind, "writer": writer}


def _normalize(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "kind",
        "writer",
    }:
        raise ValueError("message origin proof must use the closed v1 shape")
    proof = dict(value)
    writer = proof.get("writer")
    if (
        proof.get("schema") != MESSAGE_ORIGIN_SCHEMA
        or not isinstance(writer, str)
        or _WRITER_KINDS.get(writer) != proof.get("kind")
    ):
        raise ValueError("message origin proof is invalid")
    return proof


def classify_message_origin_group(
    messages: Sequence[Mapping[str, Any]],
    *,
    physical_obligations: Sequence[Mapping[str, Any]] = (),
) -> tuple[str | None, str]:
    proofs: list[dict[str, str]] = []
    for message in (*messages, *physical_obligations):
        raw = message.get("origin_proof", message.get("_origin_proof"))
        if raw is None:
            return None, "missing"
        try:
            proofs.append(_normalize(raw))
        except ValueError:
            return None, "invalid"
    if not proofs:
        return None, "missing"
    if any(proof != proofs[0] for proof in proofs[1:]):
        return None, "conflict"
    return proofs[0]["kind"], "verified"
