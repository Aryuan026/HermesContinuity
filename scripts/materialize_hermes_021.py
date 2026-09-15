#!/usr/bin/env python3
"""Apply the accepted Hermes 0.21 host series and verify its exact tree."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


UPSTREAM_REVISION = "29112bef099274229cadff79cdff7bf7b99c4b77"
ASSEMBLED_TREE = "5e82789d9984f8c338c09bdd0ebb31794af1f0dc"
SERIES = (
    "hermes-0.21.0-wave1",
    "hermes-0.21.0-wave2",
    "hermes-0.21.0-wave3",
    "hermes-0.21.0-wave4",
)
PATCH_COUNT = 35


def _git(host: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(host), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=Path, required=True)
    args = parser.parse_args()

    host = args.host.resolve()
    patch_root = Path(__file__).resolve().parents[1] / "patches"
    if _git(host, "rev-parse", "HEAD") != UPSTREAM_REVISION:
        raise SystemExit("unexpected Hermes upstream revision")
    if _git(host, "status", "--porcelain"):
        raise SystemExit("Hermes checkout must be clean before replay")

    patches = [
        patch
        for series in SERIES
        for patch in sorted((patch_root / series).glob("*.patch"))
    ]
    if len(patches) != PATCH_COUNT:
        raise SystemExit(f"expected {PATCH_COUNT} host patches, found {len(patches)}")

    manifest_path = patch_root / "hermes-0.21.0-series.sha256"
    recorded = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        digest, relative_path = line.split(maxsplit=1)
        recorded[relative_path] = digest
    actual = {
        str(patch.relative_to(patch_root.parent)): hashlib.sha256(
            patch.read_bytes()
        ).hexdigest()
        for patch in patches
    }
    if recorded != actual:
        raise SystemExit("Hermes 0.21 patch digest manifest mismatch")

    for patch in patches:
        subprocess.run(
            ["git", "-C", str(host), "apply", "--check", str(patch)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(host), "apply", "--index", str(patch)],
            check=True,
        )

    assembled_tree = _git(host, "write-tree")
    if assembled_tree != ASSEMBLED_TREE:
        raise SystemExit(
            f"assembled tree mismatch: expected {ASSEMBLED_TREE}, got {assembled_tree}"
        )
    print(
        "HERMES_021_REPLAY_GREEN "
        f"upstream={UPSTREAM_REVISION} patches={PATCH_COUNT} "
        f"digests=verified tree={assembled_tree}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
