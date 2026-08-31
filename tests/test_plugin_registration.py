from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_registration_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

ENTRY_NAME = f"{PACKAGE}.entry"
entry_spec = importlib.util.spec_from_file_location(ENTRY_NAME, ROOT / "__init__.py")
assert entry_spec is not None and entry_spec.loader is not None
plugin = importlib.util.module_from_spec(entry_spec)
sys.modules[ENTRY_NAME] = plugin
entry_spec.loader.exec_module(plugin)


@dataclass
class CompatibleResult:
    text: str
    finish_reason: str | None = None


@dataclass
class IncompatibleResult:
    text: str


class FakeLlm:
    async def acomplete(self, messages, **kwargs):
        return CompatibleResult("ok", "stop")


class FakeSessionDB:
    instances: list["FakeSessionDB"] = []

    def __init__(self, db_path=None, read_only=False):
        self.db_path = db_path
        self.read_only = read_only
        self.closed = False
        self.instances.append(self)

    def close(self):
        self.closed = True

    def get_messages_time_window(self, session_id, **kwargs):
        return {
            "messages": [],
            "scan_complete": True,
            "overflow": False,
            "physical_row_count": 0,
            "max_physical_rows": kwargs["max_physical_rows"],
        }


class FakeContext:
    def __init__(self, data_dir: Path):
        self.llm = FakeLlm()
        self.state = types.SimpleNamespace(data_dir=data_dir)
        self.middleware: list[tuple[str, object]] = []
        self.hooks: list[tuple[str, object]] = []
        self.services: list[tuple[str, object]] = []
        self.commands: list[tuple[str, object, str, str]] = []
        self.unload: list[object] = []
        self.config: dict[str, object] = {}
        self.config_reads: list[str] = []

    def get_config(self, key, default=None):
        self.config_reads.append(key)
        return self.config.get(key, default)

    def register_middleware(self, name, callback):
        self.middleware.append((name, callback))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_service(self, name, service):
        self.services.append((name, service))

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands.append((name, handler, description, args_hint))

    def on_unload(self, callback):
        self.unload.append(callback)


