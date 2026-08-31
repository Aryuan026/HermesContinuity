"""Real Hermes entrypoint proof for Continuity + Global Hot settlement.

This test deliberately does not call either plugin runtime directly.  It loads
both directory plugins through Hermes discovery, runs the production
``AIAgent.run_conversation`` loop, and treats the two SQLite stores as the
settlement oracle.
"""

from __future__ import annotations

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
GLOBAL_HOT_ROOT_VALUE = os.environ.get("HERMES_GLOBAL_HOT_ROOT", "").strip()
HERMES_ROOT = Path(HERMES_ROOT_VALUE)
GLOBAL_HOT_ROOT = Path(GLOBAL_HOT_ROOT_VALUE)
HOST_AVAILABLE = (
    bool(HERMES_ROOT_VALUE)
    and bool(GLOBAL_HOT_ROOT_VALUE)
    and (HERMES_ROOT / "agent" / "conversation_loop.py").is_file()
    and (GLOBAL_HOT_ROOT / "plugin.yaml").is_file()
)

if HOST_AVAILABLE:
    sys.path.insert(0, str(HERMES_ROOT))


SUMMARY_MARKER = re.compile(r"\[END THREAD CONTINUITY SUMMARY [0-9a-f]{64}\]")
CONTINUITY_MARKER = "[THREAD CONTINUITY QUOTED REFERENCE"
GLOBAL_HOT_MARKER = "[GLOBAL HOT QUOTED REFERENCE"


def _provider_response(text: str = "entrypoint answer") -> SimpleNamespace:
    return SimpleNamespace(
        id="entrypoint-response",
        model="entrypoint-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content=text,
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=4,
            total_tokens=104,
        ),
    )


def _sqlite_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


