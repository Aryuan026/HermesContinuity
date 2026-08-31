# Hermes Continuity

Hermes Continuity gives a Hermes conversation a bounded rolling bridge across
context compression. It reads Hermes's canonical session history, builds an
exact-source checkpoint, and inserts only the recent bridge into the current
provider request. It also exposes a profile-local, read-only canonical-window
service so a separate Global Hot plugin can assemble recent complete dialogue
from other Hermes mouths without reading `state.db` or this plugin's metadata
schema directly.

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
compression lineages from ancestor to tip, returns only complete
user/final-assistant groups, and blocks the whole window on ambiguous source
history. Every group carries one closed source class: `human`, `scheduled`,
`internal`, `delegated`, `tool`, or `unknown`. Wakeups qualify as scheduled
only when the durable user row carries host-proven wakeup provenance; an
arbitrary platform label is not enough. Response bodies exist only in the
synchronous in-process response; service traces and receipts remain body-free.
Consumers may request a closed subset through `allowed_source_classes`.
Clearly classified but disallowed groups are counted and omitted before their
bodies cross the service boundary; source ambiguity still blocks the complete
window. Hermes CLI, TUI, browser, desktop and dashboard tags are human inputs.
An owner-operated custom frontend must be listed explicitly in
`additional_human_sources`; unknown tags are never guessed to be human.

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

The reviewed host baseline and additive host seams are:

- Hermes upstream release: `fcbd1076a93841fa88855acce810e342a5b78101`;
- owner overlay: `c7c36f36ccee592a96f90e8acd9c6401808a02ad`;
- PluginLlm finish reasons: `201fe7756c57c35aaed9af8e9886e10ff4d25cfe`;
- sequential request middleware and `hermes.middleware.v2`:
  `b7fac683859f5997b4cc63a951078b99c209abbc`;
- profile-scoped plugin services:
  `22dd21241f3628e0d25b808012f07874d45310d4`;
- bounded SessionDB time-window reads:
  `20b7b9a3b4f66871686503f222e39f4c55a058a5`;
- final provider-body transport truth and `hermes.transport.v1`:
  `81f8fa21167b1fcd3929b27ee172b6cf7a94ec21`;
- closed finish-state truth across auxiliary/provider adapters:
  `5e1b05f04b193ade4eb16fb28f29198b0ee672a3`;
- host-resolved context provenance, final provider-body filtering, and
  `hermes.transport.v3`:
  `7a5c6ca23b544d73fb37a3a1c7d8b08d1a82938c`;
- verified durable wakeup provenance:
  `7c183e81832c81e29f6d095a15bb7c8cd080ee5c`;
- installer manifest-v2 alignment:
  `113b4ab5285f92a1013c6a494eb33260a7f70140`;
- joint plugin Doctor:
  `969cf5bdbc3a110e475c02ed8e4ee84f64be32ed`;
- shared request overlay ownership, scoped proof, and final-budget disposition:
  `ccd7bf350ca54a44b7351904e079f5ffdb64eec0`;
- host-accepted overlay dispositions, zero-filter provider-body estimates, and
  no byte-derived ownership reminting:
  `5a680e5e38625fb3275b4bf6973a40d089ec11a7`.

Apply the twelve ordered patches in [`patches/`](patches/) to the compatible
Hermes core. The first eight are runtime prerequisites, the next two align
the official installer with manifest v2 and let Doctor load dependency sets in
one initialized temporary profile, and the final two own generic
request-overlay carrier/proof behavior and host acceptance. They are generic
host capabilities, not plugin-specific monkey patches. Registration fails
visibly if a required runtime schema or API is absent.

The order is: `plugin-llm-finish-reason`, `request-middleware-v2`,
`plugin-service-registry`, `bounded-session-message-reads`,
`provider-transport-truth`, `closed-finish-state-truth`,
`final-provider-budget-controls`, `verified-wakeup-provenance`,
`installer-manifest-v2`, `joint-plugin-doctor`, `request-overlay-proofs`, then
`request-overlay-acceptance`.

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
HERMES_SOURCE_ROOT=/path/to/hermes \
python -B -m unittest discover -s tests -v
```

All committed fixtures are synthetic. Public GitHub Actions replays all twelve
patches from pure upstream `fcbd1076`, installs that materialized host, exports
`HERMES_SOURCE_ROOT`, runs the shared-overlay host tests, and then runs the
plugin's Python 3.11/3.12 suite with its real-host tests enabled. The
dual-plugin `AIAgent.run_conversation` entrypoint still requires a Global Hot
tree and is exercised by Global Hot's paired workflow rather than this
single-repository workflow.

## Current status

The first public replacement candidate received external review. Its
source-policy findings are incorporated in this next exact-revision candidate.
The current v2 source/checkpoint path still performs work and stores proof
material proportional to full session history; formal use on a long-lived
profile remains blocked until a stable host prefix-proof seam and compact
checkpoint v3 exist. The plugin is not installed, enabled, deployed, or
observed in a live conversation; see [`PROGRESS.md`](PROGRESS.md).

The extraction lineage and deliberate omissions are recorded in
[`PROVENANCE.md`](PROVENANCE.md). Security and privacy boundaries are in
[`SECURITY.md`](SECURITY.md). Hermes/Nous portions of the compatibility patches
retain their upstream notice in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## License

MIT.
