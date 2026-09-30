from __future__ import annotations

import copy
import hashlib
import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "hermes_continuity_algorithm_tests"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package

checkpoint_v3 = importlib.import_module(f"{PACKAGE}.checkpoint_v3")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _group(source_id: str, index: int) -> dict:
    return {
        "group_kind": "dialogue_turn",
        "source_prefix_id": source_id,
        "logical_turn_id": source_id,
        "record_id": f"capture-{source_id}",
        "effective_event_at": f"2026-09-28T00:0{index}:00+00:00",
        "messages": [
            {
                "role": "user",
                "message_id": f"user-{source_id}",
                "content": f"question {index}",
            },
            {
                "role": "assistant",
                "message_id": f"assistant-{source_id}",
                "content": f"answer {index}",
            },
        ],
    }


def compact_source_fixture(
    groups: list[dict] | None = None,
    *,
    eligible_group_count: int = 1,
) -> dict:
    groups = groups or [_group("group-2049", 1), _group("group-2050", 2)]
    if not 0 <= eligible_group_count <= len(groups):
        raise ValueError("eligible_group_count_invalid")
    rule = "hermes_continuity_group_index.v1"
    domain_id = "session-domain"
    prefix_before = {
        "schema": "thread_continuity_prefix_descriptor.v1",
        "through_anchor": "anchor-4096",
        "canonical_count": 4096,
        "group_count": 2048,
        "prefix_hash": _sha("canonical-prefix-4096"),
        "group_root": _sha("group-root-2048"),
    }
    prefixes = []
    previous = prefix_before
    for offset, group in enumerate(groups, start=1):
        fingerprint = checkpoint_v3.thread_continuity_group_fingerprint(
            checkpoint_v3._normalize_groups([group])[0]
        )
        canonical_count = 4096 + offset * 2
        prefix_hash = _sha(f"canonical-prefix-{canonical_count}")
        prefix = {
            "schema": "thread_continuity_prefix_descriptor.v1",
            "through_anchor": f"anchor-{canonical_count}",
            "canonical_count": canonical_count,
            "group_count": 2048 + offset,
            "prefix_hash": prefix_hash,
            "group_root": checkpoint_v3.extend_thread_continuity_group_root(
                previous["group_root"],
                group_count=2048 + offset,
                source_prefix_id=group["source_prefix_id"],
                source_group_fingerprint=fingerprint,
                through_anchor=f"anchor-{canonical_count}",
                canonical_count=canonical_count,
                prefix_hash=prefix_hash,
            ),
        }
        prefixes.append(
            {
                "source_prefix_id": group["source_prefix_id"],
                "source_group_fingerprint": fingerprint,
                "prefix": prefix,
            }
        )
        previous = prefix
    host_token = {
        "schema": "hermes.canonical_history_prefix.v1",
        "realm_id": "profile-realm",
        "incarnation": "host-incarnation",
        "activation_epoch": "activation-1",
        "domain_id": domain_id,
        "topology_revision": "topology-1",
        "canonical_rule_version": "hermes-canonical-v1",
        "indexed_change_seq": 17,
        "end_anchor": previous["through_anchor"],
        "canonical_count": previous["canonical_count"],
        "prefix_hash": previous["prefix_hash"],
    }
    source_proof = {
        "host_token": host_token,
        "grouping_rule_version": rule,
        "group_count": previous["group_count"],
        "group_root": previous["group_root"],
    }
    return {
        "schema": "thread_continuity_compact_source.v1",
        "status": "ready",
        "scan_complete": True,
        "source_snapshot": checkpoint_v3.canonical_proof_sha256(source_proof),
        "source_proof": source_proof,
        "prefix_before_groups": prefix_before,
        "groups": groups,
        "group_prefixes": prefixes,
        "retirement_eligibility": {
            "schema": "thread_continuity_retirement_eligibility.v1",
            "status": "eligible",
            "prefix": (
                prefixes[eligible_group_count - 1]["prefix"]
                if eligible_group_count
                else prefix_before
            ),
            "physical_ownership_sha256": _sha("physical-ownership-through-2049"),
        },
        "stats": {
            "full_prefix": False,
            "canonical_message_count": previous["canonical_count"],
            "returned_groups": len(groups),
            "workset_rows": sum(len(group["messages"]) for group in groups),
            "workset_bytes": 512,
            "compacted_prefix_group_ids": [
                group["source_prefix_id"]
                for group in groups[:eligible_group_count]
            ],
        },
    }


def checkpoint_fixture(*, previous: dict | None = None, continue_lineage: bool = False) -> dict:
    source = checkpoint_v3.normalize_thread_continuity_compact_source(
        compact_source_fixture()
    )
    return checkpoint_v3.build_thread_continuity_checkpoint_v3(
        previous_state=previous,
        source_proof=source["source_proof"],
        retirement_prefix=source["retirement_eligibility"]["prefix"],
        bridge_source_groups=[source["groups"][0]],
        bridge_text="bounded recent bridge",
        bridge_policy={
            "reference_at": "2026-09-28T00:02:00+00:00",
            "recent_horizon_hours": 72,
            "source_token_limit": 24_000,
            "output_token_limit": 2_048,
        },
        continue_lineage=continue_lineage,
    )


