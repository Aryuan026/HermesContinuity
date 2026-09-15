# Hermes Continuity

Hermes Continuity gives a Hermes conversation a bounded rolling bridge across
context compression. It reads Hermes's canonical session history, builds an
exact-source checkpoint, and inserts only the recent bridge into the current
provider request. It also exposes a profile-local, read-only canonical-window
service so a separate Global Hot plugin can assemble recent complete visible
interaction groups from other Hermes mouths without reading `state.db` or this
plugin's metadata schema directly.

The first policy is intentionally conservative:

- recent bridge horizon: 72 hours;
- exact source budget: 24,000 tokens;
- accepted bridge output budget: 2,048 tokens.

The plugin is request-only. It is not a Hermes memory provider and does not
replace or control Hermes's native compressor. It does not copy the transcript,
create FTS tables, or register a search tool. Original sentences remain owned
and retrievable through Hermes `state.db` and native `session_search`.

## Delivery contract

For each supported request, the plugin:

1. reads the canonical `SessionDB` view through a read-only handle;
2. compiles a bounded checkpoint and recent bridge;
3. projects that bridge into the current real user carrier;
4. accepts only a host-resolved context window with explicit provenance,
   applies a conservative margin to catalog/cached values, and leaves
   fallback/unknown windows native;
5. asks Hermes to estimate and, when necessary, remove only its own bridge
   from the final SDK provider body after provider preflight and Relay
   rewriting; and
6. performs checkpoint CAS only from `post_api_request`, after the projected
   body has physically reached the provider path.

Checkpoints and receipts live in a separate plugin-data SQLite database.
Both database paths are fixed by the active Hermes profile: canonical reads
use that profile's `state.db`, while Continuity metadata uses
`plugin-data/<host-owned-plugin-namespace>/continuity.sqlite3`. Neither path is
a plugin setting, so one profile cannot be configured to borrow another
profile's transcript or checkpoint realm.
Checkpoint v2 stores the generated rolling-bridge body together with source
IDs, fingerprints, hashes, and revision state. It does not copy canonical
transcript sentences. Delivery receipts and public traces contain only IDs,
hashes, counts, status, and timestamps. Ambiguous clone history, source
rewrites, unsupported carriers, and incomplete scans fail closed to the
unchanged Hermes request.

The metadata file is claimed by one plugin owner before any Continuity table is
created. Registration/store initialization rejects Hermes canonical tables,
foreign owners, and unclaimed nonempty SQLite schema rather than mixing stores.

The `canonical-source.v2` service uses bounded physical reads, follows
compression lineages from ancestor to tip, and blocks the whole window on
ambiguous source history. Consecutive user rows may share a dialogue group only
when the host-owned H13 proof keeps them in the same origin segment; a
scheduled user-only interrupted tail therefore cannot merge into the next
human turn. The first final assistant closes the group. Tool and interim
assistant rows are not exposed as source material, but their proofs remain
obligations of that complete logical group. API-only scaffolds and synthetic
Lean summaries never become source material.

Every group carries one closed source class: `human`, `scheduled`, `internal`,
`delegated`, `tool`, or `unknown`. The class comes only from Hermes's
`hermes.message_origin.v1` group classifier. Session source/title, platform
label, display metadata, message text, and old plugin configuration grant no
authority. Missing or pre-H13 proof remains `unknown`; invalid or conflicting
proof makes only the affected group unknown. Superseded physical generations
and ancestor/tip clones participate in that local fail-closed decision.
Response bodies exist only in the synchronous in-process response; service
traces and receipts remain body-free. Consumers may request a closed subset
through `allowed_source_classes`. Clearly classified but disallowed groups are
counted and omitted before their bodies cross the service boundary.

`/continuity-status [session_id]` reports process-private attempt counts,
expiry/cap state, context-window provenance, the final-body estimator's
confidence class, checkpoint publication outcomes, and unsupported host paths.
The host estimate covers messages/input, system/instructions, tools and image
allowances with a 15% + 64-token margin, but it remains a heuristic rather than
an exact tokenizer upper bound. The status output contains no bridge or
transcript body.

`api_mode=codex_app_server` is unsupported in v1 and is left unmodified. MoA
prepared requests are currently transport-ambiguous and therefore never
publish a checkpoint or delivery receipt.

## Compatibility

The accepted Wave 5 source is paired with accepted Global Hot
`01918856aa46f80ca17dd67d079eed1b7261f85f` and tested against the accepted
Hermes Agent 0.21.0 host commit
`13900108780ae712059075200b243aa049c634cf` with tree
`5e82789d9984f8c338c09bdd0ebb31794af1f0dc`. It requires
`hermes.middleware.v2`, `hermes.transport.v3`, `hermes.request_overlay.v2`,
the bounded SessionDB time-window reader, PluginLlm finish truth, profile-local
services, and the host-owned H13 message-origin group classifier. Registration
fails visibly when any required seam is absent.

The 35 ordered patches under `patches/hermes-0.21.0-wave1/` through
`patches/hermes-0.21.0-wave4/` reproduce that exact 0.21 host tree from pure
upstream `29112bef099274229cadff79cdff7bf7b99c4b77`. Their byte identities are
recorded in `patches/hermes-0.21.0-series.sha256`. The twelve top-level 0.20.5
patches remain immutable predecessor provenance and must not be applied to
0.21.

## Test

The default suite uses the Python standard library plus the shared overlay
module from the compatible Hermes tree:

```bash
PYTHONPATH=/path/to/patched/hermes \
python -B -m unittest discover -s tests -v
```

The adapter and middleware suites also contain optional real-Hermes integration
tests. Point them at a compatible checkout to exercise
`SessionDB.archive_and_compact` and the real middleware/hook registries:

```bash
PYTHONPATH=/path/to/hermes \
HERMES_SOURCE_ROOT=/path/to/hermes \
python -B -m unittest discover -s tests -v
```

All committed fixtures are synthetic. `tests/test_real_host_021.py` loads only
Continuity through real plugin discovery and enters through production
`AIAgent.run_conversation`; it covers a failed primary provider attempt,
fallback delivery, post settlement, next-turn checkpoint reuse, and manager
unload/reload. The adapter suite separately runs real Lean compaction and
read-only reopen through both the production full-prefix and bounded lineage
readers, including a tool-follow-up group. The paired production entrypoint now
uses real H13 human proofs for its synthetic dialogue groups and current turns.

The public workflow reconstructs the exact 0.21 host from the 35 digest-pinned
patches, runs the changed host seam matrix and both plugin suites, enters the
paired production conversation path, then installs both exact Git revisions
disabled in a disposable profile, runs native/joint Doctor, removes them, and
requires empty plugin directories and install metadata. It performs no network
provider call, enablement, deployment, or live-channel canary.

## Current status

The 0.20.5 public candidate remains the installed control. Wave 5 Continuity
and Wave 6 Global Hot are independently accepted source checkpoints. The
current Wave 7 revision is a public-replay and disposable disabled-lifecycle
candidate; it does not change Continuity production code.
The current v2 source/checkpoint path still performs work and stores proof
material proportional to full session history; formal use on a long-lived
profile remains blocked until a stable host prefix-proof seam and compact
checkpoint v3 exist. The new 0.21 artifact has not been installed, enabled,
deployed, or observed in a live conversation; see
[`PROGRESS.md`](PROGRESS.md).

The extraction lineage and deliberate omissions are recorded in
[`PROVENANCE.md`](PROVENANCE.md). Security and privacy boundaries are in
[`SECURITY.md`](SECURITY.md). Hermes/Nous portions of the compatibility patches
retain their upstream notice in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## License

MIT.
