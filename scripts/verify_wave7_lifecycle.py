#!/usr/bin/env python3
"""Verify exact-ref disabled install, Doctor, removal, and metadata cleanup."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


PLUGIN_IDS = ("hermes-continuity", "hermes-global-hot")


def _exact_revision(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("revision must be one full lowercase Git SHA")
    return value


def _repository(value: str) -> str:
    candidate = Path(value)
    if candidate.is_dir():
        return candidate.resolve().as_uri()
    return value


def _run(hermes: Path, home: Path, *args: str) -> str:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(home)
    result = subprocess.run(
        [str(hermes), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--continuity-repo", required=True)
    parser.add_argument("--continuity-ref", required=True, type=_exact_revision)
    parser.add_argument("--global-hot-repo", required=True)
    parser.add_argument("--global-hot-ref", required=True, type=_exact_revision)
    args = parser.parse_args()

    hermes = Path(sys.executable).with_name("hermes")
    if not hermes.is_file():
        raise SystemExit(f"Hermes console script not found beside {sys.executable}")

    continuity_repo = _repository(args.continuity_repo)
    global_hot_repo = _repository(args.global_hot_repo)
    expected = {
        "hermes-continuity": args.continuity_ref,
        "hermes-global-hot": args.global_hot_ref,
    }

    with tempfile.TemporaryDirectory(prefix="hermes-wave7-lifecycle-") as temp:
        home = Path(temp) / "profile"
        _run(
            hermes,
            home,
            "plugins",
            "install",
            continuity_repo,
            "--ref",
            args.continuity_ref,
            "--no-enable",
        )
        _run(
            hermes,
            home,
            "plugins",
            "install",
            global_hot_repo,
            "--ref",
            args.global_hot_ref,
            "--no-enable",
        )

        plugins_dir = home / "plugins"
        metadata_path = plugins_dir / ".install-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        for plugin_id, revision in expected.items():
            record = metadata.get(plugin_id)
            if not isinstance(record, dict):
                raise SystemExit(f"missing install metadata for {plugin_id}")
            if record.get("revision") != revision or record.get("pinned") is not True:
                raise SystemExit(f"untrusted install metadata for {plugin_id}")

        listing = _run(hermes, home, "plugins", "list", "--plain", "--no-bundled")
        for plugin_id in PLUGIN_IDS:
            matching = [line for line in listing.splitlines() if plugin_id in line]
            if len(matching) != 1 or "not enabled" not in matching[0]:
                raise SystemExit(f"{plugin_id} is not exactly once and disabled")

        _run(hermes, home, "plugins", "doctor", "--ci", "hermes-continuity")
        _run(
            hermes,
            home,
            "plugins",
            "doctor",
            "--ci",
            "hermes-global-hot",
            "--with",
            "hermes-continuity",
        )

        _run(hermes, home, "plugins", "remove", "hermes-global-hot")
        _run(hermes, home, "plugins", "remove", "hermes-continuity")

        installed_dirs = sorted(path.name for path in plugins_dir.iterdir() if path.is_dir())
        if installed_dirs:
            raise SystemExit(f"plugin directories remain after removal: {installed_dirs}")
        if json.loads(metadata_path.read_text(encoding="utf-8")) != {}:
            raise SystemExit("install metadata is not empty after removal")

    print(
        "WAVE7_LIFECYCLE_GREEN "
        f"continuity={args.continuity_ref} global_hot={args.global_hot_ref} "
        "enabled=false doctors=native,joint removed=true metadata_clean=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
