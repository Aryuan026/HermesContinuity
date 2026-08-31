from __future__ import annotations

import asyncio
import copy
import importlib
import json
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from hermes_cli.request_overlay import RequestOverlayFilterResult


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_runtime_adapter_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

runtime_module = importlib.import_module(f"{PACKAGE}.runtime")
ContinuityRuntime = runtime_module.ContinuityRuntime
MARKER = runtime_module.CONTINUITY_MARKER


def checkpoint(body: str, *, source_id: str = "hcg_source") -> dict:
    return {
        "schema": "thread_continuity_checkpoint.v2",
        "revision": 1,
        "source_group_ids": [source_id],
        "recent_bridge": {
            "status": "ready" if body else "empty",
            "relation": (
                "represented_in_recent_bridge"
                if body
                else "no_visible_representation"
            ),
            "body": body,
            "body_sha256": "b" * 64,
            "source_group_ids": [source_id] if body else [],
            "source_group_fingerprints": [],
            "source_slice_fingerprint": "",
            "reference_at": "2026-08-30T00:00:00+00:00",
            "recent_horizon_hours": 72,
            "source_token_limit": 24_000,
            "output_token_limit": 2_048,
        },
    }


def bundle(old: dict | None = None, *, source_status: str = "ready") -> dict:
    continuity = (
        {
            "status": "ready",
            "state": {"revision": 1, "checkpoint": copy.deepcopy(old)},
        }
        if old is not None
        else {"status": "absent", "state": {}}
    )
    return {
        "source": {
            "status": source_status,
            "scan_complete": source_status == "ready",
            "source_snapshot": "a" * 64,
            "groups": [],
            "stats": {
                "full_prefix": source_status == "ready",
                "compacted_prefix_group_ids": [],
            },
        },
        "continuity": continuity,
    }


def exact_group(index: int) -> dict:
    group_id = f"hcg_group_{index}"
    return {
        "group_kind": "dialogue_turn",
        "source_prefix_id": group_id,
        "logical_turn_id": group_id,
        "record_id": group_id,
        "effective_event_at": f"2026-08-29T0{index}:00:00+00:00",
        "message_ids": [f"hcm_u_{index}", f"hcm_a_{index}"],
        "messages": [
            {
                "role": "user",
                "message_id": f"hcm_u_{index}",
                "content": f"user {index}",
                "content_hash": "ignored-by-normalizer",
            },
            {
                "role": "assistant",
                "message_id": f"hcm_a_{index}",
                "content": f"assistant {index}",
                "content_hash": "ignored-by-normalizer",
            },
        ],
    }


def request(text: str = "current") -> dict:
    return {
        "model": "test-model",
        "max_tokens": 128,
        "messages": [
            {"role": "system", "content": "fixed"},
            {"role": "user", "content": text},
        ],
    }


class FakeReceiptStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record_receipt(self, **kwargs):
        self.rows.append(copy.deepcopy(kwargs))
        return kwargs


class FakeAdapter:
    def __init__(
        self,
        value: dict,
        *,
        cas_ok: bool = True,
        cas_error: str = "",
    ) -> None:
        self.value = value
        self.cas_ok = cas_ok
        self.cas_error = cas_error
        self.read_count = 0
        self.cas_calls: list[dict] = []
        self.metadata_store = FakeReceiptStore()

    def read_bundle(self, session_id: str) -> dict:
        self.read_count += 1
        return copy.deepcopy(self.value)

    def settle_checkpoint_delivery(self, session_id: str, **kwargs) -> dict:
        candidate = kwargs.get("checkpoint_candidate")
        if candidate is None:
            outcome = "unchanged"
            ok = True
        else:
            self.cas_calls.append(
                {
                    "session_id": session_id,
                    "expected_revision": kwargs["expected_revision"],
                    "expected_source_snapshot": kwargs["expected_source_snapshot"],
                    "checkpoint_candidate": copy.deepcopy(candidate),
                }
            )
            outcome = "applied" if self.cas_ok else "failed" if self.cas_error else "conflict"
            ok = outcome == "applied"
        self.metadata_store.record_receipt(
            receipt_id=kwargs["receipt_id"],
            session_id=session_id,
            kind="delivery",
            status=f"delivered_checkpoint_{outcome}",
            source_ids=kwargs.get("source_ids", ()),
            hashes=kwargs.get("hashes", {}),
            counts=kwargs.get("counts", {}),
        )
        return {
            "ok": ok,
            "status": outcome,
            "error": self.cas_error,
            "receipt_recorded": True,
        }


class FakeCompiler:
    def __init__(self, candidate: dict | None, *, status: str = "ready") -> None:
        self.candidate = candidate
        self.status = status
        self.calls: list[dict] = []

    async def __call__(self, input_bundle: dict, **kwargs) -> dict:
        self.calls.append({"bundle": copy.deepcopy(input_bundle), "kwargs": kwargs})
        return {
            "status": self.status,
            "reason": "source_unavailable" if self.status != "ready" else "",
            "checkpoint_candidate": copy.deepcopy(self.candidate),
            "expected_revision": 0,
            "expected_pre_turn_source_snapshot": "a" * 64,
        }


@dataclass
class LlmResult:
    text: str = "summary"
    finish_reason: str | None = "stop"
    usage: object | None = None


class FakeLlm:
    def __init__(
        self,
        result: LlmResult | None = None,
        *,
        include_completion_marker: bool = True,
    ) -> None:
        self.result = result or LlmResult()
        self.include_completion_marker = include_completion_marker
        self.calls = 0

    async def acomplete(self, messages, **kwargs):
        self.calls += 1
        text = self.result.text
        if self.include_completion_marker:
            marker = next(
                str(row.get("content") or "").splitlines()[-1]
                for row in reversed(messages)
                if runtime_module._SUMMARY_END_PREFIX
                in str(row.get("content") or "")
            )
            text = f"{text.rstrip()}\n{marker}"
        return LlmResult(
            text=text,
            finish_reason=self.result.finish_reason,
            usage=self.result.usage,
        )


