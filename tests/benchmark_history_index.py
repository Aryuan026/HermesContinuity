"""Disposable indexed-history scale check, with an external process deadline.

Setup and measurement use separate processes. Preparation and foreground are
timed separately within measurement; their RSS is the process high-water mark.
Provider/transport are synthetic; no owner database or network provider is used.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_hermes_adapter import ContinuityMetadataStore, HermesSessionAdapter
from test_runtime import ContinuityRuntime, FakeLlm, execute, post, project, request
from hermes_state import SessionDB

CASES = {"history_1x": (24, 0), "history_10x": (240, 0),
         "history_100x": (2400, 0), "clones_2000": (24, 2000),
         "clones_20000": (24, 20000),
         "streamed_image_16m": (24, 0), "streamed_image_64m": (24, 0)}


def peak_kib():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value // 1024 if sys.platform == "darwin" else value


def setup(root, case):
    pairs, clones = CASES[case]
    db = SessionDB(db_path=root / "state.db")
    db.create_session("s1", source="cli")
    db.close()
    with closing(sqlite3.connect(root / "state.db")) as connection:
        for start in range(0, pairs, 100):
            connection.executemany(
                "INSERT INTO messages(session_id,role,content,timestamp,active,compacted) "
                "VALUES ('s1',?,?,?,?,1)",
                [(role, f"{role} {number}",
                  (1787961600 if number >= pairs-24 else 1780000000) + number*2+offset, 0)
                 for number in range(start, min(start+100, pairs))
                 for offset, role in enumerate(("user", "assistant"))])
        columns = [row[1] for row in connection.execute("PRAGMA table_info(messages)") if row[1] != "id"]
        names = ",".join('"'+column+'"' for column in columns)
        for _ in range(clones//2):
            connection.execute(f"INSERT INTO messages ({names}) SELECT {names} FROM messages WHERE id<=2")
        if case.startswith("streamed_image_"):
            size = (16 if case.endswith("16m") else 64)*1024*1024
            content = "\x00json:" + json.dumps([
                {"type": "text", "text": "Recorded diagram meaning: approved design"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A"*size}},
            ])
            connection.execute("UPDATE messages SET content=? WHERE id=?", (content, pairs*2-1))
        connection.commit()


def measure(root, case):
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    db = SessionDB(db_path=root / "state.db", read_only=True)
    store = ContinuityMetadataStore(root / "metadata.db")
    adapter = HermesSessionAdapter(db, store)
    llm = FakeLlm()
    initial_peak = peak_kib()
    phases = {}
    vm_steps = 0

    def count_sql():
        nonlocal vm_steps
        vm_steps += 100
        return 0

    original_read = db._read_ctx
    original_connect = store._connect

    @contextmanager
    def counted_read():
        with original_read() as connection:
            connection.set_progress_handler(count_sql, 100)
            try:
                yield connection
            finally:
                connection.set_progress_handler(None, 0)

    def counted_connect():
        connection = original_connect()
        connection.set_progress_handler(count_sql, 100)
        return connection

    db._read_ctx = counted_read
    store._connect = counted_connect
    start = time.perf_counter()
    steps = 0
    quantum_max = 0
    try:
        while True:
            quantum_start = time.perf_counter()
            prepared = adapter.history_index.prepare_step("s1")
            quantum_max = max(quantum_max, time.perf_counter()-quantum_start)
            steps += 1
            if prepared["status"] == "ready":
                break
            assert prepared["status"] == "progress", prepared
            assert steps < 10000, "preparation did not converge"
        assert llm.calls == 0, "preparation invoked a model"
        phases["preparation"] = {"seconds": time.perf_counter()-start,
                                  "steps": steps, "peak_kib": peak_kib(),
                                  "max_quantum_seconds": quantum_max}
        start = time.perf_counter()
        sql_start = vm_steps
        source = adapter.read_source("s1", reference_at="2026-08-30T00:00:00+00:00")
        assert source["status"] == "ready", source
        assert source["source_proof"]["group_count"] == CASES[case][0]
        assert len(source["groups"]) == 24, "fixed window grew with total history"
        assert source["stats"]["workset_rows"] == 48
        phases["foreground_read"] = {"seconds": time.perf_counter()-start,
                                      "sql_vm_steps_approx": vm_steps-sql_start,
                                      "peak_kib": peak_kib(),
                                      **{key: source["stats"][key] for key in (
                                          "canonical_message_count", "returned_groups",
                                          "workset_rows", "workset_bytes")}}
        for turn in range(2):
            rt = ContinuityRuntime(adapter, llm,
                estimator=lambda messages: max(1, len(repr(messages))//8),
                clock=lambda: "2026-08-30T00:00:00+00:00")
            try:
                wire = request()
                start = time.perf_counter()
                sql_start = vm_steps
                projected = project(rt, wire, turn=f"t{turn}", api=f"a{turn}")
                assert projected is not None, rt.status_command("s1")
                phases[f"compile_{turn}"] = {"seconds": time.perf_counter()-start, "peak_kib": peak_kib(),
                                            "sql_vm_steps_approx": vm_steps-sql_start}
                _, sent = execute(rt, projected["request"], wire, turn=f"t{turn}", api=f"a{turn}")
                assert len(sent) == 1 and wire == request()
                start = time.perf_counter()
                sql_start = vm_steps
                post(rt, turn=f"t{turn}", api=f"a{turn}")
                phases[f"settlement_{turn}"] = {"seconds": time.perf_counter()-start, "peak_kib": peak_kib(),
                                               "sql_vm_steps_approx": vm_steps-sql_start}
            finally:
                rt.clear()
        with closing(store._connect()) as connection:
            assert connection.execute("SELECT COUNT(*) FROM continuity_receipts").fetchone()[0] == 2
            assert connection.execute("SELECT revision FROM continuity_checkpoints_v3").fetchone()[0] == 1
            plans = [row[3] for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM continuity_group_index "
                "WHERE session_id='s1' ORDER BY ordinal DESC LIMIT 2049")]
            assert any("INDEX" in detail for detail in plans), plans
        with db._read_ctx() as connection:
            host_queries = {
                "canonical_page": ("SELECT * FROM hermes_history_buckets WHERE domain_id=? "
                    "AND position>? AND position<=? ORDER BY position LIMIT ?", ("s1", 0, 48, 257)),
                "prefix_validation": ("SELECT prefix_hash,physical_prefix_max_seq "
                    "FROM hermes_history_buckets WHERE domain_id=? AND position=?", ("s1", 48)),
                "journal_old_domain": ("SELECT change_seq FROM hermes_history_changes "
                    "WHERE old_session_id=? AND change_seq>? ORDER BY change_seq LIMIT 256", ("s1", 0)),
                "journal_new_domain": ("SELECT change_seq FROM hermes_history_changes "
                    "WHERE new_session_id=? AND change_seq>? ORDER BY change_seq LIMIT 256", ("s1", 0)),
            }
            host_plans = {name: [row[3] for row in connection.execute("EXPLAIN QUERY PLAN "+sql, args)]
                          for name, (sql, args) in host_queries.items()}
            for plan in host_plans.values():
                assert all("SEARCH" in detail and "INDEX" in detail for detail in plan), plan
            # This reports named temp-schema storage, not SQLite's unlinked
            # transient sorter files. RSS includes native SQLite allocations;
            # foreground plans above require no temporary sorting B-tree.
            temp_schema_bytes = (connection.execute("PRAGMA temp.page_count").fetchone()[0]
                                 * connection.execute("PRAGMA temp.page_size").fetchone()[0])
        assert llm.calls == 1
        if case.startswith("streamed_image_"):
            # Includes SQLite pools/caches and the normal admitted worksets;
            # the 64 MiB case distinguishes a full giant-value allocation.
            assert peak_kib()-initial_peak < 32*1024, {
                "measurement_peak_delta_kib": peak_kib()-initial_peak,
                "initial_peak_kib": initial_peak, "peak_kib": peak_kib()}
        return {"case": case, "scope": "disposable SQLite/plugin chain; synthetic provider/transport",
                "phases": phases, "summary_calls": llm.calls, "receipts": 2,
                "recall_query_calls": llm.recall_queries,
                "group_query_plan": plans, "host_query_plans": host_plans,
                "temp_schema_bytes_at_end": temp_schema_bytes,
                "temp_measurement_scope": "named temp schema only; transient files not a disk quota",
                "peak_kib": peak_kib(), "measurement_peak_delta_kib": peak_kib()-initial_peak}
    finally:
        adapter.close()
        db.close()


if __name__ == "__main__":
    if len(sys.argv) == 4:
        action, directory, case = sys.argv[1:]
        root = Path(directory)
        os.environ["HERMES_HOME"] = str(root / "home")
        result = setup(root, case) if action == "setup" else measure(root, case)
        if result is not None:
            print(json.dumps(result, sort_keys=True))
    else:
        selected = ([case for case in CASES if case.startswith("streamed_image_")]
                    if "--streamed-only" in sys.argv else
                    [case for case in CASES if not case.startswith("streamed_image_")])
        for case in selected:
            with tempfile.TemporaryDirectory(prefix="continuity-index-scale-") as directory:
                for action in ("setup", "measure"):
                    result = subprocess.run(
                        [sys.executable, "-B", str(Path(__file__).resolve()), action, directory, case],
                        capture_output=True, text=True, timeout=180)
                    if result.returncode:
                        raise RuntimeError(result.stderr + result.stdout)
                    if action == "measure":
                        print(result.stdout.strip(), flush=True)
