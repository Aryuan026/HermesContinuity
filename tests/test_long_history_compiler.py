from __future__ import annotations

import asyncio
import copy
import importlib
import json
import re
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_algorithm_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

runtime = importlib.import_module(f"{PACKAGE}.thread_continuity_runtime")
checkpoint_v3 = importlib.import_module(f"{PACKAGE}.checkpoint_v3")
context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")
try:
    fixture_module = importlib.import_module("test_checkpoint_v3")
except ModuleNotFoundError:
    fixture_module = importlib.import_module("tests.test_checkpoint_v3")


_ASCII = re.compile(r"[A-Za-z0-9_./:@+-]+")


def estimate_messages(messages: list[dict]) -> int:
    total = 0
    for message in messages:
        text = json.dumps(message.get("content"), ensure_ascii=False)
        total += 4 + len(_ASCII.findall(text)) + len(re.findall(r"[\u4e00-\u9fff]", text))
    return total


class Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, list[dict]]] = []

    async def __call__(self, attempt: dict, messages: list[dict]) -> dict:
        self.calls.append((copy.deepcopy(attempt), copy.deepcopy(messages)))
        return {"output_text": "recent bounded summary"}


async def compile_v3(
    source: dict,
    *,
    continuity: dict | None = None,
    reference_at: str = "2026-09-28T00:02:00+00:00",
    context_window_tokens: int = 8_000,
    reserved_output_tokens: int = 512,
) -> tuple[dict, Provider]:
    provider = Provider()
    result = await runtime.compile_thread_continuity_turn(
        {
            "source": source,
            "continuity": continuity or {"status": "absent", "state": {}},
        },
        current_ephemeral={
            "role": "user",
            "message_id": "current-user",
            "content": "current request",
        },
        fixed_prompt_messages=[{"role": "system", "content": "fixed prompt"}],
        context_window_tokens=context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
        fixed_non_message_tokens=0,
        estimate_messages=estimate_messages,
        summary_call=provider,
        project_provider_attempt=lambda kind, result, *, provider_returned: {
            "status": "unknown",
            "provider_returned": provider_returned,
        },
        physical_owner_generation=object(),
        bridge_reference_at=reference_at,
    )
    return result, provider


class LongHistoryCompilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_prefix_uses_only_bounded_complete_groups(self) -> None:
        source = fixture_module.compact_source_fixture()
        result, provider = await compile_v3(source)

        self.assertEqual(
            (result["status"], result["mode"]),
            ("ready", "compacted"),
            (result["trace"], provider.calls),
        )
        self.assertEqual(len(provider.calls), 1)
        summary_messages = provider.calls[0][1]
        summary_text = json.dumps(summary_messages, ensure_ascii=False)
        self.assertIn("question 1", summary_text)
        self.assertIn("answer 1", summary_text)
        self.assertNotIn("question 2", summary_text)
        self.assertNotIn("answer 2", summary_text)
        self.assertLess(len(summary_messages), 10)

        checkpoint = result["checkpoint_candidate"]
        self.assertEqual(checkpoint["schema"], "thread_continuity_checkpoint.v3")
        self.assertEqual(checkpoint["retirement_cursor"]["group_count"], 2049)
        self.assertEqual(
            checkpoint["recent_bridge"]["source_group_ids"], ["group-2049"]
        )
        physical = result["physical_provider_messages"]
        self.assertTrue(any(row.get("content") == "question 2" for row in physical))
        self.assertTrue(any(row.get("content") == "current request" for row in physical))

    async def test_compact_source_tamper_fails_before_summary_provider(self) -> None:
        source = fixture_module.compact_source_fixture()
        source["group_prefixes"][0]["prefix"]["group_root"] = "f" * 64
        result, provider = await compile_v3(source)
        self.assertEqual(
            (result["status"], result["trace"]["reason"]),
            ("fallback", "source_unavailable"),
        )
        self.assertEqual(provider.calls, [])

    async def test_exact_bridge_inventory_reuses_body_as_reference_time_advances(
        self,
    ) -> None:
        source = fixture_module.compact_source_fixture()
        first, first_provider = await compile_v3(source)
        checkpoint = first["checkpoint_candidate"]
        validation = checkpoint_v3.make_thread_continuity_checkpoint_validation(
            checkpoint, source
        )
        second, second_provider = await compile_v3(
            source,
            continuity={
                "status": "ready",
                "state": {
                    "revision": checkpoint["revision"],
                    "revision_id": checkpoint["revision_id"],
                    "checkpoint": checkpoint,
                    "checkpoint_validation": validation,
                },
            },
            reference_at="2026-09-28T00:03:00+00:00",
        )

        self.assertEqual(len(first_provider.calls), 1)
        self.assertEqual(second_provider.calls, [])
        self.assertEqual((second["status"], second["mode"]), ("ready", "raw"))
        self.assertIsNone(second["checkpoint_candidate"])
        self.assertIn(
            "recent bounded summary",
            json.dumps(second["physical_provider_messages"], ensure_ascii=False),
        )

        expired, expired_provider = await compile_v3(
            source,
            continuity={
                "status": "ready",
                "state": {
                    "revision": checkpoint["revision"],
                    "revision_id": checkpoint["revision_id"],
                    "checkpoint": checkpoint,
                    "checkpoint_validation": validation,
                },
            },
            reference_at="2026-10-02T00:03:00+00:00",
        )
        self.assertEqual(expired_provider.calls, [])
        self.assertNotIn("recent bounded summary",
                         json.dumps(expired.get("physical_provider_messages", [])))

    async def test_large_complete_group_uses_donor_chunk_receipts_atomically(
        self,
    ) -> None:
        groups = [
            fixture_module._group("huge-2049", 1),
            fixture_module._group("huge-2050", 2),
            fixture_module._group("normal-2051", 3),
            fixture_module._group("raw-2052", 4),
        ]
        groups[0]["messages"][0]["content"] = "甲" * 80
        groups[0]["messages"][1]["content"] = "甲答" * 80
        groups[1]["messages"][0]["content"] = "乙" * 80
        groups[1]["messages"][1]["content"] = "乙答" * 80
        source = fixture_module.compact_source_fixture(
            groups, eligible_group_count=3
        )
        result, provider = await compile_v3(
            source,
            context_window_tokens=300,
            reserved_output_tokens=40,
        )

        self.assertEqual(
            (result["status"], result["mode"]),
            ("ready", "compacted"),
            (result["trace"], provider.calls),
        )
        checkpoint = result["checkpoint_candidate"]
        self.assertEqual(checkpoint["retirement_cursor"]["group_count"], 2051)
        self.assertEqual(
            checkpoint["recent_bridge"]["source_group_ids"],
            ["huge-2049", "huge-2050", "normal-2051"],
        )
        kinds = [attempt[0]["kind"] for attempt in provider.calls]
        self.assertGreater(kinds.count("chunk"), 1)
        self.assertGreater(kinds.count("summary"), 0)
        self.assertEqual(
            kinds,
            [sample["kind"] for sample in result["trace"]["attempt_samples"]],
        )
        self.assertEqual(result["trace"]["summary_call_count"], len(provider.calls))
        self.assertEqual(result["trace"]["accepted_receipt_count"], len(provider.calls))
        self.assertTrue(
            all(
                set(attempt) == {
                    "kind",
                    "descriptor_id",
                    "plan_generation",
                    "max_output_tokens",
                }
                and type(attempt["max_output_tokens"]) is int
                and attempt["max_output_tokens"] > 0
                for attempt, _messages in provider.calls
            )
        )
        self.assertTrue(
            all("current request" not in repr(messages) for _attempt, messages in provider.calls)
        )
        physical = json.dumps(result["physical_provider_messages"], ensure_ascii=False)
        self.assertNotIn("甲" * 80, physical)
        self.assertIn("question 4", physical)
        self.assertIn("current request", physical)

    async def test_source_invalid_stored_revision_rebuilds_without_old_body(
        self,
    ) -> None:
        source = fixture_module.compact_source_fixture()
        predecessor = "tcr_" + "7" * 64
        result, provider = await compile_v3(
            source,
            continuity={
                "status": "unavailable",
                "error": "thread_continuity_checkpoint_source_invalid",
                "state": {
                    "revision": 7,
                    "revision_id": predecessor,
                },
            },
        )

        self.assertEqual(len(provider.calls), 1)
        checkpoint = result["checkpoint_candidate"]
        self.assertEqual(checkpoint["lineage_status"], "rebuilt")
        self.assertEqual(checkpoint["revision"], 8)
        self.assertEqual(checkpoint["predecessor_revision_id"], predecessor)
        self.assertEqual(result["trace"]["continuity_revision_id"], predecessor)

        malformed, malformed_provider = await compile_v3(
            source,
            continuity={
                "status": "ready",
                "state": {"revision": 7, "revision_id": predecessor},
            },
        )
        self.assertEqual(
            (malformed["status"], malformed["trace"]["reason"]),
            ("fallback", "continuity_state_unavailable"),
        )
        self.assertEqual(malformed_provider.calls, [])

    async def test_first_v3_checkpoint_does_not_borrow_v2_revision_chain(
        self,
    ) -> None:
        source = fixture_module.compact_source_fixture()
        legacy = context_compactor.build_thread_continuity_checkpoint_v2(
            previous_state=None,
            source_groups=source["groups"],
            retired_source_group_ids=["group-2049"],
            bridge_source_group_ids=["group-2049"],
            bridge_text="legacy bounded bridge",
            bridge_policy={
                "reference_at": "2026-09-28T00:02:00+00:00",
                "recent_horizon_hours": 72,
                "source_token_limit": 24_000,
                "output_token_limit": 2_048,
            },
        )
        result, provider = await compile_v3(
            source,
            continuity={
                "status": "ready",
                "state": {
                    "revision": legacy["revision"],
                    "checkpoint": legacy,
                },
            },
        )

        self.assertEqual(len(provider.calls), 1)
        checkpoint = result["checkpoint_candidate"]
        self.assertEqual(checkpoint["lineage_status"], "rebuilt")
        self.assertEqual(checkpoint["revision"], 1)
        self.assertEqual(checkpoint["predecessor_revision"], 0)
        self.assertEqual(checkpoint["predecessor_revision_id"], "")
        self.assertEqual(result["trace"]["continuity_revision"], 0)
        self.assertEqual(result["trace"]["continuity_revision_id"], "")

    async def test_foreground_group_never_crosses_retirement_boundary(self) -> None:
        source = fixture_module.compact_source_fixture()
        source["retirement_eligibility"]["prefix"] = source["prefix_before_groups"]
        source["stats"]["compacted_prefix_group_ids"] = []
        result, provider = await compile_v3(source)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(provider.calls, [])
        checkpoint = result["checkpoint_candidate"]
        self.assertEqual(checkpoint["recent_bridge"]["status"], "empty")
        self.assertEqual(checkpoint["retirement_cursor"]["group_count"], 2048)
        physical_text = json.dumps(result["physical_provider_messages"], ensure_ascii=False)
        self.assertIn("question 1", physical_text)
        self.assertIn("question 2", physical_text)


if __name__ == "__main__":
    unittest.main()
