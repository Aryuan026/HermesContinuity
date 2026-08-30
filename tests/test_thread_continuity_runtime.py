from __future__ import annotations

import asyncio
import copy
import importlib
import json
import re
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_algorithm_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")
thread_continuity_runtime = importlib.import_module(
    f"{PACKAGE}.thread_continuity_runtime"
)
bind_thread_continuity_fixed_prompt_selection = (
    context_compactor.bind_thread_continuity_fixed_prompt_selection
)
build_thread_continuity_checkpoint = context_compactor.build_thread_continuity_checkpoint
build_thread_continuity_checkpoint_v2 = (
    context_compactor.build_thread_continuity_checkpoint_v2
)
plan_thread_continuity_fold = context_compactor.plan_thread_continuity_fold
read_thread_continuity_prompt_plan_carriers = (
    context_compactor.read_thread_continuity_prompt_plan_carriers
)
compile_thread_continuity_turn = (
    thread_continuity_runtime.compile_thread_continuity_turn
)
resolve_thread_continuity_context_epoch_plan = (
    thread_continuity_runtime.resolve_thread_continuity_context_epoch_plan
)
resolve_thread_continuity_fixed_prompt_plan = (
    thread_continuity_runtime.resolve_thread_continuity_fixed_prompt_plan
)


@dataclass(frozen=True)
class PromptSegment:
    segment_id: str
    version: str
    text: str
    cacheable: bool
    layer: str


@dataclass(frozen=True)
class PromptAssembly:
    segments: tuple[PromptSegment, ...]

    @classmethod
    def from_segments(cls, segments: list[PromptSegment]) -> "PromptAssembly":
        return cls(tuple(segments))

    @property
    def text(self) -> str:
        return "\n\n".join(segment.text.strip() for segment in self.segments).strip()


_ASCII_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./:@+-]+")
_CJK_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_IMAGE_TOKEN_ESTIMATE = 256


def _estimate_tokens_from_text(text: str) -> int:
    raw = str(text or "")
    if not raw.strip():
        return 0
    cjk_count = len(_CJK_CHAR_PATTERN.findall(raw))
    ascii_chunks = _ASCII_TOKEN_PATTERN.findall(raw)
    ascii_chars = sum(len(chunk) for chunk in ascii_chunks)
    residual = _CJK_CHAR_PATTERN.sub("", raw)
    residual = _ASCII_TOKEN_PATTERN.sub("", residual)
    other_visible = len(re.sub(r"\s+", "", residual))
    estimate = (cjk_count * 1.05) + (ascii_chars / 4.0) + (other_visible * 0.35)
    return max(1, int(round(estimate)))


def _estimate_tokens_from_content(content: object) -> int:
    if content is None:
        return 0
    if isinstance(content, str):
        return _estimate_tokens_from_text(content)
    if isinstance(content, list):
        return sum(_estimate_tokens_from_content(item) for item in content)
    if isinstance(content, dict):
        part_type = str(content.get("type", "")).strip().lower()
        if part_type in {"text", "input_text"}:
            return _estimate_tokens_from_text(str(content.get("text", "")))
        if part_type in {"image_url", "input_image"}:
            return _IMAGE_TOKEN_ESTIMATE
        if "content" in content:
            return _estimate_tokens_from_content(content.get("content"))
        return _estimate_tokens_from_text(json.dumps(content, ensure_ascii=False))
    return _estimate_tokens_from_text(str(content))


def group(
    source_id: str,
    user: object,
    assistant: object,
    *,
    event_at: str = "2026-08-09T00:00:00Z",
) -> dict:
    return {
        "group_kind": "dialogue_turn",
        "source_prefix_id": source_id,
        "logical_turn_id": source_id,
        "record_id": f"cap-{source_id}",
        "effective_event_at": event_at,
        "messages": [
            {"role": "user", "message_id": f"u-{source_id}", "content": user},
            {"role": "assistant", "message_id": f"a-{source_id}", "content": assistant},
        ],
        "message_ids": [f"u-{source_id}", f"a-{source_id}"],
    }


def proactive_group(source_id: str, assistant: object) -> dict:
    return {
        "group_kind": "proactive_assistant_event",
        "source_prefix_id": source_id,
        "logical_turn_id": source_id,
        "record_id": f"cap-{source_id}",
        "effective_event_at": "2026-08-09T00:00:00Z",
        "messages": [
            {"role": "assistant", "message_id": f"a-{source_id}", "content": assistant},
        ],
        "message_ids": [f"a-{source_id}"],
    }


def estimate_messages(messages: list[dict]) -> int:
    total = 0
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        total += 4
        if message.get("name"):
            total += 2
        total += _estimate_tokens_from_content(message.get("content", ""))
    return total


def project_cache(stage: str, result: object, *, provider_returned: bool) -> dict:
    del stage
    payload = result if isinstance(result, dict) else {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    read_tokens = usage.get("cacheReadInputTokens")
    creation_tokens = usage.get("cacheCreationInputTokens")
    observed = any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
        for value in (read_tokens, creation_tokens)
    )
    if not observed:
        return {"status": "unknown", "provider_returned": provider_returned}
    return {
        "status": "observed",
        "provider_returned": provider_returned,
        "cache_read_input_tokens": int(read_tokens or 0),
        "cache_creation_input_tokens": int(creation_tokens or 0),
    }


def bundle(rows: list[dict], checkpoint: dict | None = None, *, source_status: str = "ready") -> dict:
    source = {
        "status": source_status,
        "groups": rows,
        "source_prefix_ids": [row["source_prefix_id"] for row in rows],
        "source_snapshot": "snapshot-pre-turn",
        "scan_complete": source_status == "ready",
        "stats": {"full_prefix": source_status == "ready"},
    }
    continuity = (
        {"status": "ready", "state": {"revision": checkpoint["revision"], "checkpoint": checkpoint}}
        if checkpoint else {"status": "absent", "state": {}}
    )
    return {"source": source, "continuity": continuity}


class Provider:
    def __init__(self, result: object | None = None) -> None:
        self.calls: list[list[dict]] = []
        self.attempts: list[dict] = []
        self.result = result

    async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
        self.attempts.append(copy.deepcopy(attempt_meta))
        self.calls.append(copy.deepcopy(messages))
        return self.result if self.result is not None else f"摘要-{len(self.calls)}"


async def compile_turn(
    rows: list[dict], current: dict, *, checkpoint: dict | None = None,
    window: int = 2500, reserve: int = 300, fixed: int = 0,
    provider: Provider | None = None, estimator=estimate_messages,
    raw_bundle: dict | None = None, projector=project_cache,
    post_current_messages: object = None,
    minimum_fold_source_group_ids: list[str] | None = None,
    fixed_prompt_finalizer=None,
    bridge_reference_at=None,
    bridge_recent_horizon_hours: int = 72,
    bridge_source_token_limit: int = 24_000,
    bridge_output_token_limit: int = 2_048,
) -> tuple[dict, Provider]:
    callback = provider or Provider()
    result = await compile_thread_continuity_turn(
        raw_bundle or bundle(rows, checkpoint),
        current_ephemeral=current,
        fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
        context_window_tokens=window,
        reserved_output_tokens=reserve,
        fixed_non_message_tokens=fixed,
        estimate_messages=estimator,
        summary_call=callback,
        project_provider_attempt=projector,
        physical_owner_generation=object(),
        post_current_messages=post_current_messages,
        minimum_fold_source_group_ids=minimum_fold_source_group_ids,
        fixed_prompt_finalizer=fixed_prompt_finalizer,
        bridge_reference_at=bridge_reference_at,
        bridge_recent_horizon_hours=bridge_recent_horizon_hours,
        bridge_source_token_limit=bridge_source_token_limit,
        bridge_output_token_limit=bridge_output_token_limit,
    )
    return result, callback


def fold_current(
    rows: list[dict], *, window: int, reserve: int, checkpoint: dict | None = None,
    require_all: bool = False,
) -> dict:
    for size in range(1, 5000, 10):
        current = {"role": "user", "message_id": "u-current", "content": "当" * size}
        plan = plan_thread_continuity_fold(
            rows, current_ephemeral=current, context_window_tokens=window,
            reserved_output_tokens=reserve, fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
            source_complete=True, estimate_messages=estimate_messages,
            previous_state=checkpoint,
        )
        if plan.get("fold_plan_id") and (
            not require_all or plan.get("covered_source_group_ids") == [row["source_prefix_id"] for row in rows]
        ):
            return current
    raise AssertionError("unable to create token-pressure fixture")


class ThreadContinuityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _v2_checkpoint(
        rows: list[dict],
        *,
        bridge_ids: list[str],
        reference_at: str,
        horizon_hours: int = 72,
        bridge_text: str = "day-0 recent bridge body",
    ) -> dict:
        return build_thread_continuity_checkpoint_v2(
            previous_state=None,
            source_groups=rows,
            retired_source_group_ids=[row["source_prefix_id"] for row in rows],
            bridge_source_group_ids=bridge_ids,
            bridge_text=bridge_text if bridge_ids else "",
            bridge_policy={
                "reference_at": reference_at,
                "recent_horizon_hours": horizon_hours,
                "source_token_limit": 24000,
                "output_token_limit": 2048,
            },
        )

    def test_token_watermark_epoch_is_append_only_then_targets_soft_low(self) -> None:
        rows = [
            group(f"g-{index}", "u" * 70, "a" * 70)
            for index in range(5)
        ]
        current = {"role": "user", "message_id": "u-current", "content": "current"}

        def exact_chars(messages: list[dict]) -> int:
            return sum(len(str(message.get("content") or "")) for message in messages)

        healthy = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=1_200,
            reserved_output_tokens=100,
            soft_high_input_tokens=900,
            soft_low_input_tokens=420,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=exact_chars,
        )
        self.assertEqual(healthy["status"], "append_only")
        self.assertEqual(healthy["rollover_reason"], "below_soft_high")
        self.assertEqual(healthy["minimum_fold_source_group_ids"], [])

        rollover = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=1_200,
            reserved_output_tokens=100,
            soft_high_input_tokens=600,
            soft_low_input_tokens=420,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=exact_chars,
        )
        self.assertEqual(rollover["status"], "rollover_required")
        self.assertEqual(rollover["rollover_reason"], "soft_high_exceeded")
        self.assertGreater(len(rollover["minimum_fold_source_group_ids"]), 0)
        self.assertGreater(rollover["estimated_pre_input_tokens"], 600)
        self.assertLessEqual(rollover["estimated_target_input_tokens"], 420)
        self.assertEqual(rollover["maintenance_call_count"], 0)
        self.assertFalse(rollover["body_included"])

    async def test_large_current_above_soft_low_remains_hard_safe_and_exact(self) -> None:
        def exact_chars(messages: list[dict]) -> int:
            return sum(len(str(message.get("content") or "")) for message in messages)

        current = {
            "role": "user",
            "message_id": "u-current",
            "content": "C" * 240,
        }
        result = resolve_thread_continuity_context_epoch_plan(
            [],
            current_ephemeral=current,
            context_window_tokens=500,
            reserved_output_tokens=50,
            soft_high_input_tokens=180,
            soft_low_input_tokens=100,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=exact_chars,
        )

        self.assertEqual(result["status"], "append_only")
        self.assertEqual(result["rollover_reason"], "hard_safe_above_soft_low")
        self.assertFalse(result["soft_low_reached"])
        self.assertEqual(result["irreducible_input_tokens"], 245)
        self.assertEqual(result["eligible_retired_count"], 0)
        self.assertEqual(result["minimum_fold_source_group_ids"], [])

        compiled, provider = await compile_turn(
            [],
            current,
            window=500,
            reserve=50,
            estimator=exact_chars,
        )
        self.assertEqual((compiled["status"], compiled["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertEqual(compiled["physical_provider_messages"][-1], {
            "role": "user",
            "content": current["content"],
        })

    async def test_old_completed_chatter_retires_without_summary_call_or_visible_bridge(self) -> None:
        rows = [group("g-old", "已经完成的旧话题", "旧话题已完成")]
        current = {
            "role": "user",
            "message_id": "u-current",
            "content": "现在聊新的事",
        }

        compiled, provider = await compile_turn(
            rows,
            current,
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=["g-old"],
            bridge_reference_at="2026-08-16T16:00:00Z",
            bridge_recent_horizon_hours=72,
        )

        self.assertEqual((compiled["status"], compiled["mode"]), ("ready", "compacted"))
        self.assertEqual(provider.calls, [])
        checkpoint = compiled["checkpoint_candidate"]
        self.assertEqual(
            checkpoint["retirement_cursor"]["source_prefix_ids"],
            ["g-old"],
        )
        self.assertEqual(checkpoint["recent_bridge"]["status"], "empty")
        self.assertEqual(
            checkpoint["recent_bridge"]["relation"],
            "no_visible_representation",
        )
        self.assertNotIn(
            "已经完成的旧话题",
            repr(compiled["physical_provider_messages"]),
        )

    async def test_expired_v2_bridge_rolls_below_soft_high_and_disappears_physically(self) -> None:
        rows = [
            group(
                "g-day-0",
                "day-0 user body",
                "day-0 assistant body",
                event_at="2026-08-10T00:00:00Z",
            )
        ]
        checkpoint = self._v2_checkpoint(
            rows,
            bridge_ids=["g-day-0"],
            reference_at="2026-08-10T01:00:00Z",
        )
        current = {"role": "user", "message_id": "u-current", "content": "tiny"}
        epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=128000,
            reserved_output_tokens=4096,
            soft_high_input_tokens=48000,
            soft_low_input_tokens=24000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=estimate_messages,
            previous_state=checkpoint,
            minimum_fold_source_group_ids=["g-day-0"],
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )

        self.assertEqual(epoch["status"], "rollover_required")
        self.assertEqual(epoch["rollover_reason"], "currentness_expiry")
        compiled, provider = await compile_turn(
            rows,
            current,
            checkpoint=checkpoint,
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=epoch["minimum_fold_source_group_ids"],
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )
        self.assertEqual(provider.calls, [])
        self.assertEqual(compiled["checkpoint_candidate"]["recent_bridge"]["status"], "empty")
        physical = repr(compiled["physical_provider_messages"])
        self.assertNotIn("day-0 recent bridge body", physical)
        self.assertNotIn("day-0 user body", physical)

    async def test_v1_legacy_bridge_migrates_on_currentness_without_new_raw_expiry(self) -> None:
        rows = [
            group(
                "g-day-0",
                "day-0 canonical user",
                "day-0 canonical assistant",
                event_at="2026-08-10T00:00:00Z",
            )
        ]
        legacy = build_thread_continuity_checkpoint(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["g-day-0"],
            summary_text="legacy lifetime body must never become canonical evidence",
        )
        current = {"role": "user", "message_id": "u-current", "content": "tiny"}
        epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=128000,
            reserved_output_tokens=4096,
            soft_high_input_tokens=48000,
            soft_low_input_tokens=24000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=estimate_messages,
            previous_state=legacy,
            minimum_fold_source_group_ids=["g-day-0"],
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )

        self.assertEqual(
            (epoch["status"], epoch["rollover_reason"]),
            ("rollover_required", "currentness_expiry"),
        )
        compiled, provider = await compile_turn(
            rows,
            current,
            checkpoint=legacy,
            minimum_fold_source_group_ids=epoch["minimum_fold_source_group_ids"],
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )
        self.assertEqual(provider.calls, [])
        checkpoint = compiled["checkpoint_candidate"]
        self.assertEqual(checkpoint["schema"], "thread_continuity_checkpoint.v2")
        self.assertEqual(checkpoint["recent_bridge"]["status"], "empty")
        physical = repr(compiled["physical_provider_messages"])
        self.assertNotIn("legacy lifetime body", physical)
        self.assertNotIn("day-0 canonical user", physical)

        next_epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral={
                "role": "user",
                "message_id": "u-current-next",
                "content": "still tiny",
            },
            context_window_tokens=128000,
            reserved_output_tokens=4096,
            soft_high_input_tokens=48000,
            soft_low_input_tokens=24000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=estimate_messages,
            previous_state=checkpoint,
            minimum_fold_source_group_ids=["g-day-0"],
            bridge_reference_at="2026-08-15T02:00:00Z",
            bridge_recent_horizon_hours=72,
        )
        self.assertEqual(
            (next_epoch["status"], next_epoch["rollover_reason"]),
            ("append_only", "below_soft_high"),
        )

    async def test_expired_unretired_raw_prefix_rolls_below_soft_high(self) -> None:
        rows = [
            group(
                "g-old-raw",
                "old raw user",
                "old raw assistant",
                event_at="2026-08-10T00:00:00Z",
            )
        ]
        current = {"role": "user", "message_id": "u-current", "content": "tiny"}
        epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=128000,
            reserved_output_tokens=4096,
            soft_high_input_tokens=48000,
            soft_low_input_tokens=24000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=estimate_messages,
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )

        self.assertEqual(epoch["status"], "rollover_required")
        self.assertEqual(epoch["minimum_fold_source_group_ids"], ["g-old-raw"])
        compiled, _provider = await compile_turn(
            rows,
            current,
            minimum_fold_source_group_ids=epoch["minimum_fold_source_group_ids"],
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )
        self.assertEqual(
            compiled["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"],
            ["g-old-raw"],
        )
        self.assertNotIn("old raw user", repr(compiled["physical_provider_messages"]))

    async def test_currentness_expiry_does_not_mutate_canonical_source(self) -> None:
        rows = [
            group(
                "g-canonical",
                "canonical old user",
                "canonical old assistant",
                event_at="2026-08-10T00:00:00Z",
            )
        ]
        before = copy.deepcopy(rows)
        current = {"role": "user", "message_id": "u-current", "content": "tiny"}
        compiled, _provider = await compile_turn(
            rows,
            current,
            minimum_fold_source_group_ids=["g-canonical"],
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )

        self.assertEqual(compiled["status"], "ready")
        self.assertEqual(rows, before)
        self.assertEqual(bundle(rows)["source"]["source_prefix_ids"], ["g-canonical"])

    async def test_empty_currentness_expiry_uses_zero_summary_calls(self) -> None:
        rows = [
            group(
                "g-expired",
                "expired user",
                "expired assistant",
                event_at="2026-08-10T00:00:00Z",
            )
        ]
        provider = Provider()
        compiled, _provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "tiny"},
            provider=provider,
            bridge_reference_at="2026-08-15T01:00:00Z",
            bridge_recent_horizon_hours=72,
        )

        self.assertEqual(provider.calls, [])
        self.assertEqual(compiled["trace"]["summary_call_count"], 0)
        self.assertEqual(compiled["checkpoint_candidate"]["recent_bridge"]["status"], "empty")

    async def test_nonexpired_bridge_stays_append_only_with_zero_maintenance(self) -> None:
        rows = [
            group(
                "g-recent",
                "recent user",
                "recent assistant",
                event_at="2026-08-14T12:00:00Z",
            )
        ]
        checkpoint = self._v2_checkpoint(
            rows,
            bridge_ids=["g-recent"],
            reference_at="2026-08-14T13:00:00Z",
        )
        current = {"role": "user", "message_id": "u-current", "content": "tiny"}
        epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=128000,
            reserved_output_tokens=4096,
            soft_high_input_tokens=48000,
            soft_low_input_tokens=24000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=estimate_messages,
            previous_state=checkpoint,
            minimum_fold_source_group_ids=["g-recent"],
            bridge_reference_at="2026-08-15T12:00:00Z",
            bridge_recent_horizon_hours=72,
        )
        self.assertEqual((epoch["status"], epoch["rollover_reason"]), ("append_only", "below_soft_high"))
        compiled, provider = await compile_turn(
            rows,
            current,
            checkpoint=checkpoint,
            bridge_reference_at="2026-08-15T12:00:00Z",
            bridge_recent_horizon_hours=72,
        )
        self.assertEqual((compiled["status"], compiled["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertIsNone(compiled["checkpoint_candidate"])

    async def test_partial_bridge_rebuild_uses_only_bounded_exact_canonical_slice(self) -> None:
        rows = [
            group(
                "g-expired",
                "expired canonical user",
                "expired canonical assistant",
                event_at="2026-08-10T00:00:00Z",
            ),
            group(
                "g-survives",
                "surviving exact user",
                "surviving exact assistant",
                event_at="2026-08-14T12:00:00Z",
            ),
        ]
        checkpoint = self._v2_checkpoint(
            rows,
            bridge_ids=["g-expired", "g-survives"],
            reference_at="2026-08-14T13:00:00Z",
            horizon_hours=120,
            bridge_text="previous lifetime-like bridge body must not be reused",
        )
        provider = Provider(result="只代表仍然近期的 exact slice")
        compiled, _provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "tiny"},
            checkpoint=checkpoint,
            provider=provider,
            bridge_reference_at="2026-08-15T12:00:00Z",
            bridge_recent_horizon_hours=72,
            bridge_source_token_limit=1000,
        )

        self.assertEqual(len(provider.calls), 1)
        summary_input = repr(provider.calls[0])
        self.assertIn("surviving exact user", summary_input)
        self.assertIn("surviving exact assistant", summary_input)
        self.assertNotIn("expired canonical user", summary_input)
        self.assertNotIn("previous lifetime-like bridge body", summary_input)
        self.assertLessEqual(estimate_messages(provider.calls[0]), 1000)
        bridge = compiled["checkpoint_candidate"]["recent_bridge"]
        self.assertEqual(bridge["source_group_ids"], ["g-survives"])
        self.assertEqual(bridge["body"], "只代表仍然近期的 exact slice")

    def test_fixed_prompt_above_soft_low_retires_all_eligible_old_raw(self) -> None:
        def exact_chars(messages: list[dict]) -> int:
            return sum(len(str(message.get("content") or "")) for message in messages)

        result = resolve_thread_continuity_context_epoch_plan(
            [group("g-old", "U" * 80, "A" * 80)],
            current_ephemeral={
                "role": "user",
                "message_id": "u-current",
                "content": "current",
            },
            context_window_tokens=700,
            reserved_output_tokens=100,
            soft_high_input_tokens=300,
            soft_low_input_tokens=120,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "S" * 250}],
            estimate_messages=exact_chars,
        )

        self.assertEqual(result["status"], "rollover_required")
        self.assertEqual(result["rollover_reason"], "hard_safe_above_soft_low")
        self.assertFalse(result["soft_low_reached"])
        self.assertEqual(result["irreducible_input_tokens"], 257)
        self.assertEqual(result["eligible_retired_count"], 1)
        self.assertEqual(result["minimum_fold_source_group_ids"], ["g-old"])

    def test_genuine_hard_window_overflow_remains_blocked(self) -> None:
        def exact_chars(messages: list[dict]) -> int:
            return sum(len(str(message.get("content") or "")) for message in messages)

        result = resolve_thread_continuity_context_epoch_plan(
            [],
            current_ephemeral={
                "role": "user",
                "message_id": "u-current",
                "content": "C" * 100,
            },
            context_window_tokens=500,
            reserved_output_tokens=50,
            soft_high_input_tokens=300,
            soft_low_input_tokens=150,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "S" * 400}],
            estimate_messages=exact_chars,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["rollover_reason"], "fixed_context_exceeds_budget")
        self.assertFalse(result["soft_low_reached"])
        self.assertEqual(result["eligible_retired_count"], 0)

    def test_same_window_profile_identity_does_not_change_epoch_plan(self) -> None:
        rows = [group("g-one", "hello", "hi")]
        current = {"role": "user", "message_id": "u-current", "content": "again"}
        inputs = {
            "current_ephemeral": current,
            "context_window_tokens": 32_000,
            "reserved_output_tokens": 1_024,
            "soft_high_input_tokens": 20_000,
            "soft_low_input_tokens": 10_000,
            "context_epoch_policy": "token_watermark_v1",
            "fixed_prompt_messages": [{"role": "system", "content": "fixed"}],
            "estimate_messages": estimate_messages,
        }
        before = resolve_thread_continuity_context_epoch_plan(rows, **inputs)
        after = resolve_thread_continuity_context_epoch_plan(rows, **inputs)
        self.assertEqual(before, after)
        self.assertEqual(before["status"], "append_only")

    def test_pure_fixed_point_preflight_does_not_force_legacy_prompt_fold(self) -> None:
        rows = [group("g-one", "U" * 80, "A" * 80)]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        selected_assembly = PromptAssembly.from_segments(
            [
                PromptSegment(
                    segment_id="home_global_hot_context",
                    version="home_global_hot_context.v1",
                    text="GLOBAL",
                    cacheable=False,
                    layer="dynamic_tail",
                )
            ]
        )
        summary_calls = 0

        def exact_chars(messages: list[dict]) -> int:
            return sum(len(str(message.get("content") or "")) for message in messages)

        legacy_plan = plan_thread_continuity_fold(
            rows,
            current_ephemeral=current,
            context_window_tokens=320,
            reserved_output_tokens=64,
            fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "system", "content": "L" * 120}],
            source_complete=True,
            estimate_messages=exact_chars,
        )
        self.assertEqual(legacy_plan["reason"], "token_pressure")

        def finalize(plan_owner: object) -> object:
            nonlocal summary_calls
            self.assertEqual(summary_calls, 0)
            return bind_thread_continuity_fixed_prompt_selection(
                plan_owner,
                fixed_prompt_messages=[{"role": "system", "content": "GLOBAL"}],
                prompt_assembly=selected_assembly,
            )

        resolved = resolve_thread_continuity_fixed_prompt_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=320,
            reserved_output_tokens=64,
            fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "system", "content": "L" * 120}],
            estimate_messages=exact_chars,
            fixed_prompt_finalizer=finalize,
        )
        buffered = resolve_thread_continuity_fixed_prompt_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=320,
            reserved_output_tokens=64,
            fixed_non_message_tokens=20,
            fixed_prompt_messages=[{"role": "system", "content": "L" * 120}],
            estimate_messages=exact_chars,
            fixed_prompt_finalizer=finalize,
        )

        self.assertEqual(resolved["fold_plan"]["status"], "no_fold")
        self.assertEqual(buffered["fold_plan"]["status"], "no_fold")
        self.assertEqual(resolved["status"], "selected")
        self.assertIs(resolved["private_selected_prompt_assembly"], selected_assembly)

    async def test_fixed_prompt_finalizer_uses_typed_plan_owner_before_one_compile(self) -> None:
        rows = [group("g-one", "历史用户", "历史回答")]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        selected_assembly = PromptAssembly.from_segments(
            [
                PromptSegment(
                    segment_id="home_global_hot_context",
                    version="home_global_hot_context.v1",
                    text="GLOBAL FINAL",
                    cacheable=False,
                    layer="dynamic_tail",
                )
            ]
        )
        callback_calls: list[object] = []

        def finalize(plan_owner: object) -> object:
            callback_calls.append(plan_owner)
            self.assertNotIsInstance(plan_owner, dict)
            self.assertNotIn("历史用户", repr(plan_owner))
            bindings = read_thread_continuity_prompt_plan_carriers(plan_owner)
            self.assertTrue(
                any(row["carrier_kind"] == "final_raw_suffix" for row in bindings)
            )
            self.assertTrue(
                any(row["carrier_kind"] == "current_ephemeral" for row in bindings)
            )
            return bind_thread_continuity_fixed_prompt_selection(
                plan_owner,
                fixed_prompt_messages=[
                    {"role": "system", "content": selected_assembly.text}
                ],
                prompt_assembly=selected_assembly,
            )

        result, provider = await compile_turn(
            rows,
            current,
            window=128_000,
            reserve=4096,
            fixed_prompt_finalizer=finalize,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(provider.calls, [])
        self.assertGreaterEqual(len(callback_calls), 2)
        self.assertEqual(
            result["physical_provider_messages"][0],
            {"role": "system", "content": "GLOBAL FINAL"},
        )
        self.assertIs(result["private_selected_prompt_assembly"], selected_assembly)
        self.assertNotIsInstance(result["private_fixed_prompt_selection"], dict)
        self.assertNotIn("GLOBAL FINAL", repr(result["private_fixed_prompt_selection"]))

    async def test_nonconvergent_fixed_prompt_finalizer_replans_exact_legacy_without_provider_work(self) -> None:
        rows = [group("g-one", "历史用户", "历史回答")]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        assemblies = [
            PromptAssembly.from_segments(
                [
                    PromptSegment(
                        segment_id="home_global_hot_context",
                        version="home_global_hot_context.v1",
                        text=text,
                        cacheable=False,
                        layer="dynamic_tail",
                    )
                ]
            )
            for text in ("ALTERNATING A", "ALTERNATING B")
        ]
        calls = 0

        def alternate(plan_owner: object) -> object:
            nonlocal calls
            assembly = assemblies[calls % 2]
            calls += 1
            return bind_thread_continuity_fixed_prompt_selection(
                plan_owner,
                fixed_prompt_messages=[{"role": "system", "content": assembly.text}],
                prompt_assembly=assembly,
            )

        result, provider = await compile_turn(
            rows,
            current,
            window=128_000,
            reserve=4096,
            fixed_prompt_finalizer=alternate,
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(provider.calls, [])
        self.assertEqual(calls, 4)
        self.assertEqual(
            result["trace"]["fixed_prompt_finalizer_status"],
            "legacy_fallback_nonconvergent",
        )
        self.assertEqual(
            result["physical_provider_messages"][0],
            {"role": "system", "content": "固定系统提示"},
        )
        self.assertIsNone(result["private_selected_prompt_assembly"])
        self.assertIsNone(result["private_fixed_prompt_selection"])

    async def test_compacted_fixed_prompt_finalizer_uses_resolved_prompt_for_summary_owner(self) -> None:
        rows = [
            group("g-one", "历史用户一", "历史回答一"),
            group("g-two", "历史用户二", "历史回答二"),
        ]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        selected_assembly = PromptAssembly.from_segments(
            [
                PromptSegment(
                    segment_id="home_global_hot_context",
                    version="home_global_hot_context.v1",
                    text="GLOBAL FINAL",
                    cacheable=False,
                    layer="dynamic_tail",
                )
            ]
        )

        def finalize(plan_owner: object) -> object:
            return bind_thread_continuity_fixed_prompt_selection(
                plan_owner,
                fixed_prompt_messages=[
                    {"role": "system", "content": selected_assembly.text}
                ],
                prompt_assembly=selected_assembly,
            )

        result, provider = await compile_turn(
            rows,
            current,
            window=128_000,
            reserve=4096,
            minimum_fold_source_group_ids=["g-one"],
            fixed_prompt_finalizer=finalize,
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            result["physical_provider_messages"][0],
            {"role": "system", "content": "GLOBAL FINAL"},
        )
        self.assertEqual(
            result["trace"]["fixed_prompt_finalizer_status"], "selected"
        )

    async def test_proactive_assistant_carrier_keeps_role_and_exact_message_alias(self) -> None:
        rows = [proactive_group("turn-one", "same owner body")]
        current = {"role": "user", "message_id": "u-current", "content": "current"}
        observed: list[dict] = []
        selected_assembly = PromptAssembly.from_segments(
            [
                PromptSegment(
                    segment_id="home_global_hot_context",
                    version="home_global_hot_context.v1",
                    text="GLOBAL FINAL",
                    cacheable=False,
                    layer="dynamic_tail",
                )
            ]
        )

        def finalize(plan_owner: object) -> object:
            observed.extend(read_thread_continuity_prompt_plan_carriers(plan_owner))
            return bind_thread_continuity_fixed_prompt_selection(
                plan_owner,
                fixed_prompt_messages=[{"role": "system", "content": selected_assembly.text}],
                prompt_assembly=selected_assembly,
            )

        result, _provider = await compile_turn(
            rows,
            current,
            window=128_000,
            reserve=4096,
            fixed_prompt_finalizer=finalize,
        )

        self.assertEqual(result["status"], "ready")
        assistant_rows = [row for row in observed if row["role"] == "assistant"]
        self.assertTrue(assistant_rows)
        self.assertTrue(all(row["physical_index"] >= 0 for row in assistant_rows))
        self.assertTrue(
            all(row["message_aliases"] == ["a-turn-one"] for row in assistant_rows)
        )
        self.assertTrue(
            all("turn-one" in row["group_aliases"] for row in assistant_rows)
        )

    async def test_verified_transport_boundary_does_not_fold_within_hard_window(self) -> None:
        rows = [
            group("g-old-1", "旧用户一", "旧回答一"),
            group("g-old-2", "旧用户二", "旧回答二"),
            group("g-near", "近场用户", "近场回答"),
        ]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}

        result, provider = await compile_turn(
            rows,
            current,
            window=128000,
            reserve=4096,
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertIsNone(result["checkpoint_candidate"])
        physical = result["physical_provider_messages"]
        self.assertTrue(any(row.get("content") == "旧用户一" for row in physical))
        self.assertTrue(any(row.get("content") == "旧回答二" for row in physical))
        self.assertTrue(any(row.get("content") == "近场用户" for row in physical))
        self.assertTrue(any(row.get("content") == "近场回答" for row in physical))
        self.assertEqual(physical[-1]["content"], "当前")
        sidecar = result["private_physical_owner_sidecar"]
        self.assertEqual(
            sidecar["schema"], "thread_continuity_physical_owner_sidecar.v1"
        )
        self.assertEqual(sidecar["physical_message_count"], len(physical))
        self.assertNotIn("旧用户一", str(sidecar))

    async def test_one_hundred_short_turns_make_zero_history_provider_calls(self) -> None:
        rows = [
            group(f"g-{index}", f"短聊用户-{index}", f"短聊回答-{index}")
            for index in range(100)
        ]
        current = {"role": "user", "message_id": "u-current", "content": "继续聊"}
        epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=128000,
            reserved_output_tokens=4096,
            soft_high_input_tokens=48000,
            soft_low_input_tokens=24000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            estimate_messages=estimate_messages,
        )
        self.assertEqual(epoch["status"], "append_only")
        self.assertEqual(epoch["rollover_reason"], "below_soft_high")
        self.assertEqual(epoch["maintenance_call_count"], 0)

        result, provider = await compile_turn(
            rows,
            current,
            window=128000,
            reserve=4096,
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertIsNone(result["checkpoint_candidate"])
        self.assertEqual(result["trace"]["summary_call_count"], 0)
        self.assertEqual(result["trace"]["final_raw_suffix"]["count"], 100)

    def test_smaller_window_retires_old_raw_but_does_not_treat_soft_low_as_hard(self) -> None:
        rows = [group("g-large", "U" * 220, "A" * 220)]
        current = {
            "role": "user",
            "message_id": "u-current",
            "content": "current",
        }

        def exact_chars(messages: list[dict]) -> int:
            return sum(
                len(str(message.get("content") or ""))
                for message in messages
            )

        result = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            context_window_tokens=500,
            reserved_output_tokens=50,
            soft_high_input_tokens=400,
            soft_low_input_tokens=20,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[
                {"role": "system", "content": "S" * 80}
            ],
            estimate_messages=exact_chars,
        )

        self.assertEqual(result["status"], "rollover_required")
        self.assertEqual(result["rollover_reason"], "hard_safe_above_soft_low")
        self.assertFalse(result["soft_low_reached"])
        self.assertEqual(result["eligible_retired_count"], 1)
        self.assertEqual(result["minimum_fold_source_group_ids"], ["g-large"])
        self.assertEqual(result["maintenance_call_count"], 0)
        self.assertFalse(result["body_included"])

    async def test_soft_low_epoch_runway_absorbs_next_hundred_short_turns(self) -> None:
        rows = [
            group(f"g-{index}", "u" * 90, "a" * 90)
            for index in range(700)
        ]
        current = {"role": "user", "message_id": "u-current", "content": "current"}

        def shaped_estimator(messages: list[dict]) -> int:
            return 20 + sum(
                2 + len(str(message.get("content") or ""))
                for message in messages
            )

        epoch = resolve_thread_continuity_context_epoch_plan(
            rows,
            current_ephemeral=current,
            fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
            context_window_tokens=128_000,
            reserved_output_tokens=4_096,
            soft_high_input_tokens=48_000,
            soft_low_input_tokens=24_000,
            context_epoch_policy="token_watermark_v1",
            estimate_messages=shaped_estimator,
        )
        self.assertEqual(epoch["status"], "rollover_required")
        self.assertEqual(epoch["rollover_reason"], "hard_ceiling_pressure")
        self.assertEqual(epoch["estimated_target_input_tokens"], 24_000)
        self.assertTrue(epoch["minimum_fold_source_group_ids"])

        first, first_provider = await compile_turn(
            rows,
            current,
            window=128_000,
            reserve=4_096,
            estimator=shaped_estimator,
            minimum_fold_source_group_ids=epoch[
                "minimum_fold_source_group_ids"
            ],
        )
        self.assertEqual(first["status"], "ready")
        self.assertGreater(len(first_provider.calls), 0)
        checkpoint = first["checkpoint_candidate"]
        self.assertIsNotNone(checkpoint)

        extended = [
            *rows,
            *[
                group(f"later-{index}", "u" * 90, "a" * 90)
                for index in range(100)
            ],
        ]
        second_provider = Provider()
        second_epoch = resolve_thread_continuity_context_epoch_plan(
            extended,
            current_ephemeral={
                "role": "user",
                "message_id": "u-next",
                "content": "next",
            },
            context_window_tokens=128_000,
            reserved_output_tokens=4_096,
            soft_high_input_tokens=48_000,
            soft_low_input_tokens=24_000,
            context_epoch_policy="token_watermark_v1",
            fixed_prompt_messages=[
                {"role": "system", "content": "固定系统提示"}
            ],
            estimate_messages=shaped_estimator,
            previous_state=checkpoint,
            minimum_fold_source_group_ids=list(
                checkpoint["retirement_cursor"]["source_prefix_ids"]
            ),
        )
        self.assertEqual(second_epoch["status"], "append_only")
        self.assertEqual(second_epoch["rollover_reason"], "below_soft_high")
        second, _ = await compile_turn(
            extended,
            {"role": "user", "message_id": "u-next", "content": "next"},
            checkpoint=checkpoint,
            window=128_000,
            reserve=4_096,
            estimator=shaped_estimator,
            provider=second_provider,
        )

        self.assertEqual(second["status"], "ready")
        self.assertEqual(second_provider.calls, [])
        self.assertEqual(second["trace"]["summary_call_count"], 0)

    async def test_real_855_message_shape_keeps_only_seven_raw_nearfield_groups(self) -> None:
        rows = [
            group(f"g-{index}", f"历史用户-{index}", f"历史回答-{index}")
            for index in range(427)
        ]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}

        result, provider = await compile_turn(
            rows,
            current,
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=[
                f"g-{index}" for index in range(420)
            ],
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["trace"]["source_group_count"], 427)
        self.assertEqual(result["trace"]["final_retired"]["count"], 420)
        self.assertEqual(result["trace"]["final_raw_suffix"]["count"], 7)
        self.assertEqual(len(result["physical_provider_messages"]), 17)
        rendered = [str(row.get("content") or "") for row in result["physical_provider_messages"]]
        self.assertFalse(any("历史用户-0" == text for text in rendered))
        self.assertTrue(any("历史用户-420" == text for text in rendered))
        self.assertTrue(any("历史回答-426" == text for text in rendered))
        self.assertEqual(rendered[-1], "当前")

    async def test_real_855_message_shape_splits_summary_construction_below_core_attention_limit(self) -> None:
        rows = [
            group(
                f"g-{index}",
                f"history-user-{index}-" + ("u" * 500),
                f"history-assistant-{index}-" + ("a" * 500),
            )
            for index in range(427)
        ]

        result, provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "当前"},
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=[f"g-{index}" for index in range(420)],
            bridge_source_token_limit=64_000,
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertGreater(len(provider.calls), 1)
        self.assertEqual(result["trace"]["summary_construction_token_limit"], 30000)
        self.assertTrue(
            all(
                estimate_messages(messages) + attempt["max_output_tokens"] <= 30000
                for messages, attempt in zip(provider.calls, provider.attempts)
            ),
            [
                estimate_messages(messages) + attempt["max_output_tokens"]
                for messages, attempt in zip(provider.calls, provider.attempts)
            ],
        )
        self.assertEqual(result["trace"]["final_retired"]["count"], 420)
        self.assertEqual(result["trace"]["final_raw_suffix"]["count"], 7)
        self.assertEqual(len(result["physical_provider_messages"]), 17)

    async def test_natural_backlog_advances_existing_checkpoint_through_bounded_batches(self) -> None:
        rows = [
            group(
                f"g-{index}",
                f"history-user-{index}-" + ("u" * 500),
                f"history-assistant-{index}-" + ("a" * 500),
            )
            for index in range(826)
        ]
        previous = build_thread_continuity_checkpoint(
            previous_state=None,
            source_groups=rows[:399],
            covered_source_group_ids=[f"g-{index}" for index in range(399)],
            summary_text="既有连续性摘要",
        )

        result, provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "当前"},
            checkpoint=previous,
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=[f"g-{index}" for index in range(818)],
            bridge_source_token_limit=64_000,
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertGreater(len(provider.calls), 1)
        self.assertEqual(result["checkpoint_candidate"]["revision"], 2)
        self.assertEqual(
            result["checkpoint_candidate"]["predecessor_revision_id"],
            previous["revision_id"],
        )
        self.assertEqual(result["trace"]["final_retired"]["count"], 818)
        self.assertEqual(result["trace"]["final_raw_suffix"]["count"], 8)
        self.assertEqual(len(result["physical_provider_messages"]), 19)

    async def test_bounded_summary_failure_after_progress_mints_no_partial_checkpoint(self) -> None:
        rows = [
            group(
                f"g-{index}",
                f"history-user-{index}-" + ("u" * 500),
                f"history-assistant-{index}-" + ("a" * 500),
            )
            for index in range(427)
        ]

        class FailSecondBatch(Provider):
            async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
                self.attempts.append(copy.deepcopy(attempt_meta))
                self.calls.append(copy.deepcopy(messages))
                if len(self.calls) == 2:
                    raise RuntimeError("summary unavailable")
                return f"摘要-{len(self.calls)}"

        result, provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "当前"},
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=[f"g-{index}" for index in range(420)],
            provider=FailSecondBatch(),
            bridge_source_token_limit=64_000,
        )

        self.assertEqual(
            (result["status"], result["trace"]["reason"]),
            ("fallback", "summary_call_failed"),
        )
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(
            all(
                estimate_messages(messages) + attempt["max_output_tokens"] <= 30000
                for messages, attempt in zip(provider.calls, provider.attempts)
            )
        )
        self.assertEqual(result["physical_provider_messages"], [])
        self.assertIsNone(result["checkpoint_candidate"])

    async def test_verified_nearfield_boundary_advances_checkpoint_one_group_next_turn(self) -> None:
        rows = [
            group(f"g-{index}", f"历史用户-{index}", f"历史回答-{index}")
            for index in range(427)
        ]
        first, _ = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current-1", "content": "当前一"},
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=[f"g-{index}" for index in range(420)],
        )
        checkpoint = first["checkpoint_candidate"]
        advanced_rows = [
            *rows,
            group("g-427", "历史用户-427", "历史回答-427"),
        ]

        second, provider = await compile_turn(
            advanced_rows,
            {"role": "user", "message_id": "u-current-2", "content": "当前二"},
            checkpoint=checkpoint,
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=[f"g-{index}" for index in range(421)],
        )

        self.assertEqual((second["status"], second["mode"]), ("ready", "compacted"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(second["checkpoint_candidate"]["lineage_status"], "continued")
        self.assertEqual(
            second["checkpoint_candidate"]["predecessor_revision_id"],
            checkpoint["revision_id"],
        )
        self.assertEqual(second["trace"]["final_retired"]["count"], 421)
        self.assertEqual(second["trace"]["final_raw_suffix"]["count"], 7)
        summary_call = repr(provider.calls[0])
        self.assertIn("历史用户-420", summary_call)
        self.assertNotIn("摘要-1", summary_call)
        self.assertNotIn("历史用户-421", summary_call)
        self.assertEqual(len(second["physical_provider_messages"]), 17)

    async def test_required_nearfield_fold_failure_mints_no_partial_checkpoint(self) -> None:
        rows = [
            group("g-old", "旧用户", "旧回答"),
            group("g-near", "近场用户", "近场回答"),
        ]

        class RaisingProvider(Provider):
            async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
                self.attempts.append(copy.deepcopy(attempt_meta))
                self.calls.append(copy.deepcopy(messages))
                raise RuntimeError("summary unavailable")

        result, provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "当前"},
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=["g-old"],
            provider=RaisingProvider(),
        )

        self.assertEqual((result["status"], result["trace"]["reason"]), ("fallback", "summary_call_failed"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["physical_provider_messages"], [])
        self.assertIsNone(result["checkpoint_candidate"])

    async def test_cancelled_maintenance_propagates_without_checkpoint_candidate(self) -> None:
        rows = [
            group("g-old", "旧用户", "旧回答"),
            group("g-near", "近场用户", "近场回答"),
        ]

        class CancelledProvider(Provider):
            async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
                self.attempts.append(copy.deepcopy(attempt_meta))
                self.calls.append(copy.deepcopy(messages))
                raise asyncio.CancelledError()

        provider = CancelledProvider()
        with self.assertRaises(asyncio.CancelledError):
            await compile_turn(
                rows,
                {"role": "user", "message_id": "u-current", "content": "当前"},
                window=128000,
                reserve=4096,
                minimum_fold_source_group_ids=["g-old"],
                provider=provider,
            )

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.attempts[0]["kind"], "summary")

    async def test_corrupt_old_checkpoint_cannot_erase_verified_nearfield_boundary(self) -> None:
        rows = [
            group("g-old", "旧用户", "旧回答"),
            group("g-near", "近场用户", "近场回答"),
        ]
        corrupt = build_thread_continuity_checkpoint(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["g-old"],
            summary_text="旧摘要",
        )
        corrupt["summary_sha256"] = "f" * 64

        result, provider = await compile_turn(
            rows,
            {"role": "user", "message_id": "u-current", "content": "当前"},
            checkpoint=corrupt,
            window=128000,
            reserve=4096,
            minimum_fold_source_group_ids=["g-old"],
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertEqual(len(provider.calls), 1)
        physical = result["physical_provider_messages"]
        self.assertFalse(any(row.get("content") == "旧用户" for row in physical))
        self.assertTrue(any(row.get("content") == "近场用户" for row in physical))
        self.assertEqual(
            result["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"],
            ["g-old"],
        )

    async def test_force_rebuild_expands_to_first_full_carrier_prefix_before_provider(self) -> None:
        rows = [
            group("g-0", "u0", "a0"),
            group("g-1", "u1", "a1"),
            group("g-2", "pressure-g2", "a2"),
            group("g-3", "u3", "a3"),
            proactive_group("g-4", "a4"),
        ]
        previous = build_thread_continuity_checkpoint(
            previous_state=None, source_groups=rows[:2],
            covered_source_group_ids=["g-0", "g-1"],
            summary_text="旧摘要" * 400,
        )

        def boundary_estimator(messages: list[dict]) -> int:
            total = 30
            for message in messages:
                content = str(message.get("content") or "")
                total += 400 if len(content) > 1000 else 160 if "pressure-g2" in content else 5
            return total

        current = {"role": "user", "message_id": "u-current", "content": "current"}
        plan = plan_thread_continuity_fold(
            rows, current_ephemeral=current, context_window_tokens=300,
            reserved_output_tokens=40, fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "system", "content": "fixed"}],
            source_complete=True, estimate_messages=boundary_estimator,
            previous_state=previous,
        )
        result, provider = await compile_turn(
            rows, current, checkpoint=previous, window=300, reserve=40,
            estimator=boundary_estimator,
        )

        self.assertEqual(
            (plan["status"], plan["reason"], plan["continuity_mode"]),
            ("blocked", "rebuild_from_canonical_required", "rebuild"),
        )
        self.assertEqual(plan["covered_source_group_ids"], ["g-0", "g-1", "g-2"])
        self.assertEqual(plan["raw_suffix_group_ids"], ["g-3", "g-4"])
        self.assertEqual(plan["summary_output_token_limit"], 40)
        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.attempts[0]["max_output_tokens"], 40)
        self.assertEqual(
            result["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"],
            ["g-0", "g-1", "g-2"],
        )
        self.assertEqual(result["trace"]["final_raw_suffix"]["sample"], ["g-3", "g-4"])

        unavailable, blocked_provider = await compile_turn(
            rows, current, checkpoint=previous, window=300, reserve=40,
            estimator=lambda _messages: 300,
        )
        self.assertEqual(
            (unavailable["status"], unavailable["trace"]["reason"]),
            ("fallback", "summary_output_budget_unavailable"),
        )
        self.assertEqual(blocked_provider.calls, [])
        self.assertIsNone(unavailable["checkpoint_candidate"])

    async def test_raw_carrier_keeps_dialogue_and_proactive_content_exact_without_synthetic_user(self) -> None:
        rows = [
            group("dialogue", "  user-sentinel\n", "\nassistant-pair  "),
            proactive_group("proactive", "  proactive-sentinel\n"),
        ]
        current = {"role": "user", "message_id": "u-current", "content": "current"}
        result, provider = await compile_turn(rows, current, window=10000)

        self.assertEqual((result["status"], result["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertEqual(result["physical_provider_messages"][1:], [
            {"role": "user", "content": "  user-sentinel\n"},
            {"role": "assistant", "content": "\nassistant-pair  "},
            {"role": "assistant", "content": "  proactive-sentinel\n"},
            {"role": "user", "content": "current"},
        ])

    async def test_post_current_tail_preserves_exact_order_name_and_multimodal_content(self) -> None:
        image = [{"type": "image_url", "image_url": {"url": "https://example.invalid/tail.png"}}]
        tail = [
            {"role": "assistant", "name": "tool-facing-assistant", "message_id": "tail-a", "content": [{"type": "input_text", "text": "看图"}, *image]},
            {"role": "user", "message_id": "tail-u", "content": "继续处理"},
        ]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        result, provider = await compile_turn(
            [group("g-1", "历史用户", "历史回答")], current,
            window=10000, post_current_messages=tail,
        )
        self.assertEqual((result["status"], result["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertEqual(result["physical_provider_messages"][-2:], [
            {key: value for key, value in row.items() if key != "message_id"} for row in tail
        ])
        self.assertEqual([row["role"] for row in result["physical_provider_messages"]], [
            "system", "user", "assistant", "user", "assistant", "user",
        ])

    async def test_post_current_tail_invalid_fields_fail_closed_and_token_pressure_folds(self) -> None:
        rows = [group("g-1", "历史" * 80, "回答" * 80)]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        for invalid in (
            [{"role": "system", "message_id": "tail-system", "content": "不能成为尾巴"}],
            [{"role": "assistant", "message_id": "tail-tool", "content": "工具结果", "tool_call_id": "call-1"}],
            [{"role": "user", "content": "当前", "message_id": "u-current"}],
        ):
            result, provider = await compile_turn(
                rows, current, window=1000, post_current_messages=invalid,
            )
            self.assertEqual((result["status"], result["trace"]["reason"]), ("fallback", "post_current_messages_invalid"))
            self.assertEqual(provider.calls, [])

        raw, _ = await compile_turn(rows, current, window=700)
        tail = [{"role": "assistant", "message_id": "tail-a", "content": "尾" * 180}]
        folded, provider = await compile_turn(
            rows, current, window=700, post_current_messages=tail,
        )
        self.assertEqual((raw["status"], raw["mode"]), ("ready", "raw"))
        self.assertEqual((folded["status"], folded["mode"]), ("ready", "compacted"))
        self.assertEqual(folded["physical_provider_messages"][-1], {"role": "assistant", "content": "尾" * 180})
        self.assertTrue(provider.calls)
        self.assertTrue(all(tail[0]["content"] not in repr(call) and current["content"] not in repr(call) for call in provider.calls))

    async def test_no_fold_keeps_canonical_order_name_image_and_current_once(self) -> None:
        image = [{"type": "image_url", "image_url": {"url": "https://example.invalid/current.png"}}]
        rows = [group("g-1", "历史用户", "历史回答")]
        rows[0]["messages"][0]["name"] = "historical-owner"
        current = {"role": "user", "name": "current-owner", "message_id": "u-current", "content": image}
        result, provider = await compile_turn(rows, current, window=10000, fixed=173)
        self.assertEqual((result["status"], result["mode"]), ("ready", "raw"))
        self.assertEqual(provider.calls, [])
        self.assertIsNone(result["checkpoint_candidate"])
        physical = result["physical_provider_messages"]
        self.assertEqual([row["role"] for row in physical], ["system", "user", "assistant", "user"])
        self.assertEqual(physical[-1]["content"], image)
        self.assertEqual(physical[-1]["name"], "current-owner")
        self.assertEqual(sum(row.get("content") == image for row in physical), 1)
        self.assertLessEqual(estimate_messages(physical) + 173 + 300, 10000)
        self.assertEqual(
            (result["trace"]["source_status"], result["trace"]["source_scan_complete"],
             result["trace"]["source_snapshot"], result["trace"]["source_group_count"]),
            ("ready", True, "snapshot-pre-turn", 1),
        )
        self.assertEqual(result["trace"]["continuity_status"], "absent")
        self.assertFalse(result["trace"]["body_included"])
        self.assertEqual(result["trace"]["final_raw_suffix"]["sample"], ["g-1"])

    async def test_normal_batches_build_initial_checkpoint_and_exclude_current_from_calls(self) -> None:
        rows = [group(f"g-{index}", "用" * 300, "答" * 300) for index in range(4)]
        current = fold_current(rows, window=1000, reserve=160, require_all=True)
        result, provider = await compile_turn(rows, current, window=1000, reserve=160)
        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertGreaterEqual(len(provider.calls), 2)
        self.assertEqual(result["checkpoint_candidate"]["lineage_status"], "initial")
        self.assertEqual(result["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"], [
            "g-0", "g-1", "g-2", "g-3",
        ])
        self.assertTrue(all(not any(message.get("content") == current["content"] for message in call) for call in provider.calls))
        self.assertLessEqual(
            estimate_messages(result["physical_provider_messages"]) + 160,
            1000,
        )
        self.assertEqual(result["trace"]["final_retired"]["count"], 4)
        self.assertEqual(result["trace"]["final_raw_suffix"]["count"], 0)
        self.assertEqual(result["trace"]["checkpoint_revision_id"], result["checkpoint_candidate"]["revision_id"])
        self.assertEqual(
            result["trace"]["checkpoint_bridge_body_sha256"],
            result["checkpoint_candidate"]["recent_bridge"]["body_sha256"],
        )
        checkpoint_rows = [
            row
            for row in result["private_physical_owner_sidecar"]["rows"]
            if row["carrier_kind"] == "checkpoint"
        ]
        self.assertEqual(len(checkpoint_rows), 1)
        self.assertEqual(checkpoint_rows[0]["checkpoint_kind"], "recent_bridge")
        self.assertEqual(checkpoint_rows[0]["relation"], "represented_in_recent_bridge")
        self.assertEqual(checkpoint_rows[0]["source_group_aliases"], [])
        self.assertEqual(checkpoint_rows[0]["source_message_aliases"], [])

    async def test_incremental_and_huge_previous_rebuild_lineage(self) -> None:
        rows = [group("g-old", "旧", "旧答"), group("g-new", "新" * 200, "新答" * 200)]
        previous = build_thread_continuity_checkpoint(
            previous_state=None, source_groups=rows[:1],
            covered_source_group_ids=["g-old"], summary_text="旧摘要",
        )
        current = fold_current(rows, window=1400, reserve=220, checkpoint=previous)
        incremental, _ = await compile_turn(rows, current, checkpoint=previous, window=1400, reserve=220)
        self.assertEqual(incremental["status"], "ready")
        self.assertEqual(incremental["checkpoint_candidate"]["lineage_status"], "continued")
        self.assertEqual(incremental["checkpoint_candidate"]["predecessor_revision_id"], previous["revision_id"])

        huge_previous = build_thread_continuity_checkpoint(
            previous_state=None, source_groups=rows[:1],
            covered_source_group_ids=["g-old"], summary_text="旧摘要" * 2000,
        )
        rebuild_current = fold_current(rows, window=1400, reserve=220, checkpoint=huge_previous)
        rebuilt, _ = await compile_turn(rows, rebuild_current, checkpoint=huge_previous, window=1400, reserve=220)
        self.assertEqual(rebuilt["status"], "ready")
        self.assertEqual(rebuilt["checkpoint_candidate"]["lineage_status"], "continued")
        self.assertEqual(
            rebuilt["checkpoint_candidate"]["predecessor_revision_id"],
            huge_previous["revision_id"],
        )
        self.assertEqual(rebuilt["checkpoint_candidate"]["revision"], huge_previous["revision"] + 1)

    async def test_two_huge_groups_then_normal_complete_in_order(self) -> None:
        rows = [
            group("huge-1", "甲" * 80, "甲答" * 80),
            group("huge-2", "乙" * 80, "乙答" * 80),
            group("normal", "短" * 20, "短答" * 20),
        ]
        current = fold_current(rows, window=300, reserve=40, require_all=True)
        result, provider = await compile_turn(rows, current, window=300, reserve=40)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"], [
            "huge-1", "huge-2", "normal",
        ])
        self.assertGreater(result["trace"]["chunk_attempt_count"], 1)
        self.assertGreater(result["trace"]["summary_attempt_count"], 0)
        self.assertEqual(result["trace"]["summary_call_count"], len(provider.calls))
        self.assertEqual(result["trace"]["accepted_receipt_count"], len(provider.calls))
        self.assertTrue(all(set(meta) == {"kind", "descriptor_id", "plan_generation", "max_output_tokens"} for meta in provider.attempts))
        self.assertTrue(all(type(meta["max_output_tokens"]) is int and meta["max_output_tokens"] > 0 for meta in provider.attempts))
        self.assertEqual([meta["kind"] for meta in provider.attempts], [sample["kind"] for sample in result["trace"]["attempt_samples"]])

    async def test_frozen_fold_boundary_accepts_once_without_summary_replan(self) -> None:
        rows = [group(f"g-{index}", "用" * 120 + str(index), "答" * 120 + str(index)) for index in range(4)]
        current = fold_current(rows, window=1000, reserve=160)

        class OversizedFirstSummary(Provider):
            async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
                self.attempts.append(copy.deepcopy(attempt_meta))
                self.calls.append(copy.deepcopy(messages))
                return "长" * 200

        provider = OversizedFirstSummary()
        result, _ = await compile_turn(
            rows, current, window=1000, reserve=160, provider=provider,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["trace"]["replan_count"], 0)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            result["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"],
            ["g-0", "g-1"],
        )
        self.assertTrue(all(rows[3]["messages"][0]["content"] not in repr(call) for call in provider.calls))
        self.assertTrue(all(current["content"] not in repr(call) for call in provider.calls))
        [generation] = result["trace"]["plan_generations"]
        self.assertEqual((generation["final_disposition"], generation["discarded_on_replan"]), ("ready", False))
        self.assertEqual(generation["accepted_receipt_count"], 1)
        self.assertEqual(result["trace"]["accepted_receipt_count"], len(provider.calls))

    async def test_814_mixed_groups_freeze_one_summary_generation_and_exact_checkpoint_prefix(self) -> None:
        proactive_indexes = {16, 17, 22, 700}
        rows = [
            proactive_group(f"g-{index}", "a" * 20)
            if index in proactive_indexes
            else group(f"g-{index}", "u" * 20, "a" * 20)
            for index in range(814)
        ]

        def shaped_estimator(messages: list[dict]) -> int:
            return 20 + sum(
                2 + len(content) if isinstance(content, str) else 2 + len(str(content))
                for message in messages for content in [message.get("content")]
            )

        current = {"role": "user", "message_id": "u-current", "content": "current"}
        expected = plan_thread_continuity_fold(
            rows, current_ephemeral=current, context_window_tokens=25000,
            reserved_output_tokens=1000, fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
            source_complete=True, estimate_messages=shaped_estimator,
        )
        result, provider = await compile_turn(
            rows, current, window=25000, reserve=1000, estimator=shaped_estimator,
        )

        self.assertEqual((result["status"], result["mode"]), ("ready", "compacted"))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["trace"]["source_group_count"], 814)
        self.assertEqual(result["trace"]["replan_count"], 0)
        self.assertEqual(len(result["trace"]["plan_generations"]), 1)
        self.assertEqual(
            result["checkpoint_candidate"]["retirement_cursor"]["source_prefix_ids"],
            expected["covered_source_group_ids"],
        )
        self.assertEqual(
            result["trace"]["final_raw_suffix"]["count"],
            814 - len(expected["covered_source_group_ids"]),
        )
        self.assertLessEqual(
            shaped_estimator(result["physical_provider_messages"]) + 1000,
            25000,
        )

    async def test_more_than_seventeen_chunk_attempts_keep_exact_total_and_bounded_sample(self) -> None:
        rows = [group("huge", "甲" * 10, "乙" * 10)]

        def one_character_per_chunk(messages: list[dict]) -> int:
            return 100 + sum(
                len(str(row.get("content") or "")) * 20
                for row in messages if row.get("role") in {"user", "assistant"}
            )

        current = {"role": "user", "message_id": "u-current", "content": "当"}
        result, provider = await compile_turn(
            rows, current, window=150, reserve=20, estimator=one_character_per_chunk,
        )
        self.assertEqual(result["status"], "ready")
        self.assertGreater(result["trace"]["summary_call_count"], 17)
        self.assertEqual(result["trace"]["summary_call_count"], len(provider.calls))
        self.assertEqual(result["trace"]["accepted_receipt_count"], len(provider.calls))
        self.assertEqual(result["trace"]["provider_returned_count"], len(provider.calls))
        self.assertEqual(len(result["trace"]["attempt_samples"]), 17)
        self.assertTrue(result["trace"]["attempt_sample_truncated"])
        self.assertEqual(result["trace"]["attempt_sample_omitted_count"], len(provider.calls) - 17)
        self.assertTrue(all(sample["accepted"] and sample["receipt_id"] and sample["result_sha256"] for sample in result["trace"]["attempt_samples"]))
        self.assertEqual(result["trace"]["projected_cache_attempt_count"], len(provider.calls))
        self.assertEqual(result["trace"]["cache_unknown_attempt_count"], len(provider.calls))
        self.assertFalse(result["trace"]["cache_observation_complete"])

    async def test_cache_projection_counts_all_observed_and_mixed_attempts(self) -> None:
        rows = [group(f"g-{index}", "用" * 300, "答" * 300) for index in range(4)]
        current = fold_current(rows, window=1000, reserve=160, require_all=True)
        cached = {"output_text": "摘要", "usage": {"cacheReadInputTokens": 42}}
        observed, provider = await compile_turn(
            rows, current, window=1000, reserve=160, provider=Provider(cached),
        )
        self.assertEqual(len(provider.calls), 4)
        self.assertEqual(observed["trace"]["cache_observed_attempt_count"], 4)
        self.assertEqual(observed["trace"]["cache_read_input_tokens_total"], 168)
        self.assertEqual(observed["trace"]["cache_creation_input_tokens_total"], 0)
        self.assertTrue(observed["trace"]["cache_observation_complete"])
        self.assertTrue(all(sample["cache"]["cache_read_input_tokens"] == 42 for sample in observed["trace"]["attempt_samples"]))

        class MixedProvider(Provider):
            async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
                self.attempts.append(copy.deepcopy(attempt_meta))
                self.calls.append(copy.deepcopy(messages))
                return cached if len(self.calls) % 2 else {"output_text": "摘要"}

        mixed, provider = await compile_turn(
            rows, current, window=1000, reserve=160, provider=MixedProvider(),
        )
        self.assertEqual(mixed["trace"]["projected_cache_attempt_count"], len(provider.calls))
        self.assertGreater(mixed["trace"]["cache_observed_attempt_count"], 0)
        self.assertGreater(mixed["trace"]["cache_unknown_attempt_count"], 0)
        self.assertFalse(mixed["trace"]["cache_observation_complete"])

    async def test_cache_projection_sanitizes_body_and_marks_malformed_or_exception_unknown(self) -> None:
        sentinel = "CACHE-PROJECTION-PRIVATE-BODY"
        rows = [group("g", "用" * 800, "答" * 800)]
        current = fold_current(rows, window=900, reserve=140)

        def with_body(stage: str, result: object, *, provider_returned: bool) -> dict:
            return {"status": "observed", "provider_returned": provider_returned,
                    "cache_read_input_tokens": 2, "cache_creation_input_tokens": 3, "body": sentinel}

        valid, _ = await compile_turn(rows, current, window=900, reserve=140, projector=with_body)
        self.assertNotIn(sentinel, repr(valid["trace"]))
        self.assertEqual(valid["trace"]["cache_projection_error_count"], 0)

        def malformed(stage: str, result: object, *, provider_returned: bool) -> dict:
            return {"status": "observed", "provider_returned": not provider_returned,
                    "cache_read_input_tokens": True, "cache_creation_input_tokens": 0}

        invalid, provider = await compile_turn(rows, current, window=900, reserve=140, projector=malformed)
        self.assertEqual(invalid["trace"]["cache_unknown_attempt_count"], len(provider.calls))
        self.assertEqual(invalid["trace"]["cache_projection_error_count"], len(provider.calls))

        def raising(stage: str, result: object, *, provider_returned: bool) -> dict:
            raise RuntimeError("projection failed")

        errored, provider = await compile_turn(rows, current, window=900, reserve=140, projector=raising)
        self.assertEqual(errored["status"], "ready")
        self.assertEqual(errored["trace"]["cache_projection_error_count"], len(provider.calls))
        self.assertFalse(errored["trace"]["cache_observation_complete"])

    async def test_mutating_cache_projector_cannot_change_summary_or_chunk_receipts(self) -> None:
        provider_result = {"output_text": "稳定摘要", "usage": {"cacheReadInputTokens": 7}}

        def stable(stage: str, result: object, *, provider_returned: bool) -> dict:
            return {"status": "unknown", "provider_returned": provider_returned}

        mutations: list[dict] = []

        def mutating(stage: str, result: object, *, provider_returned: bool) -> dict:
            if isinstance(result, dict):
                mutations.append(copy.deepcopy(result))
                result.clear()
            return {"status": "unknown", "provider_returned": provider_returned}

        fixtures = (
            ([group(f"g-{index}", "用" * 300, "答" * 300) for index in range(4)], 1000, 160),
            ([group("huge-1", "甲" * 80, "甲答" * 80), group("huge-2", "乙" * 80, "乙答" * 80),
              group("normal", "短" * 20, "短答" * 20)], 300, 40),
        )
        for rows, window, reserve in fixtures:
            current = fold_current(rows, window=window, reserve=reserve, require_all=True)
            baseline, _ = await compile_turn(
                rows, current, window=window, reserve=reserve,
                provider=Provider(copy.deepcopy(provider_result)), projector=stable,
            )
            mutated, _ = await compile_turn(
                rows, current, window=window, reserve=reserve,
                provider=Provider(copy.deepcopy(provider_result)), projector=mutating,
            )
            self.assertEqual(mutated["checkpoint_candidate"], baseline["checkpoint_candidate"])
            self.assertEqual(mutated["physical_provider_messages"], baseline["physical_provider_messages"])
            self.assertEqual(
                [(row.get("receipt_id"), row.get("result_sha256")) for row in mutated["trace"]["attempt_samples"]],
                [(row.get("receipt_id"), row.get("result_sha256")) for row in baseline["trace"]["attempt_samples"]],
            )
        self.assertTrue(mutations)

    async def test_non_json_provider_extras_fail_summary_and_chunk_without_escaping(self) -> None:
        non_json = {"output_text": "可见摘要", "extra": {"not-json"}}
        fixtures = (
            ([group(f"g-{index}", "用" * 300, "答" * 300) for index in range(4)], 1000, 160, "summary"),
            ([group("huge", "用" * 1200, "答" * 1200)], 800, 120, "chunk"),
        )
        for rows, window, reserve, kind in fixtures:
            current = fold_current(rows, window=window, reserve=reserve, require_all=True)
            result, provider = await compile_turn(
                rows, current, window=window, reserve=reserve, provider=Provider(copy.deepcopy(non_json)),
            )
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(result["trace"]["reason"], f"{kind}_result_invalid")
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(result["trace"]["projected_cache_attempt_count"], 1)
            self.assertEqual(result["trace"]["cache_unknown_attempt_count"], 1)
            self.assertEqual(result["trace"]["cache_projection_error_count"], 1)
            self.assertEqual(result["trace"]["accepted_receipt_count"], 0)
            self.assertTrue(result["trace"]["attempt_samples"][0]["provider_returned"])
            self.assertFalse(result["trace"]["attempt_samples"][0]["accepted"])
            self.assertEqual(result["physical_provider_messages"], [])
            self.assertIsNone(result["checkpoint_candidate"])

    async def test_callback_failures_and_nonvisible_results_leave_no_partial_state(self) -> None:
        rows = [group("g-1", "用" * 1200, "答" * 1200)]
        current = fold_current(rows, window=800, reserve=120)

        class RaisingProvider(Provider):
            async def __call__(self, attempt_meta: dict, messages: list[dict]) -> object:
                self.attempts.append(copy.deepcopy(attempt_meta))
                self.calls.append(messages)
                raise RuntimeError("provider failed")

        for provider in (
            RaisingProvider(),
            Provider(result=""),
            Provider(result={"type": "reasoning", "text": "隐藏思考"}),
            Provider(result={"type": "tool_result", "output_text": "工具"}),
        ):
            result, callback = await compile_turn(rows, current, window=800, reserve=120, provider=provider)
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(result["physical_provider_messages"], [])
            self.assertIsNone(result["checkpoint_candidate"])
            self.assertEqual(result["trace"]["summary_call_count"], len(callback.calls))
            returned = 0 if isinstance(provider, RaisingProvider) else 1
            self.assertEqual(result["trace"]["provider_returned_count"], returned)
            self.assertEqual(result["trace"]["accepted_receipt_count"], 0)
            self.assertFalse(result["trace"]["attempt_samples"][0]["accepted"])
            self.assertNotIn("receipt_id", result["trace"]["attempt_samples"][0])
            self.assertEqual(result["trace"]["attempt_samples"][0]["provider_returned"], bool(returned))
            self.assertEqual(result["trace"]["projected_cache_attempt_count"], 1)
            self.assertEqual(result["trace"]["attempt_samples"][0]["cache"]["provider_returned"], bool(returned))
            self.assertEqual(result["trace"]["attempt_samples"][0]["cache"]["status"], "unknown")

    async def test_truncated_summary_and_chunk_never_mint_receipt_or_checkpoint(self) -> None:
        summary_rows = [group(f"g-{index}", "用" * 300, "答" * 300) for index in range(4)]
        summary_current = fold_current(summary_rows, window=1000, reserve=160, require_all=True)
        truncated_results = (
            {"choices": [{"message": {"role": "assistant", "content": "半截摘要"}, "finish_reason": "length"}]},
            {"status": "incomplete", "output_text": "半截摘要"},
            {"choices": [{"message": {"role": "assistant", "content": "半截摘要"}, "finish_reason": "MAX_TOKENS"}]},
        )
        for truncated in truncated_results:
            result, provider = await compile_turn(
                summary_rows, summary_current, window=1000, reserve=160,
                provider=Provider(copy.deepcopy(truncated)),
            )
            self.assertEqual(
                (result["status"], result["trace"]["reason"]),
                ("fallback", "summary_result_incomplete"),
            )
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(result["trace"]["accepted_receipt_count"], 0)
            self.assertFalse(result["trace"]["attempt_samples"][0]["accepted"])
            self.assertFalse(result["trace"]["body_included"])
            self.assertIsNone(result["checkpoint_candidate"])

        complete, _ = await compile_turn(
            summary_rows, summary_current, window=1000, reserve=160,
            provider=Provider({
                "choices": [{"message": {"role": "assistant", "content": "完整摘要"}, "finish_reason": "stop"}],
            }),
        )
        self.assertEqual(complete["status"], "ready")

        chunk_rows = [group("huge", "用" * 1200, "答" * 1200)]
        chunk_current = fold_current(chunk_rows, window=800, reserve=120)
        chunk_result, chunk_provider = await compile_turn(
            chunk_rows, chunk_current, window=800, reserve=120,
            provider=Provider({
                "choices": [{"message": {"role": "assistant", "content": "半截分片"}, "finish_reason": "MAX_TOKENS"}],
            }),
        )
        self.assertEqual(
            (chunk_result["status"], chunk_result["trace"]["reason"]),
            ("fallback", "summary_chunk_result_incomplete"),
        )
        self.assertEqual(len(chunk_provider.calls), 1)
        self.assertEqual(chunk_provider.attempts[0]["kind"], "chunk")
        self.assertEqual(chunk_result["trace"]["accepted_receipt_count"], 0)
        self.assertFalse(chunk_result["trace"]["attempt_samples"][0]["accepted"])
        self.assertNotIn("receipt_id", chunk_result["trace"]["attempt_samples"][0])
        self.assertFalse(chunk_result["trace"]["body_included"])
        self.assertIsNone(chunk_result["checkpoint_candidate"])

    async def test_atomic_image_too_large_fails_without_callback(self) -> None:
        image = [{"type": "image_url", "image_url": {"url": "https://example.invalid/huge.png"}}]
        rows = [group("image", image, "看到了")]

        def expensive_image(messages: list[dict]) -> int:
            return sum(10000 if isinstance(row.get("content"), list) else len(str(row.get("content") or "")) for row in messages)

        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        result, provider = await compile_turn(rows, current, window=500, reserve=50, estimator=expensive_image)
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["trace"]["reason"], "atomic_fragment_too_large")
        self.assertEqual(provider.calls, [])

    async def test_invalid_bundle_budget_state_and_current_fail_before_callback(self) -> None:
        rows = [group("g-1", "用户", "回答")]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        corrupt_state = bundle(rows)
        corrupt_state["continuity"] = {"status": "ready", "state": {"revision": 1}}
        invalids = (
            {"raw_bundle": {"source": []}},
            {"raw_bundle": bundle(rows, source_status="incomplete")},
            {"raw_bundle": corrupt_state},
            {"raw_bundle": {**bundle(rows), "continuity": {"status": "unavailable", "state": {}}}},
            {"window": True},
            {"reserve": -1},
            {"fixed": True},
            {"current": {"role": "user", "message_id": "u-g-1", "content": "重复ID"}},
            {"current": {"role": "user", "message_id": "", "content": "无ID"}},
        )
        for case in invalids:
            provider = Provider()
            result, _ = await compile_turn(
                rows, case.get("current", current), provider=provider,
                window=case.get("window", 2500), reserve=case.get("reserve", 300),
                fixed=case.get("fixed", 0), raw_bundle=case.get("raw_bundle"),
            )
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(provider.calls, [])
            self.assertIsNone(result["checkpoint_candidate"])

    async def test_trace_is_body_free_and_checkpoint_stays_out_of_provider_messages(self) -> None:
        sentinel = "SENTINEL-CURRENT-PRIVATE-BODY"
        rows = [group("g-1", "历史" * 800, "回答" * 800)]
        current = fold_current(rows, window=900, reserve=140)
        current["content"] = sentinel + current["content"]
        result, provider = await compile_turn(rows, current, window=900, reserve=140)
        self.assertEqual(result["status"], "ready")
        self.assertNotIn(sentinel, repr(result["trace"]))
        self.assertFalse(any(sentinel in repr(call) for call in provider.calls))
        self.assertNotIn("provider_result", repr(result["trace"]))
        self.assertNotIn("summary_text", result["trace"])


if __name__ == "__main__":
    unittest.main()
