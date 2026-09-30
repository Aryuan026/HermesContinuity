from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HOST_ROOT_TEXT = os.environ.get("HERMES_SOURCE_ROOT", "").strip()
HOST_ROOT = Path(HOST_ROOT_TEXT) if HOST_ROOT_TEXT else None
HOST_AVAILABLE = bool(
    HOST_ROOT
    and (HOST_ROOT / "hermes_state.py").is_file()
    and (HOST_ROOT / "hermes_state_history.py").is_file()
)
BASELINE_ROOT_TEXT = os.environ.get("HERMES_BASELINE_SOURCE_ROOT", "").strip()
BASELINE_ROOT = Path(BASELINE_ROOT_TEXT) if BASELINE_ROOT_TEXT else None
BASELINE_AVAILABLE = bool(BASELINE_ROOT and (BASELINE_ROOT / "hermes_state.py").is_file())
if HOST_AVAILABLE:
    sys.path.insert(0, str(HOST_ROOT))
    from hermes_state import SessionDB
else:
    SessionDB = None


PACKAGE = "hermes_continuity_history_recovery_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

hermes_adapter = importlib.import_module(f"{PACKAGE}.hermes_adapter")
runtime_module = importlib.import_module(f"{PACKAGE}.runtime")
resource_budget = importlib.import_module(f"{PACKAGE}.resource_budget")
ContinuityMetadataStore = hermes_adapter.ContinuityMetadataStore
HermesSessionAdapter = hermes_adapter.HermesSessionAdapter
ContinuityRuntime = runtime_module.ContinuityRuntime


REFERENCE_AT = "2026-08-30T00:00:00+00:00"
BASE_TIMESTAMP = 1_787_961_600


def _append_turn(db, session_id: str, number: int) -> None:
    db.append_messages_batch(
        session_id,
        [
            {
                "role": "user",
                "content": f"user-{number}",
                "timestamp": BASE_TIMESTAMP + number * 2,
            },
            {
                "role": "assistant",
                "content": f"assistant-{number}",
                "timestamp": BASE_TIMESTAMP + number * 2 + 1,
            },
        ],
    )


def _prepare_index(index, session_id: str, first: dict | None = None) -> dict:
    result = first
    for _ in range(2_000):
        if result is None:
            result = index.prepare_step(session_id)
        if result["status"] == "ready":
            return result
        if result["status"] != "progress":
            raise AssertionError(result)
        result = None
    raise AssertionError("history preparation did not finish")


def _request() -> dict:
    return {
        "model": "test-model",
        "max_tokens": 128,
        "messages": [
            {"role": "system", "content": "fixed"},
            {"role": "user", "content": "current"},
        ],
    }


class _NoopLlm:
    async def acomplete(self, _messages, **_kwargs):
        raise AssertionError("resource admission must not invoke the model")


async def _empty_compiler(bundle: dict, **_kwargs) -> dict:
    return {
        "status": "ready",
        "reason": "",
        "checkpoint_candidate": None,
        "expected_revision": 0,
        "expected_pre_turn_source_snapshot": bundle["source"]["source_snapshot"],
    }


_PARTIAL_PREPARE_CHILD = r"""
import json
from pathlib import Path
import sys
from hermes_state import SessionDB

path = Path(sys.argv[1])
db = SessionDB(db_path=path)
db.create_session("session-1", source="cli")

def append_turn(number):
    db.append_messages_batch("session-1", [
        {"role": "user", "content": f"user-{number}", "timestamp": 1787961600 + number*2},
        {"role": "assistant", "content": f"assistant-{number}", "timestamp": 1787961601 + number*2},
    ])

append_turn(0)
epoch = None
while True:
    ready = db.prepare_history_step(
        "session-1", owner_id="child-owner", activation_epoch=epoch,
        max_pages=2, max_rows_per_page=2, deadline_ms=1000)
    epoch = ready.get("activation_epoch") or epoch
    if ready["status"] == "ready":
        break
    assert ready["status"] == "progress", ready

for number in range(1, 13):
    append_turn(number)
partial = db.prepare_history_step(
    "session-1", owner_id="child-owner", activation_epoch=epoch,
    max_pages=1, max_rows_per_page=2, deadline_ms=1000)
assert partial["status"] == "progress", partial
print(json.dumps({
    "ready_token": ready["head_token"],
    "activation_epoch": epoch,
    "partial_status": partial["status"],
    "message_count": len(db.get_messages("session-1")),
}, sort_keys=True))
db.close()
"""


