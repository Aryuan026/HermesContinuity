"""Bounded calendar pages through the real index and physical settlement hooks."""
import importlib
import unittest
from unittest.mock import patch

import test_history_index as history
from test_recall import RecallLlm
from test_runtime import ContinuityRuntime, execute, post, project, request, runtime_module

recall = importlib.import_module(runtime_module.__package__ + ".recall")
calendar = importlib.import_module(runtime_module.__package__ + ".temporal_recall")


class CalendarTests(unittest.TestCase):
    def test_calendar_ranges_and_event_dates_are_distinct(self):
        for query, start, end in (
            ("回顾2026年8月的聊天", "2026-07-31T16:00:00", "2026-08-31T15:59:59"),
            ("回顾八月一日到三日的对话", "2026-07-31T16:00:00", "2026-08-03T15:59:59"),
            ("回顾2025年12月到2026年1月的聊天", "2025-11-30T16:00:00", "2026-01-31T15:59:59"),
            ("昨天聊了什么", "2026-08-28T16:00:00", "2026-08-29T15:59:59"),
        ):
            with self.subTest(query=query):
                plan = calendar.build_temporal_recall_plan(query=query, reference_time="2026-08-30T12:00:00+08:00")
                self.assertEqual(plan["retrieval_mode"], "timeline", plan)
                self.assertTrue(plan["window_start_utc"].startswith(start), plan)
                self.assertTrue(plan["window_end_utc"].startswith(end), plan)
                self.assertIn(".999999", plan["window_end_utc"])
        for query in ("12月6日 的安排？", "八月的相机预算", "2026年2月30日聊了什么", "8月20日到8月10日聊了什么"):
            with self.subTest(query=query):
                self.assertNotEqual(calendar.build_temporal_recall_plan(query=query,
                    reference_time="2026-08-30T00:00:00+00:00").get("retrieval_mode"), "timeline")


@unittest.skipUnless(history.SessionDB and hasattr(history.SessionDB, "search_history_matches"),
                     "requires accepted bounded-history host")
