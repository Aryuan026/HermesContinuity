"""Discovery -> AIAgent -> final body -> post/error -> reload, with a live hole."""
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_real_host_long_history_v3 as host
from test_recall import RecallLlm


@unittest.skipUnless(host.HOST_AVAILABLE and (host.HERMES_ROOT / "hermes_history_content.py").is_file(),
                     "requires streamed history plus bounded native search")
class RealHostRecallTests(unittest.TestCase):
    historical_image_bytes = 16 * 1024 * 1024
    tearDown = host.RealHostLongHistoryV3Tests.tearDown
    _agent = host.RealHostLongHistoryV3Tests._agent
    _prepare_index = host.RealHostLongHistoryV3Tests._prepare_index
    _continuity_status = host.RealHostLongHistoryV3Tests._continuity_status
    _diagnostics = host.RealHostLongHistoryV3Tests._diagnostics
    _acquire_without_relay = staticmethod(host.RealHostLongHistoryV3Tests._acquire_without_relay)

    def setUp(self):
        host.RealHostLongHistoryV3Tests.setUp(self)
        if not hasattr(self.session_db, "search_history_matches"):
            self.tearDown()
            self.skipTest("requires bounded native search")
        self.session_db._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=1,compacted=0 WHERE id IN "
            "(SELECT id FROM messages WHERE content LIKE '%bounded history 10')"))
        self.session_db.append_message("long-mouth", "user", "樱桃项目预算")
        self.session_db.append_message("long-mouth", "assistant", "12万元，尚未确认")
        self.llm = RecallLlm()

    def test_real_entrypoint_recall_settlement_reload_and_provider_error(self):
        bodies = []
        def provider(request, *, on_first_delta=None):
            with host.relay_llm.provider_body_scope(request):
                bodies.append(request)
                return host._provider_response()

        async def auxiliary(_plugin_llm, messages, **kwargs):
            return await self.llm.acomplete(messages, **kwargs)

        with (
            patch.object(host.AIAgent, "_create_openai_client", lambda *_a, **_kw: SimpleNamespace()),
            patch.object(host.ssl_guard, "verify_ca_bundle_with_fallback", lambda: None),
            patch.object(host.model_metadata, "get_model_context_length", lambda *_a, **_kw: 128000),
            patch.object(host.context_compressor, "get_model_context_length", lambda *_a, **_kw: 128000),
            patch("agent.plugin_llm.PluginLlm.acomplete", new=auxiliary),
            patch.object(host.relay_runtime, "resolve_execution_context", lambda _sid: (None, None, None)),
            patch.object(host.relay_runtime.SESSION_COORDINATOR, "acquire_conversation",
                         side_effect=self._acquire_without_relay),
            patch.object(host.relay_runtime.SESSION_COORDINATOR, "finalize_conversation", lambda **_kw: None),
        ):
            for number in range(2):
                host.plugins.discover_plugins()
                self._prepare_index()
                agent = self._agent()
                self.agents.append(agent)
                agent._interruptible_streaming_api_call = provider
                result = agent.run_conversation("之前樱桃项目的预算定了吗？",
                    conversation_history=[], task_id=f"recall-{number}")
                self.assertEqual(result["final_response"], "long-history answer")
                self.assertEqual(self.last_bundle["source"]["error"], "foreground_group_limit_exceeded")
                self.assertEqual(repr(bodies[-1]).count(host.CONTINUITY_MARKER), 1, self._diagnostics())
                self.assertIn("12万元", repr(bodies[-1]))
                self.assertNotIn("data:image/", repr(bodies[-1]))
                ledger = next((self.home / "plugin-data").glob("*/continuity.sqlite3"))
                with sqlite3.connect(ledger) as connection:
                    receipts = connection.execute("SELECT status,hashes_json FROM continuity_receipts").fetchall()
                    self.assertEqual(len(receipts), number+1)
                    self.assertTrue(all(row[0] == "delivered_recall" for row in receipts))
                    self.assertTrue(all("recall_source_sha256" in json.loads(row[1]) for row in receipts))
                    self.assertNotIn("12万元", repr(receipts))
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_checkpoints_v3").fetchone()[0], 0)
                if number == 0:
                    host.plugins._reset_plugin_managers_for_tests()
                    host.hermes_config._config_cache = None
            def failing(request, *, on_first_delta=None):
                with host.relay_llm.provider_body_scope(request):
                    raise RuntimeError("synthetic recall provider failure")
            self._prepare_index()
            agent = self._agent()
            self.agents.append(agent)
            agent._interruptible_streaming_api_call = failing
            result = agent.run_conversation("樱桃项目预算", conversation_history=[], task_id="recall-error")
            self.assertFalse(result["completed"])
            self.assertEqual(host._sqlite_count(ledger, "continuity_receipts"), 2)
            self.assertEqual(self.llm.calls, ["thread_continuity_recall_query", "thread_continuity_recall_summary"]*3)