_LEGACY_WRITER_CHILD = r"""
import inspect
import json
from pathlib import Path
import sys
from hermes_state import SessionDB

path = Path(sys.argv[1])
db = SessionDB(db_path=path)
db.append_messages_batch("session-1", [
    {"role": "user", "content": "legacy-user", "timestamp": 1787961700},
    {"role": "assistant", "content": "legacy-assistant", "timestamp": 1787961701},
])
print(json.dumps({
    "session_db_source": inspect.getsourcefile(SessionDB),
    "message_count": len(db.get_messages("session-1")),
}, sort_keys=True))
db.close()
"""


_CRASH_RECOVERY_CHILD = r"""
import importlib
import os
from pathlib import Path
import sys
import types

from hermes_state import SessionDB

scenario = sys.argv[1]
state_path = Path(sys.argv[2])
metadata_path = Path(sys.argv[3])
plugin_root = Path(sys.argv[4])

if scenario == "host_page":
    db = SessionDB(db_path=state_path)
    original = db._history_index_row
    indexed = 0

    def crash_mid_page(*args, **kwargs):
        global indexed
        result = original(*args, **kwargs)
        indexed += 1
        if indexed == 2:
            os._exit(73)
        return result

    db._history_index_row = crash_mid_page
    db.prepare_history_step(
        "session-1",
        owner_id="crash-host-page",
        max_pages=1,
        max_rows_per_page=4,
        deadline_ms=1_000,
    )
    raise AssertionError("host page crash boundary was not reached")

package_name = "hermes_continuity_crash_child"
package = types.ModuleType(package_name)
package.__path__ = [str(plugin_root)]
sys.modules[package_name] = package
hermes_adapter = importlib.import_module(f"{package_name}.hermes_adapter")

reader = SessionDB(db_path=state_path, read_only=True)
store = hermes_adapter.ContinuityMetadataStore(metadata_path)

# Exercise a genuinely multi-quantum host, rather than relying on CI speed.
# The production deadline is unchanged; only this fixture's row/page ceilings
# are reduced through the existing host API.
prepare = reader.prepare_history_step
def one_row_quantum(*args, **kwargs):
    kwargs.update(max_pages=1, max_rows_per_page=1)
    return prepare(*args, **kwargs)
reader.prepare_history_step = one_row_quantum

if scenario == "plugin_transaction":
    connect = store._connect

    def crash_connect():
        connection = connect()

        def trace(statement):
            normalized = " ".join(statement.split()).upper()
            if normalized.startswith(
                "UPDATE CONTINUITY_GROUP_PROGRESS SET POSITION="
            ):
                # Group occurrence and index INSERTs have executed in this
                # transaction, but neither they nor the ready marker committed.
                os._exit(75)

        connection.set_trace_callback(trace)
        return connection

    store._connect = crash_connect

adapter = hermes_adapter.HermesSessionAdapter(reader, store)
if scenario == "host_ready_group_absent":
    def crash_before_group_page(*_args, **_kwargs):
        # Host journal/index preparation already committed.  The plugin has not
        # read or published a group page yet.
        os._exit(74)

    adapter.history_index._page = crash_before_group_page

for quantum in range(2_000):
    result = adapter.history_index.prepare_step("session-1")
    if result.get("status") != "progress":
        raise AssertionError({"boundary_not_reached": scenario, "quantum": quantum,
                              "status": result.get("status"), "reason": result.get("reason")})
raise AssertionError("plugin crash boundary was not reached within bounded quanta")
"""


