"""Neutral recall-quality checks adapted from the reviewed mother-owner cases."""
import asyncio
import importlib
import json
import unittest
from unittest.mock import AsyncMock

import test_recall as existing
from test_runtime import execute, post, project, request, runtime_module

recall = importlib.import_module(runtime_module.__package__ + ".recall")


def group(key, human, answer, stamp="2026-08-29T12:00:00+00:00"):
    return {"source_prefix_id": key, "effective_event_at": stamp,
            "messages": [{"role": "user", "content": human}, {"role": "assistant", "content": answer}]}


class Index:
    def __init__(self, groups):
        self.groups, self.calls, self.validated = groups, [], []

    def read_recall(self, session_id, queries, **kwargs):
        self.calls.append((session_id, queries, kwargs))
        terms = [t.strip() for q in queries for t in q.split(" OR ")]
        groups = [g for g in self.groups if any(t.lower() in repr(g["messages"]).lower() for t in terms)]
        return {"status": "ready", "groups": groups, "source_proof": {
            "groups": [{"group_id": g["source_prefix_id"]} for g in groups]},
            "stats": {"workset_bytes": len(json.dumps(groups).encode())}}

    def validate_recall(self, proof, **kwargs):
        self.validated.append(proof)


class LexicalUnitTests(unittest.TestCase):
    def build(self, index, query, **kwargs):
        self.auxiliary = AsyncMock(side_effect=AssertionError("recall auxiliary must stay off"))
        result = asyncio.run(recall.build_recall(index, self.auxiliary,
            session_id="test-session", query=query, reference_at="2026-08-30T00:00:00+00:00",
            estimate_messages=lambda messages: sum(len(str(m["content"])) for m in messages),
            source_token_limit=24000, output_token_limit=2048, **kwargs))
        self.auxiliary.assert_not_called()
        return result

    def test_short_chinese_objects_and_english_terms_keep_original_answers(self):
        for question, human, answer in (
            ("水杯现在放在哪里呢", "水杯收好了。", "在右侧抽屉里。"),
            ("还记得我买的枕头是什么材质吗", "枕头填充物", "荞麦壳，不能水洗。"),
            ("昨天那个陶杯是谁送给我的来着", "陶杯是谁送的", "不是同事，是海宁送的。"),
            ("How much did the Orion V3 repair cost?", "Orion V3 repair cost", "240, not 420."),
        ):
            with self.subTest(question=question):
                index = Index([group("fact", human, answer), group("noise", "晚上看云。", "晴天。")])
                result = self.build(index, question)
                self.assertEqual(result["source_ids"], ["fact"])
                self.assertIn(answer, result["body"])
                self.assertIn("[user]", result["body"])
                self.assertIn("[assistant]", result["body"])
                self.assertIn("semantic selection not requested", result["body"])
                self.assertEqual(len(index.calls), 1)
                self.assertTrue(all(len(q) <= 80 for q in index.calls[0][1]))

    def test_pronoun_borrows_visible_subject_but_new_named_object_does_not(self):
        for model in ("Nimbus R7", "Quartz P4"):
            with self.subTest(model=model):
                index = Index([group("fact", model, "支持离线只读模式。"),
                               group("noise", "这个装饰物能用来计时。", "可以。")])
                result = self.build(index, "它还有哪些功能呀", recent_query=f"刚装好了 {model}。")
                self.assertEqual(result["source_ids"], ["fact"])
                self.assertIsNone(self.build(index, "这个围巾怎么清洗？", recent_query=f"刚装好了 {model}。"))

    def test_rank_and_passage_preserve_fact_condition_not_recent_noise(self):
        fact = "磁轨校准前必须关闭线圈供电，等指示灯熄灭后才能拆罩。"
        original = "无关的包装信息。" * 40 + fact + "外壳的说明。" * 40
        index = Index([group("weak", "旧模型从外表看不出差别。", "是的。"),
                       group("fact", "磁轨校准的条件？", original)])
        result = self.build(index, "磁轨校准以后看不出线圈供电变化")
        self.assertEqual(result["source_ids"][0], "fact")
        self.assertIn(fact, result["body"])
        self.assertIn("…", result["body"])
        self.assertNotIn(original, result["body"])
        self.assertEqual(original, index.groups[1]["messages"][1]["content"])

    def test_empty_unrelated_bounds_and_read_failure_are_not_semantic_success(self):
        index = Index([group("fact", "磁轨校准", "先断电。")])
        for query in ("", "你好呀", "我喜欢草莓", "x" * 4097):
            self.assertIsNone(self.build(index, query))
        index.read_recall = lambda *_args, **_kwargs: {"status": "pending"}
        with self.assertRaisesRegex(ValueError, "recall_source_unavailable"):
            self.build(index, "磁轨校准")

    def test_excerpt_boundaries_and_large_group_do_not_forge_complete_evidence(self):
        for length in (119, 120, 121, 220, 221):
            text = "前" * (length - 8) + "别忘了先断电。"
            excerpt = recall._excerpt(text, ["断电"], 120)
            self.assertLessEqual(len(excerpt), 120)
            self.assertTrue(excerpt.endswith("别忘了先断电。"))
        index = Index([group("huge", "磁轨校准", "很长" * 13000)])
        self.assertIsNone(self.build(index, "磁轨校准"))