@unittest.skipUnless(
    HOST_AVAILABLE,
    "set HERMES_SOURCE_ROOT and HERMES_GLOBAL_HOT_ROOT to run real host proof",
)
class RealHostEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name) / ".hermes"
        plugin_dir = self.home / "plugins"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "hermes-continuity").symlink_to(
            CONTINUITY_ROOT, target_is_directory=True
        )
        (plugin_dir / "hermes-global-hot").symlink_to(
            GLOBAL_HOT_ROOT, target_is_directory=True
        )
        (self.home / "config.yaml").write_text(
            "plugins:\n"
            "  enabled:\n"
            "    - hermes-continuity\n"
            "    - hermes-global-hot\n"
            "auxiliary:\n"
            "  title_generation:\n"
            "    enabled: false\n",
            encoding="utf-8",
        )
        self.env = patch.dict(os.environ, {"HERMES_HOME": str(self.home)})
        self.env.start()
        global AIAgent, PluginLlmCompleteResult, PluginLlmUsage, SessionDB
        global context_compressor, hermes_config, model_metadata, plugins
        global relay_llm, relay_runtime
        from agent import context_compressor, model_metadata, relay_llm, relay_runtime
        from agent.plugin_llm import PluginLlmCompleteResult, PluginLlmUsage
        from hermes_cli import config as hermes_config
        from hermes_cli import plugins
        from hermes_state import SessionDB
        from run_agent import AIAgent

        hermes_config._config_cache = None
        plugins._reset_plugin_managers_for_tests()
        self.agents = []

        self.session_db = SessionDB(self.home / "state.db")
        now = time.time()
        self.session_db.create_session("mouth-a", "cli")
        self.session_db.append_message(
            "mouth-a",
            "user",
            "A mouth recently asked about blue lanterns",
            timestamp=now - 120,
        )
        self.session_db.append_message(
            "mouth-a",
            "assistant",
            "A mouth received the blue-lantern answer",
            timestamp=now - 119,
        )
        self.session_db.create_session("mouth-b", "cli")
        for index in range(4):
            self.session_db.append_message(
                "mouth-b",
                "user",
                f"durable history user {index}: " + ("u" * 3_000),
                timestamp=now - 10_000 + index * 2,
            )
            self.session_db.append_message(
                "mouth-b",
                "assistant",
                f"durable history answer {index}: " + ("a" * 3_000),
                timestamp=now - 9_999 + index * 2,
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
        self.env.stop()
        self.tempdir.cleanup()

    @staticmethod
    async def _summary_complete(_self, messages, **_kwargs):
        rendered = "\n".join(str(row.get("content") or "") for row in messages)
        marker = SUMMARY_MARKER.search(rendered)
        if marker is None:
            raise AssertionError("Continuity summary marker missing from host LLM call")
        return PluginLlmCompleteResult(
            text="durable rolling bridge\n" + marker.group(0),
            provider="entrypoint-provider",
            model="entrypoint-summary-model",
            agent_id="default",
            usage=PluginLlmUsage(input_tokens=100, output_tokens=8, total_tokens=108),
            finish_reason="stop",
        )

    def _agent(self, platform: str = "cli") -> AIAgent:
        agent = AIAgent(
            api_key="test-key",
            base_url="http://127.0.0.1:1/v1",
            provider="openai-compat",
            model="entrypoint-model",
            max_iterations=1,
            max_tokens=256,
            enabled_toolsets=[],
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            save_trajectories=False,
            platform=platform,
            session_id="mouth-b",
            session_db=self.session_db,
        )
        agent._api_max_retries = 1
        agent._build_api_kwargs = lambda messages: {
            "model": agent.model,
            "messages": messages,
            "max_tokens": 256,
        }
        agent._try_recover_primary_transport = lambda *_args, **_kwargs: False
        agent._try_activate_fallback = lambda *_args, **_kwargs: False
        agent._has_pending_fallback = lambda: False
        agent.context_compressor.context_length = 4_096
        resolution = {
            "tokens": 4_096,
            "source": "config",
            "confidence": "authoritative",
        }
        agent._context_window_resolution = resolution
        agent.context_compressor._context_window_resolution = resolution
        return agent

    def test_real_discovery_conversation_settlement_and_restart(self) -> None:
        provider_bodies: list[dict] = []

        def acquire_without_relay(**kwargs):
            return relay_runtime.ConversationLease(
                profile_key=kwargs["profile_key"],
                session_id=kwargs["session_id"],
                platform=kwargs["platform"],
                host=relay_runtime.NoopRelayRuntime(
                    kwargs["profile_key"], "entrypoint test"
                ),
                session=None,
                parent_session_id=kwargs.get("parent_session_id", ""),
            )

        def provider(request, *, on_first_delta=None):
            del on_first_delta
            with relay_llm.provider_body_scope(request):
                provider_bodies.append(request)
                return _provider_response()

        async def fake_acomplete(plugin_llm, messages, **kwargs):
            return await self._summary_complete(plugin_llm, messages, **kwargs)

        with (
            patch.object(
                AIAgent,
                "_create_openai_client",
                lambda *_a, **_kw: SimpleNamespace(),
            ),
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
            patch.dict(sys.modules, {"httpx": types.ModuleType("httpx")}),
            patch.object(
                relay_runtime,
                "resolve_execution_context",
                lambda _sid: (None, None, None),
            ),
            patch.object(
                relay_runtime.SESSION_COORDINATOR,
                "acquire_conversation",
                side_effect=acquire_without_relay,
            ),
            patch.object(
                relay_runtime.SESSION_COORDINATOR,
                "finalize_conversation",
                lambda **_kwargs: None,
            ),
        ):
            plugins.discover_plugins()
            manager = plugins.get_plugin_manager()
            loaded = {row["name"]: row for row in manager.list_plugins()}
            self.assertEqual(loaded["hermes-continuity"]["error"], None)
            self.assertTrue(loaded["hermes-continuity"]["enabled"])
            self.assertEqual(loaded["hermes-global-hot"]["error"], None)
            self.assertTrue(loaded["hermes-global-hot"]["enabled"])

            agent = self._agent()
            self.agents.append(agent)
            agent._interruptible_streaming_api_call = provider
            result = agent.run_conversation(
                "What should this mouth remember?",
                conversation_history=[],
                task_id="entrypoint-turn-1",
            )

            self.assertEqual(result["final_response"], "entrypoint answer")
            self.assertEqual(len(provider_bodies), 1)
            rendered = repr(provider_bodies[0])
            self.assertEqual(rendered.count(CONTINUITY_MARKER), 1)
            self.assertEqual(rendered.count(GLOBAL_HOT_MARKER), 1)
            self.assertIn("blue lanterns", rendered)

            continuity_paths = list(
                (self.home / "plugin-data").glob("*/continuity.sqlite3")
            )
            hot_paths = list(
                (self.home / "plugin-data").glob("*/global_hot.sqlite3")
            )
            self.assertEqual(len(continuity_paths), 1)
            self.assertEqual(len(hot_paths), 1)
            continuity_db = continuity_paths[0]
            hot_db = hot_paths[0]
            self.assertEqual(_sqlite_count(continuity_db, "continuity_checkpoints"), 1)
            self.assertEqual(_sqlite_count(continuity_db, "continuity_receipts"), 1)
            self.assertEqual(_sqlite_count(hot_db, "global_hot_delivery_receipts"), 1)
            with sqlite3.connect(continuity_db) as connection:
                first_revision = int(
                    connection.execute(
                        "SELECT revision FROM continuity_checkpoints "
                        "WHERE session_id = ?",
                        ("mouth-b",),
                    ).fetchone()[0]
                )

            now = time.time()
            self.session_db.append_message(
                "mouth-b",
                "user",
                "history added before process restart: " + ("r" * 3_000),
                timestamp=now,
            )
            self.session_db.append_message(
                "mouth-b",
                "assistant",
                "restart-safe history answer: " + ("s" * 3_000),
                timestamp=now + 1,
            )

            plugins._reset_plugin_managers_for_tests()
            hermes_config._config_cache = None
            plugins.discover_plugins()
            restarted_agent = self._agent(platform="telegram")
            self.agents.append(restarted_agent)
            restarted_agent._interruptible_streaming_api_call = provider
            restarted = restarted_agent.run_conversation(
                "Does the restarted mouth retain continuity?",
                conversation_history=[],
                task_id="entrypoint-turn-2",
            )
            self.assertEqual(restarted["final_response"], "entrypoint answer")
            self.assertEqual(len(provider_bodies), 2)
            restarted_rendered = repr(provider_bodies[1])
            self.assertEqual(restarted_rendered.count(CONTINUITY_MARKER), 1)
            self.assertEqual(restarted_rendered.count(GLOBAL_HOT_MARKER), 1)
            self.assertIn(
                f"checkpoint_revision={first_revision}", restarted_rendered
            )
            with sqlite3.connect(continuity_db) as connection:
                revision = connection.execute(
                    "SELECT revision FROM continuity_checkpoints WHERE session_id = ?",
                    ("mouth-b",),
                ).fetchone()
            self.assertIsNotNone(revision)
            self.assertGreaterEqual(int(revision[0]), first_revision)
            self.assertEqual(_sqlite_count(continuity_db, "continuity_receipts"), 2)
            self.assertEqual(_sqlite_count(hot_db, "global_hot_delivery_receipts"), 2)

            failed_provider_calls = []

            def failing_provider(request, *, on_first_delta=None):
                del on_first_delta
                with relay_llm.provider_body_scope(request):
                    failed_provider_calls.append(request)
                    raise RuntimeError("entrypoint provider failure")

            failing_agent = self._agent(platform="telegram")
            self.agents.append(failing_agent)
            failing_agent._interruptible_streaming_api_call = failing_provider
            failed = failing_agent.run_conversation(
                "This provider call must not settle",
                conversation_history=[],
                task_id="entrypoint-turn-error",
            )
            self.assertFalse(failed["completed"])
            self.assertEqual(len(failed_provider_calls), 1)
            self.assertEqual(_sqlite_count(continuity_db, "continuity_receipts"), 2)
            self.assertEqual(_sqlite_count(hot_db, "global_hot_delivery_receipts"), 2)


if __name__ == "__main__":
    unittest.main()
