from __future__ import annotations

import copy
import hashlib
import importlib
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_middleware_integration"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

runtime_module = importlib.import_module(f"{PACKAGE}.runtime")
ContinuityRuntime = runtime_module.ContinuityRuntime

HERMES_ROOT = Path(os.environ.get("HERMES_SOURCE_ROOT", ""))
HERMES_AVAILABLE = (HERMES_ROOT / "hermes_cli" / "middleware.py").is_file()
if HERMES_AVAILABLE:
    sys.path.insert(0, str(HERMES_ROOT))
    from hermes_cli.middleware import (  # noqa: E402
        LLM_EXECUTION_MIDDLEWARE,
        LLM_REQUEST_MIDDLEWARE,
        TRANSPORT_SCHEMA_VERSION,
        TransportRecord,
        apply_llm_request_middleware,
        run_llm_execution_middleware,
    )
    from hermes_cli.lifecycle import invoke_hook  # noqa: E402
    from hermes_cli.plugins import get_plugin_manager  # noqa: E402


def _checkpoint(revision: int, body: str) -> dict:
    body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return {
        "schema": "thread_continuity_checkpoint.v2",
        "revision": revision,
        "recent_bridge": {
            "schema": "thread_continuity_recent_bridge.v1",
            "status": "ready" if body else "empty",
            "relation": (
                "represented_in_recent_bridge"
                if body
                else "no_visible_representation"
            ),
            "source_group_ids": ["g1"] if body else [],
            "source_group_fingerprints": ["f" * 64] if body else [],
            "source_slice_fingerprint": "e" * 64 if body else "",
            "reference_at": "2026-08-30T00:00:00+00:00",
            "recent_horizon_hours": 72,
            "source_token_limit": 24_000,
            "output_token_limit": 2_048,
            "body": body,
            "body_sha256": body_sha256,
        },
    }


OLD_CHECKPOINT = _checkpoint(1, "old bridge")
CANDIDATE = _checkpoint(2, "candidate bridge")


class _Metadata:
    def __init__(self) -> None:
        self.receipts: list[dict] = []

    def record_receipt(self, **kwargs):
        self.receipts.append(copy.deepcopy(kwargs))


class _Adapter:
    def __init__(self) -> None:
        self.metadata_store = _Metadata()
        self.cas_calls: list[dict] = []

    def read_bundle(self, session_id: str) -> dict:
        return {
            "source": {
                "status": "ready",
                "groups": [],
                "source_snapshot": "a" * 64,
                "scan_complete": True,
                "stats": {
                    "full_prefix": True,
                    "compacted_prefix_group_ids": [],
                },
            },
            "continuity": {
                "status": "ready",
                "state": {"revision": 1, "checkpoint": OLD_CHECKPOINT},
            },
        }

    def settle_checkpoint_delivery(self, session_id: str, **kwargs) -> dict:
        self.cas_calls.append(
            {
                "session_id": session_id,
                "expected_revision": kwargs["expected_revision"],
                "expected_source_snapshot": kwargs["expected_source_snapshot"],
                "checkpoint_candidate": copy.deepcopy(
                    kwargs["checkpoint_candidate"]
                ),
            }
        )
        self.metadata_store.record_receipt(
            receipt_id=kwargs["receipt_id"],
            session_id=session_id,
            kind="delivery",
            status="delivered_checkpoint_applied",
            source_ids=kwargs.get("source_ids", ()),
            hashes=kwargs.get("hashes", {}),
            counts=kwargs.get("counts", {}),
        )
        return {"ok": True, "status": "applied", "receipt_recorded": True}


class _Llm:
    async def acomplete(self, *_args, **_kwargs):  # pragma: no cover - fake compiler skips it
        raise AssertionError("summary call was not expected")


class _Compiler:
    def __init__(self, candidate: dict | None = None) -> None:
        self.calls = 0
        self.candidate = copy.deepcopy(candidate or CANDIDATE)

    async def __call__(self, _bundle, **_kwargs) -> dict:
        self.calls += 1
        return {
            "status": "ready",
            "checkpoint_candidate": copy.deepcopy(self.candidate),
            "expected_revision": 1,
            "expected_pre_turn_source_snapshot": "a" * 64,
        }


