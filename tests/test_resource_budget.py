import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


class ResourceBudgetTests(unittest.TestCase):
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
