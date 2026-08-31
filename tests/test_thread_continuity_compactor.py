from __future__ import annotations

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

context_compactor = importlib.import_module(f"{PACKAGE}.context_compactor")
accept_summary_chunk_attempt = context_compactor.accept_summary_chunk_attempt
accept_summary_attempt = context_compactor.accept_summary_attempt
build_thread_continuity_checkpoint_v2 = (
    context_compactor.build_thread_continuity_checkpoint_v2
)
build_thread_continuity_checkpoint_from_attempts = (
    context_compactor.build_thread_continuity_checkpoint_from_attempts
)
normalize_complete_thread_groups = context_compactor.normalize_complete_thread_groups
normalize_thread_continuity_fold_plan = (
    context_compactor.normalize_thread_continuity_fold_plan
)
normalize_thread_continuity_checkpoint = (
    context_compactor.normalize_thread_continuity_checkpoint
)
plan_next_summary_chunk_attempt = context_compactor.plan_next_summary_chunk_attempt
plan_next_summary_attempt = context_compactor.plan_next_summary_attempt
plan_thread_continuity_fold = context_compactor.plan_thread_continuity_fold
render_thread_continuity_checkpoint_message = (
    context_compactor.render_thread_continuity_checkpoint_message
)
thread_continuity_prefix_fingerprint = (
    context_compactor.thread_continuity_prefix_fingerprint
)
thread_continuity_retirement_source_group_ids = (
    context_compactor.thread_continuity_retirement_source_group_ids
)
validate_thread_continuity_input = context_compactor.validate_thread_continuity_input


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


def group(source_id: str, user: object, assistant: object, *, event_at: str = "2026-08-09T00:00:00Z") -> dict:
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


def v2_checkpoint_fixture(
    *,
    previous_state: dict | None,
    source_groups: list[dict],
    covered_source_group_ids: list[str],
    summary_text: str,
) -> dict:
    reference_at = max(
        str(row.get("effective_event_at") or "") for row in source_groups
    )
    return build_thread_continuity_checkpoint_v2(
        previous_state=previous_state,
        source_groups=source_groups,
        retired_source_group_ids=covered_source_group_ids,
        bridge_source_group_ids=covered_source_group_ids,
        bridge_text=summary_text,
        bridge_policy={
            "reference_at": reference_at,
            "recent_horizon_hours": 72,
            "source_token_limit": 24_000,
            "output_token_limit": 2_048,
        },
    )


def fold_plan(
    rows: list[dict],
    *,
    window: int = 2500,
    reserve: int = 300,
    fixed_non_message: int = 0,
    current: dict | None = None,
    previous: dict | None = None,
    estimator=estimate_messages,
    minimum_fold_ids: list[str] | None = None,
    tail: object = None,
) -> dict:
    return plan_thread_continuity_fold(
        rows,
        current_ephemeral=current
        or {"role": "user", "message_id": "u-current", "content": "当前用户消息"},
        context_window_tokens=window,
        reserved_output_tokens=reserve,
        fixed_non_message_tokens=fixed_non_message,
        fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
        source_complete=True,
        estimate_messages=estimator,
        previous_state=previous,
        minimum_fold_source_group_ids=minimum_fold_ids,
        post_current_messages=tail,
    )


def validate_owner_plan(
    plan: dict, rows: list[dict], *, previous: dict | None = None,
    current: dict | None = None, window: int = 2500, reserve: int = 300,
    fixed_non_message: int = 0,
    fixed: list[dict] | None = None,
    tail: object = None,
) -> dict:
    return normalize_thread_continuity_fold_plan(
        plan,
        source_groups=rows,
        current_ephemeral=current
        or {"role": "user", "message_id": "u-current", "content": "当前用户消息"},
        context_window_tokens=window,
        reserved_output_tokens=reserve,
        fixed_non_message_tokens=fixed_non_message,
        fixed_prompt_messages=fixed or [{"role": "system", "content": "固定系统提示"}],
        source_complete=True,
        estimate_messages=estimate_messages,
        previous_state=previous,
        post_current_messages=tail,
    )


def summary_owner(
    rows: list[dict], *, window: int = 2500, reserve: int = 300,
    fixed_non_message: int = 0,
    previous: dict | None = None,
) -> tuple[dict, dict]:
    previous_ids = thread_continuity_retirement_source_group_ids(previous)
    minimum = previous_ids or [row["source_prefix_id"] for row in rows]
    for size in range(1, window + 1, 10):
        current = {"role": "user", "message_id": "u-current", "content": "当" * size}
        pressure_owner = fold_plan(
            rows, window=window, reserve=reserve, current=current,
            fixed_non_message=fixed_non_message,
            previous=previous, minimum_fold_ids=previous_ids,
        )
        if pressure_owner["status"] == "fold_required" or pressure_owner.get("fold_plan_id"):
            owner = fold_plan(
                rows, window=window, reserve=reserve, current=current,
                fixed_non_message=fixed_non_message,
                previous=previous, minimum_fold_ids=minimum,
            )
            return owner, current
    return pressure_owner, current


def summary_attempt(
    rows: list[dict], owner: dict, current: dict, *,
    previous: dict | None = None, accepted_attempts: list[dict] | None = None,
    chunk_completions: list[list[dict]] | None = None,
    tail: object = None,
) -> dict:
    return plan_next_summary_attempt(
        rows,
        fold_plan=owner,
        current_ephemeral=current,
        context_window_tokens=owner.get("context_window_tokens"),
        reserved_output_tokens=owner.get("reserved_output_tokens"),
        fixed_non_message_tokens=owner.get("fixed_non_message_tokens"),
        fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
        source_complete=True,
        estimate_messages=estimate_messages,
        previous_checkpoint=previous,
        minimum_fold_source_group_ids=owner["covered_source_group_ids"],
        accepted_attempts=accepted_attempts,
        accepted_chunk_completions=chunk_completions,
        post_current_messages=tail,
    )


def accept_attempt(
    plan: dict, result: object, rows: list[dict], owner: dict, current: dict, *,
    previous: dict | None = None, accepted_attempts: list[dict] | None = None,
    chunk_completions: list[list[dict]] | None = None,
    tail: object = None,
) -> dict:
    return accept_summary_attempt(
        plan["descriptor"], result,
        groups=rows,
        fold_plan=owner,
        current_ephemeral=current,
        context_window_tokens=owner["context_window_tokens"],
        reserved_output_tokens=owner["reserved_output_tokens"],
        fixed_non_message_tokens=owner["fixed_non_message_tokens"],
        fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
        source_complete=True,
        estimate_messages=estimate_messages,
        previous_checkpoint=previous,
        minimum_fold_source_group_ids=owner["covered_source_group_ids"],
        accepted_attempts=accepted_attempts,
        accepted_chunk_completions=chunk_completions,
        post_current_messages=tail,
    )


def chunk_inputs(
    rows: list[dict], owner: dict, current: dict, *, previous: dict | None = None,
    estimator=estimate_messages, summary_attempts: list[dict] | None = None,
    chunk_completions: list[list[dict]] | None = None,
    chunk_attempts: list[dict] | None = None, minimum: list[str] | None = None,
    tail: object = None,
) -> dict:
    return {
        "groups": rows,
        "fold_plan": owner,
        "current_ephemeral": current,
        "context_window_tokens": owner["context_window_tokens"],
        "reserved_output_tokens": owner["reserved_output_tokens"],
        "fixed_non_message_tokens": owner["fixed_non_message_tokens"],
        "fixed_prompt_messages": [{"role": "system", "content": "固定系统提示"}],
        "source_complete": True,
        "estimate_messages": estimator,
        "previous_checkpoint": previous,
        "minimum_fold_source_group_ids": (
            owner["covered_source_group_ids"]
            if minimum is None else minimum
        ),
        "accepted_summary_attempts": summary_attempts,
        "accepted_chunk_completions": chunk_completions,
        "accepted_chunk_attempts": chunk_attempts,
        "post_current_messages": tail,
    }


def checkpoint_from_attempts(
    rows: list[dict], owner: dict, current: dict, *, previous: dict | None = None,
    summary_attempts: list[dict] | None = None,
    chunk_completions: list[list[dict]] | None = None,
    tail: object = None,
    **owner_overrides: object,
) -> dict:
    inputs = {
        "source_groups": rows, "fold_plan": owner, "current_ephemeral": current,
        "context_window_tokens": owner["context_window_tokens"],
        "reserved_output_tokens": owner["reserved_output_tokens"],
        "fixed_non_message_tokens": owner["fixed_non_message_tokens"],
        "fixed_prompt_messages": [{"role": "system", "content": "固定系统提示"}],
        "source_complete": True, "estimate_messages": estimate_messages,
        "previous_checkpoint": previous,
        "minimum_fold_source_group_ids": owner["covered_source_group_ids"],
        "accepted_summary_attempts": summary_attempts,
        "accepted_chunk_completions": chunk_completions,
        "post_current_messages": tail,
    }
    inputs.update(owner_overrides)
    return build_thread_continuity_checkpoint_from_attempts(**inputs)