@unittest.skipUnless(existing.SessionDB and hasattr(existing.SessionDB, "search_history_matches"), "requires native history search")
class LexicalNativeTests(unittest.TestCase):
    setUp = existing.RecallTests.setUp
    tearDown = existing.RecallTests.tearDown
    seed = existing.RecallTests.seed
    prepare = existing.RecallTests.prepare
    rows = existing.RecallTests.rows

    def test_native_fts_final_body_settlement_and_retry_with_zero_auxiliary_calls(self):
        self.runtime.recall_auxiliary_enabled = False
        wire = request("之前樱桃项目的预算定了吗？")
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        self.assertIn("12万元", repr(projected["request"]))
        self.assertEqual(self.llm.calls, [])
        execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(self.rows()[0][0], "delivered_recall")
        self.assertNotIn("12万元", repr(self.rows()))
        self.assertIsNotNone(project(self.runtime, wire, session="session-1", api="request-2"))
        self.assertEqual(self.llm.calls, [])

    def test_original_visible_context_supplies_pronoun_not_overlay_or_tool_text(self):
        self.runtime.recall_auxiliary_enabled = False
        wire = request("它的预算定了吗？")
        wire["messages"][:0] = [{"role": "user", "content": "樱桃项目预算"},
                                {"role": "assistant", "content": "我们接着看。"}]
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        self.assertIn("12万元", repr(projected["request"]))
        self.assertEqual(self.llm.calls, [])

    def test_rewritten_source_removes_lexical_reference_before_provider(self):
        self.runtime.recall_auxiliary_enabled = False
        wire = request("樱桃项目预算")
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected)
        self.writer._execute_write(lambda c: c.execute(
            "UPDATE messages SET content='changed' WHERE content='12万元，尚未确认'"))
        _, received = execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(received, [wire])
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.llm.calls, [])

    def test_query_resource_failure_is_partial_not_empty_or_source_repair(self):
        index = self.adapter.history_index
        native = index.db.search_history_matches
        from unittest.mock import patch
        def bounded(session, *, query, **kwargs):
            if query == "budget":
                return {"status": "unavailable", "reason": "native_search_sqlite_toobig"}
            return native(session, query=query, **kwargs)
        with patch.object(index.db, "search_history_matches", side_effect=bounded):
            self.assertEqual(index.read_recall("session-1", ["budget"])["status"], "unavailable")
            self.assertEqual(index.read_recall("session-1", ["budget"], allow_partial_queries=True)["status"], "unavailable")
            found = index.read_recall("session-1", ["budget", "樱桃项目"], allow_partial_queries=True)
            self.assertEqual((found["status"], found["stats"]["query_failure_count"]), ("ready", 1))
            index.validate_recall(found["source_proof"], session_id="session-1")
        with patch.object(index.db, "search_history_matches", return_value={"status": "pending", "reason": "history_source_changed"}):
            self.assertEqual(index.read_recall("session-1", ["budget"], allow_partial_queries=True)["status"], "unavailable")

    def test_pending_user_row_does_not_replace_completed_history(self):
        self.runtime.recall_auxiliary_enabled = False
        question = "之前樱桃项目的预算定了吗？"
        self.writer.append_message("session-1", "user", question, timestamp=1787965100)
        self.prepare()
        found = self.adapter.history_index.read_recall("session-1", ["樱桃项目"])
        self.assertNotIn(question, repr(found["groups"]))
        projected = project(self.runtime, request(question), session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        plan = next(iter(self.runtime._turns.values()))
        self.assertIn("12万元", repr(projected["request"]))
        self.writer.append_message("session-1", "assistant", "本轮回答", timestamp=1787965101)
        self.prepare()
        self.adapter.history_index.validate_recall(plan.recall_proof, session_id="session-1")
        self.assertEqual(self.llm.calls, [])