class TimelineTests(unittest.TestCase):
    tearDown = history.HistoryIndexTests.tearDown
    prepare = history.HistoryIndexTests.prepare

    def setUp(self):
        history.HistoryIndexTests.setUp(self)
        history.HistoryIndexTests.seed(self, 1200)
        # Keep the existing long-history/live-hole gate, outside the recap range.
        self.writer._execute_write(lambda c: c.execute("UPDATE messages SET timestamp=timestamp-5184000"))
        self.writer._execute_write(lambda c: c.execute(
            "UPDATE messages SET active=1,compacted=0 WHERE id IN (SELECT id FROM messages ORDER BY id LIMIT 2 OFFSET 20)"))
        for number in range(7):
            self.pair(f"topic-{number}", 1785628800+number*86400)
        self.pair("future", 1788134400)
        self.writer.create_session("foreign", "cli")
        self.writer.append_message("foreign", "user", "foreign secret", timestamp=1785628800)
        self.writer.append_message("foreign", "assistant", "not this domain", timestamp=1785628801)
        self.prepare()
        self.llm = RecallLlm()
        self.runtime = self.new_runtime()

    def new_runtime(self):
        runtime = ContinuityRuntime(self.adapter, self.llm, clock=lambda: "2026-08-30T00:00:00+00:00")
        self.addCleanup(runtime.clear)
        return runtime

    def pair(self, text, stamp):
        self.writer.append_message("session-1", "user", text, timestamp=stamp)
        self.writer.append_message("session-1", "assistant", "answer "+text, timestamp=stamp+1)

    def receipt(self):
        return self.store.status_summary("session-1")["last_delivery"]

    def page(self, wire, turn, *, settle=True):
        projected = project(self.runtime, wire, session="session-1", turn=turn)
        self.assertIsNotNone(projected, self.runtime.status_command())
        execute(self.runtime, projected["request"], wire, session="session-1", turn=turn, settle=settle)
        post(self.runtime, session="session-1", turn=turn)
        return projected["request"]

    def test_first_page_continue_reload_and_normal_appends(self):
        wire = request("回顾2026年8月的聊天")
        first = self.page(wire, "first")
        for number in range(4):
            self.assertIn(f"topic-{number}", repr(first))
        for text in ("topic-4", "future", "foreign secret", "user 0"):
            self.assertNotIn(text, repr(first))
        self.assertIn("timeline_complete=false", repr(first))
        first_receipt = self.receipt()
        self.assertEqual(first_receipt["counts"]["timeline_after_ordinal"], 1204)
        self.pair("new ordinary turn", 1787968000)
        self.prepare()
        self.runtime = self.new_runtime()  # No in-memory cursor survives.
        wire["messages"] += [{"role": "assistant", "content": "first page answer"}, {"role": "user", "content": "继续回顾"}]
        second = self.page(wire, "second")
        for number in range(4, 7):
            self.assertIn(f"topic-{number}", repr(second))
        for text in ("topic-0", "new ordinary turn", "future"):
            self.assertNotIn(text, repr(second))
        self.assertIn("timeline_complete=true", repr(second))
        self.assertEqual(self.receipt()["counts"]["timeline_snapshot_groups"], first_receipt["counts"]["timeline_snapshot_groups"])
        self.assertEqual(self.llm.calls, [])
        self.assertNotIn("topic-", repr(self.receipt()))
        wire["messages"] += [{"role": "assistant", "content": "second page answer"}, {"role": "user", "content": "下一页"}]
        last = self.page(wire, "done")
        self.assertIn("No complete groups", repr(last))
        self.assertEqual(self.receipt()["counts"]["timeline_more"], 0)

    def test_undelivered_attempt_retry_does_not_advance_or_borrow_another_topic(self):
        wire = request("回顾2026年8月的聊天")
        self.page(wire, "first")
        first_receipt = self.receipt()
        wire["messages"] += [{"role": "assistant", "content": "answer"}, {"role": "user", "content": "继续回顾"}]
        failed = self.page(wire, "failed", settle=False)
        self.assertEqual(self.receipt(), first_receipt)
        wire["messages"] += [{"role": "user", "content": "继续回顾"}]
        retried = self.page(wire, "retry")
        self.assertEqual(failed["messages"][-1]["content"].count("topic-4"), retried["messages"][-1]["content"].count("topic-4"))
        self.assertIn("topic-4", repr(retried))
        wire["messages"] += [{"role": "user", "content": "换个话题"}, {"role": "user", "content": "继续回顾"}]
        self.assertIsNone(project(self.runtime, wire, session="session-1", turn="unrelated"))
        self.assertEqual(len(self.llm.calls), 0)

    def test_budget_clipping_does_not_skip_unrepresented_groups(self):
        self.runtime.estimator = lambda messages: sum(len(str(m["content"])) for m in messages)
        self.runtime.output_token_limit = 800
        wire = request("回顾2026年8月的聊天")
        result = self.page(wire, "small")
        count = self.receipt()["counts"]["timeline_after_ordinal"]-1200
        self.assertGreater(count, 0)
        self.assertLess(count, 4)
        wire["messages"] += [{"role": "assistant", "content": "answer"}, {"role": "user", "content": "继续回顾"}]
        self.runtime.output_token_limit = 2048
        next_page = self.page(wire, "next")
        self.assertIn(f"topic-{count}", repr(next_page))
        self.assertIn("timeline_complete=false", repr(result))

    def test_snapshot_rewrite_group_rule_and_foreign_proof_are_rejected(self):
        index = self.adapter.history_index
        source = index.read_timeline("session-1", start_at="2026-08-01T00:00:00+00:00", end_at="2026-08-30T00:00:00+00:00")
        with self.assertRaises(ValueError):
            index.validate_recall(source["source_proof"], session_id="foreign")
        with patch.object(index, "grouping_rule", "different"):
            self.assertNotEqual(index.read_timeline("session-1", cursor=source["timeline"])["status"], "ready")
        self.writer._execute_write(lambda c: c.execute("UPDATE messages SET content='rewritten' WHERE content='topic-0'"))
        with self.assertRaises(ValueError):
            index.validate_recall(source["source_proof"], session_id="session-1")
        self.prepare()
        with self.assertRaisesRegex(ValueError, "source_changed"):
            index.read_timeline("session-1", cursor=source["timeline"])

    def test_missing_delivery_and_too_small_budget_leave_native_request_unchanged(self):
        self.assertIsNone(project(self.runtime, request("继续回顾"), session="session-1", turn="absent"))
        self.runtime.output_token_limit = 129
        with patch.object(self.runtime, "estimator", lambda messages: sum(len(str(m["content"])) for m in messages)):
            self.assertIsNone(project(self.runtime, request("回顾2026年8月的聊天"), session="session-1", turn="budget"))
        self.assertIsNone(self.receipt())
        self.assertEqual(self.llm.calls, [])

    def test_empty_snapshot_stays_empty_after_append_and_day_end_is_inclusive(self):
        index = self.adapter.history_index
        self.writer.create_session("empty", "cli")
        for _ in range(100):
            if index.prepare_step("empty")["status"] == "ready":
                break
        window = {"start_at": "2026-08-01T00:00:00+00:00", "end_at": "2026-08-31T23:59:59.999999+00:00"}
        empty = index.read_timeline("empty", **window)
        stamp = 1788220799.999999
        self.writer.append_message("empty", "user", "last microsecond", timestamp=stamp)
        self.writer.append_message("empty", "assistant", "day end answer", timestamp=stamp)
        for _ in range(100):
            if index.prepare_step("empty")["status"] == "ready":
                break
        self.assertEqual(index.read_timeline("empty", cursor=empty["timeline"])["groups"], [])
        fresh = index.read_timeline("empty", **window)
        self.assertEqual(len(fresh["groups"]), 1)
        self.assertIn("day end answer", repr(fresh["groups"]))