class ThreadContinuityIdentityTests(unittest.TestCase):
    def test_proactive_assistant_group_is_atomic_and_untyped_singleton_stays_incomplete(self) -> None:
        dialogue = group("dialogue", "用户", "回答")
        proactive = proactive_group("proactive", "主动来到前台的原话")
        normalized = normalize_complete_thread_groups([dialogue, proactive])

        self.assertTrue(normalized["complete"])
        self.assertEqual(
            [row["group_kind"] for row in normalized["groups"]],
            ["dialogue_turn", "proactive_assistant_event"],
        )
        self.assertEqual(
            [message["role"] for message in normalized["groups"][1]["messages"]],
            ["assistant"],
        )
        no_kind = copy.deepcopy(proactive)
        no_kind.pop("group_kind")
        legacy_pair = copy.deepcopy(dialogue)
        legacy_pair.pop("group_kind")
        wrong_role = copy.deepcopy(proactive)
        wrong_role["messages"][0]["role"] = "user"
        wrong_pair = copy.deepcopy(proactive)
        wrong_pair["messages"].insert(0, {"role": "user", "message_id": "u", "content": "伪造"})
        self.assertFalse(normalize_complete_thread_groups([no_kind])["complete"])
        self.assertFalse(normalize_complete_thread_groups([legacy_pair])["complete"])
        self.assertFalse(normalize_complete_thread_groups([wrong_role])["complete"])
        self.assertFalse(normalize_complete_thread_groups([wrong_pair])["complete"])

    def test_mixed_dialogue_and_proactive_groups_reach_one_summary_attempt_in_order(self) -> None:
        rows = [
            group("dialogue-1", "用户一" * 100, "回答一" * 100),
            proactive_group("proactive-1", "主动原话" * 100),
            group("dialogue-2", "用户二" * 100, "回答二" * 100),
        ]
        owner, current = summary_owner(rows, window=2500, reserve=100)
        attempt = summary_attempt(rows, owner, current)

        self.assertEqual(owner["status"], "fold_required")
        self.assertEqual(owner["covered_source_group_ids"], [
            "dialogue-1", "proactive-1", "dialogue-2",
        ])
        self.assertEqual(attempt["status"], "ready")
        self.assertEqual(
            [message["role"] for message in attempt["provider_messages"][2:]],
            ["user", "assistant", "assistant", "user", "assistant"],
        )

        checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["dialogue-1", "proactive-1", "dialogue-2"],
            summary_text="accepted summary",
        )
        self.assertEqual(
            checkpoint["retirement_cursor"]["source_prefix_ids"],
            ["dialogue-1", "proactive-1", "dialogue-2"],
        )
        self.assertEqual(
            len(checkpoint["retirement_cursor"]["source_group_fingerprints"]), 3
        )

        changed = copy.deepcopy(rows)
        changed[1] = group("proactive-1", "后来出现的用户", "主动原话" * 100)
        with self.assertRaisesRegex(ValueError, "thread_continuity_checkpoint_invalid"):
            normalize_thread_continuity_checkpoint(checkpoint, source_groups=changed)
        rebuilt = v2_checkpoint_fixture(
            previous_state=checkpoint,
            source_groups=changed,
            covered_source_group_ids=["dialogue-1", "proactive-1", "dialogue-2"],
            summary_text="rebuilt summary",
        )
        self.assertEqual(rebuilt["lineage_status"], "rebuilt")
        self.assertEqual(rebuilt["predecessor_revision_id"], "")

    def test_complete_groups_keep_multimodal_bodies_and_use_canonical_identity(self) -> None:
        image = [{"type": "image_url", "image_url": {"url": "https://example.invalid/a.png"}}]
        same_text_one = group("g-1", "一样", "一样")
        same_text_two = group("g-2", "一样", "一样")
        multimodal = group("g-3", image, "看到了")
        normalized = normalize_complete_thread_groups(
            [same_text_one, same_text_two, same_text_one, multimodal]
        )
        self.assertTrue(normalized["complete"])
        self.assertEqual(
            [row["source_prefix_id"] for row in normalized["groups"]],
            ["g-1", "g-2", "g-3"],
        )
        self.assertEqual(normalized["groups"][2]["messages"][0]["content"], image)
        typed = [{"type": "input_text", "text": "输入"}, *image]
        typed_group = group("g-typed", typed, "回答")
        typed_normalized = normalize_complete_thread_groups([typed_group])
        self.assertTrue(typed_normalized["complete"])
        self.assertEqual(typed_normalized["groups"][0]["messages"][0]["content"], typed)
        unknown = group("g-unknown", [{"type": "audio", "data": "opaque"}], "回答")
        self.assertFalse(normalize_complete_thread_groups([unknown])["complete"])
        malformed_image = group("g-image-bad", [{"type": "image_url"}], "回答")
        self.assertFalse(normalize_complete_thread_groups([malformed_image])["complete"])
        self.assertNotEqual(
            thread_continuity_prefix_fingerprint(normalized["groups"][:1]),
            thread_continuity_prefix_fingerprint(normalized["groups"][:2]),
        )

        conflict = group("g-1", "正文变了", "一样")
        self.assertFalse(normalize_complete_thread_groups([same_text_one, conflict])["complete"])
        reused_message = group("g-4", "不同", "不同")
        reused_message["messages"][0]["message_id"] = "u-g-1"
        identity_conflict = normalize_complete_thread_groups([same_text_one, reused_message])
        self.assertFalse(identity_conflict["complete"])
        self.assertTrue(any(error.startswith("source_identity_conflict:") for error in identity_conflict["errors"]))
        within_pair = group("g-pair", "用户", "回答")
        within_pair["messages"][1]["message_id"] = within_pair["messages"][0]["message_id"]
        self.assertFalse(normalize_complete_thread_groups([within_pair])["complete"])
        incomplete = {**group("g-bad", "user", "assistant"), "messages": [{"role": "user", "content": "user"}]}
        self.assertFalse(normalize_complete_thread_groups([incomplete])["complete"])

    def test_current_user_is_ephemeral_and_never_enters_durable_prefix(self) -> None:
        rows = [group("g-1", "历史用户", "历史回答")]
        normalized = normalize_complete_thread_groups(
            rows,
            current_ephemeral={
                "role": "user",
                "message_id": "u-current",
                "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid/current.png"}}],
                "content_hash": "caller-forged",
            },
        )
        self.assertTrue(normalized["complete"])
        self.assertEqual([row["source_prefix_id"] for row in normalized["groups"]], ["g-1"])
        self.assertTrue(normalized["current_ephemeral"]["ephemeral"])
        self.assertEqual(normalized["current_ephemeral"]["message_id"], "u-current")
        self.assertNotEqual(normalized["current_ephemeral"]["content_hash"], "caller-forged")
        self.assertNotIn("u-current", normalized["groups"][0]["message_ids"])

    def test_opaque_revision_binds_ordered_prefix_summary_and_predecessor(self) -> None:
        rows = [group("g-1", "一", "答一"), group("g-2", "二", "答二")]
        first = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows[:1],
            covered_source_group_ids=["g-1"],
            summary_text="第一版摘要",
        )
        self.assertRegex(first["revision_id"], r"^tcr_[0-9a-f]{64}$")
        second = v2_checkpoint_fixture(
            previous_state=first,
            source_groups=rows,
            covered_source_group_ids=["g-1", "g-2"],
            summary_text="第二版摘要",
        )
        self.assertEqual(second["lineage_status"], "continued")
        self.assertEqual(second["predecessor_revision_id"], first["revision_id"])
        self.assertEqual(second["source_group_ids"], ["g-1", "g-2"])
        self.assertEqual(
            normalize_thread_continuity_checkpoint(second, source_groups=rows, previous_state=first),
            second,
        )

        with self.assertRaisesRegex(ValueError, "retirement_cursor_regression"):
            v2_checkpoint_fixture(
                previous_state=second,
                source_groups=rows,
                covered_source_group_ids=["g-1"],
                summary_text="不得缩短",
            )

    def test_late_repair_reorder_or_substitution_rebuilds_from_canonical_source(self) -> None:
        rows = [group("g-1", "原始", "回答"), group("g-2", "后续", "回答")]
        checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["g-1"],
            summary_text="旧摘要",
        )
        variants = (
            [group("g-1", "修复正文", "回答"), rows[1]],
            [group("g-1", "原始", "回答", event_at="2026-08-09T00:01:00Z"), rows[1]],
            [rows[1], rows[0]],
        )
        for changed in variants:
            rebuilt = v2_checkpoint_fixture(
                previous_state=checkpoint,
                source_groups=changed,
                covered_source_group_ids=[changed[0]["source_prefix_id"]],
                summary_text="从 canonical 原文重建",
            )
            self.assertEqual(rebuilt["lineage_status"], "rebuilt")
            self.assertEqual(rebuilt["predecessor_revision_id"], "")

    def test_checkpoint_tampering_fails_closed(self) -> None:
        rows = [group("g-1", "用户", "回答")]
        state = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["g-1"],
            summary_text="摘要",
        )
        tampered_rows = (
            {**state, "revision_id": "tcr_" + "0" * 64},
            {
                **state,
                "recent_bridge": {
                    **state["recent_bridge"],
                    "body_sha256": "0" * 64,
                },
            },
            {**state, "source_fingerprint": "0" * 64},
            {
                **state,
                "retirement_cursor": {
                    **state["retirement_cursor"],
                    "source_group_fingerprints": ["0" * 64],
                },
            },
        )
        for tampered in tampered_rows:
            with self.assertRaises(ValueError):
                normalize_thread_continuity_checkpoint(tampered, source_groups=rows)

        two_rows = [*rows, group("g-2", "用户二", "回答二")]
        two_covered = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=two_rows,
            covered_source_group_ids=["g-1", "g-2"],
            summary_text="两轮摘要",
        )
        reduced_source = {
            **two_covered,
            "source_group_ids": ["g-1"],
            "source_fingerprint": thread_continuity_prefix_fingerprint(
                normalize_complete_thread_groups(rows)["groups"]
            ),
        }
        with self.assertRaises(ValueError):
            normalize_thread_continuity_checkpoint(reduced_source, source_groups=two_rows)

    def test_checkpoint_renderer_has_one_validated_system_message_owner(self) -> None:
        rows = [group("g-1", "用户", "回答")]
        checkpoint = v2_checkpoint_fixture(
            previous_state=None, source_groups=rows,
            covered_source_group_ids=["g-1"], summary_text="可递送摘要",
        )
        rendered = render_thread_continuity_checkpoint_message(
            checkpoint, source_groups=rows,
        )
        self.assertEqual(rendered["role"], "system")
        self.assertIn(checkpoint["revision_id"], rendered["content"])
        self.assertTrue(rendered["content"].endswith("可递送摘要"))
        forged = {
            **checkpoint,
            "recent_bridge": {
                **checkpoint["recent_bridge"],
                "body": "伪摘要",
            },
        }
        with self.assertRaises(ValueError):
            render_thread_continuity_checkpoint_message(forged, source_groups=rows)


