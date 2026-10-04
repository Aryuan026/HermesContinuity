from __future__ import annotations

import json
import re
import sqlite3
import copy
import asyncio
from unittest.mock import patch
from types import SimpleNamespace
import unittest

import test_history_index as history
from test_history_index import SessionDB
from test_runtime import ContinuityRuntime, project, execute, post, request, runtime_module


class RecallLlm:
    def __init__(self, *, invalid_id=False, empty=False):
        self.calls = []
        self.invalid_id, self.empty = invalid_id, empty

    async def acomplete(self, messages, **kwargs):
        self.calls.append(kwargs["purpose"])
        rendered = "\n".join(str(row["content"]) for row in messages)
        marker = re.search(r"\[END THREAD CONTINUITY SUMMARY [0-9a-f]{64}\]", rendered).group(0)
        if kwargs["purpose"] == "thread_continuity_recall_query":
            value = {"queries": [] if self.empty else ["樱桃项目"], "start_at": None, "end_at": None}
        elif kwargs["purpose"] == "thread_continuity_summary":
            return SimpleNamespace(text="rolling bridge\n"+marker, finish_reason="stop", usage=None)
        else:
            payload = json.loads(messages[-1]["content"].split("\n\nEnd the response", 1)[0])
            budget = next(group for group in payload["candidate_groups"] if "12万元" in repr(group))
            value = {"selected_group_ids": ["invented-id" if self.invalid_id else budget["group_id"]],
                     "summary": "樱桃项目预算12万元，尚未确认。"}
        return SimpleNamespace(text=json.dumps(value, ensure_ascii=False)+"\n"+marker,
                               finish_reason="stop", usage=None)


@unittest.skipUnless(SessionDB and hasattr(SessionDB, "search_history_matches"),
                     "requires bounded native history search")
