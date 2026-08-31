"""Hermes Continuity plugin registration."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from .hermes_adapter import (
    ContinuityCanonicalSourceService,
    ContinuityMetadataStore,
    HermesSessionAdapter,
)
from .runtime import ContinuityRuntime


def _string_list_setting(ctx: Any, key: str) -> list[str]:
    value = ctx.get_config(key, default=[])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise RuntimeError(f"Hermes Continuity {key} must be a list of source tags")
    return [item.strip() for item in value]


def _require_compatible_host(ctx: Any) -> None:
    for name in (
        "register_middleware",
        "register_hook",
        "register_service",
        "register_command",
        "on_unload",
    ):
        if not callable(getattr(ctx, name, None)):
            raise RuntimeError(f"Hermes Continuity requires PluginContext.{name}()")

    from agent.plugin_llm import PluginLlmCompleteResult
    try:
        from hermes_cli.middleware import (
            MIDDLEWARE_SCHEMA_VERSION,
            TRANSPORT_SCHEMA_VERSION,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Hermes Continuity requires hermes.middleware.v2 and "
            "hermes.transport.v3"
        ) from exc

    if "finish_reason" not in {field.name for field in fields(PluginLlmCompleteResult)}:
        raise RuntimeError(
            "Hermes Continuity requires the generic PluginLlm finish_reason "
            "seam; apply patches/hermes-0.20.5-plugin-llm-finish-reason.patch"
        )
    if not callable(getattr(ctx.llm, "acomplete", None)):
        raise RuntimeError("Hermes Continuity requires PluginLlm.acomplete()")
    if MIDDLEWARE_SCHEMA_VERSION != "hermes.middleware.v2":
        raise RuntimeError("Hermes Continuity requires hermes.middleware.v2")
    if TRANSPORT_SCHEMA_VERSION != "hermes.transport.v3":
        raise RuntimeError("Hermes Continuity requires hermes.transport.v3")


def register(ctx: Any) -> None:
    """Register request projection, execution proof, and settlement hooks."""

    _require_compatible_host(ctx)
    from hermes_state import SessionDB

    additional_human_sources = _string_list_setting(
        ctx, "additional_human_sources"
    )
    # Hermes owns this layout: <profile>/plugin-data/<plugin namespace>.
    plugin_data_dir = ctx.state.data_dir
    profile_home = plugin_data_dir.parent.parent
    session_db_path = profile_home / "state.db"
    session_db = SessionDB(db_path=session_db_path, read_only=True)
    # Register resource cleanup at acquisition time. The host disposes its
    # ownership ledger in reverse order, so the service registered last below
    # becomes unreachable before runtime cleanup and SessionDB.close().
    ctx.on_unload(session_db.close)
    if not callable(getattr(session_db, "get_messages_time_window", None)):
        session_db.close()
        raise RuntimeError(
            "Hermes Continuity requires "
            "SessionDB.get_messages_time_window()"
        )
    metadata_path = plugin_data_dir / "continuity.sqlite3"
    try:
        metadata_store = ContinuityMetadataStore(metadata_path)
    except Exception:
        session_db.close()
        raise
    adapter = HermesSessionAdapter(session_db, metadata_store)
    canonical_source_service = ContinuityCanonicalSourceService(
        adapter,
        additional_human_sources=additional_human_sources,
    )
    runtime = ContinuityRuntime(
        adapter,
        ctx.llm,
        recent_horizon_hours=ctx.get_config(
            "recent_horizon_hours", default=72
        ),
        source_token_limit=ctx.get_config(
            "source_token_limit", default=24_000
        ),
        output_token_limit=ctx.get_config(
            "output_token_limit", default=2_048
        ),
        max_projection_chars=ctx.get_config(
            "max_projection_chars", default=24_000
        ),
        max_cached_turns=ctx.get_config("max_cached_turns", default=128),
        attempt_ttl_seconds=ctx.get_config(
            "attempt_ttl_seconds", default=600.0
        ),
        summary_timeout_seconds=ctx.get_config(
            "summary_timeout_seconds", default=120.0
        ),
    )
    ctx.on_unload(runtime.clear)

    ctx.register_middleware("llm_request", runtime.llm_request)
    ctx.register_middleware("llm_execution", runtime.llm_execution)
    ctx.register_hook("post_api_request", runtime.post_api_request)
    ctx.register_hook("api_request_error", runtime.api_request_error)
    ctx.register_command(
        "continuity-status",
        runtime.status_command,
        description="Show body-free Continuity runtime health",
        args_hint="[session_id]",
    )
    ctx.register_service("canonical-source.v2", canonical_source_service)