class CheckpointV3Tests(unittest.TestCase):
    def test_compact_source_proves_large_prefix_without_full_group_array(self) -> None:
        source = checkpoint_v3.normalize_thread_continuity_compact_source(
            compact_source_fixture()
        )
        self.assertEqual(source["prefix_before_groups"]["group_count"], 2048)
        self.assertEqual(len(source["groups"]), 2)
        self.assertEqual(source["source_proof"]["group_count"], 2050)

    def test_checkpoint_source_validation_and_continued_lineage(self) -> None:
        source = compact_source_fixture()
        first = checkpoint_fixture()
        validation = checkpoint_v3.make_thread_continuity_checkpoint_validation(
            first, source
        )
        self.assertEqual(
            checkpoint_v3.validate_thread_continuity_checkpoint_v3_source(
                first,
                compact_source=source,
                checkpoint_validation=validation,
            ),
            first,
        )
        second = checkpoint_fixture(previous=first, continue_lineage=True)
        self.assertEqual(second["lineage_status"], "continued")
        self.assertEqual(second["predecessor_revision_id"], first["revision_id"])

        appended = compact_source_fixture()
        appended["source_proof"]["host_token"].update(
            indexed_change_seq=18,
            end_anchor="anchor-4101",
            canonical_count=4101,
            prefix_hash=_sha("canonical-prefix-4101"),
        )
        appended["source_snapshot"] = checkpoint_v3.canonical_proof_sha256(
            appended["source_proof"]
        )
        appended["stats"]["canonical_message_count"] = 4101
        validation = checkpoint_v3.make_thread_continuity_checkpoint_validation(
            first, appended
        )
        self.assertEqual(
            checkpoint_v3.validate_thread_continuity_checkpoint_v3_source(
                first,
                compact_source=appended,
                checkpoint_validation=validation,
            ),
            first,
        )

    def test_cross_format_first_v3_starts_rebuilt_chain(self) -> None:
        checkpoint = checkpoint_v3.build_thread_continuity_checkpoint_v3(
            previous_state={"schema": "thread_continuity_checkpoint.v2"},
            source_proof=compact_source_fixture()["source_proof"],
            retirement_prefix=compact_source_fixture()["retirement_eligibility"]["prefix"],
            bridge_source_groups=[compact_source_fixture()["groups"][0]],
            bridge_text="bounded recent bridge",
            bridge_policy={
                "reference_at": "2026-09-28T00:02:00+00:00",
                "recent_horizon_hours": 72,
                "source_token_limit": 24_000,
                "output_token_limit": 2_048,
            },
            continue_lineage=False,
        )
        self.assertEqual(checkpoint["lineage_status"], "rebuilt")
        self.assertEqual(checkpoint["revision"], 1)
        self.assertEqual(checkpoint["predecessor_revision_id"], "")

    def test_source_invalid_stored_v3_rebuild_preserves_cas_predecessor(self) -> None:
        first = checkpoint_fixture()
        source = compact_source_fixture()
        rebuilt = checkpoint_v3.build_thread_continuity_checkpoint_v3(
            previous_state=None,
            source_proof=source["source_proof"],
            retirement_prefix=source["retirement_eligibility"]["prefix"],
            bridge_source_groups=[source["groups"][0]],
            bridge_text="rebuilt bounded bridge",
            bridge_policy={
                "reference_at": "2026-09-28T00:02:00+00:00",
                "recent_horizon_hours": 72,
                "source_token_limit": 24_000,
                "output_token_limit": 2_048,
            },
            continue_lineage=False,
            predecessor_revision=first["revision"],
            predecessor_revision_id=first["revision_id"],
        )
        self.assertEqual(rebuilt["lineage_status"], "rebuilt")
        self.assertEqual(rebuilt["revision"], 2)
        self.assertEqual(rebuilt["predecessor_revision_id"], first["revision_id"])
        self.assertEqual(
            checkpoint_v3.normalize_thread_continuity_checkpoint_v3(
                rebuilt, previous_state=first
            ),
            rebuilt,
        )

    def test_tamper_and_bridge_beyond_retirement_fail_closed(self) -> None:
        source = compact_source_fixture()
        checkpoint = checkpoint_fixture()
        for mutate in (
            lambda row: row["recent_bridge"].__setitem__("body", "changed"),
            lambda row: row["source_proof"].__setitem__("group_root", _sha("changed")),
            lambda row: row.__setitem__("predecessor_revision_id", "tcr_" + "1" * 64),
        ):
            tampered = copy.deepcopy(checkpoint)
            mutate(tampered)
            with self.assertRaises(ValueError):
                checkpoint_v3.normalize_thread_continuity_checkpoint_v3(tampered)

        impossible_prefix = copy.deepcopy(source)
        impossible_prefix["prefix_before_groups"]["canonical_count"] = 1
        with self.assertRaises(ValueError):
            checkpoint_v3.normalize_thread_continuity_compact_source(
                impossible_prefix
            )

        impossible_lineage = copy.deepcopy(checkpoint)
        impossible_lineage["lineage_status"] = "continued"
        impossible_lineage["predecessor_revision_id"] = "tcr_" + "1" * 64
        impossible_lineage["revision_id"] = checkpoint_v3._checkpoint_revision_id(
            impossible_lineage
        )
        with self.assertRaises(ValueError):
            checkpoint_v3.normalize_thread_continuity_checkpoint_v3(
                impossible_lineage
            )

        beyond = checkpoint_v3.build_thread_continuity_checkpoint_v3(
            previous_state=None,
            source_proof=source["source_proof"],
            retirement_prefix=source["retirement_eligibility"]["prefix"],
            bridge_source_groups=[source["groups"][1]],
            bridge_text="foreground must not become bridge",
            bridge_policy={
                "reference_at": "2026-09-28T00:02:00+00:00",
                "recent_horizon_hours": 72,
                "source_token_limit": 24_000,
                "output_token_limit": 2_048,
            },
            continue_lineage=False,
        )
        with self.assertRaises(ValueError):
            checkpoint_v3.validate_thread_continuity_checkpoint_v3_source(
                beyond, compact_source=source
            )


if __name__ == "__main__":
    unittest.main()
