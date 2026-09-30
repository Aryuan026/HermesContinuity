"""Real host proof for compact v3 preparation, settlement, and reuse.

The test enters through plugin discovery and ``AIAgent.run_conversation``.  It
does not call Continuity request/execution/post hooks or settlement helpers.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CONTINUITY_ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT_VALUE = os.environ.get("HERMES_SOURCE_ROOT", "").strip()
HERMES_ROOT = Path(HERMES_ROOT_VALUE)
HOST_AVAILABLE = bool(HERMES_ROOT_VALUE) and all(
    path.is_file()
    for path in (
        HERMES_ROOT / "agent" / "conversation_loop.py",
        HERMES_ROOT / "hermes_state_history.py",
        HERMES_ROOT / "hermes_cli" / "plugins.py",
    )
)

if HOST_AVAILABLE:
    sys.path.insert(0, str(HERMES_ROOT))


SUMMARY_MARKER = re.compile(r"\[END THREAD CONTINUITY SUMMARY [0-9a-f]{64}\]")
CONTINUITY_MARKER = "[THREAD CONTINUITY QUOTED REFERENCE"


def _provider_response(text: str = "long-history answer") -> SimpleNamespace:
    return SimpleNamespace(
        id="long-history-response",
        model="long-history-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant", content=text, tool_calls=None
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100, completion_tokens=4, total_tokens=104
        ),
    )


def _sqlite_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


@unittest.skipUnless(
    HOST_AVAILABLE,
    "set HERMES_SOURCE_ROOT to a Block 3 compatible Hermes tree",
)
class RealHostLongHistoryV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name) / ".hermes"
        plugin_dir = self.home / "plugins"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "hermes-continuity").symlink_to(
            CONTINUITY_ROOT, target_is_directory=True
        )
        (self.home / "config.yaml").write_text(
            "plugins:\n"
            "  enabled:\n"
            "    - hermes-continuity\n"
            "auxiliary:\n"
            "  title_generation:\n"
            "    enabled: false\n",
            encoding="utf-8",
        )
        self.env = patch.dict(os.environ, {"HERMES_HOME": str(self.home)})
        self.env.start()
        self.transport_modules = patch.dict(
            sys.modules,
            {
                "httpx": types.ModuleType("httpx"),
                "requests": types.ModuleType("requests"),
            },
        )
        self.transport_modules.start()

        global AIAgent, PluginLlmCompleteResult, PluginLlmUsage, SessionDB
        global context_compressor, hermes_config, model_metadata, plugins, ssl_guard
        global relay_llm, relay_runtime
        from agent import (
            context_compressor,
            model_metadata,
            relay_llm,
            relay_runtime,
            ssl_guard,
        )
        from agent.plugin_llm import PluginLlmCompleteResult, PluginLlmUsage
        from hermes_cli import config as hermes_config
        from hermes_cli import plugins
        from hermes_state import SessionDB
        from run_agent import AIAgent

        hermes_config._config_cache = None
        plugins._reset_plugin_managers_for_tests()
        self.agents = []
        self.summary_calls = 0
        self.validation_errors: list[str] = []
        self.last_bundle = {}
        self.last_prepared = {}
        self.session_db = SessionDB(self.home / "state.db")
        self.session_db.create_session("long-mouth", "cli")
        now = time.time() - 1_800
        self.session_db.append_message("long-mouth", "user", "legacy notification",
                                       timestamp=now-2, display_kind="internal_notification")
        missing = dict(self.session_db.get_messages("long-mouth")[0], display_kind=None)
        self.session_db.archive_and_compact("long-mouth", [missing])
        self.session_db.archive_and_compact("long-mouth", [missing])
        self.session_db.append_message("long-mouth", "assistant", "legacy reply", timestamp=now-1)
        self.legacy_row_ids = [row[0] for row in self.session_db._conn.execute("SELECT id FROM messages")]
        for start in range(0, 1_200, 100):
            self.session_db.append_messages_batch(
                "long-mouth",
                [
                    {
                        "role": role,
                        "content": f"{role} bounded history {index}",
                        "timestamp": now + index * 2 + offset,
                    }
                    for index in range(start, min(start + 100, 1_200))
                    for offset, role in enumerate(("user", "assistant"))
                ],
            )
        self.session_db._execute_write(
            lambda connection: connection.execute(
                "UPDATE messages SET active=0,compacted=1 "
                "WHERE session_id='long-mouth'"
            )
        )

    def tearDown(self) -> None:
        for agent in self.agents:
            agent._end_session_on_close = False
            agent.close()
        plugins._reset_plugin_managers_for_tests()
        hermes_config._config_cache = None
        self.session_db.close()
        try:
            import hermes_logging

            hermes_logging._reset_queued_handlers()
        except Exception:
            pass
        self.transport_modules.stop()
        self.env.stop()
        self.tempdir.cleanup()

    async def _summary_complete(self, _plugin_llm, messages, **_kwargs):
        self.summary_calls += 1
        rendered = "\n".join(str(row.get("content") or "") for row in messages)
        marker = SUMMARY_MARKER.search(rendered)
        if marker is None:
            raise AssertionError("Continuity summary marker missing from host LLM call")
        return PluginLlmCompleteResult(
            text="bounded long-history bridge\n" + marker.group(0),
            provider="long-history-provider",
            model="long-history-summary-model",
            agent_id="default",
            usage=PluginLlmUsage(
                input_tokens=100, output_tokens=8, total_tokens=108
            ),
            finish_reason="stop",
        )

    def _agent(self, *, prepare_before_request: bool = True) -> AIAgent:
        agent = AIAgent(
            api_key="test-key",
            base_url="http://127.0.0.1:1/v1",
            provider="openai-compat",
            model="long-history-model",
            max_iterations=1,
            max_tokens=256,
            enabled_toolsets=[],
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            save_trajectories=False,
            platform="cli",
            session_id="long-mouth",
            session_db=self.session_db,
        )
        agent._api_max_retries = 1
        def build_kwargs(messages):
            # The host persists this turn's user before request middleware.
            # Positive reuse requires that new journal entry to be prepared;
            # preparing only before run_conversation races the bounded worker.
            if prepare_before_request:
                self._prepare_index()
            return {"model": agent.model, "messages": messages, "max_tokens": 256}

        agent._build_api_kwargs = build_kwargs
        agent._try_recover_primary_transport = lambda *_args, **_kwargs: False
        agent._try_activate_fallback = lambda *_args, **_kwargs: False
        agent._has_pending_fallback = lambda: False
        agent.context_compressor.context_length = 128_000
        resolution = {
            "tokens": 128_000,
            "source": "config",
            "confidence": "authoritative",
        }
        agent._context_window_resolution = resolution
        agent.context_compressor._context_window_resolution = resolution
        return agent

    @staticmethod
    def _acquire_without_relay(**kwargs):
        return relay_runtime.ConversationLease(
            profile_key=kwargs["profile_key"],
            session_id=kwargs["session_id"],
            platform=kwargs["platform"],
            host=relay_runtime.NoopRelayRuntime(
                kwargs["profile_key"], "long history entrypoint test"
            ),
            session=None,
            parent_session_id=kwargs.get("parent_session_id", ""),
        )

    def _prepare_index(self) -> None:
        manager = plugins.get_plugin_manager()
        service = manager._get_plugin_service(
            "hermes-continuity:canonical-source.v2"
        )
        self.assertIsNotNone(service)
        index = service.adapter.history_index
        self.assertIsNotNone(index)
        preparation = importlib.import_module(type(index).__module__)
        with preparation.PREPARATION_LOCK:
            for _ in range(2_000):
                result = index.prepare_step("long-mouth")
                self.last_prepared = {key: result.get(key) for key in (
                    "status", "reason", "phase", "canonical_count", "pages_processed")}
                if result.get("status") == "ready":
                    break
                self.assertEqual(result.get("status"), "progress", result)
            else:
                self.fail("history preparation did not finish within bounded work steps")
        if not getattr(index, "_continuity_test_validation_probe", False):
            original_validate = index.validate_checkpoint

            def validate_with_reason(*args, **kwargs):
                try:
                    return original_validate(*args, **kwargs)
                except ValueError as exc:
                    self.validation_errors.append(str(exc))
                    raise

            index.validate_checkpoint = validate_with_reason
            original_bundle = service.adapter.read_bundle

            def observe_bundle(*args, **kwargs):
                bundle = original_bundle(*args, **kwargs)
                self.last_bundle = {
                    section: {key: bundle.get(section, {}).get(key)
                              for key in ("status", "error", "reasons", "scan_complete")}
                    for section in ("source", "continuity")}
                return bundle

            service.adapter.read_bundle = observe_bundle
            index._continuity_test_validation_probe = True

    def _continuity_status(self) -> str:
        manager = plugins.get_plugin_manager()
        for callback in manager._middleware.get("llm_request", ()):
            runtime = getattr(callback, "__self__", None)
            if runtime is not None and type(runtime).__name__ == "ContinuityRuntime":
                return runtime.status_command("long-mouth")
        return "continuity runtime middleware unavailable"

    def _diagnostics(self) -> str:
        manager = plugins.get_plugin_manager()
        service = manager._get_plugin_service("hermes-continuity:canonical-source.v2")
        with self.session_db._read_ctx() as connection:
            domain = connection.execute(
                "SELECT phase,cursor_message_id,canonical_count,physical_cursor_position "
                "FROM hermes_history_domains WHERE domain_id='long-mouth'").fetchone()
        package = type(service.adapter.history_index).__module__.rsplit(".", 1)[0]
        budget = importlib.import_module(package + ".resource_budget")
        leases = {name: {"leases": len(getattr(budget, name)._leases),
                         "bytes": sum(getattr(budget, name)._leases.values())}
                  for name in ("PREPARATION_WORKSETS", "ACTIVE_WORKSETS", "COLD_PLANS")}
        return json.dumps({"runtime": json.loads(self._continuity_status()),
                           "validation_errors": self.validation_errors,
                           "last_bundle": self.last_bundle, "last_prepared": self.last_prepared,
                           "host_domain": dict(domain) if domain else None,
                           "admission": leases}, sort_keys=True)

    def test_real_host_v3_settlement_reload_reuse_and_error(self) -> None:
        # The old Gateway replay lost producer tags before compaction. Keep
        # those physical rows unchanged and exercise the normal host entry.
        placeholders = ",".join("?" for _ in self.legacy_row_ids)
        before = [tuple(row) for row in self.session_db._conn.execute(
            f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY id", self.legacy_row_ids)]
        provider_bodies: list[dict] = []

        def provider(request, *, on_first_delta=None):
            del on_first_delta
            with relay_llm.provider_body_scope(request):
                provider_bodies.append(request)
                return _provider_response()

        async def fake_acomplete(plugin_llm, messages, **kwargs):
            return await self._summary_complete(plugin_llm, messages, **kwargs)

        with (
            patch.object(
                AIAgent, "_create_openai_client", lambda *_a, **_kw: SimpleNamespace()
            ),
            patch.object(ssl_guard, "verify_ca_bundle_with_fallback", lambda: None),
            patch.object(
                model_metadata,
                "get_model_context_length",
                lambda *_a, **_kw: 128_000,
            ),
            patch.object(
                context_compressor,
                "get_model_context_length",
                lambda *_a, **_kw: 128_000,
            ),
            patch("agent.plugin_llm.PluginLlm.acomplete", new=fake_acomplete),
            patch.object(
                relay_runtime,
                "resolve_execution_context",
                lambda _sid: (None, None, None),
            ),
            patch.object(
                relay_runtime.SESSION_COORDINATOR,
                "acquire_conversation",
                side_effect=self._acquire_without_relay,
            ),
            patch.object(
                relay_runtime.SESSION_COORDINATOR,
                "finalize_conversation",
                lambda **_kwargs: None,
            ),
        ):
            plugins.discover_plugins()
            loaded = {
                row["name"]: row
                for row in plugins.get_plugin_manager().list_plugins()
            }
            self.assertEqual(loaded["hermes-continuity"]["error"], None)
            self.assertTrue(loaded["hermes-continuity"]["enabled"])
            self._prepare_index()

            cancelled_agent = self._agent()
            self.agents.append(cancelled_agent)
            cancelled_agent._interruptible_streaming_api_call = provider
            manager = plugins.get_plugin_manager()
            runtime = next(callback.__self__ for callback in manager._middleware["llm_request"]
                           if type(getattr(callback, "__self__", None)).__name__ == "ContinuityRuntime")
            budget = importlib.import_module(runtime.__module__).ACTIVE_WORKSETS
            async def cancelled_summary(*args, **kwargs):
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
            with patch("agent.plugin_llm.PluginLlm.acomplete", new=cancelled_summary):
                with self.assertRaises(asyncio.CancelledError):
                    cancelled_agent.run_conversation("Cancelled long-history summary",
                        conversation_history=[], task_id="cancelled-summary")
            self.assertEqual(provider_bodies, [])
            self.assertEqual(runtime._turns, {})
            self.assertEqual(runtime._compiling, set())
            self.assertFalse(any(key[0] is runtime._budget_identity for key in budget._leases))
            plugins._reset_plugin_managers_for_tests()
            hermes_config._config_cache = None
            plugins.discover_plugins()
            self._prepare_index()

            first_agent = self._agent()
            self.agents.append(first_agent)
            first_agent._interruptible_streaming_api_call = provider
            first = first_agent.run_conversation(
                "First long-history turn",
                conversation_history=[],
                task_id="long-history-turn-1",
            )
            self.assertEqual(first["final_response"], "long-history answer")
            self.assertEqual(self.summary_calls, 1, provider_bodies[0])
            self.assertEqual(repr(provider_bodies[0]).count(CONTINUITY_MARKER), 1)

            continuity_paths = list(
                (self.home / "plugin-data").glob("*/continuity.sqlite3")
            )
            self.assertEqual(len(continuity_paths), 1)
            continuity_db = continuity_paths[0]
            self.assertEqual(
                _sqlite_count(continuity_db, "continuity_checkpoints_v3"),
                1,
                f"{self._continuity_status()} validation_errors={self.validation_errors}",
            )
            self.assertEqual(
                _sqlite_count(continuity_db, "continuity_receipts"), 1
            )

            plugins._reset_plugin_managers_for_tests()
            hermes_config._config_cache = None
            plugins.discover_plugins()
            self._prepare_index()
            service = plugins.get_plugin_manager()._get_plugin_service(
                "hermes-continuity:canonical-source.v2")
            preparation = importlib.import_module(type(service.adapter.history_index).__module__)
            pending_agent = self._agent(prepare_before_request=False)
            self.agents.append(pending_agent)
            pending_agent._interruptible_streaming_api_call = provider
            # Deterministically keep preparation pending after real user
            # persistence. Do not enlarge the foreground wait or retry it.
            with preparation.PREPARATION_LOCK:
                pending = pending_agent.run_conversation(
                    "Native turn while reload preparation is busy",
                    conversation_history=[], task_id="pending-reload")
                self.assertEqual(pending["final_response"], "long-history answer")
                self.assertEqual(repr(provider_bodies[-1]).count(CONTINUITY_MARKER), 0)
                self.assertEqual(self.last_bundle["source"]["status"], "pending",
                                 self._diagnostics())
                self.assertEqual(self.last_bundle["source"]["error"], "history_source_pending")
                self.assertEqual(_sqlite_count(continuity_db, "continuity_receipts"), 1)
                self.assertEqual(self.summary_calls, 1)
            self._prepare_index()
            restarted_agent = self._agent()
            self.agents.append(restarted_agent)
            restarted_agent._interruptible_streaming_api_call = provider
            second = restarted_agent.run_conversation(
                "Second long-history turn after reload",
                conversation_history=[],
                task_id="long-history-turn-2",
            )
            self.assertEqual(second["final_response"], "long-history answer")
            self.assertEqual(self.summary_calls, 1)
            self.assertEqual(repr(provider_bodies[-1]).count(CONTINUITY_MARKER), 1,
                             self._diagnostics())
            self.assertEqual(
                _sqlite_count(continuity_db, "continuity_receipts"), 2
            )

            self._prepare_index()
            receipts_before_error = _sqlite_count(
                continuity_db, "continuity_receipts"
            )

            def failing_provider(request, *, on_first_delta=None):
                del on_first_delta
                with relay_llm.provider_body_scope(request):
                    raise RuntimeError("long-history provider failure")

            failing_agent = self._agent()
            self.agents.append(failing_agent)
            failing_agent._interruptible_streaming_api_call = failing_provider
            failed = failing_agent.run_conversation(
                "Provider failure must not settle",
                conversation_history=[],
                task_id="long-history-turn-error",
            )
            self.assertFalse(failed["completed"])
            self.assertEqual(
                _sqlite_count(continuity_db, "continuity_receipts"),
                receipts_before_error,
            )
        self.assertEqual([tuple(row) for row in self.session_db._conn.execute(
            f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY id", self.legacy_row_ids)], before)


if __name__ == "__main__":
    unittest.main()
