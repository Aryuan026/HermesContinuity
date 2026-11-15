"""Neutral recall-quality checks adapted from the reviewed mother-owner cases."""
import asyncio
import importlib
import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
    def test_recall_outside_checkpoint_does_not_change_checkpoint_receipt_sources(self):
        runtime = runtime_module.ContinuityRuntime(SimpleNamespace(history_index=SimpleNamespace(
            db=SimpleNamespace(search_history_matches=lambda: None))), None)
        self.addCleanup(runtime.clear)
        for field in ("checkpoint_candidate", "source_checkpoint"):
            with self.subTest(field=field):
                plan = runtime_module._TurnPlan("current", bridge_body="rolling bridge",
                    source_ids=("bridge-source",), **{field: {"revision": 2}})
                selected = {"body": "unrelated live reference", "source_ids": ["recall-source"],
                    "source_proof": {"groups": [{"group_id": "recall-source"}]}, "workset_bytes": 100}
                with patch.object(recall, "build_recall", new=AsyncMock(return_value=selected)):
                    combined = runtime._add_recall(plan, session_id="session", query="保修",
                        reference_at="2026-08-30T00:00:00+00:00")
                self.assertEqual(combined.source_ids, ("bridge-source",))
                self.assertIn("checkpoint_revision=2", combined.marker)
                self.assertEqual(combined.recall_proof, selected["source_proof"])
                self.assertIn("unrelated live reference", combined.bridge_body)

    def test_reference_borrowing_retains_current_attribute_and_context_route(self):
        index = Index([group("fact", "镜头保修多久", "保修三年。"),
                       *[group(f"noise-{n}", "ZK7 相机的电池怎么换？", "更换电池步骤。") for n in range(6)]])
        result = self.build(index, "它的镜头保修多久？", recent_query="ZK7 相机的电池怎么换？")
        self.assertEqual(result["source_ids"][0], "fact")
        self.assertTrue(any(key.startswith("noise-") for key in result["source_ids"]))
        self.assertIn("保修三年", result["body"])
        self.assertLessEqual(len(index.calls[0][1]), 3)
        self.assertGreater(index.calls[0][2]["primary_query_count"], 0)

    def test_long_original_question_reserves_search_slots_and_quoted_names(self):
        query = "它的" + "、".join(f"当前问题{n}" for n in range(50)) + "《我们》"
        queries, primary, context, count = recall._search_queries(query, "ZK7 相机电池")
        self.assertEqual(len(queries), 3)
        self.assertEqual(count, 2)
        self.assertTrue(primary and context)
        self.assertIn("我们", primary)
        self.assertIn("zk7", queries[-1])
        self.assertTrue(all(len(q) <= 80 for q in queries))

    def test_history_header_keeps_object_time_and_speaker_confirmation_distinct(self):
        result = self.build(Index([group("fact", "相机维修记录", "我猜已经全部修完。")]), "相机维修记录")
        self.assertIn("object scope and completion belong to their own quoted statements", result["body"])
        self.assertIn("an old assistant inference is not human confirmation", result["body"])
        self.assertIn("old state is not necessarily current", result["body"])
        self.assertIn("[assistant] 我猜已经全部修完。", result["body"])

    def test_latin_identifiers_do_not_match_inside_other_names(self):
        for term in ("ZK7", "ZK7-R1", "ZK7_R1", "ZK7.R1"):
            with self.subTest(term=term):
                exact = group("exact", "型号"+term+"，已确认。", "不是另一个型号。")
                noise = [group("prefix", "A"+term, "前缀不同。"),
                         group("suffix", term+"Pro", "后缀不同。"),
                         group("compound", term+"-X", "复合名不同。")]
                self.assertEqual(recall._ranked_groups([*noise, exact], [term.lower()]), [exact])
                self.assertEqual(recall._term_positions(term.lower(), "型号"+term+"。"), [2])
                self.assertIn(term.lower(), recall._query_terms("看看 "+term+"。"))
        text = "AZK7Pro。" + "无关段落。"*50 + "ZK7，必须保留冷却条件。"
        excerpt = recall._excerpt(text, ["zk7"], 50)
        self.assertIn("必须保留冷却条件", excerpt)
        self.assertNotIn("AZK7Pro", excerpt)

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

    def test_subjectless_followups_borrow_only_the_recent_subject(self):
        for question, recent, subject, answer in (
            ("花了多少？", "银杉相机的镜头修好了。", "银杉相机", "八十元。"),
            ("最后定在几号了？", "秋风陶艺课的日期改好了。", "秋风陶艺课", "二十三号。"),
            ("在哪儿办的？", "海岬借阅证已经办好了。", "海岬借阅证", "在南馆。"),
        ):
            with self.subTest(question=question):
                index = Index([group("fact", subject, answer)])
                result = self.build(index, question, recent_query=recent)
                self.assertIsNotNone(result)
                self.assertEqual(result["source_ids"], ["fact"])
                self.assertIn(answer, result["body"])
                self.assertIsNone(self.build(index, question))
                self.assertIsNone(self.build(index, "火星观测站花了多少？", recent_query=recent))

    def test_event_dates_remain_content_without_a_conversation_date_window(self):
        for date in ("12月6日", "2026年12月6日", "12/6", "2026-12-06"):
            with self.subTest(date=date):
                index = Index([group("fact", date, "归还画架。"),
                               group("noise", "12月7日", "领取水壶。")])
                result = self.build(index, date + " 的安排？")
                self.assertIsNotNone(result)
                self.assertEqual(result["source_ids"], ["fact"])
                self.assertIn("归还画架。", result["body"])
                # An event in December may have been discussed in August.
                # Only the existing as-of bound limits the conversation rows.
                self.assertEqual(index.calls[0][2], {
                    "end_at": "2026-08-30T00:00:00+00:00", "allow_partial_queries": True})

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

    def test_fresh_validation_releases_read_snapshot_before_another_writer(self):
        index = self.adapter.history_index
        original = index.validate_recall
        validated = []
        def validate(proof, **kwargs):
            with sqlite3.connect(self.store.path, timeout=0.1) as writer:
                writer.execute("UPDATE continuity_group_progress SET position=position")
            validated.append(True)
            return original(proof, **kwargs)
        with patch.object(index, "validate_recall", side_effect=validate):
            lexical = index.read_recall("session-1", ["樱桃项目"])
            timeline = index.read_timeline("session-1", start_at="2026-08-29T00:00:00+00:00",
                end_at="2026-08-30T00:00:00+00:00")
        self.assertEqual([lexical["status"], timeline["status"]], ["ready", "ready"])
        self.assertEqual(len(validated), 2)

    def test_primary_fact_survives_native_candidate_pool_and_final_delivery(self):
        self.runtime.recall_auxiliary_enabled = False
        for n in range(40):
            self.writer.append_message("session-1", "user", "ZK7 电池更换步骤", timestamp=1787965100+n*2)
            self.writer.append_message("session-1", "assistant", "先关闭电源。", timestamp=1787965101+n*2)
        self.writer.append_message("session-1", "user", "镜头保修期", timestamp=1787965004)
        self.writer.append_message("session-1", "assistant", "保修三年。", timestamp=1787965005)
        self.prepare()
        wire = request("它的镜头保修期是多久？")
        wire["messages"][:0] = [{"role": "user", "content": "ZK7 电池更换步骤"},
                                {"role": "assistant", "content": "接着说。"}]
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        self.assertIn("保修三年", repr(projected["request"]))
        execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(self.rows()[0][0], "delivered_recall")
        self.assertNotIn("保修三年", repr(self.rows()))
        self.assertEqual(self.llm.calls, [])

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

    def test_subjectless_followup_reaches_native_history_and_settlement(self):
        self.runtime.recall_auxiliary_enabled = False
        self.writer.append_message("session-1", "user", "银杉相机的镜头维修", timestamp=1787965100)
        self.writer.append_message("session-1", "assistant", "八十元，不含运费。", timestamp=1787965101)
        self.prepare()
        wire = request("花了多少？")
        wire["messages"][:0] = [{"role": "user", "content": "银杉相机的镜头修好了。"},
                                {"role": "assistant", "content": "我们接着看。"}]
        projected = project(self.runtime, wire, session="session-1")
        self.assertIsNotNone(projected, self.runtime.status_command())
        self.assertIn("八十元，不含运费。", repr(projected["request"]))
        self.assertEqual(wire["messages"][-1]["content"], "花了多少？")
        execute(self.runtime, projected["request"], wire, session="session-1")
        post(self.runtime, session="session-1")
        self.assertEqual(self.rows()[0][0], "delivered_recall")
        self.assertNotIn("八十元", repr(self.rows()))
        self.assertEqual(self.llm.calls, [])

    def test_native_date_punctuation_keeps_event_history_before_the_event(self):
        self.runtime.recall_auxiliary_enabled = False
        dates = ("12月6日", "2026年12月6日", "12/6", "2026-12-06")
        for number, date in enumerate(dates):
            self.writer.append_message("session-1", "user", date, timestamp=1787965100+number*2)
            self.writer.append_message("session-1", "assistant", "归还画架。", timestamp=1787965101+number*2)
        self.writer.append_message("session-1", "user", "12月6日", timestamp=1788134400)
        self.writer.append_message("session-1", "assistant", "未来追加不应出现。", timestamp=1788134401)
        self.prepare()
        for number, date in enumerate(dates):
            with self.subTest(date=date):
                wire = request(date + " 的安排？")
                turn = f"date-{number}"
                projected = project(self.runtime, wire, session="session-1", turn=turn)
                self.assertIsNotNone(projected, self.runtime.status_command())
                self.assertIn("归还画架。", repr(projected["request"]))
                self.assertNotIn("未来追加不应出现", repr(projected["request"]))
                execute(self.runtime, projected["request"], wire, session="session-1", turn=turn)
                post(self.runtime, session="session-1", turn=turn)
                self.assertEqual(len(self.rows()), number+1)
                self.assertTrue(all(row[0] == "delivered_recall" for row in self.rows()))
        self.assertIsNone(project(self.runtime, request("12月9日 的安排？"),
                                  session="session-1", turn="date-miss"))
        self.assertEqual(len(self.rows()), len(dates))
        self.assertEqual(self.llm.calls, [])

    def test_native_compound_identifier_reaches_settlement_without_partial_name_credit(self):
        self.runtime.recall_auxiliary_enabled = False
        for number, term in enumerate(("ZK7", "QR8-R1", "QS9_R2", "QT8.R3")):
            for offset, (text, answer) in enumerate(((term, "exact identifier answer"),
                                                  ("A"+term+"Pro", "wrong identifier answer"))):
                stamp = 1787965100+number*4+offset*2
                self.writer.append_message("session-1", "user", text, timestamp=stamp)
                self.writer.append_message("session-1", "assistant", answer, timestamp=stamp+1)
        self.prepare()
        for number, term in enumerate(("ZK7", "QR8-R1", "QS9_R2", "QT8.R3")):
            with self.subTest(term=term):
                wire = request("看看 "+term)
                turn = f"identifier-{number}"
                projected = project(self.runtime, wire, session="session-1", turn=turn)
                self.assertIsNotNone(projected, self.runtime.status_command())
                self.assertIn("exact identifier answer", repr(projected["request"]))
                self.assertNotIn("wrong identifier answer", repr(projected["request"]))
                execute(self.runtime, projected["request"], wire, session="session-1", turn=turn)
                post(self.runtime, session="session-1", turn=turn)
        self.assertEqual(len(self.rows()), 4)
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
