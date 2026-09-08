"""Continuity-only proof against the accepted Hermes 0.21 host.

The test enters through real plugin discovery and ``AIAgent.run_conversation``.
It exercises provider fallback, post-settlement, checkpoint reuse, and manager
unload/reload without loading Global Hot or copying the canonical transcript.
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
HERMES_ROOT = Path(HERMES_ROOT_VALUE)
HOST_AVAILABLE = bool(HERMES_ROOT_VALUE) and (
    HERMES_ROOT / "agent" / "conversation_loop.py"
).is_file()

if HOST_AVAILABLE:
    sys.path.insert(0, str(HERMES_ROOT))


SUMMARY_MARKER = re.compile(r"\[END THREAD CONTINUITY SUMMARY [0-9a-f]{64}\]")
CONTINUITY_MARKER = "[THREAD CONTINUITY QUOTED REFERENCE"


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


class _NonRetryableProviderError(RuntimeError):
    status_code = 400

    def __init__(self) -> None:
        super().__init__("Error code: 400 - unsupported primary request")
        self.response = SimpleNamespace(status_code=400, headers={})


@unittest.skipUnless(
    HOST_AVAILABLE,
    "set HERMES_SOURCE_ROOT to run the Hermes 0.21 Continuity proof",
)
class RealHost021ContinuityTests(unittest.TestCase):
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

        # The host checkout is intentionally sparse and omits built-in browser
        # provider packages. ``run_agent`` imports their legacy class aliases at
        # module load even though this test enables no tools, so provide the
        # smallest inert import surface rather than fetching unrelated plugins.
        plugin_stubs = {
            name: types.ModuleType(name)
            for name in (
                "plugins",
                "plugins.browser",
                "plugins.browser.browserbase",
                "plugins.browser.browser_use",
                "plugins.browser.firecrawl",
                "plugins.browser.browserbase.provider",
                "plugins.browser.browser_use.provider",
                "plugins.browser.firecrawl.provider",
                "plugins.web",
                "plugins.web.firecrawl",
                "plugins.web.parallel",
                "plugins.web.exa",
                "plugins.web.firecrawl.provider",
                "plugins.web.parallel.provider",
                "plugins.web.exa.provider",
                "plugins.video_gen",
                "plugins.video_gen.xai",
            )
        }
        for name in (
            "plugins",
            "plugins.browser",
            "plugins.browser.browserbase",
            "plugins.browser.browser_use",
            "plugins.browser.firecrawl",
            "plugins.web",
            "plugins.web.firecrawl",
            "plugins.web.parallel",
            "plugins.web.exa",
            "plugins.video_gen",
        ):
            plugin_stubs[name].__path__ = []
        plugin_stubs[
            "plugins.browser.browserbase.provider"
        ].BrowserbaseBrowserProvider = type("BrowserbaseBrowserProvider", (), {})
        plugin_stubs[
            "plugins.browser.browser_use.provider"
        ].BrowserUseBrowserProvider = type("BrowserUseBrowserProvider", (), {})
        plugin_stubs[
            "plugins.browser.firecrawl.provider"
        ].FirecrawlBrowserProvider = type("FirecrawlBrowserProvider", (), {})
        firecrawl = plugin_stubs["plugins.web.firecrawl.provider"]
        firecrawl.Firecrawl = None
        for name in (
            "_firecrawl_backend_help_suffix",
            "_get_firecrawl_client",
            "_get_firecrawl_gateway_url",
            "_is_tool_gateway_ready",
            "check_firecrawl_api_key",
        ):
            setattr(firecrawl, name, lambda *_args, **_kwargs: None)
        parallel = plugin_stubs["plugins.web.parallel.provider"]
        parallel._get_async_parallel_client = lambda *_args, **_kwargs: None
        parallel._get_parallel_client = lambda *_args, **_kwargs: None
        plugin_stubs[
            "plugins.web.exa.provider"
        ]._get_exa_client = lambda *_args, **_kwargs: None
        video = plugin_stubs["plugins.video_gen.xai"]
        video.has_xai_video_credentials = lambda: False
        video.run_xai_video_edit = lambda **_kwargs: None
        video.run_xai_video_extend = lambda **_kwargs: None
        self.browser_plugins = patch.dict(sys.modules, plugin_stubs)
        self.browser_plugins.start()

        global AIAgent, PluginLlmCompleteResult, PluginLlmUsage, SessionDB
        global context_compressor, hermes_config, model_metadata, plugins
        global relay_llm, relay_runtime, human_origin
        from agent import context_compressor, model_metadata, relay_llm, relay_runtime
        from agent.message_origin import CLI_USER, build_message_origin_proof
        from agent.plugin_llm import PluginLlmCompleteResult, PluginLlmUsage
        from hermes_cli import config as hermes_config
        from hermes_cli import plugins
        from hermes_state import SessionDB
        from run_agent import AIAgent

        human_origin = build_message_origin_proof(CLI_USER)
        hermes_config._config_cache = None
        plugins._reset_plugin_managers_for_tests()
        self.agents = []

        self.session_db = SessionDB(self.home / "state.db")
        self.session_db.create_session("mouth-b", "qqbot")
        now = time.time()
        for index in range(4):
            self.session_db.append_message(
                "mouth-b",
                "user",
                f"durable history user {index}: " + ("u" * 3_000),
                timestamp=now - 10_000 + index * 2,
                origin_proof=human_origin,
            )
            self.session_db.append_message(
                "mouth-b",
                "assistant",
                f"durable history answer {index}: " + ("a" * 3_000),
                timestamp=now - 9_999 + index * 2,
                origin_proof=human_origin,
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
        self.browser_plugins.stop()
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

    def _agent(self) -> AIAgent:
        agent = AIAgent(
            api_key="test-key",
            base_url="http://127.0.0.1:1/v1",
            provider="openai-compat",
            model="entrypoint-primary-model",
            max_iterations=1,
            max_tokens=256,
            enabled_toolsets=[],
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            save_trajectories=False,
            platform="qqbot",
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
        agent.context_compressor.context_length = 4_096
        resolution = {
            "tokens": 4_096,
            "source": "config",
            "confidence": "authoritative",
        }
        agent._context_window_resolution = resolution
        agent.context_compressor._context_window_resolution = resolution
        return agent

    def test_fallback_settlement_next_turn_reuse_and_manager_reload(self) -> None:
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

        async def fake_acomplete(plugin_llm, messages, **kwargs):
            return await self._summary_complete(plugin_llm, messages, **kwargs)

        with (
            patch.object(
                AIAgent,
                "_create_openai_client",
                lambda *_args, **_kwargs: SimpleNamespace(),
            ),
            patch.object(
                model_metadata,
                "get_model_context_length",
                lambda *_args, **_kwargs: 128_000,
            ),
            patch.object(
                context_compressor,
                "get_model_context_length",
                lambda *_args, **_kwargs: 128_000,
            ),
            patch("agent.plugin_llm.PluginLlm.acomplete", new=fake_acomplete),
            patch.dict(sys.modules, {"httpx": types.ModuleType("httpx")}),
            patch.object(
                relay_runtime,
                "resolve_execution_context",
                lambda _session_id: (None, None, None),
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

            agent = self._agent()
            self.agents.append(agent)
            fallback_used = False

            def activate_fallback(*_args, **_kwargs):
                nonlocal fallback_used
                if fallback_used:
                    return False
                fallback_used = True
                agent._fallback_index = 1
                agent.model = "entrypoint-fallback-model"
                resolution = {
                    "tokens": 8_192,
                    "source": "config",
                    "confidence": "authoritative",
                }
                agent._context_window_resolution = resolution
                agent.context_compressor.context_length = 8_192
                agent.context_compressor._context_window_resolution = resolution
                return True

            agent._fallback_chain = [
                {"provider": "openai-compat", "model": "entrypoint-fallback-model"}
            ]
            agent._fallback_index = 0
            agent._has_pending_fallback = lambda: not fallback_used
            agent._try_activate_fallback = activate_fallback

            def fallback_provider(request, *, on_first_delta=None):
                del on_first_delta
                with relay_llm.provider_body_scope(request):
                    provider_bodies.append(request)
                    if len(provider_bodies) == 1:
                        raise _NonRetryableProviderError()
                    return _provider_response("fallback answer")

            agent._interruptible_streaming_api_call = fallback_provider
            result = agent.run_conversation(
                "What survives provider fallback?",
                conversation_history=[],
                task_id="entrypoint-fallback-turn",
                message_origin_proof=human_origin,
            )

            self.assertTrue(fallback_used)
            self.assertEqual(result["final_response"], "fallback answer")
            self.assertEqual(len(provider_bodies), 2)
            self.assertTrue(
                all(repr(body).count(CONTINUITY_MARKER) == 1 for body in provider_bodies)
            )

            continuity_paths = list(
                (self.home / "plugin-data").glob("*/continuity.sqlite3")
            )
            self.assertEqual(len(continuity_paths), 1)
            continuity_db = continuity_paths[0]
            self.assertEqual(_sqlite_count(continuity_db, "continuity_checkpoints"), 1)
            self.assertEqual(_sqlite_count(continuity_db, "continuity_receipts"), 1)
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
                "history added before manager reload: " + ("r" * 3_000),
                timestamp=now,
                origin_proof=human_origin,
            )
            self.session_db.append_message(
                "mouth-b",
                "assistant",
                "reload-safe history answer: " + ("s" * 3_000),
                timestamp=now + 1,
                origin_proof=human_origin,
            )

            plugins._reset_plugin_managers_for_tests()
            hermes_config._config_cache = None
            plugins.discover_plugins()
            reloaded_agent = self._agent()
            self.agents.append(reloaded_agent)

            def provider(request, *, on_first_delta=None):
                del on_first_delta
                with relay_llm.provider_body_scope(request):
                    provider_bodies.append(request)
                    return _provider_response("reloaded answer")

            reloaded_agent._try_activate_fallback = lambda *_args, **_kwargs: False
            reloaded_agent._has_pending_fallback = lambda: False
            reloaded_agent._interruptible_streaming_api_call = provider
            reloaded = reloaded_agent.run_conversation(
                "Does the next turn retain continuity?",
                conversation_history=[],
                task_id="entrypoint-reloaded-turn",
                message_origin_proof=human_origin,
            )

            self.assertEqual(reloaded["final_response"], "reloaded answer")
            self.assertEqual(len(provider_bodies), 3)
            rendered = repr(provider_bodies[-1])
            self.assertEqual(rendered.count(CONTINUITY_MARKER), 1)
            self.assertIn(f"checkpoint_revision={first_revision}", rendered)
            self.assertEqual(_sqlite_count(continuity_db, "continuity_receipts"), 2)
            with sqlite3.connect(continuity_db) as connection:
                current_revision = int(
                    connection.execute(
                        "SELECT revision FROM continuity_checkpoints "
                        "WHERE session_id = ?",
                        ("mouth-b",),
                    ).fetchone()[0]
                )
            self.assertGreaterEqual(current_revision, first_revision)


if __name__ == "__main__":
    unittest.main()
