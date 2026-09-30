"""Actual host probe/preparation in disposable, externally timed processes.

Setup is separate from measurement; RSS includes native SQLite allocations.
Only synthetic data is used, with no provider call or transcript output.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time

from hermes_state import SessionDB

MIB = 1024*1024
CASES = {"within_budget": MIB, "oversized_16m": 16*MIB, "oversized_64m": 64*MIB}


def peak_kib():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak // 1024 if sys.platform == "darwin" else peak


def setup(root, size):
    with SessionDB(root / "state.db") as db:
        db.create_session("large", source="cli")
        db.create_session("small", source="cli")
    with closing(sqlite3.connect(root / "state.db")) as conn:
        conn.execute("INSERT INTO messages(session_id,role,content,api_content,timestamp,active,compacted) "
                     "VALUES ('large','user','visible body',CAST(zeroblob(?) AS TEXT),1,1,0)", (size,))
        conn.execute("INSERT INTO messages(session_id,role,content,timestamp,active,compacted) "
                     "VALUES ('small','user','small body',2,1,0)")
        conn.commit()


def measure(root, case, size, *, probe_only=False):
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    with SessionDB(root / "state.db") as db:
        original_decode = db._decode_message_rows
        decoded = 0
        def decode(rows):
            nonlocal decoded
            decoded += len(rows)
            return original_decode(rows)
        db._decode_message_rows = decode
        before = peak_kib()
        start = time.perf_counter()
        # Execute the actual SQL probe before any host decoder.
        with db._read_ctx() as conn:
            old_limit = conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH)
            result = db._history_probe_page(conn, {"domain_id": "large",
                "cursor_message_id": 0, "target_max_message_id": 1}, max_rows=256, max_bytes=4*MIB)
            assert conn.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == old_limit
        probe_peak = peak_kib()
        probe_seconds = time.perf_counter() - start
        if probe_only:
            return {"case": case, "stored_field_bytes": size, "reason": result[4],
                    "returned_rows": len(result[0]), "probe_peak_delta_kib": probe_peak-before,
                    "peak_kib": probe_peak, "scope": "actual SessionDB probe only"}
        start = time.perf_counter()
        prepared = db.prepare_history_step("large", owner_id="benchmark", deadline_ms=2000)
        after = peak_kib()
        if size > 4*MIB:
            assert result == ([], {}, 0, True, "history_row_byte_limit_exceeded"), result[4]
            assert prepared["status"] == "overflow", prepared
            assert prepared["reason"] == "history_row_byte_limit_exceeded", prepared
            assert decoded == 0, "oversized value reached decoder"
            # A generous discriminator for a 16/64 MiB native materialization,
            # not a production RSS ceiling or a claim of zero allocations.
            assert after-before < 8*1024, {"native_peak_delta_kib": after-before}
        else:
            assert len(result[0]) == 1 and result[4] is None
            assert len(result[0][0]["api_content"]) == size
            assert prepared["status"] == "ready", prepared
            page = db.read_history_page("large", target=prepared["head_token"])
            assert page["status"] == "ready" and page["rows"][0]["content"] == "visible body"
        prepare_seconds = time.perf_counter() - start
        small = db.prepare_history_step("small", owner_id="benchmark", deadline_ms=2000)
        assert small["status"] == "ready", small
        page = db.read_history_page("small", target=small["head_token"])
        assert page["rows"][0]["content"] == "small body"
        return {"case": case, "stored_field_bytes": size, "status": prepared["status"],
                "probe_seconds": probe_seconds, "preparation_seconds": prepare_seconds,
                "probe_peak_delta_kib": probe_peak-before,
                "preparation_peak_delta_kib": after-probe_peak,
                "native_peak_delta_kib": after-before, "peak_kib": after,
                "small_session_recovered": True,
                "scope": "actual SessionDB probe/preparation; disposable SQLite; no provider"}


if __name__ == "__main__":
    if len(sys.argv) == 4:
        action, directory, case = sys.argv[1:]
        root = Path(directory)
        os.environ["HERMES_HOME"] = str(root / "home")
        if action == "setup":
            setup(root, CASES[case])
        else:
            print(json.dumps(measure(root, case, CASES[case], probe_only=action == "probe"), sort_keys=True))
    else:
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix="continuity-value-guard-") as directory:
                for action in ("setup", "measure"):
                    completed = subprocess.run([sys.executable, "-B", __file__, action, directory, case],
                        capture_output=True, text=True, timeout=45)
                    if completed.returncode:
                        raise RuntimeError(f"{action}/{case} exited {completed.returncode}: {completed.stderr}")
                    if action == "measure":
                        result = json.loads(completed.stdout)
                        print(json.dumps(result, sort_keys=True), flush=True)