class PluginRegistrationTests(unittest.TestCase):
    def setUp(self):
        FakeSessionDB.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.profile_home = Path(self.temp.name) / "profile"
        self.plugin_data_dir = (
            self.profile_home / "plugin-data" / "hermes-continuity"
        )
        self.ctx = FakeContext(self.plugin_data_dir)

    def tearDown(self):
        self.temp.cleanup()

    def _modules(self, result_type, *, session_db_type=FakeSessionDB):
        agent = types.ModuleType("agent")
        plugin_llm = types.ModuleType("agent.plugin_llm")
        plugin_llm.PluginLlmCompleteResult = result_type
        hermes_state = types.ModuleType("hermes_state")
        hermes_state.SessionDB = session_db_type
        hermes_cli = types.ModuleType("hermes_cli")
        middleware = types.ModuleType("hermes_cli.middleware")
        middleware.MIDDLEWARE_SCHEMA_VERSION = "hermes.middleware.v2"
        middleware.TRANSPORT_SCHEMA_VERSION = "hermes.transport.v3"
        request_overlay = types.ModuleType("hermes_cli.request_overlay")
        request_overlay.REQUEST_OVERLAY_SCHEMA_VERSION = (
            "hermes.request_overlay.v2"
        )
        return {
            "agent": agent,
            "agent.plugin_llm": plugin_llm,
            "hermes_state": hermes_state,
            "hermes_cli": hermes_cli,
            "hermes_cli.middleware": middleware,
            "hermes_cli.request_overlay": request_overlay,
        }

    def test_registers_only_request_execution_and_settlement_boundaries(self):
        self.ctx.config["additional_human_sources"] = ["custom_frontend"]
        with patch.dict(sys.modules, self._modules(CompatibleResult)):
            plugin.register(self.ctx)

        self.assertEqual(
            [name for name, _callback in self.ctx.middleware],
            ["llm_request", "llm_execution"],
        )
        self.assertEqual(
            [name for name, _callback in self.ctx.hooks],
            ["post_api_request", "api_request_error"],
        )
        self.assertEqual(
            [name for name, _service in self.ctx.services],
            ["canonical-source.v2"],
        )
        self.assertEqual(
            [name for name, _handler, _description, _args in self.ctx.commands],
            ["continuity-status"],
        )
        self.assertIsInstance(
            self.ctx.services[0][1], plugin.ContinuityCanonicalSourceService
        )
        self.assertTrue(callable(self.ctx.services[0][1].read_window))
        self.assertIn(
            "custom_frontend", self.ctx.services[0][1].human_session_sources
        )
        self.assertEqual(len(FakeSessionDB.instances), 1)
        self.assertTrue(FakeSessionDB.instances[0].read_only)
        self.assertEqual(
            FakeSessionDB.instances[0].db_path,
            self.profile_home / "state.db",
        )
        self.assertTrue(
            (self.plugin_data_dir / "continuity.sqlite3").exists()
        )

        for callback in reversed(self.ctx.unload):
            callback()
        self.assertTrue(FakeSessionDB.instances[0].closed)

    def test_missing_finish_reason_seam_fails_visibly_before_db_open(self):
        with patch.dict(sys.modules, self._modules(IncompatibleResult)):
            with self.assertRaisesRegex(RuntimeError, "finish_reason"):
                plugin.register(self.ctx)

        self.assertEqual(FakeSessionDB.instances, [])
        self.assertEqual(self.ctx.middleware, [])
        self.assertEqual(self.ctx.hooks, [])
        self.assertEqual(self.ctx.services, [])

    def test_invalid_additional_human_sources_fail_before_db_open(self):
        self.ctx.config["additional_human_sources"] = "custom_frontend"
        with patch.dict(sys.modules, self._modules(CompatibleResult)):
            with self.assertRaisesRegex(RuntimeError, "must be a list"):
                plugin.register(self.ctx)

        self.assertEqual(FakeSessionDB.instances, [])

    def test_missing_service_registry_fails_before_db_open(self):
        self.ctx.register_service = None
        with patch.dict(sys.modules, self._modules(CompatibleResult)):
            with self.assertRaisesRegex(RuntimeError, "register_service"):
                plugin.register(self.ctx)

        self.assertEqual(FakeSessionDB.instances, [])

    def test_legacy_database_path_settings_cannot_escape_profile_realm(self):
        outside_state = Path(self.temp.name) / "outside-state.db"
        outside_metadata = Path(self.temp.name) / "outside-metadata.db"
        self.ctx.config.update(
            state_db=str(outside_state),
            metadata_db=str(outside_metadata),
        )
        with patch.dict(sys.modules, self._modules(CompatibleResult)):
            plugin.register(self.ctx)

        self.assertEqual(len(FakeSessionDB.instances), 1)
        self.assertEqual(
            FakeSessionDB.instances[0].db_path,
            self.profile_home / "state.db",
        )
        self.assertNotIn("state_db", self.ctx.config_reads)
        self.assertNotIn("metadata_db", self.ctx.config_reads)
        self.assertFalse(outside_state.exists())
        self.assertFalse(outside_metadata.exists())
        self.assertTrue(
            (self.plugin_data_dir / "continuity.sqlite3").exists()
        )

    def test_missing_bounded_window_seam_closes_db_before_registration(self):
        class IncompatibleSessionDB(FakeSessionDB):
            get_messages_time_window = None

        with patch.dict(
            sys.modules,
            self._modules(
                CompatibleResult,
                session_db_type=IncompatibleSessionDB,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "get_messages_time_window"):
                plugin.register(self.ctx)

        self.assertEqual(len(FakeSessionDB.instances), 1)
        self.assertTrue(FakeSessionDB.instances[0].closed)
        self.assertEqual(self.ctx.middleware, [])
        self.assertEqual(self.ctx.hooks, [])
        self.assertEqual(self.ctx.services, [])

    def test_middleware_v1_fails_before_db_open(self):
        modules = self._modules(CompatibleResult)
        modules["hermes_cli.middleware"].MIDDLEWARE_SCHEMA_VERSION = (
            "hermes.middleware.v1"
        )
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "hermes.middleware.v2"):
                plugin.register(self.ctx)

        self.assertEqual(FakeSessionDB.instances, [])

    def test_transport_v0_fails_before_db_open(self):
        modules = self._modules(CompatibleResult)
        modules["hermes_cli.middleware"].TRANSPORT_SCHEMA_VERSION = (
            "hermes.transport.v0"
        )
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "hermes.transport.v3"):
                plugin.register(self.ctx)

        self.assertEqual(FakeSessionDB.instances, [])

    def test_request_overlay_v1_fails_before_db_open(self):
        modules = self._modules(CompatibleResult)
        modules["hermes_cli.request_overlay"].REQUEST_OVERLAY_SCHEMA_VERSION = (
            "hermes.request_overlay.v1"
        )
        with patch.dict(sys.modules, modules):
            with self.assertRaisesRegex(RuntimeError, "hermes.request_overlay.v2"):
                plugin.register(self.ctx)

        self.assertEqual(FakeSessionDB.instances, [])