class ThreadContinuityPlannerTests(unittest.TestCase):
    def test_raw_fit_is_never_folded_by_turn_count(self) -> None:
        rows = [group(f"g-{index}", f"u{index}", f"a{index}") for index in range(100)]
        plan = fold_plan(rows, window=10000, reserve=0)
        self.assertEqual((plan["status"], plan["reason"]), ("no_fold", "within_budget"))
        self.assertEqual(plan["raw_suffix_group_ids"], [f"g-{index}" for index in range(100)])

    def test_minimum_prefix_preserves_names_multimodal_and_current_once(self) -> None:
        rows = [group(f"g-{index}", "门" * 900, "a " * 900) for index in range(3)]
        rows[0]["messages"][0]["name"] = "owner"
        images = [
            {"type": "image_url", "image_url": {"url": f"https://example.invalid/{index}.png"}}
            for index in range(4)
        ]
        seen: list[list[dict]] = []

        def estimator(messages: list[dict]) -> int:
            seen.append(messages)
            return estimate_messages(messages)

        plan = fold_plan(
            rows,
            window=3000,
            estimator=estimator,
            current={"role": "user", "name": "current-owner", "message_id": "u-current", "content": images},
        )
        self.assertEqual(plan["fold_source_group_ids"], ["g-0", "g-1"])
        self.assertEqual(plan["raw_suffix_group_ids"], ["g-2"])
        self.assertTrue(any(message.get("name") == "owner" for call in seen for message in call))
        self.assertTrue(any(message.get("name") == "current-owner" for call in seen for message in call))
        self.assertTrue(any(message.get("content") == images for call in seen for message in call))

    def test_blocked_statuses_oversized_signal_reserve_and_identity(self) -> None:
        rows = [group("small", "短", "短"), group("huge", "中" * 3000, "a" * 3000), group("tail", "尾", "尾")]
        oversized = fold_plan(rows)
        self.assertEqual(oversized["status"], "fold_required")
        self.assertEqual(oversized["oversized_raw_group_ids"], ["huge"])
        self.assertEqual(oversized["summary_call_feasibility"], "unverified")
        reserve = fold_plan([group("g-1", "中" * 2000, "a" * 2000)], reserve=0)
        self.assertEqual((reserve["status"], reserve["reason"]), ("blocked", "summary_output_budget_unavailable"))
        self.assertEqual(
            validate_thread_continuity_input(
                reserve, {"role": "system", "content": "摘要"},
                fixed_non_message_tokens=0, estimate_messages=estimate_messages,
                physical_owner_generation=object(),
            )["status"],
            "not_applicable",
        )
        unresolved = fold_plan(
            [group("g-1", "短", "短")],
            current={"role": "user", "message_id": "", "content": "当前"},
        )
        self.assertEqual((unresolved["status"], unresolved["reason"]), ("blocked", "identity_unresolved"))

    def test_previous_summary_infeasible_requires_canonical_rebuild(self) -> None:
        old = [group("g-old", "旧", "旧回答")]
        rows = old + [group("g-new", "新" * 2400, "答" * 2400)]
        previous = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=old,
            covered_source_group_ids=["g-old"],
            summary_text="旧摘要",
        )
        forged = {
            **previous,
            "recent_bridge": {
                **previous["recent_bridge"],
                "body": "伪造不同正文",
            },
        }
        plan = fold_plan(rows, previous=forged)
        fresh = fold_plan(rows)
        self.assertEqual((plan["status"], plan["continuity_mode"]), ("fold_required", "rebuild"))
        self.assertEqual(plan["predecessor_revision_id"], "")
        self.assertEqual(plan["fold_source_group_ids"], fresh["fold_source_group_ids"])
        self.assertEqual(plan["raw_suffix_group_ids"], fresh["raw_suffix_group_ids"])
        self.assertEqual(plan["fold_plan_id"], fresh["fold_plan_id"])

        huge_previous = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=old,
            covered_source_group_ids=["g-old"],
            summary_text="旧摘要" * 1000,
        )
        infeasible = fold_plan(
            rows,
            previous=huge_previous,
        )
        self.assertEqual(infeasible["reason"], "rebuild_from_canonical_required")

    def test_proposed_summary_is_reestimated_and_replan_strictly_advances(self) -> None:
        rows = [group(f"g-{index}", "用" * 900, "答" * 900) for index in range(3)]
        plan = fold_plan(rows, window=2800)
        ready = validate_thread_continuity_input(
            plan,
            {"role": "system", "name": "continuity", "content": "[marker]\n短摘要"},
            fixed_non_message_tokens=plan["fixed_non_message_tokens"],
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(ready["status"], "ready")
        provider = ready["provider_messages"]
        self.assertEqual(provider[1]["name"], "continuity")
        self.assertEqual(provider[-1]["content"], "当前用户消息")
        self.assertEqual(sum(message["content"] == "当前用户消息" for message in provider), 1)
        self.assertEqual([message["role"] for message in provider[2:-1]], ["user", "assistant"])

        plan["raw_suffix_groups"][0]["messages"][0]["name"] = "raw-owner"
        plan["current_ephemeral"]["name"] = "current-owner"
        named_ready = validate_thread_continuity_input(
            {**plan, "context_window_tokens": 10000},
            {"role": "system", "content": "[marker]\n短摘要"},
            fixed_non_message_tokens=plan["fixed_non_message_tokens"],
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        named_messages = named_ready["provider_messages"]
        self.assertEqual(named_messages[-1]["name"], "current-owner")
        self.assertTrue(any(message.get("name") == "raw-owner" for message in named_messages))
        unnamed_tokens = estimate_messages([{key: value for key, value in message.items() if key != "name"} for message in named_messages])
        boundary = validate_thread_continuity_input(
            {**plan, "context_window_tokens": unnamed_tokens + plan["reserved_output_tokens"]},
            {"role": "system", "content": "[marker]\n短摘要"},
            fixed_non_message_tokens=plan["fixed_non_message_tokens"],
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(boundary["status"], "replan_required")

        replan = validate_thread_continuity_input(
            plan,
            {"role": "system", "content": "[marker]\n" + "摘要" * 2100},
            fixed_non_message_tokens=plan["fixed_non_message_tokens"],
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(replan["status"], "replan_required")
        self.assertEqual(replan["required_fold_source_group_ids"], ["g-0", "g-1", "g-2"])
        advanced = fold_plan(
            rows, window=2800,
            minimum_fold_ids=replan["required_fold_source_group_ids"],
        )
        terminal = validate_thread_continuity_input(
            advanced,
            {"role": "system", "content": "[marker]\n" + "摘要" * 2100},
            fixed_non_message_tokens=advanced["fixed_non_message_tokens"],
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(terminal["status"], "blocked")

    def test_incremental_replan_emits_full_canonical_minimum_prefix(self) -> None:
        rows = [group(f"g-{index}", "用" * 900, "答" * 900) for index in range(3)]
        previous = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows[:1],
            covered_source_group_ids=["g-0"],
            summary_text="旧摘要",
        )
        plan = fold_plan(rows, previous=previous, window=2800)
        self.assertEqual(plan["fold_source_group_ids"], ["g-1"])
        self.assertEqual(plan["covered_source_group_ids"], ["g-0", "g-1"])
        self.assertEqual(plan["raw_suffix_group_ids"], ["g-2"])
        replan = validate_thread_continuity_input(
            plan,
            {"role": "system", "content": "[continuity]\n" + "摘要" * 2100},
            fixed_non_message_tokens=0,
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(replan["status"], "replan_required")
        self.assertEqual(replan["required_fold_source_group_ids"], ["g-0", "g-1", "g-2"])
        self.assertEqual(replan["required_covered_source_group_ids"], ["g-0", "g-1", "g-2"])
        expanded = fold_plan(
            rows, previous=previous, window=2800,
            minimum_fold_ids=replan["required_fold_source_group_ids"],
        )
        self.assertEqual(expanded["covered_source_group_ids"], ["g-0", "g-1", "g-2"])
        self.assertEqual(expanded["raw_suffix_group_ids"], [])
        attempts: list[dict] = []
        for index in range(3):
            attempt = summary_attempt(
                rows, expanded, {"role": "user", "message_id": "u-current", "content": "当前用户消息"},
                previous=previous, accepted_attempts=attempts,
            )
            if attempt["status"] == "complete":
                break
            result = f"扩展摘要{index}"
            accepted = accept_attempt(
                attempt, result, rows, expanded,
                {"role": "user", "message_id": "u-current", "content": "当前用户消息"},
                previous=previous, accepted_attempts=attempts,
            )
            attempts.append({"descriptor": attempt["descriptor"], "provider_result": result, "receipt": accepted["receipt"]})
        checkpoint = checkpoint_from_attempts(
            rows, expanded, {"role": "user", "message_id": "u-current", "content": "当前用户消息"},
            previous=previous, summary_attempts=attempts,
        )
        self.assertEqual(checkpoint["retirement_cursor"]["source_prefix_ids"], ["g-0", "g-1", "g-2"])

    def test_fold_plan_owner_identity_validates_rebuild_incremental_and_tamper(self) -> None:
        rows = [group(f"g-{index}", "用" * 800, "答" * 800) for index in range(3)]
        rebuild = fold_plan(rows)
        self.assertEqual((rebuild["status"], rebuild["continuity_mode"]), ("fold_required", "rebuild"))
        self.assertEqual(rebuild["predecessor_revision_id"], "")
        self.assertRegex(rebuild["fold_plan_id"], r"^tcfp_[0-9a-f]{64}$")
        self.assertEqual(validate_owner_plan(rebuild, rows), rebuild)

        checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows[:1],
            covered_source_group_ids=["g-0"],
            summary_text="第一轮摘要",
        )
        incremental = fold_plan(rows, previous=checkpoint)
        self.assertEqual(incremental["continuity_mode"], "incremental")
        self.assertEqual(incremental["predecessor_revision_id"], checkpoint["revision_id"])
        validate_owner_plan(incremental, rows, previous=checkpoint)

        tampered = {
            **rebuild,
            "fold_source_group_ids": list(reversed(rebuild["fold_source_group_ids"])),
        }
        tampered["fold_plan_id"] = context_compactor._fold_plan_id(
            tampered, normalize_complete_thread_groups(rows)["groups"]
        )
        with self.assertRaisesRegex(ValueError, "fold_plan_invalid"):
            validate_owner_plan(tampered, rows)

        raw_body = copy.deepcopy(rebuild)
        self.assertTrue(raw_body["raw_suffix_groups"])
        raw_body["raw_suffix_groups"][0]["messages"][0]["content"] = "伪造 raw body"
        raw_body["fold_plan_id"] = context_compactor._fold_plan_id(
            raw_body, normalize_complete_thread_groups(rows)["groups"]
        )
        injected_base = copy.deepcopy(rebuild)
        injected_base["base_messages"] = [{"role": "system", "content": "注入提示"}]
        injected_base["fixed_prompt_fingerprint"] = context_compactor._content_hash(
            injected_base["base_messages"]
        )
        injected_base["fold_plan_id"] = context_compactor._fold_plan_id(
            injected_base, normalize_complete_thread_groups(rows)["groups"]
        )
        changed_current = copy.deepcopy(rebuild)
        changed_current["current_ephemeral"]["content"] = "伪造当前正文"
        changed_current["current_ephemeral"]["content_hash"] = context_compactor._content_hash(
            "伪造当前正文"
        )
        changed_current["fold_plan_id"] = context_compactor._fold_plan_id(
            changed_current, normalize_complete_thread_groups(rows)["groups"]
        )
        changed_budget = {**rebuild, "context_window_tokens": 2600}
        changed_budget["fold_plan_id"] = context_compactor._fold_plan_id(
            changed_budget, normalize_complete_thread_groups(rows)["groups"]
        )
        for forged in (raw_body, injected_base, changed_current, changed_budget):
            with self.assertRaisesRegex(ValueError, "fold_plan_invalid"):
                validate_owner_plan(forged, rows)

    def test_invalid_inputs_never_authorize_fold(self) -> None:
        rows = [group("g-1", "用" * 900, "答" * 900)]
        for window, reserve in ((None, None), (100, 100), (True, 0), (100, -1)):
            plan = plan_thread_continuity_fold(
                rows,
                current_ephemeral={"role": "user", "message_id": "current", "content": "当前"},
                context_window_tokens=window,
                reserved_output_tokens=reserve,
                fixed_non_message_tokens=0,
                fixed_prompt_messages=[{"role": "system", "content": "固定"}],
                source_complete=True,
                estimate_messages=estimate_messages,
            )
            self.assertEqual((plan["status"], plan["reason"]), ("blocked", "budget_unknown"))
        invalid_fixed = plan_thread_continuity_fold(
            rows,
            current_ephemeral={"role": "user", "message_id": "current", "content": "当前"},
            context_window_tokens=2500,
            reserved_output_tokens=300,
            fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "user", "content": "不是固定提示"}],
            source_complete=True,
            estimate_messages=estimate_messages,
        )
        self.assertEqual(invalid_fixed["reason"], "base_prompt_invalid")
        self.assertEqual(fold_plan(rows, estimator=lambda _messages: True)["reason"], "estimator_invalid")

    def test_fixed_non_message_tokens_bind_owner_and_main_input_budget(self) -> None:
        short_rows = [group("short", "用" * 100, "答" * 100)]
        within = fold_plan(short_rows)
        self.assertEqual((within["status"], within["reason"]), ("no_fold", "within_budget"))
        physical = validate_thread_continuity_input(
            within, None, fixed_non_message_tokens=0, estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(physical["status"], "ready")
        self.assertEqual([message["role"] for message in physical["provider_messages"]], ["system", "user", "assistant", "user"])
        self.assertEqual(
            validate_thread_continuity_input(
                within, {"role": "system", "content": "不得生成摘要"},
                fixed_non_message_tokens=0, estimate_messages=estimate_messages,
                physical_owner_generation=object(),
            )["reason"],
            "summary_message_unexpected",
        )
        crossing_fixed = (
            within["context_window_tokens"]
            - within["reserved_output_tokens"]
            - within["estimated_main_input_tokens"]
            + 1
        )
        crossed = fold_plan(short_rows, fixed_non_message=crossing_fixed)
        self.assertEqual((crossed["status"], crossed["reason"]), ("fold_required", "token_pressure"))

        rows = [group(f"g-{index}", "用" * 900, "答" * 900) for index in range(3)]
        current = {"role": "user", "message_id": "u-current", "content": "当前用户消息"}
        initial = fold_plan(rows, current=current)
        summary = {"role": "system", "content": "[continuity]\n短摘要"}
        initial_ready = validate_thread_continuity_input(
            initial, summary, fixed_non_message_tokens=0, estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(initial_ready["status"], "ready")
        fixed_tokens = (
            initial["context_window_tokens"]
            - initial["reserved_output_tokens"]
            - initial_ready["estimated_input_tokens"]
            + 1
        )
        self.assertGreater(fixed_tokens, 0)
        pressured = fold_plan(rows, current=current, fixed_non_message=fixed_tokens)
        self.assertEqual(
            (pressured["status"], pressured["reason"]),
            ("blocked", "fixed_context_exceeds_budget"),
        )
        self.assertNotIn("fold_plan_id", pressured)
        self.assertEqual(
            validate_thread_continuity_input(
                initial,
                summary,
                fixed_non_message_tokens=1,
                estimate_messages=estimate_messages,
                physical_owner_generation=object(),
            )["reason"],
            "fixed_non_message_tokens_invalid",
        )

        def summary_call(owner: dict) -> dict:
            return plan_next_summary_attempt(
                rows,
                fold_plan=owner,
                current_ephemeral=current,
                context_window_tokens=owner["context_window_tokens"],
                reserved_output_tokens=owner["reserved_output_tokens"],
                fixed_non_message_tokens=owner["fixed_non_message_tokens"],
                fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
                source_complete=True,
                estimate_messages=estimate_messages,
                minimum_fold_source_group_ids=owner["fold_source_group_ids"],
            )

        bound = fold_plan(rows, current=current, fixed_non_message=1)
        plain_summary = summary_call(initial)
        bound_summary = summary_call(bound)
        self.assertEqual(plain_summary["provider_messages"], bound_summary["provider_messages"])
        self.assertNotEqual(
            plain_summary["descriptor"]["descriptor_id"],
            bound_summary["descriptor"]["descriptor_id"],
        )

        for invalid in (None, True, -1):
            plan = fold_plan(rows, current=current, fixed_non_message=invalid)
            self.assertEqual((plan["status"], plan["reason"]), ("blocked", "budget_unknown"))
        forged = {**initial, "fixed_non_message_tokens": 1}
        forged["fold_plan_id"] = context_compactor._fold_plan_id(
            forged, normalize_complete_thread_groups(rows)["groups"]
        )
        with self.assertRaisesRegex(ValueError, "fold_plan_invalid"):
            validate_owner_plan(forged, rows, current=current)


class ThreadContinuitySummaryBatchTests(unittest.TestCase):
    def test_openai_compatible_summary_without_role_is_visible_assistant_output(self) -> None:
        legal = {
            "choices": [{
                "message": {"content": "保留人、关系、决定、未完事项与必要因果。"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20},
        }
        self.assertEqual(
            context_compactor._visible_summary_text(legal),
            "保留人、关系、决定、未完事项与必要因果。",
        )
        explicit_non_assistant = copy.deepcopy(legal)
        explicit_non_assistant["choices"][0]["message"]["role"] = "user"
        self.assertEqual(context_compactor._visible_summary_text(explicit_non_assistant), "")

    def test_summary_receipt_and_checkpoint_cannot_cross_post_current_tail(self) -> None:
        rows = [group("g-1", "用户" * 40, "回答" * 40)]
        _owner, current = summary_owner(rows, window=700, reserve=120)
        tail_a = [{"role": "assistant", "name": "aji", "message_id": "tail-a", "content": "相同正文"}]
        tail_b = [{"role": "assistant", "name": "aji", "message_id": "tail-b", "content": "相同正文"}]
        owner_a = fold_plan(rows, window=700, reserve=120, current=current, tail=tail_a)
        owner_b = fold_plan(rows, window=700, reserve=120, current=current, tail=tail_b)
        self.assertEqual((owner_a["status"], owner_b["status"]), ("fold_required", "fold_required"))
        self.assertNotEqual(owner_a["fold_plan_id"], owner_b["fold_plan_id"])
        with self.assertRaisesRegex(ValueError, "fold_plan_invalid"):
            validate_owner_plan(owner_a, rows, current=current, window=700, reserve=120, tail=tail_b)

        planned = summary_attempt(rows, owner_a, current, tail=tail_a)
        accepted = accept_attempt(planned, "摘要A", rows, owner_a, current, tail=tail_a)
        attempt = [{
            "descriptor": planned["descriptor"],
            "provider_result": "摘要A",
            "receipt": accepted["receipt"],
        }]
        replay = summary_attempt(rows, owner_b, current, accepted_attempts=attempt, tail=tail_b)
        self.assertEqual((replay["status"], replay["reason"]), ("blocked", "accepted_receipt_invalid"))
        with self.assertRaisesRegex(ValueError, "summary_incomplete"):
            checkpoint_from_attempts(
                rows, owner_b, current, summary_attempts=attempt, tail=tail_b,
            )
        self.assertTrue(all(message.get("content") != tail_a[0]["content"] for message in planned["provider_messages"]))

    def test_prompt_preserves_typed_multimodal_names_and_excludes_current(self) -> None:
        parts = [
            {"type": "input_text", "text": "看这四张图"},
            *[
                {"type": "image_url", "image_url": {"url": f"https://example.invalid/{index}.png"}}
                for index in range(4)
            ],
        ]
        rows = [group("g-image", parts, "都看到了")]
        rows[0]["messages"][0]["name"] = "owner"
        owner, current = summary_owner(rows, window=5000)
        plan = summary_attempt(rows, owner, current)
        self.assertEqual(plan["status"], "ready")
        prompt = plan["provider_messages"]
        self.assertTrue(any(message.get("name") == "owner" for message in prompt))
        self.assertTrue(any(message.get("content") == parts for message in prompt))
        self.assertFalse(any(message.get("content") == current["content"] for message in prompt))
        instruction = prompt[0]["content"].lower()
        for term in ("people", "events", "decisions", "emotions", "causes", "promises", "open loops", "uncertainty"):
            self.assertIn(term, instruction)
        for term in ("profile", "persona", "memory", "diagnosis", "preference", "action authority"):
            self.assertIn(term, instruction)

    def test_visible_output_contract_accepts_only_assistant_text(self) -> None:
        rows = [group(f"g-{index}", "用户" * 400, "回答" * 400) for index in range(3)]
        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        owner = fold_plan(rows, current=current)
        plan = summary_attempt(rows, owner, current)
        mixed = {
            "output": [
                {"type": "reasoning", "text": "隐藏思考"},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "第一段"},
                        {"type": "tool_call", "text": "工具"},
                        {"type": "text", "text": "第二段"},
                        {"type": "image_url", "url": "https://example.invalid/a.png"},
                    ],
                },
            ]
        }
        accepted = accept_attempt(plan, mixed, rows, owner, current)
        self.assertEqual(accepted["accepted_summary"], "第一段\n第二段")
        for result in (
            "直接摘要",
            {"output_text": "顶层摘要"},
            {"type": "output_text", "role": "assistant", "text": "typed摘要"},
            {"choices": [{"message": {"role": "assistant", "content": "OpenAI摘要"}}]},
            {"choices": [{"message": {"content": "省略role的OpenAI摘要"}}]},
        ):
            self.assertEqual(accept_attempt(plan, result, rows, owner, current)["status"], "accepted")
        for result in (
            {"type": "message", "role": "user", "content": "用户正文"},
            {"type": "assistant_message", "role": "tool", "content": "工具正文"},
            {"role": "user", "output_text": "不得走顶层快路"},
            {"role": "system", "output_text": "不得走顶层快路"},
            {"type": "reasoning", "output_text": "不得冒充visible"},
            {"type": "reasoning", "output": [{"type": "output_text", "text": "不得洗白"}]},
            {"type": "tool_result", "output": [{"type": "output_text", "text": "不得洗白"}]},
            {"role": "user", "output": [{"type": "output_text", "text": "不得洗白"}]},
            {"output": [{"type": "reasoning", "text": "只有思考"}]},
            {"text": {"nested": "不得str"}},
        ):
            rejected = accept_attempt(plan, result, rows, owner, current)
            self.assertEqual((rejected["status"], rejected["progress_source_group_count"]), ("rejected", 0))

    def test_incremental_carry_and_oversized_carry_switch_to_rebuild(self) -> None:
        rows = [group("g-1", "一" * 400, "答一" * 400), group("g-2", "二" * 400, "答二" * 400)]
        checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows[:1],
            covered_source_group_ids=["g-1"],
            summary_text="已有摘要",
        )
        owner, current = summary_owner(rows, previous=checkpoint)
        plan = summary_attempt(rows, owner, current, previous=checkpoint)
        self.assertEqual(plan["descriptor"]["mode"], "bridge_rebuild")
        self.assertEqual(plan["descriptor"]["predecessor_revision_id"], checkpoint["revision_id"])
        self.assertEqual(plan["descriptor"]["processed_source_group_ids"], [])
        self.assertFalse(any(message.get("content") == "已有摘要" for message in plan["provider_messages"]))
        incremental_result = "增量摘要"
        incremental_accept = accept_attempt(
            plan, incremental_result, rows, owner, current, previous=checkpoint,
        )
        incremental_attempt = [{
            "descriptor": plan["descriptor"],
            "provider_result": incremental_result,
            "receipt": incremental_accept["receipt"],
        }]
        while True:
            next_plan = summary_attempt(
                rows,
                owner,
                current,
                previous=checkpoint,
                accepted_attempts=incremental_attempt,
            )
            if next_plan["status"] == "complete":
                break
            next_result = f"近场桥批次{len(incremental_attempt) + 1}"
            next_accept = accept_attempt(
                next_plan,
                next_result,
                rows,
                owner,
                current,
                previous=checkpoint,
                accepted_attempts=incremental_attempt,
            )
            incremental_attempt.append({
                "descriptor": next_plan["descriptor"],
                "provider_result": next_result,
                "receipt": next_accept["receipt"],
            })
        incremental_checkpoint = checkpoint_from_attempts(
            rows, owner, current, previous=checkpoint,
            summary_attempts=incremental_attempt,
        )
        self.assertEqual(incremental_checkpoint["lineage_status"], "continued")
        self.assertEqual(incremental_checkpoint["predecessor_revision_id"], checkpoint["revision_id"])

        large_checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows[:1],
            covered_source_group_ids=["g-1"],
            summary_text="旧摘要" * 2000,
        )
        large_owner, large_current = summary_owner(rows, window=1800, reserve=250, previous=large_checkpoint)
        self.assertEqual(
            (large_owner["status"], large_owner["reason"]),
            ("blocked", "rebuild_from_canonical_required"),
        )
        self.assertEqual(large_owner["fold_source_group_ids"], ["g-1", "g-2"])
        self.assertEqual(large_owner["raw_suffix_group_ids"], [])
        rebuilt = summary_attempt(rows, large_owner, large_current, previous=large_checkpoint)
        self.assertEqual((rebuilt["status"], rebuilt["descriptor"]["mode"]), ("ready", "bridge_rebuild"))
        self.assertEqual(
            rebuilt["descriptor"]["predecessor_revision_id"],
            large_checkpoint["revision_id"],
        )
        self.assertEqual(rebuilt["descriptor"]["processed_source_group_ids"], [])
        self.assertEqual(rebuilt["descriptor"]["target_source_group_ids"], ["g-1", "g-2"])
        normalized_owner = validate_owner_plan(
            large_owner, rows, previous=large_checkpoint, current=large_current,
            window=1800, reserve=250,
        )
        ready_input = validate_thread_continuity_input(
            normalized_owner,
            {"role": "system", "content": "[continuity]\n重建摘要"},
            fixed_non_message_tokens=0,
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(ready_input["status"], "ready")
        replan = validate_thread_continuity_input(
            normalized_owner,
            {"role": "system", "content": "[continuity]\n" + "长摘要" * 1000},
            fixed_non_message_tokens=0,
            estimate_messages=estimate_messages,
            physical_owner_generation=object(),
        )
        self.assertEqual(
            (replan["status"], replan["reason"]),
            ("blocked", "summary_too_large_all_groups_folded"),
        )
        stale_relative = fold_plan(
            rows, window=1800, reserve=250, current=large_current,
            previous=large_checkpoint, minimum_fold_ids=["g-2"],
        )
        self.assertEqual(stale_relative["reason"], "replan_prefix_invalid")
        accepted_attempts: list[dict] = []
        complete = rebuilt
        while complete["status"] == "ready":
            provider_result = f"重建摘要-{len(accepted_attempts) + 1}"
            accepted = accept_attempt(
                complete, provider_result, rows, large_owner, large_current,
                previous=large_checkpoint, accepted_attempts=accepted_attempts,
            )
            accepted_attempts.append({
                "descriptor": complete["descriptor"],
                "provider_result": provider_result,
                "receipt": accepted["receipt"],
            })
            complete = summary_attempt(
                rows, large_owner, large_current, previous=large_checkpoint,
                accepted_attempts=accepted_attempts,
            )
        self.assertEqual(complete["status"], "complete")


        self.assertEqual(complete["owner_completion"]["continuity_mode"], "bridge_rebuild")
        self.assertEqual(complete["owner_completion"]["bridge_source_group_ids"], ["g-1", "g-2"])
        self.assertEqual(
            complete["owner_completion"]["predecessor_revision_id"],
            large_checkpoint["revision_id"],
        )
        rebuilt_checkpoint = checkpoint_from_attempts(
            rows, large_owner, large_current, previous=large_checkpoint,
            summary_attempts=accepted_attempts,
        )
        self.assertEqual(rebuilt_checkpoint["revision"], large_checkpoint["revision"] + 1)
        self.assertEqual(
            (
                rebuilt_checkpoint["lineage_status"],
                rebuilt_checkpoint["predecessor_revision_id"],
            ),
            ("continued", large_checkpoint["revision_id"]),
        )
        tampered_owner = copy.deepcopy(large_owner)
        tampered_owner["fold_groups"][0]["messages"][0]["content"] = "伪造 canonical"
        tampered_owner["fold_plan_id"] = context_compactor._fold_plan_id(
            tampered_owner, normalize_complete_thread_groups(rows)["groups"]
        )
        self.assertEqual(
            summary_attempt(rows, tampered_owner, large_current, previous=large_checkpoint)["reason"],
            "fold_plan_invalid",
        )

        forged_checkpoint = {
            **checkpoint,
            "recent_bridge": {
                **checkpoint["recent_bridge"],
                "body": "伪造不同正文",
            },
        }
        canonical_owner, canonical_current = summary_owner(rows, previous=forged_checkpoint)
        fresh_owner = fold_plan(
            rows,
            window=canonical_owner["context_window_tokens"],
            reserve=canonical_owner["reserved_output_tokens"],
            current=canonical_current,
        )
        self.assertEqual(canonical_owner["fold_source_group_ids"], fresh_owner["fold_source_group_ids"])
        self.assertEqual(canonical_owner["raw_suffix_group_ids"], fresh_owner["raw_suffix_group_ids"])
        recovered = summary_attempt(rows, canonical_owner, canonical_current, previous=forged_checkpoint)
        self.assertEqual((recovered["status"], recovered["descriptor"]["mode"]), ("ready", "bridge_rebuild"))

    def test_descriptor_reconstruction_rejects_rehashed_prompt_batch_and_mode(self) -> None:
        rows = [group("g-1", "一" * 300, "答" * 300), group("g-2", "二" * 300, "答" * 300)]
        owner, current = summary_owner(rows)
        plan = summary_attempt(rows, owner, current)
        for field, value in (
            ("mode", "incremental"),
            ("batch_source_group_ids", ["g-2"]),
            ("input_sha256", "0" * 64),
        ):
            forged = {**plan["descriptor"], field: value}
            unsigned = {key: item for key, item in forged.items() if key != "descriptor_id"}
            forged["descriptor_id"] = "tcsd_" + context_compactor._content_hash(unsigned)
            rejected = accept_summary_attempt(
                forged, "摘要", groups=rows, fold_plan=owner,
                current_ephemeral=current,
                context_window_tokens=owner["context_window_tokens"],
                reserved_output_tokens=owner["reserved_output_tokens"],
                fixed_non_message_tokens=owner["fixed_non_message_tokens"],
                fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
                source_complete=True, estimate_messages=estimate_messages,
                minimum_fold_source_group_ids=owner["fold_source_group_ids"],
            )
            self.assertEqual((rejected["status"], rejected["progress_source_group_count"]), ("rejected", 0))

    def test_receipt_is_only_progress_authority_and_natural_end_is_exact(self) -> None:
        rows = [group(f"g-{index}", "用" * 260, "答" * 260) for index in range(4)]
        owner, current = summary_owner(rows, window=1500, reserve=220)
        accepted_attempts: list[dict] = []
        seen: list[str] = []
        for _ in range(5):
            plan = summary_attempt(rows, owner, current, accepted_attempts=accepted_attempts)
            if plan["status"] == "complete":
                break
            seen.extend(plan["descriptor"]["batch_source_group_ids"])
            provider_result = "累计摘要"
            accepted = accept_attempt(
                plan, provider_result, rows, owner, current, accepted_attempts=accepted_attempts,
            )
            self.assertGreaterEqual(accepted["progress_source_group_count"], 1)
            self.assertNotIn("accepted_summary", accepted["receipt"])
            self.assertNotIn("normalized_accepted_result", accepted["receipt"])
            accepted_attempts.append(
                {
                    "descriptor": plan["descriptor"],
                    "provider_result": provider_result,
                    "receipt": accepted["receipt"],
                }
            )
            repeated = accept_attempt(
                plan, provider_result, rows, owner, current, accepted_attempts=accepted_attempts,
            )
            self.assertEqual(repeated["progress_source_group_count"], 0)
        self.assertEqual(plan["status"], "complete")
        self.assertEqual(plan["progress_source_group_count"], 0)
        self.assertEqual(seen, owner["covered_source_group_ids"])
        self.assertEqual(len(seen), len(set(seen)))

        forged_attempts = copy.deepcopy(accepted_attempts)
        forged_carry = forged_attempts[-1]["receipt"]
        forged_carry["accepted_summary_sha256"] = context_compactor._content_hash("伪造carry")
        receipt_body = {key: value for key, value in forged_carry.items() if key != "receipt_id"}
        forged_carry["receipt_id"] = "tcsr_" + context_compactor._content_hash(receipt_body)
        self.assertEqual(
            summary_attempt(rows, owner, current, accepted_attempts=forged_attempts)["reason"],
            "accepted_receipt_invalid",
        )

    def test_summary_replay_rejects_changed_fixed_non_message_owner(self) -> None:
        rows = [group(f"g-{index}", "用" * 300, "答" * 300) for index in range(2)]
        owner, current = summary_owner(rows, window=1500, reserve=220)
        first = summary_attempt(rows, owner, current)
        accepted = accept_attempt(first, "累计摘要", rows, owner, current)
        attempts = [{
            "descriptor": first["descriptor"],
            "provider_result": "累计摘要",
            "receipt": accepted["receipt"],
        }]
        changed_owner = fold_plan(
            rows,
            window=owner["context_window_tokens"],
            reserve=owner["reserved_output_tokens"],
            fixed_non_message=1,
            current=current,
            minimum_fold_ids=[row["source_prefix_id"] for row in rows],
        )
        replay = summary_attempt(
            rows, changed_owner, current, accepted_attempts=attempts,
        )
        self.assertEqual((replay["status"], replay["reason"]), ("blocked", "accepted_receipt_invalid"))
        complete_attempts = list(attempts)
        while summary_attempt(rows, owner, current, accepted_attempts=complete_attempts)["status"] != "complete":
            next_plan = summary_attempt(rows, owner, current, accepted_attempts=complete_attempts)
            next_result = "最终摘要"
            next_accept = accept_attempt(
                next_plan, next_result, rows, owner, current,
                accepted_attempts=complete_attempts,
            )
            complete_attempts.append({
                "descriptor": next_plan["descriptor"],
                "provider_result": next_result,
                "receipt": next_accept["receipt"],
            })
        self.assertEqual(
            checkpoint_from_attempts(rows, owner, current, summary_attempts=complete_attempts)["lineage_status"],
            "initial",
        )
        forged = copy.deepcopy(complete_attempts)
        forged[0]["receipt"]["accepted_summary_sha256"] = context_compactor._content_hash("伪摘要")
        body = {key: value for key, value in forged[0]["receipt"].items() if key != "receipt_id"}
        forged[0]["receipt"]["receipt_id"] = "tcsr_" + context_compactor._content_hash(body)
        for kwargs in (
            {"summary_attempts": None},
            {"summary_attempts": forged},
            {"summary_attempts": complete_attempts, "fixed_non_message_tokens": 1},
            {"summary_attempts": complete_attempts, "context_window_tokens": owner["context_window_tokens"] + 1},
            {"summary_attempts": complete_attempts, "minimum_fold_source_group_ids": []},
        ):
            with self.assertRaisesRegex(ValueError, "summary_incomplete"):
                checkpoint_from_attempts(rows, owner, current, **kwargs)

    def test_nonfirst_oversized_group_and_zero_reserve_block_without_progress(self) -> None:
        rows = [group("small", "短", "短"), group("huge", "中" * 8000, "答" * 8000)]
        owner, current = summary_owner(rows, window=1400, reserve=200)
        first = summary_attempt(rows, owner, current)
        self.assertEqual(first["descriptor"]["batch_source_group_ids"], ["small"])
        provider_result = "短摘要"
        accepted = accept_attempt(first, provider_result, rows, owner, current)
        blocked = summary_attempt(
            rows,
            owner,
            current,
            accepted_attempts=[
                {
                    "descriptor": first["descriptor"],
                    "provider_result": provider_result,
                    "receipt": accepted["receipt"],
                }
            ],
        )
        self.assertEqual((blocked["status"], blocked["reason"]), ("blocked", "chunk_required"))
        self.assertEqual(blocked["progress_source_group_count"], 0)

        zero_owner = fold_plan(rows, reserve=0)
        zero = plan_next_summary_attempt(
            rows,
            fold_plan=zero_owner,
            current_ephemeral={"role": "user", "message_id": "u-current", "content": "当前用户消息"},
            context_window_tokens=2500,
            reserved_output_tokens=0,
            fixed_non_message_tokens=0,
            fixed_prompt_messages=[{"role": "system", "content": "固定系统提示"}],
            source_complete=True,
            estimate_messages=estimate_messages,
        )
        self.assertEqual((zero["status"], zero["progress_source_group_count"]), ("blocked", 0))


class ThreadContinuityPhysicalOwnerSidecarTests(unittest.TestCase):
    def test_sidecar_requires_the_current_external_generation_witness(self) -> None:
        rows = [group("g-1", "同一条历史正文", "历史回答")]
        current = {
            "role": "user",
            "message_id": "u-current",
            "canonical_ids": ["turn-current"],
            "content": "同一条当前正文",
        }
        old_generation = object()
        current_generation = object()
        old_plan = fold_plan(
            rows,
            window=10_000,
            reserve=300,
            current=current,
        )
        current_plan = fold_plan(
            rows,
            window=12_000,
            reserve=300,
            current=current,
        )
        old_ready = validate_thread_continuity_input(
            old_plan,
            None,
            fixed_non_message_tokens=0,
            estimate_messages=estimate_messages,
            physical_owner_generation=old_generation,
        )
        current_ready = validate_thread_continuity_input(
            current_plan,
            None,
            fixed_non_message_tokens=0,
            estimate_messages=estimate_messages,
            physical_owner_generation=current_generation,
        )
        self.assertEqual(
            old_ready["provider_messages"], current_ready["provider_messages"]
        )
        self.assertEqual(
            context_compactor._read_thread_continuity_physical_owner_sidecar(
                old_ready["physical_owner_sidecar"],
                physical_messages=current_ready["provider_messages"],
                expected_generation=current_generation,
            ),
            {},
        )
        self.assertEqual(
            context_compactor._read_thread_continuity_physical_owner_sidecar(
                current_ready["physical_owner_sidecar"],
                physical_messages=current_ready["provider_messages"],
                expected_generation=current_generation,
            ),
            current_ready["physical_owner_sidecar"],
        )

    def _ready(
        self,
        *,
        previous: dict | None = None,
        tail: list[dict] | None = None,
    ) -> tuple[dict, dict, object]:
        rows = [group("g-1", "同一条历史正文", "历史回答")]
        current = {
            "role": "user",
            "message_id": "u-current",
            "canonical_ids": ["turn-current"],
            "content": "同一条当前正文",
        }
        plan = fold_plan(
            rows,
            window=10_000,
            reserve=300,
            current=current,
            previous=previous,
            tail=tail,
        )
        generation = object()
        ready = validate_thread_continuity_input(
            plan,
            None,
            fixed_non_message_tokens=0,
            estimate_messages=estimate_messages,
            physical_owner_generation=generation,
        )
        self.assertEqual(ready["status"], "ready")
        return ready, plan, generation

    def test_ready_sidecar_classifies_exact_physical_owner_without_changing_payload(self) -> None:
        ready, _plan, generation = self._ready(
            tail=[
                {
                    "role": "assistant",
                    "message_id": "tail-1",
                    "content": "同一条当前正文",
                }
            ]
        )

        sidecar = ready["physical_owner_sidecar"]
        self.assertNotIsInstance(sidecar, dict)
        self.assertNotIn("u-current", repr(sidecar))
        self.assertNotIn("同一条", repr(sidecar))
        with self.assertRaisesRegex(AttributeError, "sidecar_frozen"):
            sidecar._payload_json = "{}"
        for detached_sidecar in (
            copy.copy(sidecar),
            copy.deepcopy(sidecar),
            json.loads(json.dumps(dict(sidecar))),
        ):
            self.assertIsInstance(detached_sidecar, dict)
            self.assertEqual(
                context_compactor._read_thread_continuity_physical_owner_sidecar(
                    detached_sidecar,
                    physical_messages=ready["provider_messages"],
                    expected_generation=generation,
                ),
                {},
            )
        self.assertEqual(
            sidecar["schema"], "thread_continuity_physical_owner_sidecar.v1"
        )
        self.assertEqual(
            [row["physical_index"] for row in sidecar["rows"]],
            list(range(len(ready["provider_messages"]))),
        )
        self.assertEqual(
            [row["carrier_kind"] for row in sidecar["rows"]],
            ["fixed", "raw", "raw", "current", "postcurrent"],
        )
        self.assertEqual(sidecar["rows"][1]["source_group_aliases"], ["g-1", "cap-g-1"])
        self.assertEqual(sidecar["rows"][1]["source_message_aliases"], ["u-g-1"])
        self.assertEqual(sidecar["rows"][3]["source_message_aliases"], ["u-current"])
        self.assertEqual(sidecar["rows"][4]["source_message_aliases"], ["tail-1"])
        self.assertEqual(
            context_compactor._read_thread_continuity_physical_owner_sidecar(
                sidecar,
                physical_messages=ready["provider_messages"],
                expected_generation=generation,
            ),
            sidecar,
        )
        self.assertNotIn("同一条", str(sidecar))
        self.assertFalse(sidecar["body_included"])

    def test_existing_checkpoint_is_reference_only_with_zero_alias_omission_authority(self) -> None:
        rows = [group("g-1", "同一条历史正文", "历史回答")]
        checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["g-1"],
            summary_text="同一条历史正文",
        )
        ready, _plan, _generation = self._ready(previous=checkpoint)

        checkpoint_rows = [
            row
            for row in ready["physical_owner_sidecar"]["rows"]
            if row["carrier_kind"] == "checkpoint"
        ]
        self.assertEqual(len(checkpoint_rows), 1)
        self.assertEqual(checkpoint_rows[0]["checkpoint_kind"], "recent_bridge")
        self.assertEqual(
            checkpoint_rows[0]["relation"], "represented_in_recent_bridge"
        )
        self.assertEqual(checkpoint_rows[0]["source_group_aliases"], [])
        self.assertEqual(checkpoint_rows[0]["source_message_aliases"], [])

    def test_sidecar_tamper_or_physical_drift_fails_closed(self) -> None:
        ready, _plan, generation = self._ready()
        sidecar = ready["physical_owner_sidecar"]

        attacks: list[tuple[dict, list[dict]]] = []
        for field, value in (
            ("plan_binding_sha256", "0" * 64),
            ("fixed_prompt_sha256", "1" * 64),
            ("physical_vector_sha256", "2" * 64),
            ("rows_sha256", "3" * 64),
            ("receipt_sha256", "4" * 64),
        ):
            attacked = copy.deepcopy(dict(sidecar))
            attacked[field] = value
            attacks.append((attacked, ready["provider_messages"]))
        for key, value in (
            ("physical_index", 7),
            ("carrier_kind", "current"),
            ("role", "assistant"),
            ("name", "forged"),
            ("body_sha256", "5" * 64),
            ("source_message_aliases", ["u-forged"]),
            ("source_fingerprint", "6" * 64),
        ):
            attacked = copy.deepcopy(dict(sidecar))
            attacked["rows"][1][key] = value
            attacks.append((attacked, ready["provider_messages"]))
        for index, value in (
            (1, {"role": "assistant", "content": "同一条历史正文"}),
            (2, {"role": "assistant", "content": "改过的正文"}),
        ):
            physical = copy.deepcopy(ready["provider_messages"])
            physical[index] = value
            attacks.append((sidecar, physical))

        for attacked, physical in attacks:
            with self.subTest(attacked=attacked, physical=physical):
                self.assertEqual(
                    context_compactor._read_thread_continuity_physical_owner_sidecar(
                        attacked,
                        physical_messages=physical,
                        expected_generation=generation,
                    ),
                    {},
                )

    def test_plain_mapping_cannot_coordinate_reseal_postcurrent_as_raw(self) -> None:
        ready, _plan, generation = self._ready(
            tail=[
                {
                    "role": "assistant",
                    "message_id": "tail-1",
                    "content": "同一条历史正文",
                }
            ]
        )
        sidecar = ready["physical_owner_sidecar"]
        forged = copy.deepcopy(dict(sidecar))
        raw_row = next(row for row in forged["rows"] if row["carrier_kind"] == "raw")
        postcurrent_row = next(
            row for row in forged["rows"] if row["carrier_kind"] == "postcurrent"
        )
        postcurrent_row.update(
            carrier_kind="raw",
            checkpoint_kind="none",
            source_group_aliases=list(raw_row["source_group_aliases"]),
            source_message_aliases=list(raw_row["source_message_aliases"]),
            source_fingerprint=raw_row["source_fingerprint"],
            relation="same_canonical_body",
        )
        forged["rows_sha256"] = context_compactor._content_hash(forged["rows"])
        forged["receipt_sha256"] = context_compactor._content_hash(
            {key: value for key, value in forged.items() if key != "receipt_sha256"}
        )

        self.assertEqual(
            context_compactor._read_thread_continuity_physical_owner_sidecar(
                forged,
                physical_messages=ready["provider_messages"],
                expected_generation=generation,
            ),
            {},
        )


class ThreadContinuitySummaryChunkTests(unittest.TestCase):
    @staticmethod
    def _typed_stream(content: object) -> str:
        if isinstance(content, str):
            return content
        out = ""
        for part in content:
            if part["type"] in {"text", "input_text"}:
                out += part["text"]
            else:
                image = part.get("image_url")
                url = image.get("url") if isinstance(image, dict) else image or part.get("file_id")
                out += f"\0{part['type']}:{url}\0"
        return out

    def _complete_chunk(self, inputs: dict, label: str) -> list[dict]:
        attempts: list[dict] = []
        for index in range(30):
            plan = plan_next_summary_chunk_attempt(**{**inputs, "accepted_chunk_attempts": attempts})
            if plan["status"] == "complete":
                return attempts
            result = f"{label}-{index}"
            accepted = accept_summary_chunk_attempt(
                plan["descriptor"], result, **{**inputs, "accepted_chunk_attempts": attempts}
            )
            attempts.append(
                {"descriptor": plan["descriptor"], "provider_result": result, "receipt": accepted["receipt"]}
            )
        self.fail("chunk protocol did not terminate")

    def test_fragments_preserve_canonical_body_and_only_finalize_source_once(self) -> None:
        user = "甲" * 100 + " \n\t  " + "乙" * 100
        assistant = [
            {"type": "input_text", "text": "丙" * 80},
            {"type": "input_text", "text": ""},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/one.png"}},
            {"type": "text", "text": "丁" * 80},
        ]
        rows = [group("huge", user, assistant), group("tail", "未折叠尾巴", "尾巴回答")]
        rows[0]["messages"][0]["name"] = "human-owner"
        rows[0]["messages"][1]["name"] = "assistant-owner"
        current = {"role": "user", "message_id": "u-current", "content": "当前不能进入chunk" * 30}
        owner = fold_plan(rows, window=600, reserve=60, current=current)
        self.assertEqual(owner["raw_suffix_group_ids"], ["tail"])
        inputs = chunk_inputs(rows, owner, current, minimum=[])
        attempts: list[dict] = []
        canonical_group = normalize_complete_thread_groups(rows)["groups"][0]
        atoms = context_compactor._chunk_atoms(canonical_group)
        carry = ""
        user_fragments: list[str] = []
        assistant_fragments: list[str] = []
        empty_part_seen = False
        phases: list[str] = []
        for index in range(40):
            plan = plan_next_summary_chunk_attempt(**{**inputs, "accepted_chunk_attempts": attempts})
            if plan["status"] == "complete":
                break
            self.assertEqual(plan["status"], "ready")
            descriptor = plan["descriptor"]
            phases.append(descriptor["phase"])
            self.assertLessEqual(
                estimate_messages(plan["provider_messages"]) + owner["reserved_output_tokens"],
                owner["context_window_tokens"],
            )
            if descriptor["fragment_end"] < descriptor["fragment_total"]:
                one_more = context_compactor._chunk_prompt(
                    carry,
                    canonical_group,
                    atoms,
                    descriptor["fragment_start"],
                    descriptor["fragment_end"] + 1,
                )
                self.assertGreater(
                    estimate_messages(one_more) + owner["reserved_output_tokens"],
                    owner["context_window_tokens"],
                )
            self.assertEqual([row[2] for row in descriptor["message_lineage"]], ["u-huge", "a-huge"])
            self.assertFalse(any(message.get("content") == current["content"] for message in plan["provider_messages"]))
            self.assertFalse(any(message.get("content") == "未折叠尾巴" for message in plan["provider_messages"]))
            for message in plan["provider_messages"]:
                if message["role"] == "user":
                    self.assertEqual(message.get("name"), "human-owner")
                    user_fragments.append(self._typed_stream(message["content"]))
                elif message["role"] == "assistant":
                    self.assertEqual(message.get("name"), "assistant-owner")
                    assistant_fragments.append(self._typed_stream(message["content"]))
                    empty_part_seen |= any(
                        part.get("type") == "input_text" and part.get("text") == ""
                        for part in message["content"]
                    )
            result = f"滚动摘要{index}"
            accepted = accept_summary_chunk_attempt(
                descriptor, result, **{**inputs, "accepted_chunk_attempts": attempts}
            )
            expected_progress = 1 if descriptor["phase"] == "group_finalize" else 0
            self.assertEqual(accepted["progress_source_group_count"], expected_progress)
            self.assertNotIn("accepted_summary", accepted["receipt"])
            self.assertEqual(
                accepted["covered_source_group_ids"], ["huge"] if expected_progress else []
            )
            attempts.append(
                {"descriptor": descriptor, "provider_result": result, "receipt": accepted["receipt"]}
            )
            carry = result
        self.assertEqual(plan["status"], "complete")
        self.assertEqual(plan["covered_source_group_ids"], ["huge"])
        self.assertEqual("".join(user_fragments), user)
        self.assertEqual("".join(assistant_fragments), self._typed_stream(assistant))
        self.assertTrue(empty_part_seen)
        self.assertEqual(phases[-1], "group_finalize")
        self.assertTrue(all(phase == "fragment_update" for phase in phases[:-1]))
        self.assertEqual(
            plan_next_summary_chunk_attempt(
                **{**inputs, "accepted_chunk_attempts": list(reversed(attempts))}
            )["reason"],
            "accepted_chunk_receipt_invalid",
        )

    def test_chunk_replay_rejects_changed_fixed_non_message_owner(self) -> None:
        rows = [group("huge", "用" * 120, "答" * 120)]
        owner, current = summary_owner(rows, window=300, reserve=40)
        inputs = chunk_inputs(rows, owner, current)
        first = plan_next_summary_chunk_attempt(**inputs)
        self.assertEqual(first["status"], "ready")
        accepted = accept_summary_chunk_attempt(first["descriptor"], "分段摘要", **inputs)
        attempts = [{
            "descriptor": first["descriptor"],
            "provider_result": "分段摘要",
            "receipt": accepted["receipt"],
        }]
        changed_owner = fold_plan(
            rows,
            window=owner["context_window_tokens"],
            reserve=owner["reserved_output_tokens"],
            fixed_non_message=1,
            current=current,
            minimum_fold_ids=["huge"],
        )
        replay = plan_next_summary_chunk_attempt(
            **chunk_inputs(
                rows, changed_owner, current, chunk_attempts=attempts,
            )
        )
        self.assertEqual((replay["status"], replay["reason"]), ("blocked", "accepted_chunk_receipt_invalid"))

    def test_chunk_receipt_cannot_cross_post_current_tail(self) -> None:
        rows = [group("huge", "用" * 120, "答" * 120)]
        _owner, current = summary_owner(rows, window=300, reserve=40)
        tail_a = [{"role": "assistant", "message_id": "tail-a", "content": "相同正文"}]
        tail_b = [{"role": "assistant", "message_id": "tail-b", "content": "相同正文"}]
        owner_a = fold_plan(rows, window=300, reserve=40, current=current, tail=tail_a)
        owner_b = fold_plan(rows, window=300, reserve=40, current=current, tail=tail_b)
        inputs_a = chunk_inputs(rows, owner_a, current, tail=tail_a)
        first = plan_next_summary_chunk_attempt(**inputs_a)
        self.assertEqual(first["status"], "ready")
        accepted = accept_summary_chunk_attempt(first["descriptor"], "分段摘要", **inputs_a)
        attempt = [{
            "descriptor": first["descriptor"],
            "provider_result": "分段摘要",
            "receipt": accepted["receipt"],
        }]
        replay = plan_next_summary_chunk_attempt(
            **chunk_inputs(rows, owner_b, current, chunk_attempts=attempt, tail=tail_b)
        )
        self.assertEqual((replay["status"], replay["reason"]), ("blocked", "accepted_chunk_receipt_invalid"))
        self.assertTrue(all(message.get("content") != tail_a[0]["content"] for message in first["provider_messages"]))

    def test_chunk_replay_rejects_skip_repeat_repair_and_rehashed_trace(self) -> None:
        rows = [group("huge", "用" * 60, "答" * 60)]
        owner, current = summary_owner(rows, window=280, reserve=40)
        inputs = chunk_inputs(rows, owner, current)
        first = plan_next_summary_chunk_attempt(**inputs)
        forged_descriptor = {**first["descriptor"], "fragment_end": first["descriptor"]["fragment_end"] + 1}
        forged_descriptor["descriptor_id"] = "tccd_" + context_compactor._content_hash(
            {key: value for key, value in forged_descriptor.items() if key != "descriptor_id"}
        )
        self.assertEqual(
            accept_summary_chunk_attempt(forged_descriptor, "摘要", **inputs)["status"], "rejected"
        )

        result = "真实摘要"
        accepted = accept_summary_chunk_attempt(first["descriptor"], result, **inputs)
        attempt = {"descriptor": first["descriptor"], "provider_result": result, "receipt": accepted["receipt"]}
        self.assertEqual(
            plan_next_summary_chunk_attempt(**{**inputs, "accepted_chunk_attempts": [attempt, attempt]})["reason"],
            "accepted_chunk_receipt_invalid",
        )
        forged_attempt = copy.deepcopy(attempt)
        forged_attempt["receipt"]["accepted_summary_sha256"] = context_compactor._content_hash("伪摘要")
        body = {key: value for key, value in forged_attempt["receipt"].items() if key != "receipt_id"}
        forged_attempt["receipt"]["receipt_id"] = "tccr_" + context_compactor._content_hash(body)
        self.assertEqual(
            plan_next_summary_chunk_attempt(**{**inputs, "accepted_chunk_attempts": [forged_attempt]})["reason"],
            "accepted_chunk_receipt_invalid",
        )
        repaired = copy.deepcopy(rows)
        repaired[0]["messages"][0]["content"] = "修复后的不同canonical"
        self.assertEqual(
            plan_next_summary_chunk_attempt(**{**inputs, "groups": repaired})["reason"],
            "chunk_owner_invalid",
        )

        checkpoint = v2_checkpoint_fixture(
            previous_state=None,
            source_groups=rows,
            covered_source_group_ids=["huge"],
            summary_text="旧摘要",
        )
        forged_checkpoint = {
            **checkpoint,
            "recent_bridge": {
                **checkpoint["recent_bridge"],
                "body": "篡改摘要",
            },
        }
        recovered_owner, recovered_current = summary_owner(
            rows, window=280, reserve=40, previous=forged_checkpoint
        )
        recovered = plan_next_summary_chunk_attempt(
            **chunk_inputs(rows, recovered_owner, recovered_current, previous=forged_checkpoint)
        )
        self.assertEqual((recovered["status"], recovered["descriptor"]["fragment_start"]), ("ready", 0))

    def test_atomic_image_over_budget_blocks_without_cursor_or_source_progress(self) -> None:
        image = [{"type": "image_url", "image_url": {"url": "https://example.invalid/huge.png"}}]
        rows = [group("image", image, "回答" * 100)]

        def expensive_image(messages: list[dict]) -> int:
            cost = estimate_messages(messages)
            for message in messages:
                content = message.get("content")
                if isinstance(content, list) and any(part.get("type") == "image_url" for part in content):
                    cost += 5000
            return cost

        current = {"role": "user", "message_id": "u-current", "content": "当前"}
        owner = fold_plan(rows, window=280, reserve=40, current=current, estimator=expensive_image)
        blocked = plan_next_summary_chunk_attempt(
            **chunk_inputs(rows, owner, current, estimator=expensive_image, minimum=[])
        )
        self.assertEqual(
            (blocked["status"], blocked["reason"], blocked["blocked_atom_kind"]),
            ("blocked", "atomic_fragment_too_large", "image_url"),
        )
        self.assertEqual(blocked["progress_source_group_count"], 0)

    def test_nonmonotonic_estimator_never_turns_first_over_second_fit_into_progress(self) -> None:
        rows = [group("huge", "用" * 60, "答" * 60)]
        owner, current = summary_owner(rows, window=280, reserve=40)

        def nonmonotonic(messages: list[dict]) -> int:
            if any(message.get("name") == "continuity_fragment_metadata" for message in messages):
                fragment_size = sum(
                    len(context_compactor._content_to_text(message.get("content")))
                    for message in messages
                    if message.get("role") in {"user", "assistant"}
                )
                return 500 if fragment_size == 1 else 100
            return estimate_messages(messages)

        blocked = plan_next_summary_chunk_attempt(
            **chunk_inputs(rows, owner, current, estimator=nonmonotonic)
        )
        self.assertEqual(
            (blocked["status"], blocked["reason"], blocked["progress_source_group_count"]),
            ("blocked", "estimator_invalid", 0),
        )
        self.assertEqual(blocked["estimator_call_count"], 2)
        self.assertTrue(blocked["observed_violation"])

    def test_bounded_prefix_search_handles_4k_and_reports_sampled_midpath_drop(self) -> None:
        build = lambda end: [{"role": "user", "content": "字" * end}]
        estimator = lambda messages: len(messages[0]["content"])
        end, calls, violation = context_compactor._bounded_chunk_end(
            build, estimator, start=0, total=4000, window=2345, reserve=0
        )
        self.assertEqual(end, 2345)
        self.assertLess(calls, 64)
        self.assertFalse(violation)
        self.assertGreater(estimator(build(end + 1)), 2345)

        def sampled_drop(messages: list[dict]) -> int:
            size = len(messages[0]["content"])
            return 50 if size >= 2000 else 100 + size

        self.assertEqual(
            context_compactor._bounded_chunk_end(
                build, sampled_drop, start=0, total=4000, window=3000, reserve=0
            ),
            (0, 3, True),
        )

    def test_existing_summary_progress_is_carried_but_tool_output_never_advances(self) -> None:
        rows = [group("small", "短", "短答"), group("huge", "长" * 60, "长答" * 60)]
        owner, current = summary_owner(rows, window=280, reserve=40)
        summary_plan = summary_attempt(rows, owner, current)
        summary_result = "已处理small"
        accepted = accept_attempt(summary_plan, summary_result, rows, owner, current)
        summary_attempts = [
            {
                "descriptor": summary_plan["descriptor"],
                "provider_result": summary_result,
                "receipt": accepted["receipt"],
            }
        ]
        inputs = chunk_inputs(rows, owner, current, summary_attempts=summary_attempts)
        chunk = plan_next_summary_chunk_attempt(**inputs)
        self.assertTrue(any(message.get("content") == summary_result for message in chunk["provider_messages"]))
        rejected = accept_summary_chunk_attempt(
            chunk["descriptor"], {"type": "tool_result", "text": "不得推进"}, **inputs
        )
        self.assertEqual((rejected["status"], rejected["progress_source_group_count"]), ("rejected", 0))
        chunk_attempts: list[dict] = []
        for index in range(30):
            chunk = plan_next_summary_chunk_attempt(
                **{**inputs, "accepted_chunk_attempts": chunk_attempts}
            )
            if chunk["status"] == "complete":
                break
            result = f"续接摘要{index}"
            accepted_chunk = accept_summary_chunk_attempt(
                chunk["descriptor"], result, **{**inputs, "accepted_chunk_attempts": chunk_attempts}
            )
            if chunk["descriptor"]["phase"] == "group_finalize":
                self.assertEqual(accepted_chunk["covered_source_group_ids"], ["small", "huge"])
                self.assertEqual(accepted_chunk["progress_source_group_count"], 1)
            chunk_attempts.append(
                {
                    "descriptor": chunk["descriptor"],
                    "provider_result": result,
                    "receipt": accepted_chunk["receipt"],
                }
            )
        self.assertEqual(chunk["status"], "complete")

    def test_chunk_completion_advances_a1b2_once_then_normal_batch_completes(self) -> None:
        rows = [group("huge", "大" * 60, "大答" * 60), group("next", "下一条", "下一答")]
        owner, current = summary_owner(rows, window=280, reserve=40)
        inputs = chunk_inputs(rows, owner, current)
        chunk_attempts: list[dict] = []
        for index in range(30):
            chunk = plan_next_summary_chunk_attempt(
                **{**inputs, "accepted_chunk_attempts": chunk_attempts}
            )
            if chunk["status"] == "complete":
                break
            result = f"大组摘要{index}"
            accepted = accept_summary_chunk_attempt(
                chunk["descriptor"], result, **{**inputs, "accepted_chunk_attempts": chunk_attempts}
            )
            chunk_attempts.append(
                {"descriptor": chunk["descriptor"], "provider_result": result, "receipt": accepted["receipt"]}
            )
        self.assertEqual(chunk["status"], "complete")

        next_plan = summary_attempt(rows, owner, current, chunk_completions=[chunk_attempts])
        self.assertEqual(next_plan["descriptor"]["batch_source_group_ids"], ["next"])
        next_result = "完成下一条"
        next_accepted = accept_attempt(
            next_plan, next_result, rows, owner, current, chunk_completions=[chunk_attempts]
        )
        next_attempt = {
            "descriptor": next_plan["descriptor"],
            "provider_result": next_result,
            "receipt": next_accepted["receipt"],
        }
        complete = summary_attempt(
            rows,
            owner,
            current,
            accepted_attempts=[next_attempt],
            chunk_completions=[chunk_attempts],
        )
        self.assertEqual((complete["status"], complete["bridge_source_group_ids"]), ("complete", ["huge", "next"]))
        self.assertEqual(summary_attempt(rows, owner, current)["reason"], "chunk_required")

        tampered = copy.deepcopy(chunk_attempts)
        tampered[-1]["receipt"]["fragment_end"] -= 1
        body = {key: value for key, value in tampered[-1]["receipt"].items() if key != "receipt_id"}
        tampered[-1]["receipt"]["receipt_id"] = "tccr_" + context_compactor._content_hash(body)
        self.assertEqual(
            summary_attempt(rows, owner, current, chunk_completions=[tampered])["reason"],
            "accepted_chunk_completion_invalid",
        )
        self.assertEqual(
            summary_attempt(rows, owner, current, chunk_completions=[chunk_attempts, chunk_attempts])["reason"],
            "accepted_chunk_completion_invalid",
        )

    def test_consecutive_huge_groups_replay_in_exact_order_before_normal_batch(self) -> None:
        rows = [
            group("huge-1", "甲" * 60, "甲答" * 60),
            group("huge-2", "乙" * 60, "乙答" * 60),
            group("normal", "短", "短答"),
        ]
        owner, current = summary_owner(rows, window=280, reserve=40)
        first = self._complete_chunk(chunk_inputs(rows, owner, current), "第一组")
        second_inputs = chunk_inputs(rows, owner, current, chunk_completions=[first])
        second_plan = plan_next_summary_chunk_attempt(**second_inputs)
        self.assertEqual(second_plan["descriptor"]["source_group_id"], "huge-2")
        second = self._complete_chunk(second_inputs, "第二组")

        normal = summary_attempt(rows, owner, current, chunk_completions=[first, second])
        self.assertEqual(normal["descriptor"]["batch_source_group_ids"], ["normal"])
        accepted = accept_attempt(
            normal, "普通组完成", rows, owner, current, chunk_completions=[first, second]
        )
        normal_attempt = {
            "descriptor": normal["descriptor"],
            "provider_result": "普通组完成",
            "receipt": accepted["receipt"],
        }
        complete = summary_attempt(
            rows, owner, current, accepted_attempts=[normal_attempt],
            chunk_completions=[first, second],
        )
        self.assertEqual(complete["bridge_source_group_ids"], ["huge-1", "huge-2", "normal"])
        self.assertEqual(len(complete["bridge_source_group_ids"]), len(set(complete["bridge_source_group_ids"])))
        checkpoint = checkpoint_from_attempts(
            rows, owner, current, summary_attempts=[normal_attempt],
            chunk_completions=[first, second],
        )
        self.assertEqual((checkpoint["lineage_status"], checkpoint["revision"]), ("initial", 1))
        self.assertEqual(checkpoint["retirement_cursor"]["source_prefix_ids"], ["huge-1", "huge-2", "normal"])

        for invalid in ([second], [second, first], [first, first]):
            blocked = plan_next_summary_chunk_attempt(
                **chunk_inputs(rows, owner, current, chunk_completions=invalid)
            )
            self.assertEqual((blocked["status"], blocked["reason"]), ("blocked", "chunk_owner_invalid"))
            with self.assertRaisesRegex(ValueError, "summary_incomplete"):
                checkpoint_from_attempts(rows, owner, current, chunk_completions=invalid)
        tampered = copy.deepcopy(first)
        tampered[-1]["provider_result"] = "伪造完成"
        blocked = plan_next_summary_chunk_attempt(
            **chunk_inputs(rows, owner, current, chunk_completions=[tampered])
        )
        self.assertEqual((blocked["status"], blocked["reason"]), ("blocked", "chunk_owner_invalid"))
        with self.assertRaisesRegex(ValueError, "summary_incomplete"):
            checkpoint_from_attempts(rows, owner, current, chunk_completions=[tampered])


if __name__ == "__main__":
    unittest.main()