@unittest.skipUnless(
    HOST_AVAILABLE
    and SessionDB is not None
    and hasattr(SessionDB, "prepare_history_step")
    and hasattr(SessionDB, "invalidate_history_for_rollback"),
    "requires HERMES_SOURCE_ROOT with the Block 3 history host seam",
)
class HistoryRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.adapters: list[tuple[object, object]] = []

    def tearDown(self) -> None:
        for adapter, reader in reversed(self.adapters):
            adapter.close()
            reader.close()
        self.temp.cleanup()

    def _adapter(self, profile: str, session_id: str = "session-1"):
        profile_root = self.root / profile
        profile_root.mkdir(parents=True, exist_ok=True)
        state_path = profile_root / "state.db"
        reader = SessionDB(db_path=state_path, read_only=True)
        store = ContinuityMetadataStore(profile_root / "continuity.sqlite3")
        adapter = HermesSessionAdapter(reader, store)
        self.adapters.append((adapter, reader))
        self.assertIsNotNone(adapter.history_index)
        return adapter, reader, store

    def _seed_crash_profile(self, profile: str) -> tuple[Path, Path]:
        profile_root = self.root / profile
        profile_root.mkdir()
        state_path = profile_root / "state.db"
        with SessionDB(db_path=state_path) as writer:
            writer.create_session("session-1", source="cli")
            for number in range(3):
                _append_turn(writer, "session-1", number)
        return state_path, profile_root / "continuity.sqlite3"

    def _run_crash_child(
        self,
        scenario: str,
        state_path: Path,
        metadata_path: Path,
        expected_returncode: int,
    ) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in (str(HOST_ROOT), environment.get("PYTHONPATH", ""))
            if value
        )
        environment["HERMES_HOME"] = str(state_path.parent / "crash-child-home")
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                _CRASH_RECOVERY_CHILD,
                scenario,
                str(state_path),
                str(metadata_path),
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(
            child.returncode,
            expected_returncode,
            child.stderr + child.stdout,
        )

    def _expire_crashed_owner(self, state_path: Path) -> None:
        with sqlite3.connect(state_path) as connection:
            connection.execute(
                "UPDATE hermes_history_state SET lease_expires_at=0 WHERE singleton=1"
            )

    def _assert_crash_recovery(self, profile: str) -> None:
        adapter, _reader, _store = self._adapter(profile)
        ready = _prepare_index(adapter.history_index, "session-1")
        self.assertEqual(ready["status"], "ready")
        source = adapter.read_source("session-1", reference_at=REFERENCE_AT)
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["source_proof"]["group_count"], 3)
        group_ids = [group["source_prefix_id"] for group in source["groups"]]
        self.assertEqual(len(group_ids), len(set(group_ids)))
        self.assertEqual(
            [message["content"] for group in source["groups"] for message in group["messages"]],
            [
                "user-0",
                "assistant-0",
                "user-1",
                "assistant-1",
                "user-2",
                "assistant-2",
            ],
        )

    def test_abrupt_exit_mid_host_page_rolls_back_partial_index_and_recovers(self):
        profile = "crash-host-page"
        state_path, metadata_path = self._seed_crash_profile(profile)
        self._run_crash_child("host_page", state_path, metadata_path, 73)

        with sqlite3.connect(state_path) as connection:
            durable_buckets = connection.execute(
                "SELECT COUNT(*) FROM hermes_history_buckets WHERE domain_id='session-1'"
            ).fetchone()[0]
        self.assertEqual(durable_buckets, 0)

        self._expire_crashed_owner(state_path)
        self._assert_crash_recovery(profile)

    def test_abrupt_exit_after_host_commit_before_group_page_recovers_once(self):
        profile = "crash-host-ready"
        state_path, metadata_path = self._seed_crash_profile(profile)
        self._run_crash_child(
            "host_ready_group_absent", state_path, metadata_path, 74
        )

        with sqlite3.connect(state_path) as connection:
            host_domain = connection.execute(
                "SELECT phase,canonical_count,indexed_change_seq "
                "FROM hermes_history_domains WHERE domain_id='session-1'"
            ).fetchone()
        self.assertEqual(tuple(host_domain[:2]), ("ready", 6))
        self.assertGreater(host_domain[2], 0)
        with sqlite3.connect(metadata_path) as connection:
            progress = connection.execute(
                "SELECT position,group_count,ready FROM continuity_group_progress "
                "WHERE session_id='session-1'"
            ).fetchone()
            groups = connection.execute(
                "SELECT COUNT(*) FROM continuity_group_index"
            ).fetchone()[0]
        self.assertEqual(tuple(progress), (0, 0, 0))
        self.assertEqual(groups, 0)

        self._expire_crashed_owner(state_path)
        self._assert_crash_recovery(profile)

    def test_abrupt_exit_with_uncommitted_group_staging_rolls_back_and_recovers(self):
        profile = "crash-plugin-transaction"
        state_path, metadata_path = self._seed_crash_profile(profile)
        self._run_crash_child("plugin_transaction", state_path, metadata_path, 75)

        with sqlite3.connect(metadata_path) as connection:
            progress = connection.execute(
                "SELECT position,group_count,ready FROM continuity_group_progress "
                "WHERE session_id='session-1'"
            ).fetchone()
            group_rows = connection.execute(
                "SELECT COUNT(*) FROM continuity_group_index"
            ).fetchone()[0]
            occurrence_rows = connection.execute(
                "SELECT COUNT(*) FROM continuity_group_occurrences"
            ).fetchone()[0]
        self.assertEqual(tuple(progress), (0, 0, 0))
        self.assertEqual(group_rows, 0)
        self.assertEqual(occurrence_rows, 0)

        self._expire_crashed_owner(state_path)
        self._assert_crash_recovery(profile)

    def test_real_process_partial_prepare_expires_lease_and_rebuilds_new_epoch(self):
        profile = self.root / "process-recovery"
        profile.mkdir()
        state_path = profile / "state.db"
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in (str(HOST_ROOT), environment.get("PYTHONPATH", ""))
            if value
        )
        environment["HERMES_HOME"] = str(profile / "child-home")
        child = subprocess.run(
            [sys.executable, "-c", _PARTIAL_PREPARE_CHILD, str(state_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)
        child_state = json.loads(
            next(line for line in reversed(child.stdout.splitlines()) if line.strip())
        )
        self.assertEqual(child_state["partial_status"], "progress")
        self.assertEqual(child_state["message_count"], 26)

        # The subprocess really ended; only lease expiry is test-controlled.
        with sqlite3.connect(state_path) as connection:
            connection.execute(
                "UPDATE hermes_history_state SET lease_expires_at=0 WHERE singleton=1"
            )

        adapter, reader, _store = self._adapter("process-recovery")
        first = adapter.history_index.prepare_step("session-1")
        self.assertIn(first["status"], {"progress", "ready"}, first)
        self.assertNotEqual(
            adapter.history_index.activation_epoch, child_state["activation_epoch"]
        )
        self.assertEqual(
            reader.validate_history_prefix(child_state["ready_token"])["status"],
            "incompatible",
        )

        ready = _prepare_index(adapter.history_index, "session-1", first)
        self.assertEqual(ready["status"], "ready")
        source = adapter.read_source("session-1", reference_at=REFERENCE_AT)
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["source_proof"]["group_count"], 13)
        self.assertEqual(source["groups"][0]["messages"][0]["content"], "user-0")
        self.assertEqual(source["groups"][-1]["messages"][1]["content"], "assistant-12")

    @unittest.skipUnless(
        BASELINE_AVAILABLE,
        "requires HERMES_BASELINE_SOURCE_ROOT with the accepted old SessionDB",
    )
    def test_rollback_actual_legacy_writer_rebuilds_and_preserves_rows(self):
        profile = self.root / "rollback-recovery"
        profile.mkdir()
        state_path = profile / "state.db"
        with SessionDB(db_path=state_path) as writer:
            writer.create_session("session-1", source="cli")
            _append_turn(writer, "session-1", 0)
            _append_turn(writer, "session-1", 1)

        adapter, reader, _store = self._adapter("rollback-recovery")
        _prepare_index(adapter.history_index, "session-1")
        original_source = adapter.read_source(
            "session-1", reference_at=REFERENCE_AT
        )
        self.assertEqual(original_source["status"], "ready", original_source)
        original_token = copy.deepcopy(
            original_source["source_proof"]["host_token"]
        )
        original_epoch = original_token["activation_epoch"]

        with SessionDB(db_path=state_path) as trusted_writer:
            invalidated = trusted_writer.invalidate_history_for_rollback()
        self.assertEqual(invalidated["status"], "invalidated")
        adapter.close()
        reader.close()

        with sqlite3.connect(state_path) as connection:
            tail_before = connection.execute(
                "SELECT journal_tail FROM hermes_history_state WHERE singleton=1"
            ).fetchone()[0]

        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(
            value
            for value in (
                str(BASELINE_ROOT),
                str(HOST_ROOT),
                environment.get("PYTHONPATH", ""),
            )
            if value
        )
        environment["HERMES_HOME"] = str(profile / "legacy-home")
        legacy = subprocess.run(
            [sys.executable, "-c", _LEGACY_WRITER_CHILD, str(state_path)],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
        self.assertEqual(legacy.returncode, 0, legacy.stderr + legacy.stdout)
        legacy_state = json.loads(
            next(line for line in reversed(legacy.stdout.splitlines()) if line.strip())
        )
        self.assertEqual(
            Path(legacy_state["session_db_source"]).resolve(),
            (BASELINE_ROOT / "hermes_state.py").resolve(),
        )
        self.assertEqual(legacy_state["message_count"], 6)
        with sqlite3.connect(state_path) as connection:
            state = connection.execute(
                "SELECT capture_enabled,journal_tail FROM hermes_history_state "
                "WHERE singleton=1"
            ).fetchone()
        self.assertEqual(tuple(state), (0, tail_before))

        recovered_adapter, recovered_reader, _ = self._adapter(
            "rollback-recovery"
        )
        recovered = _prepare_index(recovered_adapter.history_index, "session-1")
        self.assertEqual(recovered["status"], "ready")
        recovered_epoch = recovered_adapter.history_index.activation_epoch
        self.assertNotEqual(recovered_epoch, original_epoch)
        self.assertNotEqual(
            recovered_epoch, invalidated["activation_epoch"]
        )
        self.assertEqual(
            recovered_reader.validate_history_prefix(original_token)["status"],
            "incompatible",
        )
        source = recovered_adapter.read_source(
            "session-1", reference_at=REFERENCE_AT
        )
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(source["source_proof"]["group_count"], 3)
        self.assertEqual(
            [message["content"] for message in source["groups"][-1]["messages"]],
            ["legacy-user", "legacy-assistant"],
        )

    def test_continuous_append_during_bootstrap_reaches_finite_ready_target(self):
        profile = self.root / "ongoing-bootstrap"
        profile.mkdir()
        state_path = profile / "state.db"
        seed_turns = 10
        writer = SessionDB(db_path=state_path)
        try:
            writer.create_session("session-1", source="cli")
            for number in range(seed_turns):
                _append_turn(writer, "session-1", number)
            adapter, reader, _store = self._adapter("ongoing-bootstrap")
            epoch = None
            ready = None
            appended = 0
            for attempt in range(100):
                result = reader.prepare_history_step(
                    "session-1",
                    owner_id="ongoing-bootstrap-owner",
                    activation_epoch=epoch,
                    max_pages=1,
                    max_rows_per_page=4,
                    deadline_ms=100,
                )
                epoch = result.get("activation_epoch") or epoch
                role = "user" if appended % 2 == 0 else "assistant"
                writer.append_message(
                    "session-1",
                    role,
                    f"bootstrap-tail-{attempt}",
                    timestamp=BASE_TIMESTAMP + 1_000 + appended,
                )
                appended += 1
                if result["status"] == "ready":
                    ready = result
                    break
                self.assertEqual(result["status"], "progress", result)
            self.assertIsNotNone(ready)
            self.assertGreater(appended, 0)
            # Finish a final user row only after proving the finite old target
            # became ready while a new physical row was added after every step.
            if appended % 2:
                writer.append_message(
                    "session-1",
                    "assistant",
                    "bootstrap-tail-final",
                    timestamp=BASE_TIMESTAMP + 1_000 + appended,
                )
                appended += 1
        finally:
            writer.close()

        latest = _prepare_index(adapter.history_index, "session-1")
        self.assertEqual(latest["status"], "ready")
        source = adapter.read_source("session-1", reference_at=REFERENCE_AT)
        self.assertEqual(source["status"], "ready", source)
        self.assertEqual(
            source["source_proof"]["group_count"], seed_turns + appended // 2
        )

    def test_two_profile_adapters_share_active_budget_and_release_recovers(self):
        profile_budget_modules = []
        for name in ("history_recovery_profile_a", "history_recovery_profile_b"):
            spec = importlib.util.spec_from_file_location(
                name, ROOT / "resource_budget.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            profile_budget_modules.append(module)
        self.assertIs(
            profile_budget_modules[0].ACTIVE_WORKSETS,
            profile_budget_modules[1].ACTIVE_WORKSETS,
        )
        self.assertIs(
            profile_budget_modules[0].ACTIVE_WORKSETS,
            resource_budget.ACTIVE_WORKSETS,
        )
        adapters = []
        for profile in ("profile-a", "profile-b"):
            profile_root = self.root / profile
            profile_root.mkdir()
            with SessionDB(db_path=profile_root / "state.db") as writer:
                writer.create_session("session-1", source="cli")
                _append_turn(writer, "session-1", 0)
            adapter, _reader, _store = self._adapter(profile)
            _prepare_index(adapter.history_index, "session-1")
            adapters.append(adapter)

        runtime_a = ContinuityRuntime(
            adapters[0], _NoopLlm(), compiler=_empty_compiler,
            clock=lambda: REFERENCE_AT,
        )
        runtime_b = ContinuityRuntime(
            adapters[1], _NoopLlm(), compiler=_empty_compiler,
            clock=lambda: REFERENCE_AT,
        )
        turn_a = ("session-1", "held-by-profile-a")
        budget = resource_budget.ACTIVE_WORKSETS
        runtime_a._turns[turn_a] = runtime_module._TurnPlan(
            "", workset_bytes=budget.limit
        )
        self.assertTrue(
            budget.acquire(runtime_a._budget_key(turn_a), budget.limit)
        )
        arguments = {
            "request": _request(),
            "session_id": "session-1",
            "turn_id": "profile-b-turn",
            "model": "test-model",
            "provider": "test-provider",
            "base_url": "",
            "context_window_tokens": 16_000,
            "context_window_source": "config",
            "context_window_confidence": "authoritative",
        }
        try:
            with patch.object(
                adapters[1], "read_bundle", wraps=adapters[1].read_bundle
            ) as read_bundle:
                refused = runtime_b._plan_for_request(**arguments)
                self.assertEqual(refused.reason, "workset_capacity_exceeded")
                read_bundle.assert_not_called()

                runtime_a.clear()
                recovered = runtime_b._plan_for_request(**arguments)
                self.assertEqual(recovered.reason, "")
                self.assertEqual(read_bundle.call_count, 1)
        finally:
            runtime_a.clear()
            runtime_b.clear()
            for name in (
                "history_recovery_profile_a",
                "history_recovery_profile_b",
            ):
                sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