class FakeTransportRecord:
    schema_version = "hermes.transport.v3"
    _PRIVATE_KEYS = {
        "_moa_prepared_request",
        "__bedrock_region__",
        "__bedrock_converse__",
    }

    def __init__(self) -> None:
        self.middleware_verified_request: dict | None = None
        self.provider_body: dict | None = None
        self.capture_count = 0
        self.ambiguous = False
        self.settled = False
        self.provider_body_estimated_tokens: int | None = None
        self.provider_body_estimate_source = "unknown"
        self.provider_body_estimate_confidence = "unknown"
        self._filters = []

    def register_provider_body_filter(self, callback, *, phase="transform") -> None:
        self._filters.append((phase, callback))

    @staticmethod
    def _estimate(payload: dict) -> dict:
        return {
            "estimated_tokens": max(1, len(repr(payload)) // 4) + 64,
            "estimate_source": "hermes.provider_body.rough.v1",
            "estimate_confidence": "heuristic_with_margin",
        }

    def filter_provider_body(self, payload: dict) -> dict:
        if "_moa_prepared_request" in payload:
            return payload
        current = self._snapshot(payload)
        filters = sorted(self._filters, key=lambda item: item[0] == "final_guard")
        for _phase, callback in filters:
            try:
                result = callback(current, **self._estimate(current))
                if isinstance(result, RequestOverlayFilterResult):
                    accepted = result.body
                    if not result._accept(current, accepted):
                        self.ambiguous = True
                        continue
                    current = accepted
                else:
                    current = result
            except Exception:
                self.ambiguous = True
        estimate = self._estimate(current)
        self.provider_body_estimated_tokens = estimate["estimated_tokens"]
        self.provider_body_estimate_source = estimate["estimate_source"]
        self.provider_body_estimate_confidence = estimate["estimate_confidence"]
        return current

    def _snapshot(self, payload: dict) -> dict:
        return copy.deepcopy(
            {
                key: value
                for key, value in payload.items()
                if key not in self._PRIVATE_KEYS
            }
        )

    def mark_middleware_verified(self, payload: dict) -> None:
        if "_moa_prepared_request" in payload:
            self.ambiguous = True
            self.settled = False
            return
        self.middleware_verified_request = self._snapshot(payload)

    def capture_provider_body(self, payload: dict) -> None:
        self.capture_count += 1
        if self.capture_count != 1:
            self.ambiguous = True
            self.settled = False
            return
        self.provider_body = self._snapshot(payload)

    def settle(self) -> None:
        self.settled = bool(
            not self.ambiguous
            and self.middleware_verified_request is not None
            and self.provider_body is not None
            and self.capture_count == 1
        )


def make_runtime(
    adapter: FakeAdapter,
    compiler: FakeCompiler,
    *,
    llm: FakeLlm | None = None,
) -> ContinuityRuntime:
    return ContinuityRuntime(
        adapter,
        llm or FakeLlm(),
        compiler=compiler,
        estimator=lambda messages: max(1, len(repr(messages)) // 4),
        clock=lambda: "2026-08-30T00:00:00+00:00",
    )


def project(
    runtime: ContinuityRuntime,
    wire: dict,
    *,
    session="s1",
    turn="t1",
    api="a1",
    mode="chat_completions",
    context_window_tokens=16_000,
    context_window_source="config",
    context_window_confidence="authoritative",
):
    return runtime.llm_request(
        request=wire,
        original_request=wire,
        session_id=session,
        turn_id=turn,
        api_request_id=api,
        model="test-model",
        provider="test-provider",
        base_url="",
        api_mode=mode,
        context_window_tokens=context_window_tokens,
        context_window_source=context_window_source,
        context_window_confidence=context_window_confidence,
    )


def execute(
    runtime: ContinuityRuntime,
    projected: dict,
    original: dict,
    *,
    session="s1",
    turn="t1",
    api="a1",
    provider_transform=None,
    capture=True,
    settle=True,
    record=None,
    before_provider=None,
    context_window_tokens=16_000,
    context_window_source="config",
    context_window_confidence="authoritative",
):
    calls: list[dict] = []
    record = record or FakeTransportRecord()

    def next_call(payload):
        record.mark_middleware_verified(payload)
        provider_payload = (
            provider_transform(copy.deepcopy(payload))
            if provider_transform is not None
            else payload
        )
        if before_provider is not None:
            before_provider(record)
        if capture:
            provider_payload = record.filter_provider_body(provider_payload)
            record.capture_provider_body(provider_payload)
        calls.append(copy.deepcopy(provider_payload))
        return {"provider": "ok"}

    result = runtime.llm_execution(
        request=projected,
        original_request=original,
        next_call=next_call,
        session_id=session,
        turn_id=turn,
        api_request_id=api,
        transport_record=record,
        transport_schema_version="hermes.transport.v3",
        context_window_tokens=context_window_tokens,
        context_window_source=context_window_source,
        context_window_confidence=context_window_confidence,
    )
    if settle:
        record.settle()
    records = getattr(runtime, "_test_transport_records", None)
    if records is None:
        records = {}
        runtime._test_transport_records = records
    records[(session, turn, api)] = record
    return result, calls


def post(
    runtime: ContinuityRuntime,
    *,
    session="s1",
    turn="t1",
    api="a1",
    record=None,
    schema="hermes.transport.v3",
):
    if record is None:
        record = runtime._test_transport_records[(session, turn, api)]
    return runtime.post_api_request(
        session_id=session,
        turn_id=turn,
        api_request_id=api,
        transport_record=record,
        transport_schema_version=schema,
    )


class ContinuityRuntimeTests(unittest.TestCase):
    def test_real_extracted_compiler_reaches_projection_and_settlement(self) -> None:
        value = bundle()
        groups = [exact_group(1), exact_group(2)]
        value["source"].update(
            groups=groups,
            source_snapshot="d" * 64,
            stats={
                "full_prefix": True,
                "compacted_prefix_group_ids": [groups[0]["source_prefix_id"]],
            },
        )
        adapter = FakeAdapter(value)
        llm = FakeLlm(LlmResult(text="bounded bridge", finish_reason="stop"))
        runtime = ContinuityRuntime(
            adapter,
            llm,
            estimator=lambda messages: max(1, len(repr(messages)) // 8),
            clock=lambda: "2026-08-30T00:00:00+00:00",
        )
        original = request()

        projected = project(runtime, original)
        self.assertIsNotNone(projected)
        self.assertIn("bounded bridge", repr(projected["request"]))
        execute(runtime, projected["request"], original)
        post(runtime)

        self.assertGreaterEqual(llm.calls, 1)
        self.assertEqual(len(adapter.cas_calls), 1)

    def test_candidate_bridge_wins_and_settles_exactly_once_after_post(self) -> None:
        adapter = FakeAdapter(bundle(checkpoint("old bridge")))
        compiler = FakeCompiler(checkpoint("new bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()

        projected = project(runtime, original)
        self.assertIsNotNone(projected)
        self.assertIn("new bridge", repr(projected["request"]))
        self.assertNotIn("old bridge", repr(projected["request"]))
        self.assertEqual(original, request())

        _result, calls = execute(runtime, projected["request"], original)
        self.assertEqual(len(calls), 1)
        self.assertEqual(adapter.cas_calls, [])

        post(runtime)
        post(runtime)

        self.assertEqual(len(adapter.cas_calls), 1)
        self.assertEqual(len(adapter.metadata_store.rows), 1)
        receipt = adapter.metadata_store.rows[0]
        self.assertEqual(receipt["status"], "delivered_checkpoint_applied")
        self.assertNotIn("new bridge", repr(receipt))
        self.assertNotIn("old bridge", repr(receipt))

    def test_empty_candidate_does_not_resurrect_old_bridge(self) -> None:
        adapter = FakeAdapter(bundle(checkpoint("old bridge")))
        compiler = FakeCompiler(checkpoint(""))
        runtime = make_runtime(adapter, compiler)
        original = request()

        self.assertIsNone(project(runtime, original))
        _result, calls = execute(runtime, original, original)
        post(runtime)

        self.assertEqual(calls, [original])
        self.assertEqual(len(adapter.cas_calls), 1)
        self.assertEqual(
            adapter.cas_calls[0]["checkpoint_candidate"]["recent_bridge"]["status"],
            "empty",
        )
        self.assertEqual(
            adapter.metadata_store.rows[0]["status"],
            "delivered_checkpoint_applied",
        )
        self.assertNotIn("old bridge", repr(calls))

    def test_user_authored_continuity_boundaries_are_never_removed_without_proof(self) -> None:
        namespace = runtime_module.CONTINUITY_MARKER_NAMESPACE
        boundary = runtime_module.CONTINUITY_END_BOUNDARY
        fake_block = f"{namespace} fake]\nquoted by user\n{boundary}"
        contents = {
            "string": f"{fake_block}\n\nactual",
            "list": [
                {"type": "input_text", "text": fake_block},
                {"type": "input_text", "text": "actual"},
            ],
        }

        for name, content in contents.items():
            with self.subTest(name=name):
                adapter = FakeAdapter(bundle())
                runtime = make_runtime(adapter, FakeCompiler(checkpoint("bridge")))
                original = request()
                original["messages"][-1]["content"] = content

                self.assertIsNone(project(runtime, original))
                _result, calls = execute(runtime, original, original)

                self.assertEqual(calls, [original])
                self.assertEqual(adapter.cas_calls, [])

    def test_user_authored_exact_current_block_never_mints_overlay_authority(self) -> None:
        seed_runtime = make_runtime(FakeAdapter(bundle()), FakeCompiler(checkpoint("bridge")))
        seed = project(seed_runtime, request())
        self.assertIsNotNone(seed)
        plan = seed_runtime._turns[("s1", "t1")]
        exact_block = f"{plan.marker}\n{plan.bridge_body}"

        contents = (
            f"{exact_block}\n\nactual",
            [
                {"type": "text", "text": exact_block},
                {"type": "text", "text": "actual"},
            ],
        )
        for content in contents:
            with self.subTest(kind=type(content).__name__):
                adapter = FakeAdapter(bundle())
                runtime = make_runtime(adapter, FakeCompiler(checkpoint("bridge")))
                original = request()
                original["messages"][-1]["content"] = content

                self.assertIsNone(project(runtime, original))
                _result, calls = execute(runtime, original, original)

                self.assertEqual(calls, [original])
                self.assertEqual(adapter.cas_calls, [])
                self.assertEqual(adapter.metadata_store.rows, [])

    def test_old_checkpoint_projects_without_rewriting_revision(self) -> None:
        adapter = FakeAdapter(bundle(checkpoint("old bridge")))
        compiler = FakeCompiler(None)
        runtime = make_runtime(adapter, compiler)
        original = request()

        projected = project(runtime, original)
        _result, calls = execute(runtime, projected["request"], original)
        post(runtime)

        self.assertIn("old bridge", repr(calls[0]))
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(
            adapter.metadata_store.rows[0]["status"],
            "delivered_checkpoint_unchanged",
        )

    def test_retry_and_tool_followup_reuse_one_frozen_compile(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()

        first = project(runtime, original)
        retry = project(runtime, original)
        tool_followup = {
            **original,
            "messages": [
                *original["messages"],
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
                {"role": "tool", "content": "result", "tool_call_id": "c1"},
            ],
        }
        followup = project(runtime, tool_followup, api="a2")

        self.assertIsNotNone(first)
        self.assertIsNotNone(retry)
        self.assertIsNotNone(followup)
        self.assertEqual(len(compiler.calls), 1)
        self.assertEqual(adapter.read_count, 1)
        carrier = followup["request"]["messages"][1]["content"]
        self.assertEqual(carrier.count("\nbridge\n[END THREAD CONTINUITY"), 1)

    def test_scoped_proof_allows_downstream_additive_user_block(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = {
            "model": "test-model",
            "max_tokens": 128,
            "messages": [
                {"role": "system", "content": "fixed"},
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "current"}],
                },
            ],
        }

        projected = project(runtime, original)
        downstream = copy.deepcopy(projected["request"])
        hot_block = {"type": "text", "text": "[GLOBAL HOT] additive field"}
        downstream["messages"][-1]["content"].append(hot_block)
        _result, calls = execute(runtime, downstream, original)
        post(runtime)

        self.assertEqual(calls, [downstream])
        self.assertEqual(calls[0]["messages"][-1]["content"][-1], hot_block)
        self.assertEqual(len(adapter.cas_calls), 1)

    def test_codex_sanitize_stages_the_provider_bound_request_hash(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = {**request(), "temperature": 0.2, "unsupported": "drop-me"}
        projected = project(runtime, original)

        def sanitize(payload):
            payload.pop("unsupported")
            return payload

        _result, calls = execute(
            runtime,
            projected["request"],
            original,
            provider_transform=sanitize,
        )
        post(runtime)

        self.assertEqual(len(calls), 1)
        self.assertNotIn("unsupported", calls[0])
        self.assertEqual(
            adapter.metadata_store.rows[0]["hashes"]["request_sha256"],
            runtime_module._request_sha256(calls[0]),
        )
        self.assertNotEqual(
            runtime_module._request_sha256(projected["request"]),
            runtime_module._request_sha256(calls[0]),
        )

    def test_relay_delete_or_modify_bridge_withholds_publish_but_returns(self) -> None:
        for replacement in ("", "relay-tampered"):
            with self.subTest(replacement=replacement or "deleted"):
                adapter = FakeAdapter(bundle())
                compiler = FakeCompiler(checkpoint("bridge"))
                runtime = make_runtime(adapter, compiler)
                original = request()
                projected = project(runtime, original)
                plan = runtime._turns[("s1", "t1")]

                def relay(payload):
                    payload["messages"][-1]["content"] = payload["messages"][-1][
                        "content"
                    ].replace(
                        f"{plan.marker}\n{plan.bridge_body}\n\n",
                        replacement,
                    )
                    return payload

                result, calls = execute(
                    runtime,
                    projected["request"],
                    original,
                    provider_transform=relay,
                )
                post(runtime)

                self.assertEqual(result, {"provider": "ok"})
                self.assertEqual(len(calls), 1)
                self.assertEqual(adapter.cas_calls, [])
                self.assertEqual(adapter.metadata_store.rows, [])

    def test_moa_prepared_request_is_ambiguous_and_never_publishes(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()
        projected = project(runtime, original)
        moa_request = copy.deepcopy(projected["request"])
        moa_request["_moa_prepared_request"] = {"prepared": True}

        result, calls = execute(
            runtime,
            moa_request,
            original,
        )
        record = runtime._test_transport_records[("s1", "t1", "a1")]
        post(runtime)

        self.assertEqual(result, {"provider": "ok"})
        self.assertIn("_moa_prepared_request", calls[0])
        self.assertNotIn("_moa_prepared_request", record.provider_body)
        self.assertTrue(record.ambiguous)
        self.assertFalse(record.settled)
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_non_moa_private_key_is_excluded_from_provider_body_hash(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()
        projected = project(runtime, original)
        bedrock_request = copy.deepcopy(projected["request"])
        bedrock_request["__bedrock_region__"] = "us-east-1"

        _result, calls = execute(runtime, bedrock_request, original)
        record = runtime._test_transport_records[("s1", "t1", "a1")]
        post(runtime)

        self.assertNotIn("__bedrock_region__", calls[0])
        self.assertNotIn("__bedrock_region__", record.provider_body)
        self.assertEqual(len(adapter.cas_calls), 1)
        self.assertEqual(
            adapter.metadata_store.rows[0]["hashes"]["request_sha256"],
            runtime_module._request_sha256(record.provider_body),
        )

    def test_post_requires_same_settled_unambiguous_transport_record(self) -> None:
        cases = ("missing_capture", "ambiguous", "unsettled", "wrong_record")
        for case in cases:
            with self.subTest(case=case):
                adapter = FakeAdapter(bundle())
                compiler = FakeCompiler(checkpoint("bridge"))
                runtime = make_runtime(adapter, compiler)
                original = request()
                projected = project(runtime, original)
                if case == "missing_capture":
                    execute(
                        runtime,
                        projected["request"],
                        original,
                        capture=False,
                    )
                    post(runtime)
                elif case == "ambiguous":
                    record = FakeTransportRecord()
                    execute(
                        runtime,
                        projected["request"],
                        original,
                        record=record,
                        settle=False,
                    )
                    record.capture_provider_body(projected["request"])
                    record.settle()
                    post(runtime, record=record)
                elif case == "unsettled":
                    execute(
                        runtime,
                        projected["request"],
                        original,
                        settle=False,
                    )
                    post(runtime)
                else:
                    execute(runtime, projected["request"], original)
                    wrong = FakeTransportRecord()
                    wrong.mark_middleware_verified(projected["request"])
                    wrong.capture_provider_body(projected["request"])
                    wrong.settle()
                    post(runtime, record=wrong)

                self.assertEqual(adapter.cas_calls, [])
                self.assertEqual(adapter.metadata_store.rows, [])

    def test_execution_drift_removes_only_bound_projection_and_never_settles(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()
        original["earlier_middleware"] = "preserve-before"

        projected = project(runtime, original)
        drifted = copy.deepcopy(projected["request"])
        drifted["model"] = "rewritten-model"
        drifted["later_middleware"] = "preserve-after"
        _result, calls = execute(runtime, drifted, request())
        post(runtime)

        self.assertEqual(calls[0]["model"], "rewritten-model")
        self.assertEqual(calls[0]["earlier_middleware"], "preserve-before")
        self.assertEqual(calls[0]["later_middleware"], "preserve-after")
        self.assertNotIn("bridge", repr(calls[0]))
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_replaced_original_carrier_fails_open_current_without_settlement(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()

        projected = project(runtime, original)
        drifted = copy.deepcopy(projected["request"])
        drifted["messages"][-1]["content"] = drifted["messages"][-1][
            "content"
        ].replace("current", "replaced payload")
        _result, calls = execute(runtime, drifted, original)
        post(runtime)

        self.assertEqual(calls, [drifted])
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_attachment_payload_is_part_of_frozen_current_identity(self) -> None:
        fixtures = {
            "openai": lambda payload: {
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "fixed"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": payload}}
                        ],
                    },
                ],
            },
            "codex": lambda payload: {
                "model": "test-model",
                "instructions": "fixed",
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_image", "image_url": payload}],
                    }
                ],
            },
            "bedrock": lambda payload: {
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": [{"text": "fixed"}]},
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": "png",
                                    "source": {"bytes": payload.encode("utf-8")},
                                }
                            }
                        ],
                    },
                ],
            },
            "document": lambda payload: {
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "fixed"},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {"bytes": payload.encode("utf-8")},
                            }
                        ],
                    },
                ],
            },
            "file": lambda payload: {
                "model": "test-model",
                "instructions": "fixed",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "file_data": payload.encode("utf-8"),
                            }
                        ],
                    }
                ],
            },
        }
        for kind, build in fixtures.items():
            with self.subTest(kind=kind):
                adapter = FakeAdapter(bundle())
                compiler = FakeCompiler(checkpoint("bridge"))
                runtime = make_runtime(adapter, compiler)

                first = project(runtime, build("payload-a"), api="a1")
                same = project(runtime, build("payload-a"), api="a2")
                changed = project(runtime, build("payload-b"), api="a3")

                self.assertIsNotNone(first)
                self.assertIsNotNone(same)
                self.assertIsNone(changed)
                self.assertEqual(len(compiler.calls), 1)

    def test_provider_fallback_normalizes_string_text_and_bedrock_carriers(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        chat = request()
        responses = {
            "model": "test-model",
            "max_output_tokens": 128,
            "instructions": "fixed",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "current"}],
                }
            ],
        }
        bedrock = {
            "model": "test-model",
            "max_tokens": 128,
            "messages": [
                {"role": "system", "content": [{"text": "fixed"}]},
                {"role": "user", "content": [{"text": "current"}]},
            ],
        }

        first = runtime.llm_request(
            request=chat,
            original_request=chat,
            session_id="s1",
            turn_id="t1",
            api_request_id="a1",
            model="test-model",
            provider="openai",
            api_mode="chat_completions",
            context_window_tokens=16_000,
            context_window_source="config",
            context_window_confidence="authoritative",
        )
        runtime.api_request_error(session_id="s1", turn_id="t1", api_request_id="a1")
        second = runtime.llm_request(
            request=responses,
            original_request=responses,
            session_id="s1",
            turn_id="t1",
            api_request_id="a2",
            model="test-model",
            provider="openai-responses",
            api_mode="responses",
            context_window_tokens=16_000,
            context_window_source="config",
            context_window_confidence="authoritative",
        )
        runtime.api_request_error(session_id="s1", turn_id="t1", api_request_id="a2")
        third = runtime.llm_request(
            request=bedrock,
            original_request=bedrock,
            session_id="s1",
            turn_id="t1",
            api_request_id="a3",
            model="test-model",
            provider="bedrock",
            api_mode="bedrock_converse",
            context_window_tokens=16_000,
            context_window_source="config",
            context_window_confidence="authoritative",
        )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(third)
        self.assertEqual(len(compiler.calls), 1)
        self.assertIn("bridge", repr(second["request"]))
        self.assertIn("bridge", repr(third["request"]))
        _result, calls = execute(
            runtime,
            third["request"],
            bedrock,
            api="a3",
        )
        post(runtime, api="a3")
        self.assertEqual(calls, [third["request"]])
        self.assertEqual(len(adapter.cas_calls), 1)

    def test_image_url_and_input_image_share_content_identity(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        openai = {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "fixed"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.test/a.png"},
                        }
                    ],
                },
            ],
        }
        codex = {
            "model": "test-model",
            "instructions": "fixed",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": "https://example.test/a.png",
                        }
                    ],
                }
            ],
        }
        changed = copy.deepcopy(codex)
        changed["input"][0]["content"][0]["image_url"] = (
            "https://example.test/b.png"
        )

        self.assertIsNotNone(project(runtime, openai, api="a1"))
        self.assertIsNotNone(project(runtime, codex, api="a2"))
        self.assertIsNone(project(runtime, changed, api="a3"))
        self.assertEqual(len(compiler.calls), 1)

    def test_visible_user_continuations_keep_first_turn_anchor(self) -> None:
        shapes = {
            "ack": (
                {"role": "assistant", "content": "I will now do that.", "finish_reason": "incomplete"},
                {
                    "role": "user",
                    "content": (
                        "[System: Continue now. Execute the required tool calls "
                        "and only send your final answer after completing the task.]"
                    ),
                },
            ),
            "length": (
                {"role": "assistant", "content": "partial answer"},
                {
                    "role": "user",
                    "content": (
                        "[System: Your previous response was truncated by the "
                        "output length limit. Continue exactly where you left "
                        "off. Do not restart or repeat prior text. Finish the "
                        "answer directly.]"
                    ),
                    "_length_continuation_nudge": True,
                },
            ),
            "redirect": (
                {"role": "assistant", "content": "visible partial reply"},
                {
                    "role": "user",
                    "content": "Return JSON instead.",
                    "api_content": (
                        "[Context from the interrupted assistant response]\n"
                        "[This response was interrupted by a user correction.]\n\n"
                        "Return JSON instead."
                    ),
                },
            ),
        }
        for kind, (interim, continuation) in shapes.items():
            with self.subTest(kind=kind):
                adapter = FakeAdapter(bundle())
                compiler = FakeCompiler(checkpoint("bridge"))
                runtime = make_runtime(adapter, compiler)
                first_wire = request("frozen original")
                first = project(runtime, first_wire, api="a1")
                runtime.api_request_error(
                    session_id="s1", turn_id="t1", api_request_id="a1"
                )
                continued = {
                    **first_wire,
                    "messages": [
                        *first_wire["messages"],
                        interim,
                        continuation,
                    ],
                }

                projected = project(runtime, continued, api="a2")

                self.assertIsNotNone(first)
                self.assertIsNotNone(projected)
                self.assertEqual(len(compiler.calls), 1)
                self.assertNotIn("bridge", projected["request"]["messages"][1]["content"])
                self.assertIn("bridge", projected["request"]["messages"][-1]["content"])
                _result, calls = execute(
                    runtime,
                    projected["request"],
                    continued,
                    api="a2",
                )
                self.assertEqual(calls, [projected["request"]])

    def test_missing_first_turn_anchor_blocks_continuation_projection(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        first_wire = request("frozen original")

        self.assertIsNotNone(project(runtime, first_wire, api="a1"))
        runtime.api_request_error(session_id="s1", turn_id="t1", api_request_id="a1")
        replaced = {
            **first_wire,
            "messages": [
                {"role": "system", "content": "fixed"},
                {"role": "user", "content": "replacement only"},
            ],
        }

        self.assertIsNone(project(runtime, replaced, api="a2"))
        self.assertEqual(len(compiler.calls), 1)

    def test_lru_eviction_in_projection_lease_gap_never_returns_bound_request(self) -> None:
        for body in ("bridge", ""):
            with self.subTest(body=body or "empty-candidate"):
                adapter = FakeAdapter(bundle())
                compiler = FakeCompiler(checkpoint(body))
                runtime = make_runtime(adapter, compiler)
                runtime.max_cached_turns = 1
                entered = threading.Event()
                release = threading.Event()
                attempt_budget = runtime._attempt_budget
                gate_lock = threading.Lock()
                gated = False

                def gated_budget(request_value, plan, provider_key, **kwargs):
                    nonlocal gated
                    result = attempt_budget(
                        request_value, plan, provider_key, **kwargs
                    )
                    with gate_lock:
                        should_wait = not gated
                        if should_wait:
                            gated = True
                    if should_wait:
                        entered.set()
                        self.assertTrue(release.wait(5))
                    return result

                runtime._attempt_budget = gated_budget
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(
                        project,
                        runtime,
                        request("one"),
                        session="s1",
                        turn="t1",
                        api="a1",
                    )
                    self.assertTrue(entered.wait(5))
                    second = project(
                        runtime,
                        request("two"),
                        session="s2",
                        turn="t2",
                        api="a2",
                    )
                    release.set()
                    first_result = first.result(timeout=5)

                if body:
                    self.assertIsNotNone(second)
                else:
                    self.assertIsNone(second)
                self.assertIsNone(first_result)
                self.assertNotIn(("s1", "t1", "a1"), runtime._projections)
                self.assertNotIn(("s1", "t1"), runtime._turns)

    def test_summary_result_requires_stop_and_exact_terminal_marker(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(None)
        for reason, incomplete in (
            ("stop", False),
            ("length", True),
            ("max_tokens", True),
            ("content_filter", True),
            ("tool_calls", True),
            ("cancelled", True),
            ("future_provider_status", True),
            (None, True),
        ):
            with self.subTest(reason=reason):
                runtime = make_runtime(
                    adapter,
                    compiler,
                    llm=FakeLlm(LlmResult(finish_reason=reason)),
                )
                result = asyncio.run(
                    runtime._summary_call(
                        {"max_output_tokens": 128},
                        [{"role": "user", "content": "summarize"}],
                    )
                )
                self.assertEqual(result.get("status") == "incomplete", incomplete)
                self.assertNotIn(runtime_module._SUMMARY_END_PREFIX, result["content"])

        missing = make_runtime(
            adapter,
            compiler,
            llm=FakeLlm(include_completion_marker=False),
        )
        result = asyncio.run(
            missing._summary_call(
                {"max_output_tokens": 128},
                [{"role": "user", "content": "summarize"}],
            )
        )
        self.assertEqual(result["status"], "incomplete")

    def test_summary_marker_digest_accepts_multimodal_and_bedrock_bytes(self) -> None:
        contents = {
            "input-image": [
                {"type": "input_text", "text": "look"},
                {
                    "type": "input_image",
                    "image_url": {"url": "data:image/png;base64,AA=="},
                },
            ],
            "bedrock-bytes": [
                {"text": "look"},
                {
                    "image": {
                        "format": "png",
                        "source": {"bytes": b"\x89PNG"},
                    }
                },
            ],
        }
        for name, content in contents.items():
            with self.subTest(name=name):
                runtime = make_runtime(FakeAdapter(bundle()), FakeCompiler(None))
                messages = [{"role": "user", "content": content}]
                original = copy.deepcopy(messages)

                result = asyncio.run(
                    runtime._summary_call(
                        {"max_output_tokens": 128},
                        messages,
                    )
                )

                self.assertNotIn("status", result)
                self.assertEqual(result["content"], "summary")
                self.assertEqual(messages, original)

    def test_missing_post_error_or_execution_drift_never_publishes(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()

        projected = project(runtime, original)
        execute(runtime, projected["request"], original)
        self.assertEqual(adapter.cas_calls, [])

        runtime.api_request_error(session_id="s1", turn_id="t1", api_request_id="a1")
        post(runtime)
        self.assertEqual(adapter.cas_calls, [])

        projected = project(runtime, original, api="a2")
        _result, calls = execute(runtime, original, original, api="a2")
        post(runtime, api="a2")
        self.assertEqual(calls, [original])
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_source_fallback_current_drift_and_codex_mode_are_native(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"), status="fallback")
        runtime = make_runtime(adapter, compiler)

        self.assertIsNone(project(runtime, request()))
        self.assertIsNone(project(runtime, request("changed")))
        self.assertEqual(len(compiler.calls), 1)

        codex_adapter = FakeAdapter(bundle())
        codex_compiler = FakeCompiler(checkpoint("bridge"))
        codex_runtime = make_runtime(codex_adapter, codex_compiler)
        self.assertIsNone(
            project(codex_runtime, request(), mode="codex_app_server")
        )
        self.assertEqual(codex_compiler.calls, [])
        self.assertEqual(codex_adapter.metadata_store.rows, [])

    def test_untrusted_host_context_never_compiles_or_projects(self) -> None:
        cases = (
            (None, "unknown", "unknown"),
            (256_000, "fallback", "fallback"),
            (256_000, "unknown", "catalog"),
        )
        for tokens, source, confidence in cases:
            with self.subTest(tokens=tokens, source=source, confidence=confidence):
                adapter = FakeAdapter(bundle())
                compiler = FakeCompiler(checkpoint("bridge"))
                runtime = make_runtime(adapter, compiler)

                projected = project(
                    runtime,
                    request(),
                    context_window_tokens=tokens,
                    context_window_source=source,
                    context_window_confidence=confidence,
                )

                self.assertIsNone(projected)
                self.assertEqual(compiler.calls, [])
                self.assertEqual(adapter.read_count, 0)

    def test_final_provider_budget_removes_only_continuity_before_sdk(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()
        projected = project(
            runtime,
            original,
            context_window_tokens=2_000,
        )
        self.assertIsNotNone(projected)
        downstream = copy.deepcopy(projected["request"])
        downstream_block = "[GLOBAL HOT]\n" + ("x" * 20_000)
        downstream["messages"][-1]["content"] += "\n\n" + downstream_block

        result, calls = execute(
            runtime,
            downstream,
            original,
            context_window_tokens=2_000,
        )
        post(runtime)

        self.assertEqual(result, {"provider": "ok"})
        self.assertEqual(len(calls), 1)
        self.assertIn(downstream_block, calls[0]["messages"][-1]["content"])
        self.assertNotIn("bridge", calls[0]["messages"][-1]["content"])
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_final_budget_guard_runs_after_expanding_transforms_in_both_orders(
        self,
    ) -> None:
        for order in ("transform_first", "guard_first"):
            with self.subTest(order=order):
                adapter = FakeAdapter(bundle())
                runtime = make_runtime(adapter, FakeCompiler(checkpoint("bridge")))
                original = request()
                projected = project(
                    runtime,
                    original,
                    context_window_tokens=2_000,
                )
                self.assertIsNotNone(projected)
                record = FakeTransportRecord()

                def expand(body, **_estimate):
                    body["messages"][-1]["content"] += "\n[LATE]" + ("x" * 20_000)
                    return body

                def register_transform(target):
                    target.register_provider_body_filter(expand)

                if order == "transform_first":
                    register_transform(record)
                    before_provider = None
                else:
                    before_provider = register_transform

                _result, calls = execute(
                    runtime,
                    projected["request"],
                    original,
                    record=record,
                    before_provider=before_provider,
                    context_window_tokens=2_000,
                )
                post(runtime, record=record)

                self.assertEqual(len(calls), 1)
                self.assertIn("[LATE]", calls[0]["messages"][-1]["content"])
                self.assertNotIn("bridge", calls[0]["messages"][-1]["content"])
                self.assertEqual(adapter.cas_calls, [])
                self.assertEqual(adapter.metadata_store.rows, [])

    def test_catalog_context_uses_a_conservative_compilation_window(self) -> None:
        runtime = make_runtime(FakeAdapter(bundle()), FakeCompiler(checkpoint("bridge")))

        projected = project(
            runtime,
            request(),
            context_window_tokens=10_000,
            context_window_source="model_catalog",
            context_window_confidence="catalog",
        )

        self.assertIsNotNone(projected)
        plan = runtime._turns[("s1", "t1")]
        self.assertEqual(plan.context_window_tokens, 10_000)
        self.assertEqual(plan.usable_context_window_tokens, 9_000)
        self.assertEqual(plan.context_window_confidence, "catalog")

    def test_provider_fallback_requires_equal_or_greater_headroom(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = ContinuityRuntime(
            adapter,
            FakeLlm(),
            compiler=compiler,
            estimator=lambda messages: max(1, len(repr(messages)) // 4),
            clock=lambda: "2026-08-30T00:00:00+00:00",
        )

        def invoke(
            model: str,
            api_request_id: str,
            *,
            context_window_tokens: int | None = None,
        ):
            wire = {**request(), "model": model}
            return wire, runtime.llm_request(
                request=wire,
                original_request=wire,
                session_id="s1",
                turn_id="t1",
                api_request_id=api_request_id,
                model=model,
                provider="provider",
                base_url="",
                api_mode="chat_completions",
                context_window_tokens=(
                    context_window_tokens
                    if context_window_tokens is not None
                    else {
                        "primary": 16_000,
                        "smaller": 512,
                        "larger": 32_000,
                    }[model]
                ),
                context_window_source="config",
                context_window_confidence="authoritative",
            )

        _primary_wire, primary = invoke("primary", "a1")
        self.assertIsNotNone(primary)
        runtime.api_request_error(session_id="s1", turn_id="t1", api_request_id="a1")

        _same_wire, same_provider_smaller = invoke(
            "primary",
            "a-same-smaller",
            context_window_tokens=512,
        )
        self.assertIsNone(same_provider_smaller)

        smaller_wire, smaller = invoke("smaller", "a2")
        self.assertIsNone(smaller)
        _result, smaller_calls = execute(
            runtime,
            smaller_wire,
            smaller_wire,
            api="a2",
        )
        post(runtime, api="a2")
        self.assertEqual(smaller_calls, [smaller_wire])
        self.assertEqual(adapter.cas_calls, [])

        larger_wire, larger = invoke("larger", "a3")
        self.assertIsNotNone(larger)
        _result, larger_calls = execute(
            runtime,
            larger["request"],
            larger_wire,
            api="a3",
            context_window_tokens=32_000,
        )
        post(runtime, api="a3")

        self.assertIn("bridge", repr(larger_calls[0]))
        self.assertEqual(len(compiler.calls), 1)
        self.assertEqual(len(adapter.cas_calls), 1)

    def test_cas_conflict_records_delivery_without_retrying_over_old_state(self) -> None:
        adapter = FakeAdapter(bundle(), cas_ok=False)
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()

        projected = project(runtime, original)
        execute(runtime, projected["request"], original)
        post(runtime)

        second = project(runtime, original, api="a2")
        execute(runtime, second["request"], original, api="a2")
        post(runtime, api="a2")

        self.assertEqual(len(adapter.cas_calls), 1)
        self.assertEqual(
            [row["status"] for row in adapter.metadata_store.rows],
            ["delivered_checkpoint_conflict", "delivered_checkpoint_conflict"],
        )

    def test_non_conflict_cas_failure_is_persistently_reported_as_failed(self) -> None:
        adapter = FakeAdapter(
            bundle(),
            cas_ok=False,
            cas_error="checkpoint_storage_failed",
        )
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        original = request()

        for api_request_id in ("a1", "a2"):
            projected = project(runtime, original, api=api_request_id)
            execute(
                runtime,
                projected["request"],
                original,
                api=api_request_id,
            )
            post(runtime, api=api_request_id)

        self.assertEqual(len(adapter.cas_calls), 1)
        self.assertEqual(
            [row["status"] for row in adapter.metadata_store.rows],
            ["delivered_checkpoint_failed", "delivered_checkpoint_failed"],
        )

    def test_attempt_cap_rejects_new_work_until_live_attempt_clears(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)
        runtime.max_cached_turns = 1

        first_wire = request("one")
        first = project(
            runtime,
            first_wire,
            session="s1",
            turn="t1",
            api="a1",
        )
        execute(
            runtime,
            first["request"],
            first_wire,
            session="s1",
            turn="t1",
            api="a1",
        )
        second = project(
            runtime,
            request("two"),
            session="s2",
            turn="t2",
            api="a2",
        )

        self.assertIsNone(second)
        self.assertIn(("s1", "t1"), runtime._turns)
        self.assertNotIn(("s2", "t2"), runtime._turns)
        self.assertIn(("s1", "t1", "a1"), runtime._transport)

        post(runtime)
        self.assertEqual(len(adapter.cas_calls), 1)
        self.assertNotIn(("s1", "t1", "a1"), runtime._projections)
        self.assertNotIn(("s1", "t1", "a1"), runtime._transport)

        second = project(
            runtime,
            request("two"),
            session="s2",
            turn="t2",
            api="a2",
        )
        self.assertIsNotNone(second)
        runtime.api_request_error(session_id="s2", turn_id="t2", api_request_id="a2")
        self.assertNotIn(("s2", "t2", "a2"), runtime._projections)
        self.assertNotIn(("s2", "t2", "a2"), runtime._transport)

    def test_orphan_attempts_are_bounded_and_expire_to_native_request(self) -> None:
        now = [0.0]
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = ContinuityRuntime(
            adapter,
            FakeLlm(),
            compiler=compiler,
            estimator=lambda messages: max(1, len(repr(messages)) // 4),
            clock=lambda: "2026-08-30T00:00:00+00:00",
            max_cached_turns=8,
            attempt_ttl_seconds=10,
            monotonic=lambda: now[0],
        )
        original = request()
        first = project(runtime, original, api="a0")
        self.assertIsNotNone(first)

        for index in range(1, 10_001):
            project(runtime, original, api=f"a{index}")

        self.assertEqual(len(runtime._projections), 8)
        self.assertLessEqual(len(runtime._turns), 8)

        now[0] = 11.0
        _result, calls = execute(
            runtime,
            first["request"],
            original,
            api="a0",
        )
        self.assertEqual(calls, [original])
        post(runtime, api="a0")
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_expired_modified_projection_is_not_removed(self) -> None:
        now = [0.0]
        adapter = FakeAdapter(bundle())
        runtime = ContinuityRuntime(
            adapter,
            FakeLlm(),
            compiler=FakeCompiler(checkpoint("bridge")),
            estimator=lambda messages: max(1, len(repr(messages)) // 4),
            attempt_ttl_seconds=10,
            monotonic=lambda: now[0],
        )
        original = request()
        projected = project(runtime, original)
        plan = runtime._turns[("s1", "t1")]
        modified = copy.deepcopy(projected["request"])
        modified_body = plan.bridge_body.replace("bridge", "modified bridge", 1)
        modified["messages"][-1]["content"] = modified["messages"][-1]["content"].replace(
            f"{plan.marker}\n{plan.bridge_body}\n\n",
            f"{plan.marker}\n{modified_body}\n\n",
            1,
        )

        now[0] = 11.0
        _result, calls = execute(runtime, modified, original)

        self.assertEqual(calls, [modified])
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_projection_swept_before_execution_is_not_removed_without_proof(self) -> None:
        now = [0.0]
        adapter = FakeAdapter(bundle())
        runtime = ContinuityRuntime(
            adapter,
            FakeLlm(),
            compiler=FakeCompiler(checkpoint("bridge")),
            estimator=lambda messages: max(1, len(repr(messages)) // 4),
            attempt_ttl_seconds=10,
            monotonic=lambda: now[0],
        )
        original = request()
        projected = project(runtime, original)

        now[0] = 11.0
        runtime.status_command()
        self.assertNotIn(("s1", "t1", "a1"), runtime._projections)
        _result, calls = execute(runtime, projected["request"], original)

        self.assertEqual(calls, [projected["request"]])
        self.assertEqual(adapter.cas_calls, [])
        self.assertEqual(adapter.metadata_store.rows, [])

    def test_status_command_is_body_free_and_exposes_attempt_health(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("private generated bridge"))
        runtime = make_runtime(adapter, compiler)
        projected = project(runtime, request("private current sentence"))

        payload = json.loads(runtime.status_command("s1"))

        self.assertIsNotNone(projected)
        self.assertEqual(payload["schema"], "hermes_continuity_status.v1")
        self.assertEqual(payload["active_projection_count"], 1)
        self.assertTrue(payload["checkpoint_contains_generated_bridge_body"])
        self.assertFalse(payload["stores_canonical_message_bodies"])
        self.assertEqual(payload["context_window_source_counts"], {"config": 1})
        self.assertEqual(
            payload["context_window_confidence_counts"], {"authoritative": 1}
        )
        self.assertFalse(
            payload["final_provider_estimate"]["is_exact_tokenizer_bound"]
        )
        self.assertNotIn("private generated bridge", repr(payload))
        self.assertNotIn("private current sentence", repr(payload))

    def test_sessions_and_turns_do_not_overwrite_each_other(self) -> None:
        adapter = FakeAdapter(bundle())
        compiler = FakeCompiler(checkpoint("bridge"))
        runtime = make_runtime(adapter, compiler)

        s1 = project(runtime, request("one"), session="s1", turn="t1", api="a1")
        s2 = project(runtime, request("two"), session="s2", turn="t2", api="a2")

        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertEqual(len(compiler.calls), 2)
        self.assertEqual(adapter.read_count, 2)


if __name__ == "__main__":
    unittest.main()