class RecallTests(unittest.TestCase):
    tearDown = history.HistoryIndexTests.tearDown
    seed = history.HistoryIndexTests.seed
    prepare = history.HistoryIndexTests.prepare

    def setUp(self):
        history.HistoryIndexTests.setUp(self)
        self.seed(1200)
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=1,compacted=0 WHERE id IN "
            "(SELECT id FROM messages ORDER BY id LIMIT 2 OFFSET 20)"))
        for offset, (question, answer) in enumerate((
                ("樱桃项目预算", "12万元，尚未确认"), ("樱桃项目的配色", "橙色背景"))):
            self.writer.append_message("session-1", "user", question, timestamp=1787965000+offset*2)
            self.writer.append_message("session-1", "assistant", answer, timestamp=1787965001+offset*2)
        self.prepare()
        self.llm = RecallLlm()
        self.runtime = ContinuityRuntime(self.adapter, self.llm,
            clock=lambda: "2026-08-30T00:00:00+00:00")
        self.addCleanup(self.runtime.clear)

    def rows(self):
        with sqlite3.connect(self.store.path) as connection:
            return connection.execute("SELECT status,source_ids_json,hashes_json FROM continuity_receipts").fetchall()

    def test_selected_reference_is_delivered_without_checkpoint_and_retry_reuses_plan(self):
        wire = request("之前樱桃项目的预算定了吗？")
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        text = repr(projected["request"])
        self.assertIn("12万元", text)
        self.assertNotIn("橙色背景", text)
        self.assertEqual(self.llm.calls, ["thread_continuity_recall_query", "thread_continuity_recall_summary"])
        self.assertEqual(self.rows(), [])
        execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(self.rows()[0][0], "delivered_recall")
        self.assertEqual(len(json.loads(self.rows()[0][1])), 1)
        self.assertIn("recall_source_sha256", json.loads(self.rows()[0][2]))
        self.assertNotIn("12万元", repr(self.rows()))
        again = project(self.runtime, wire, session="session-1", api="request-2")
        self.assertIsNotNone(again)
        self.assertEqual(len(self.llm.calls), 2)
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_checkpoints_v3").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM continuity_checkpoints").fetchone()[0], 0)
        self.assertEqual(self.writer._conn.execute("SELECT COUNT(*) FROM messages WHERE active=1 AND compacted=0").fetchone()[0], 6)

    def test_rewrite_before_execution_removes_only_recall_and_records_no_delivery(self):
        wire = request("樱桃项目预算")
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected)
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET content='changed' WHERE content='12万元，尚未确认'"))
        _, received = execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(received, [wire])
        self.assertEqual(self.rows(), [])

    def test_empty_plan_and_invented_selection_are_not_projected(self):
        for flag in ("empty", "invalid_id"):
            self.runtime.clear()
            self.runtime = ContinuityRuntime(self.adapter, RecallLlm(**{flag: True}),
                                             clock=lambda: "2026-08-30T00:00:00+00:00")
            self.assertIsNone(project(self.runtime, request(), session="session-1"))
            self.assertEqual(self.rows(), [])
        self.runtime.clear()

    def test_rewrite_after_provider_keeps_delivery_fact_but_grants_no_retirement(self):
        wire = request("樱桃项目预算")
        projected = project(self.runtime, wire, session="session-1")
        execute(self.runtime, projected["request"], wire, session="session-1")
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET content='changed' WHERE content='12万元，尚未确认'"))
        post(self.runtime, session="session-1")
        self.assertEqual(self.rows()[0][0], "delivered_recall_source_changed")
        self.assertNotIn("12万元", repr(self.rows()))

    def test_auxiliary_deadline_leaves_native_and_releases_admission(self):
        class SlowLlm:
            async def acomplete(self, *args, **kwargs):
                await asyncio.sleep(1)
        self.runtime.plugin_llm = SlowLlm()
        self.runtime.summary_timeout_seconds = 0.01
        self.assertIsNone(project(self.runtime, request(), session="session-1"))
        status = json.loads(self.runtime.status_command())
        self.assertEqual(status["recall_reason_counts"], {"recall_auxiliary_timeout": 1})
        self.assertEqual(self.rows(), [])
        self.runtime.clear()
        from test_runtime import runtime_module
        self.assertFalse(any(key[0] is self.runtime._budget_identity
                             for key in runtime_module.ACTIVE_WORKSETS._leases))

    def test_final_body_budget_removes_only_recall_before_provider(self):
        wire = request("樱桃项目预算")
        projected = project(self.runtime, wire, session="session-1", context_window_tokens=2000)
        self.assertIsNotNone(projected)
        downstream = copy.deepcopy(projected["request"])
        late = "[OTHER OWNER]" + "x"*20000
        downstream["messages"][-1]["content"] += "\n"+late
        _, calls = execute(self.runtime, downstream, wire, session="session-1", context_window_tokens=2000)
        post(self.runtime, session="session-1")
        self.assertEqual(len(calls), 1)
        self.assertIn(late, repr(calls[0]))
        self.assertNotIn("12万元", repr(calls[0]))
        self.assertEqual(self.rows(), [])

    def test_shared_capacity_preserves_original_rolling_bridge(self):
        plan = runtime_module._TurnPlan("current", marker="existing",
            bridge_body="valid rolling bridge", workset_bytes=4*1024*1024)
        async def maximum_recall(*args, **kwargs):
            return {"body": "selected reference", "source_ids": ["selected"],
                    "source_proof": {}, "workset_bytes": 4*1024*1024}
        with patch(runtime_module.__package__+".recall.build_recall", new=maximum_recall):
            result = self.runtime._add_recall(plan, session_id="session-1",
                query="预算", reference_at="2026-08-30T00:00:00+00:00")
        self.assertIs(result, plan)
        self.assertEqual(result.bridge_body, "valid rolling bridge")
        self.assertIsNone(result.recall_proof)
        self.assertEqual(result.recall_reason, "recall_shared_workset_budget")

    def test_rolling_bridge_and_recall_share_one_overlay_and_keep_checkpoint_contract(self):
        self.writer._execute_write(lambda connection: connection.execute(
            "UPDATE messages SET active=0,compacted=1"))
        self.prepare()
        wire = request("樱桃项目预算")
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        self.assertIn("rolling bridge", repr(projected["request"]))
        self.assertIn("12万元", repr(projected["request"]))
        self.assertEqual(repr(projected["request"]).count("[THREAD CONTINUITY QUOTED REFERENCE"), 1)
        execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("recall_source_sha256", json.loads(self.rows()[0][2]))
        with sqlite3.connect(self.store.path) as connection:
            checkpoint = json.loads(connection.execute("SELECT checkpoint_json FROM continuity_checkpoints_v3").fetchone()[0])
        self.assertNotIn("QUESTION-SELECTED", repr(checkpoint))
