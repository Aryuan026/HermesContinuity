import importlib.util
import asyncio
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ResourceBudgetTests(unittest.TestCase):
    def test_compile_unwind_releases_only_its_own_admission(self):
        from test_runtime import runtime_module, ContinuityRuntime, FakeAdapter, FakeLlm, request
        budget = runtime_module.ACTIVE_WORKSETS
        other = object()
        self.assertTrue(budget.acquire(other, 8*1024*1024))
        try:
            for error in (asyncio.CancelledError(), ValueError("compile failed")):
                adapter = FakeAdapter({})
                adapter.history_index = SimpleNamespace()
                runtime = ContinuityRuntime(adapter, FakeLlm())
                async def cancelled_compile():
                    await asyncio.sleep(0)
                    raise error
                def compile_plan(*args, **kwargs):
                    return asyncio.run(cancelled_compile())
                try:
                    with patch.object(runtime, "_compile_plan", side_effect=compile_plan):
                        with self.assertRaises(type(error)):
                            runtime._plan_for_request(request(), session_id="s", turn_id="t",
                                model="m", provider="p", base_url="", context_window_tokens=10000,
                                context_window_source="test", context_window_confidence="exact")
                    self.assertEqual(runtime._turns, {})
                    self.assertEqual(runtime._compiling, set())
                    self.assertNotIn(runtime._budget_key(("s", "t")), budget._leases)
                finally:
                    runtime.clear()
                    budget.release(runtime._budget_key(("s", "t")))
            self.assertEqual(budget._leases[other], 8*1024*1024)
            replacement = ContinuityRuntime(adapter, FakeLlm())
            plan = runtime_module._TurnPlan("", workset_bytes=1)
            try:
                with patch.object(replacement, "_compile_plan", return_value=plan):
                    result = replacement._plan_for_request(request(), session_id="s", turn_id="t",
                        model="m", provider="p", base_url="", context_window_tokens=10000,
                        context_window_source="test", context_window_confidence="exact")
                self.assertIs(result, plan)
                self.assertIn(replacement._budget_key(("s", "t")), budget._leases)
            finally:
                replacement.clear()
            self.assertEqual(budget._leases[other], 8*1024*1024)
        finally:
            budget.release(other)

    def test_clear_during_compile_retains_lease_until_worker_unwinds(self):
        from test_runtime import runtime_module, ContinuityRuntime, FakeAdapter, FakeLlm, request
        adapter = FakeAdapter({})
        adapter.history_index = SimpleNamespace()
        runtime = ContinuityRuntime(adapter, FakeLlm())
        entered, finish = threading.Event(), threading.Event()
        results = []
        def compile_plan(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(5))
            return runtime_module._TurnPlan("", workset_bytes=1)
        def run():
            results.append(runtime._plan_for_request(request(), session_id="s", turn_id="t",
                model="m", provider="p", base_url="", context_window_tokens=10000,
                context_window_source="test", context_window_confidence="exact"))
        worker = threading.Thread(target=run)
        key = runtime._budget_key(("s", "t"))
        try:
            with patch.object(runtime, "_compile_plan", side_effect=compile_plan):
                worker.start()
                self.assertTrue(entered.wait(5))
                runtime.clear()
                self.assertIn(key, runtime_module.ACTIVE_WORKSETS._leases)
                finish.set()
                worker.join(5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(results[0].reason, "runtime_unloaded")
            self.assertNotIn(key, runtime_module.ACTIVE_WORKSETS._leases)
            self.assertEqual(runtime._turns, {})
        finally:
            finish.set()
            worker.join(5)
            runtime.clear()
            runtime_module.ACTIVE_WORKSETS.release(key)

    def test_v3_checkpoint_budget_cannot_outgrow_pre_read_reservation(self):
        from test_checkpoint_store_v3 import checkpoint_store_v3
        from types import SimpleNamespace
        limit = checkpoint_store_v3._max_checkpoint_bytes
        self.assertEqual(limit(SimpleNamespace(max_checkpoint_bytes=2**30)), 1024*1024)
        self.assertEqual(limit(SimpleNamespace(max_checkpoint_bytes=512)), 512)

    def test_cold_admission_counts_source_ids_and_all_plan_fields(self):
        from test_runtime import runtime_module, ContinuityRuntime, FakeAdapter, FakeLlm
        from test_hermes_adapter import PACKAGE
        import importlib
        budget_class = importlib.import_module(f"{PACKAGE}.resource_budget").WorksetBudget
        runtime = ContinuityRuntime(FakeAdapter({}), FakeLlm())
        key = ("s", "turn")
        plan = runtime_module._TurnPlan("digest", source_ids=("large-id"*1000,), workset_bytes=1)
        runtime._turns[key] = plan
        try:
            self.assertGreater(plan.serialized_bytes(), 8000)
            with patch.object(runtime_module, "COLD_PLANS", budget_class(1024)):
                runtime._release_workset(key)
            self.assertNotIn(key, runtime._turns)
        finally:
            runtime.clear()

    def test_independent_profile_imports_share_process_admission(self):
        modules = []
        for name in ("budget_profile_a", "budget_profile_b"):
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).resolve().parents[1] / "resource_budget.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            modules.append(module)
        first, second = modules
        self.assertIs(first.ACTIVE_WORKSETS, second.ACTIVE_WORKSETS)
        self.assertIs(first.PREPARATION_LOCK, second.PREPARATION_LOCK)
        key_a, key_b = object(), object()
        try:
            self.assertTrue(first.ACTIVE_WORKSETS.acquire(key_a, 32*1024*1024))
            self.assertFalse(second.ACTIVE_WORKSETS.acquire(key_b, 1))
            first.ACTIVE_WORKSETS.release(key_a)
            self.assertTrue(second.ACTIVE_WORKSETS.acquire(key_b, 1))
        finally:
            first.ACTIVE_WORKSETS.release(key_a)
            second.ACTIVE_WORKSETS.release(key_b)
            for name in ("budget_profile_a", "budget_profile_b"):
                sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