def _request() -> dict:
    return {
        "model": "test-model",
        "max_tokens": 128,
        "messages": [
            {"role": "system", "content": "fixed prompt"},
            {"role": "user", "content": "current question"},
        ],
        "temperature": 0.2,
    }


def _context() -> dict:
    return {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "api_request_id": "turn-1:api:1",
        "api_call_count": 1,
        "model": "test-model",
        "provider": "openai",
        "base_url": "",
        "api_mode": "chat_completions",
        "context_window_tokens": 8192,
        "context_window_source": "config",
        "context_window_confidence": "authoritative",
    }


@unittest.skipUnless(HERMES_AVAILABLE, "set HERMES_SOURCE_ROOT to a Hermes 0.20.5 tree")
class HermesMiddlewareIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = get_plugin_manager()
        self.saved_middleware = self.manager._middleware
        self.saved_middleware_owners = self.manager._middleware_owners
        self.saved_hooks = self.manager._hooks
        self.saved_discovered = self.manager._discovered
        self.manager._middleware = {}
        self.manager._middleware_owners = {}
        self.manager._hooks = {}
        self.manager._discovered = True
        self.adapter = _Adapter()
        self.compiler = _Compiler()
        self.runtime = ContinuityRuntime(
            self.adapter,
            _Llm(),
            compiler=self.compiler,
            estimator=lambda messages: len(messages) * 8,
            clock=lambda: "2026-08-30T00:00:00+00:00",
        )
        self.manager._middleware = {
            LLM_REQUEST_MIDDLEWARE: [self.runtime.llm_request],
            LLM_EXECUTION_MIDDLEWARE: [self.runtime.llm_execution],
        }
        self.manager._middleware_owners = {
            LLM_REQUEST_MIDDLEWARE: ["hermes-continuity"],
            LLM_EXECUTION_MIDDLEWARE: ["hermes-continuity"],
        }
        self.manager._hooks = {
            "post_api_request": [self.runtime.post_api_request],
            "api_request_error": [self.runtime.api_request_error],
        }
        self.transport_records: dict[str, object] = {}

    def tearDown(self) -> None:
        self.manager._middleware = self.saved_middleware
        self.manager._middleware_owners = self.saved_middleware_owners
        self.manager._hooks = self.saved_hooks
        self.manager._discovered = self.saved_discovered

    def _project(self):
        original = _request()
        result = apply_llm_request_middleware(original, **_context())
        self.assertTrue(result.changed)
        self.assertEqual(result.trace, [{"source": "hermes-continuity", "reason": "bridge_projected"}])
        self.assertIn("candidate bridge", str(result.payload["messages"][-1]["content"]))
        self.assertEqual(result.original_payload, original)
        return original, result

    def _execute(self, projected, provider, *, provider_transform=None):
        record = TransportRecord()

        def terminal(request):
            record.mark_middleware_verified(request)
            provider_body = (
                provider_transform(copy.deepcopy(request))
                if provider_transform is not None
                else request
            )
            if "_moa_prepared_request" not in provider_body:
                provider_body = record.filter_provider_body(provider_body)
            record.capture_provider_body(provider_body)
            return provider(provider_body)

        response = run_llm_execution_middleware(
            projected.payload,
            terminal,
            original_request=projected.original_payload,
            transport_record=record,
            **_context(),
        )
        record.settle()
        self.transport_records[_context()["api_request_id"]] = record
        return response

    def _post(self, *, record=None):
        record = record or self.transport_records[_context()["api_request_id"]]
        invoke_hook(
            "post_api_request",
            transport_record=record,
            transport_schema_version=TRANSPORT_SCHEMA_VERSION,
            **_context(),
        )

    def test_real_registry_delivers_once_and_only_post_publishes(self) -> None:
        original, projected = self._project()
        provider_bodies: list[dict] = []

        def provider(request: dict) -> dict:
            provider_bodies.append(copy.deepcopy(request))
            return {"choices": [{"finish_reason": "stop"}]}

        response = self._execute(projected, provider)
        self.assertEqual(response["choices"][0]["finish_reason"], "stop")
        self.assertEqual(len(provider_bodies), 1)
        self.assertIn("candidate bridge", str(provider_bodies[0]))
        self.assertEqual(self.adapter.cas_calls, [])
        self.assertEqual(self.adapter.metadata_store.receipts, [])

        self._post()
        self._post()
        self.assertEqual(len(self.adapter.cas_calls), 1)
        self.assertEqual(len(self.adapter.metadata_store.receipts), 1)
        receipt = self.adapter.metadata_store.receipts[0]
        self.assertEqual(
            receipt["hashes"]["request_sha256"],
            runtime_module._request_sha256(provider_bodies[0]),
        )
        receipt_text = str(receipt)
        self.assertNotIn("candidate bridge", receipt_text)
        self.assertNotIn("current question", receipt_text)
        self.assertEqual(original, _request())

    def test_no_post_never_publishes(self) -> None:
        _original, projected = self._project()
        calls = 0

        def provider(request: dict) -> dict:
            nonlocal calls
            calls += 1
            self.assertIn("candidate bridge", str(request))
            return {"ok": True}

        self._execute(projected, provider)
        self.assertEqual(calls, 1)
        self.assertEqual(self.adapter.cas_calls, [])
        self.assertEqual(self.adapter.metadata_store.receipts, [])

    def test_empty_bridge_candidate_settles_through_zero_filter_transport(self) -> None:
        self.compiler = _Compiler(_checkpoint(2, ""))
        self.runtime = ContinuityRuntime(
            self.adapter,
            _Llm(),
            compiler=self.compiler,
            estimator=lambda messages: len(messages) * 8,
            clock=lambda: "2026-08-30T00:00:00+00:00",
        )
        self.manager._middleware = {
            LLM_REQUEST_MIDDLEWARE: [self.runtime.llm_request],
            LLM_EXECUTION_MIDDLEWARE: [self.runtime.llm_execution],
        }
        self.manager._middleware_owners = {
            LLM_REQUEST_MIDDLEWARE: ["hermes-continuity"],
            LLM_EXECUTION_MIDDLEWARE: ["hermes-continuity"],
        }
        self.manager._hooks = {
            "post_api_request": [self.runtime.post_api_request],
            "api_request_error": [self.runtime.api_request_error],
        }

        projected = apply_llm_request_middleware(_request(), **_context())
        self.assertFalse(projected.changed)
        provider_bodies: list[dict] = []
        self._execute(
            projected,
            lambda body: provider_bodies.append(copy.deepcopy(body)) or {"ok": True},
        )
        record = self.transport_records[_context()["api_request_id"]]
        self.assertIsNotNone(record.provider_body_estimated_tokens)
        self._post(record=record)

        self.assertEqual(provider_bodies, [_request()])
        self.assertEqual(len(self.adapter.cas_calls), 1)
        self.assertEqual(len(self.adapter.metadata_store.receipts), 1)
        self.assertEqual(
            self.adapter.cas_calls[0]["checkpoint_candidate"]["recent_bridge"][
                "status"
            ],
            "empty",
        )

    def test_stored_projection_detects_drift_and_post_cannot_publish(self) -> None:
        original, projected = self._project()
        drifted = copy.deepcopy(projected.payload)
        drifted["messages"][-1]["content"] = str(
            drifted["messages"][-1]["content"]
        ).replace("candidate bridge", "tampered bridge")
        provider_bodies: list[dict] = []

        drifted_result = types.SimpleNamespace(
            payload=drifted,
            original_payload=original,
        )
        self._execute(
            drifted_result,
            lambda request: provider_bodies.append(copy.deepcopy(request))
            or {"ok": True},
        )
        self.assertEqual(len(provider_bodies), 1)
        # Hermes still owns the effective provider request.  When another
        # middleware replaces the bound carrier, Continuity cannot safely
        # reconstruct its pre-projection bytes; it therefore preserves the
        # final request but withholds transport proof and publication.
        self.assertEqual(provider_bodies[0], drifted)
        self._post()
        self.assertEqual(self.adapter.cas_calls, [])
        self.assertEqual(self.adapter.metadata_store.receipts, [])
        self.assertEqual(self.compiler.calls, 1)

    def test_moa_prepared_request_is_unsettled_and_never_publishes(self) -> None:
        _original, projected = self._project()
        moa_request = copy.deepcopy(projected.payload)
        moa_request["_moa_prepared_request"] = {"prepared": True}
        moa_result = types.SimpleNamespace(
            payload=moa_request,
            original_payload=projected.original_payload,
        )
        provider_bodies: list[dict] = []

        self._execute(
            moa_result,
            lambda body: provider_bodies.append(copy.deepcopy(body)) or {"ok": True},
        )
        record = self.transport_records[_context()["api_request_id"]]
        self._post()

        self.assertEqual(len(provider_bodies), 1)
        self.assertIn("_moa_prepared_request", provider_bodies[0])
        self.assertTrue(record.ambiguous)
        self.assertFalse(record.settled)
        self.assertEqual(self.adapter.cas_calls, [])
        self.assertEqual(self.adapter.metadata_store.receipts, [])

    def test_real_dual_middleware_chain_preserves_both_blocks_and_calls_once(self) -> None:
        def downstream_request(*, request, **_kwargs):
            next_request = copy.deepcopy(request)
            next_request["messages"][-1]["content"] += "\n\n[GLOBAL HOT]\nhot"
            return {
                "request": next_request,
                "source": "synthetic-global-hot",
                "reason": "hot_projected",
            }

        execution_calls: list[dict] = []

        def downstream_execution(*, request, next_call, **_kwargs):
            execution_calls.append(copy.deepcopy(request))
            return next_call(request)

        self.manager._middleware = {
            LLM_REQUEST_MIDDLEWARE: [self.runtime.llm_request, downstream_request],
            LLM_EXECUTION_MIDDLEWARE: [
                self.runtime.llm_execution,
                downstream_execution,
            ],
        }
        self.manager._middleware_owners = {
            LLM_REQUEST_MIDDLEWARE: [
                "hermes-continuity",
                "synthetic-global-hot",
            ],
            LLM_EXECUTION_MIDDLEWARE: [
                "hermes-continuity",
                "synthetic-global-hot",
            ],
        }
        original = _request()
        projected = apply_llm_request_middleware(original, **_context())
        provider_bodies: list[dict] = []

        self._execute(
            projected,
            lambda body: provider_bodies.append(copy.deepcopy(body)) or {"ok": True},
        )
        self._post()

        self.assertEqual(len(execution_calls), 1)
        self.assertEqual(len(provider_bodies), 1)
        body_text = str(provider_bodies[0])
        self.assertEqual(body_text.count("candidate bridge"), 1)
        self.assertEqual(body_text.count("[GLOBAL HOT]"), 1)
        self.assertEqual(len(self.adapter.cas_calls), 1)

    def test_real_final_body_filter_removes_only_continuity_on_overflow(self) -> None:
        huge_hot = "[GLOBAL HOT]\n" + ("x" * 100_000)

        def downstream_request(*, request, **_kwargs):
            next_request = copy.deepcopy(request)
            next_request["messages"][-1]["content"] += "\n\n" + huge_hot
            return {
                "request": next_request,
                "source": "synthetic-global-hot",
                "reason": "hot_projected",
            }

        self.manager._middleware = {
            LLM_REQUEST_MIDDLEWARE: [self.runtime.llm_request, downstream_request],
            LLM_EXECUTION_MIDDLEWARE: [self.runtime.llm_execution],
        }
        self.manager._middleware_owners = {
            LLM_REQUEST_MIDDLEWARE: [
                "hermes-continuity",
                "synthetic-global-hot",
            ],
            LLM_EXECUTION_MIDDLEWARE: ["hermes-continuity"],
        }
        projected = apply_llm_request_middleware(_request(), **_context())
        provider_bodies: list[dict] = []

        self._execute(
            projected,
            lambda body: provider_bodies.append(copy.deepcopy(body)) or {"ok": True},
        )
        self._post()

        self.assertEqual(len(provider_bodies), 1)
        carrier = provider_bodies[0]["messages"][-1]["content"]
        self.assertIn(huge_hot, carrier)
        self.assertNotIn("candidate bridge", carrier)
        self.assertEqual(self.adapter.cas_calls, [])
        self.assertEqual(self.adapter.metadata_store.receipts, [])

    def test_final_guard_runs_after_expanding_filter_in_both_execution_orders(
        self,
    ) -> None:
        for order in ("continuity_first", "transform_first"):
            with self.subTest(order=order):
                self.adapter = _Adapter()
                self.compiler = _Compiler()
                self.runtime = ContinuityRuntime(
                    self.adapter,
                    _Llm(),
                    compiler=self.compiler,
                    estimator=lambda messages: len(messages) * 8,
                    clock=lambda: "2026-08-30T00:00:00+00:00",
                )
                self.transport_records = {}

                def expanding_execution(
                    *, request, next_call, transport_record, **_kwargs
                ):
                    def expand(body):
                        body["messages"][-1]["content"] += (
                            "\n[LATE TRANSFORM]" + ("x" * 100_000)
                        )
                        return body

                    transport_record.register_provider_body_filter(expand)
                    return next_call(request)

                callbacks = {
                    "hermes-continuity": self.runtime.llm_execution,
                    "synthetic-transform": expanding_execution,
                }
                owners = (
                    ["hermes-continuity", "synthetic-transform"]
                    if order == "continuity_first"
                    else ["synthetic-transform", "hermes-continuity"]
                )
                self.manager._middleware = {
                    LLM_REQUEST_MIDDLEWARE: [self.runtime.llm_request],
                    LLM_EXECUTION_MIDDLEWARE: [callbacks[owner] for owner in owners],
                }
                self.manager._middleware_owners = {
                    LLM_REQUEST_MIDDLEWARE: ["hermes-continuity"],
                    LLM_EXECUTION_MIDDLEWARE: owners,
                }
                self.manager._hooks = {
                    "post_api_request": [self.runtime.post_api_request],
                    "api_request_error": [self.runtime.api_request_error],
                }
                projected = apply_llm_request_middleware(_request(), **_context())
                provider_bodies: list[dict] = []

                self._execute(
                    projected,
                    lambda body: provider_bodies.append(copy.deepcopy(body))
                    or {"ok": True},
                )
                self._post()

                self.assertEqual(len(provider_bodies), 1)
                carrier = provider_bodies[0]["messages"][-1]["content"]
                self.assertIn("[LATE TRANSFORM]", carrier)
                self.assertNotIn("candidate bridge", carrier)
                self.assertEqual(self.adapter.cas_calls, [])
                self.assertEqual(self.adapter.metadata_store.receipts, [])

    def test_reversed_request_and_execution_order_keeps_both_blocks(self) -> None:
        def upstream_request(*, request, **_kwargs):
            next_request = copy.deepcopy(request)
            next_request["messages"][-1]["content"] += "\n\n[GLOBAL HOT]\nhot"
            return {
                "request": next_request,
                "source": "synthetic-global-hot",
                "reason": "hot_projected",
            }

        def upstream_execution(*, request, next_call, **_kwargs):
            return next_call(request)

        self.manager._middleware = {
            LLM_REQUEST_MIDDLEWARE: [upstream_request, self.runtime.llm_request],
            LLM_EXECUTION_MIDDLEWARE: [
                upstream_execution,
                self.runtime.llm_execution,
            ],
        }
        self.manager._middleware_owners = {
            LLM_REQUEST_MIDDLEWARE: [
                "synthetic-global-hot",
                "hermes-continuity",
            ],
            LLM_EXECUTION_MIDDLEWARE: [
                "synthetic-global-hot",
                "hermes-continuity",
            ],
        }
        projected = apply_llm_request_middleware(_request(), **_context())
        provider_bodies: list[dict] = []

        self._execute(
            projected,
            lambda body: provider_bodies.append(copy.deepcopy(body)) or {"ok": True},
        )
        self._post()

        self.assertEqual(len(provider_bodies), 1)
        body_text = str(provider_bodies[0])
        self.assertEqual(body_text.count("candidate bridge"), 1)
        self.assertEqual(body_text.count("[GLOBAL HOT]"), 1)
        self.assertEqual(len(self.adapter.cas_calls), 1)
        self.assertEqual(len(self.adapter.metadata_store.receipts), 1)


if __name__ == "__main__":
    unittest.main()