class HermesPluginManagerIntegrationTests(unittest.TestCase):
    def _source_root(self) -> str:
        source_root = os.environ.get("HERMES_SOURCE_ROOT", "").strip()
        if not source_root:
            self.skipTest("set HERMES_SOURCE_ROOT to run against a Hermes checkout")
        return source_root

    @staticmethod
    def _load_plugin_in_profile(manager, manifest, home):
        from hermes_constants import (
            reset_hermes_home_override,
            set_hermes_home_override,
        )

        token = set_hermes_home_override(home)
        try:
            manager._load_plugin(manifest)
        finally:
            reset_hermes_home_override(token)

    def test_real_ledger_withdraws_service_before_sessiondb_close(self):
        source_root = self._source_root()
        sys.path.insert(0, source_root)
        try:
            import hermes_state
            from hermes_cli.plugins import PluginManager, PluginManifest

            real_session_db = hermes_state.SessionDB
            opened = []

            class TrackingSessionDB(real_session_db):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    opened.append(self)

            with tempfile.TemporaryDirectory() as temp_dir:
                state_db = real_session_db(Path(temp_dir) / "state.db")
                state_db.close()
                manager = PluginManager(scope_key=temp_dir)
                manifest = PluginManifest(
                    name="hermes-continuity",
                    key="hermes-continuity",
                    source="user",
                    path=str(ROOT),
                )
                with patch.object(hermes_state, "SessionDB", TrackingSessionDB):
                    self._load_plugin_in_profile(manager, manifest, temp_dir)

                qualified = "hermes-continuity:canonical-source.v2"
                service = manager._get_plugin_service(qualified)
                self.assertIsNotNone(service)
                self.assertEqual(len(opened), 1)
                registrations = manager._ownership_ledger["hermes-continuity"]
                self.assertEqual(registrations[-1].kind, "service")
                close_registration = next(
                    item
                    for item in registrations
                    if item.kind == "on_unload" and item.key == "close"
                )
                original_close = close_registration.release
                visible_at_close = []

                def observed_close():
                    visible_at_close.append(
                        manager._get_plugin_service(qualified) is not None
                    )
                    original_close()

                close_registration.release = observed_close
                self.assertTrue(manager.unload("hermes-continuity"))

                self.assertEqual(visible_at_close, [False])
                self.assertIsNone(manager._get_plugin_service(qualified))
                self.assertIsNone(opened[0]._conn)
                self.assertNotIn("hermes-continuity", manager._ownership_ledger)
        finally:
            sys.path.remove(source_root)

    def test_real_duplicate_service_failure_sweeps_every_owned_registration(self):
        source_root = self._source_root()
        sys.path.insert(0, source_root)
        try:
            import hermes_state
            from hermes_cli.plugins import PluginManager, PluginManifest

            real_session_db = hermes_state.SessionDB
            opened = []

            class TrackingSessionDB(real_session_db):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    opened.append(self)

            with tempfile.TemporaryDirectory() as temp_dir:
                state_db = real_session_db(Path(temp_dir) / "state.db")
                state_db.close()
                manager = PluginManager(scope_key=temp_dir)
                manifest = PluginManifest(
                    name="hermes-continuity",
                    key="hermes-continuity",
                    source="user",
                    path=str(ROOT),
                )
                with patch.object(hermes_state, "SessionDB", TrackingSessionDB):
                    self._load_plugin_in_profile(manager, manifest, temp_dir)
                    self._load_plugin_in_profile(manager, manifest, temp_dir)

                qualified = "hermes-continuity:canonical-source.v2"
                self.assertEqual(len(opened), 2)
                self.assertTrue(all(item._conn is None for item in opened))
                self.assertIsNone(manager._get_plugin_service(qualified))
                self.assertNotIn("hermes-continuity", manager._ownership_ledger)
                self.assertFalse(manager._middleware)
                self.assertFalse(manager._hooks)
                self.assertFalse(
                    manager._plugins["hermes-continuity"].enabled
                )
        finally:
            sys.path.remove(source_root)

    def test_real_managers_keep_canonical_and_metadata_realms_profile_local(self):
        source_root = self._source_root()
        sys.path.insert(0, source_root)
        try:
            from hermes_cli.plugins import PluginManager, PluginManifest
            from hermes_state import SessionDB

            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                homes = [root / "profile-a", root / "profile-b"]
                managers = []
                services = []
                manifest = PluginManifest(
                    name="hermes-continuity",
                    key="hermes-continuity",
                    source="user",
                    path=str(ROOT),
                )
                try:
                    for home in homes:
                        state_db = SessionDB(home / "state.db")
                        state_db.close()
                        manager = PluginManager(scope_key=str(home))
                        self._load_plugin_in_profile(manager, manifest, home)
                        managers.append(manager)
                        services.append(
                            manager._get_plugin_service(
                                "hermes-continuity:canonical-source.v2"
                            )
                        )

                    self.assertIsNot(services[0], services[1])
                    for home, service in zip(homes, services, strict=True):
                        self.assertIsNotNone(service)
                        self.assertEqual(
                            service.session_db.db_path,
                            home / "state.db",
                        )
                        metadata_path = service.adapter.metadata_store.path
                        self.assertEqual(metadata_path.name, "continuity.sqlite3")
                        self.assertEqual(
                            metadata_path.parent.parent,
                            home / "plugin-data",
                        )

                    services[0].adapter.metadata_store.record_receipt(
                        receipt_id="receipt_a",
                        session_id="session_a",
                        kind="delivery",
                        status="delivered",
                    )
                    self.assertEqual(
                        services[0].adapter.metadata_store.status_summary()[
                            "receipt_count"
                        ],
                        1,
                    )
                    self.assertEqual(
                        services[1].adapter.metadata_store.status_summary()[
                            "receipt_count"
                        ],
                        0,
                    )
                finally:
                    for manager in managers:
                        manager.unload("hermes-continuity")
        finally:
            sys.path.remove(source_root)


if __name__ == "__main__":
    unittest.main()
