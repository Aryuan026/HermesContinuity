"""Disposable full plugin-chain benchmark; provider/transport are synthetic.

Run with the compatible 0.20.5 host on PYTHONPATH and HERMES_SOURCE_ROOT.
Every fixture is built in a separate process so setup does not pollute RSS.
The parent enforces a wall deadline; Linux children also have a 1 GiB AS limit.
No network/provider traffic and no owner databases are used.
"""
from __future__ import annotations

import json
import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
CONTROL = os.environ.get("CONTINUITY_BENCH_CONTROL", "")
if CONTROL:
    for name in ("hermes_continuity_adapter_tests", "hermes_continuity_runtime_adapter_tests"):
        package = types.ModuleType(name)
        package.__path__ = [CONTROL]
        sys.modules[name] = package
from test_hermes_adapter import ContinuityMetadataStore, HermesSessionAdapter, hermes_adapter
from test_runtime import ContinuityRuntime, FakeLlm, execute, post, project, request
from hermes_state import SessionDB

CASES = ("small", "large_message", "near_byte_budget", "large_checkpoint", "overflow_checkpoint", "clones_2000", "clones_20000")


def prepare(directory, case):
    db = SessionDB(db_path=directory / "state.db")
    db.create_session("s1", source="cli")
    for role, body in (("user", "past question"), ("assistant", "past answer"),
                       ("user", "recent question"), ("assistant", "recent answer")):
        db.append_message("s1", role, body)
    db.close()
    with sqlite3.connect(directory / "state.db") as connection:
        connection.execute("UPDATE messages SET timestamp=1787961600+id, active=CASE WHEN id<=2 THEN 0 ELSE 1 END, compacted=CASE WHEN id<=2 THEN 1 ELSE 0 END")
        if case == "large_message":
            connection.execute("UPDATE messages SET api_content=printf('%.*c', 16777216, 'x') WHERE id=1")
        if case == "near_byte_budget":
            connection.execute("UPDATE messages SET content=printf('%.*c', 750000, 'x')")
        clones = 20000 if case in ("clones_20000", "overflow_checkpoint") else 2000 if case == "clones_2000" else 0
        columns = [r[1] for r in connection.execute("PRAGMA table_info(messages)") if r[1] != "id"]
        names = ",".join('"' + c + '"' for c in columns)
        for _ in range(clones // 2):
            connection.execute(f"INSERT INTO messages ({names}) SELECT {names} FROM messages WHERE id<=2")
    store = ContinuityMetadataStore(directory / "metadata.db")
    if case in ("large_checkpoint", "overflow_checkpoint"):
        with sqlite3.connect(store.path) as connection:
            connection.execute("INSERT INTO continuity_checkpoints VALUES ('s1',1,'snapshot','[]',printf('%.*c',16777216,'x'),'hash','now')")


def measure(directory, case):
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    db = SessionDB(db_path=directory / "state.db", read_only=True)
    store = ContinuityMetadataStore(directory / "metadata.db")
    adapter = HermesSessionAdapter(db, store)
    phases = {}

    def rss():
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value // 1024 if sys.platform == "darwin" else value

    def timed(name, fn):
        def wrapped(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                item = phases.setdefault(name, {"calls": 0, "seconds": 0.0, "high_water_kib": 0})
                item["calls"] += 1
                item["seconds"] += time.perf_counter() - start
                item["high_water_kib"] = rss()
        return wrapped

    llm = FakeLlm()
    def runtime():
        result = ContinuityRuntime(adapter, llm,
            estimator=lambda messages: max(1, len(repr(messages)) // 8),
            clock=lambda: "2026-08-30T00:00:00+00:00")
        compiler = result.compiler
        async def compile_timed(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await compiler(*args, **kwargs)
            finally:
                item = phases.setdefault("compile", {"calls": 0, "seconds": 0.0, "high_water_kib": 0})
                item["calls"] += 1
                item["seconds"] += time.perf_counter() - start
                item["high_water_kib"] = rss()
        result.compiler = compile_timed
        return result

    adapter.read_source = timed("read", adapter.read_source)
    store.read_continuity = timed("checkpoint_read", store.read_continuity)
    adapter.settle_checkpoint_delivery = timed("settlement", adapter.settle_checkpoint_delivery)
    start_rss = rss()
    started = time.perf_counter()
    rounds = []
    with patch.object(hermes_adapter, "_audit_canonical_view", timed("audit", hermes_adapter._audit_canonical_view)):
        for number in range(2):
            rt = runtime()
            wire = request()
            projected = project(rt, wire, turn=f"t{number}", api=f"a{number}")
            assert wire == request(), "original request mutated"
            _, sent = execute(rt, projected["request"] if projected else wire, wire,
                              turn=f"t{number}", api=f"a{number}")
            if not CONTROL and case in ("large_message", "large_checkpoint", "overflow_checkpoint", "clones_20000"):
                assert sent == [wire], "guard changed native provider request"
            post(rt, turn=f"t{number}", api=f"a{number}")
            rounds.append({"projected": projected is not None, "runtime": json.loads(rt.status_command())})
            rt.clear()
    status = timed("status", store.status_summary)("s1")
    peak = rss()
    db.close()
    positive = case in ("small", "clones_2000")
    if not CONTROL and case != "near_byte_budget":
        assert all(r["projected"] for r in rounds) == positive, rounds
    if positive:
        assert status["receipt_count"] == 2 and status["checkpoint"]["revision"] == 1, status
        assert llm.calls == 1, "next turn did not reuse the first checkpoint"
    elif not CONTROL and case != "near_byte_budget":
        assert llm.calls == 0 and status["receipt_count"] == 0, status
    return {"case": case, "lane": "control-0.4.1" if CONTROL else "candidate", "scope": "real SessionDB + plugin read/compile/execution/post/status; synthetic provider and transport",
            "peak_kib": peak, "peak_growth_kib": peak-start_rss,
            "total_seconds": time.perf_counter()-started, "phases": phases,
            "projected_rounds": sum(r["projected"] for r in rounds), "summary_calls": llm.calls,
            "recall_query_calls": llm.recall_queries,
            "receipt_count": status["receipt_count"], "checkpoint": status["checkpoint"],
            "reasons": [r["runtime"]["reason_counts"] for r in rounds]}


if __name__ == "__main__":
    if len(sys.argv) == 4:
        action, path, case = sys.argv[1:]
        os.environ["HERMES_HOME"] = str(Path(path) / "home")
        result = prepare(Path(path), case) if action == "prepare" else measure(Path(path), case)
        if result is not None:
            print(json.dumps(result, sort_keys=True))
    else:
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix="continuity-resource-") as directory:
                command = [sys.executable, "-B", str(Path(__file__).resolve())]
                setup = subprocess.run([*command, "prepare", directory, case], timeout=90, capture_output=True, text=True)
                if setup.returncode:
                    raise RuntimeError(setup.stderr)
                try:
                    result = subprocess.run([*command, "measure", directory, case], timeout=30, capture_output=True, text=True)
                except subprocess.TimeoutExpired:
                    if not CONTROL:
                        raise
                    print(json.dumps({"case": case, "lane": "control-0.4.1", "terminated": "external_timeout"}), flush=True)
                    continue
                if result.returncode:
                    raise RuntimeError(result.stderr)
                print(result.stdout.strip(), flush=True)
