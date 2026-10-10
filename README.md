# Hermes Continuity

**Keep recent conversational continuity without loading the whole past.**

A request-only Hermes plugin that combines a bounded rolling bridge with
question-selected historical recall. It reads canonical history rather than
copying transcripts, and exposes a profile-local source service for
[Global Hot](https://github.com/Aryuan026/HermesGlobalHot).

## Compatibility

Last reviewed: **2026-10-10**. Compatibility means an exact plugin/host pairing,
not support for every installation sharing the same version number.

- **Hermes 0.20.5 — public integration baseline.** Current public main is based
  on plugin `0.4.2`. Use the ordered host patches in [patches/](patches/),
  starting from upstream `fcbd1076`. The original twelve provide the runtime
  foundation; patches 13–19 add bounded long-history preparation, streamed
  values and native-search recall. This lane received source review,
  exact installation/Doctor checks and owner-controlled deployment.
- **Hermes 0.21.3 — historical, separately ported integration.** Enabled paired
  replay, Lean compression and disposable migration/rollback were accepted
  for that exact lane. The 0.20.5 patch files are not its installation recipe;
  that evidence does not qualify arbitrary 0.21.3 hosts or current main.
- **Hermes 0.21.5 — maintained owner-controlled integration.** The adapted
  plugin `75aecd6d6544f3dcb313c42bf917c4a015a31cea` was tested with the
  corresponding patched host and installed/enabled on 2026-10-10. Its H13
  source adapter differs from this public main. This repository does not yet
  package that complete public installation lane; do not install main as a
  substitute or apply the 0.20.5 patches to 0.21.5.
- **Other versions — not qualified.** A newer release is not automatically
  compatible. Historical 0.21.0 acceptance is a regression reference, not the
  selected upgrade target.

Required host contracts include `hermes.middleware.v2`,
`hermes.transport.v3`, `hermes.request_overlay.v2`, profile-local services,
closed completion states and provenance-bearing context windows. Registration
rejects missing contracts. A pure upstream install is not the patched host.

## Highlights

- **Rolling continuity, not an eternal transcript.** A recent bridge survives
  context compression while Hermes keeps ownership of history and compression.
- **Automatic question-driven recall.** Bounded keyword candidates from native
  FTS/LIKE are verified as complete groups, then selected and summarized for
  the current question. This is semantic delivery, not merely an enabled
  search tool, and not embedding-based similarity search.
- **Long history with a bounded foreground.** Incremental, body-free source
  proofs and finite background preparation replace repeated full-history
  loading when the indexed host seam is available.
- **Delivery-backed publication.** A checkpoint can advance only after the
  final provider body is verified and the successful request is post-settled.
- **One profile, one source realm.** The read-only canonical service can supply
  peer plugins without exposing private storage internals or borrowing another
  profile's databases.

## How it works

1. The compatible host maintains canonical lineage, change and source proofs.
   Background preparation verifies finite pages without calling a model.
2. The foreground admits a bounded complete-group window and compiles the
   rolling bridge; question recall separately selects relevant verified groups.
3. Both share the output budget and project into the real current-user carrier,
   without creating a new conversation role.
4. Hermes estimates the final SDK body after provider transforms. If needed,
   the host removes only the owned overlay; the native request remains usable.
5. `post_api_request` may conditionally publish a checkpoint and write a
   body-free receipt. Subsequent reuse revalidates its source proof.

Recall-only delivery never advances retirement or checkpoint CAS. A successful
store write is `stored_unvalidated`, not proof that the next turn can reuse it.
Ambiguous, changed, incomplete or over-budget material does not acquire delivery
authority.

## Installation

Choose the exact **0.20.5** host/plugin pairing from
[PROVENANCE.md](PROVENANCE.md) and [PROGRESS.md](PROGRESS.md) first.
Apply the ordered patches to that host; the baseline twelve alone do not
provide the indexed long-history/recall path.

With an initialized Hermes profile and the compatible host:

```bash
hermes plugins install Aryuan026/HermesContinuity \
  --ref <reviewed-40-character-plugin-commit> --no-enable
hermes plugins doctor hermes-continuity
hermes plugins enable hermes-continuity
```

The placeholder must be replaced with the reviewed full SHA. Install disabled,
check Doctor, then enable in the intended profile. Original-sentence search
remains Hermes's native `session_search`. No replacement memory backend or
search tool is installed.

## Configuration and limits

Defaults in [plugin.yaml](plugin.yaml):

- Recent bridge horizon: **72 hours**.
- Canonical source input: **24,000 estimated tokens** per build.
- Accepted bridge plus recall output: **2,048 estimated tokens**.
- Full-prefix fallback: **2,048 physical rows / 4 MiB** before decoding.
- Stored checkpoint budget: **1 MiB**.
- Indexed foreground groups/window: **2,048 rows / 4 MiB**; recall admits at
  most **24 groups**, from up to **three** keyword queries.
- Recall auxiliary calls share `summary_timeout_seconds`; they do not each
  acquire a new full timeout. Empty or failed recall preserves a valid bridge.
  Planning adds one bounded auxiliary call; nonempty candidates may add a
  second, besides the rolling summary. This is not a token-saving guarantee.

These are work/serialized-payload bounds, not hard Python RSS limits or exact
provider-tokenizer guarantees. The horizon controls delivery, **not automatic
history deletion**. Index completion does not trigger whole-history summaries.

Canonical history remains in the active profile's `state.db`. Derived metadata
is fixed under `plugin-data/<host-owned-plugin-namespace>/continuity.sqlite3`;
there are no arbitrary database-path settings. Checkpoint v2 and compact v3
have separate storage; checkpoints contain generated bridge material and
source proof, not another transcript. Receipts/status are body-free.

This is an experimental working-context component, not a permanent memory
archive or a guarantee of perfect recall. Historical image pixels are not
repeatedly injected; recorded image meanings are used by the bounded path.
`codex_app_server` is unsupported; ambiguous MoA transport cannot publish a
checkpoint. Natural relevance, latency and sustained stability need their own
runtime evidence.

## Verification

Use a Python environment with the dependencies of the exact patched host:

```bash
PYTHONPATH=/path/to/patched/hermes \
HERMES_SOURCE_ROOT=/path/to/patched/hermes \
python -B -m unittest discover -s tests -v
```

For the paired production-entrypoint test, also set
`HERMES_GLOBAL_HOT_ROOT=/path/to/reviewed/HermesGlobalHot`. Real-host tests are
conditional without these roots; inspect skips rather than calling them a
host pass. Fixtures/provider responses are synthetic, not live QQ/WeChat or
a measured token-saving result. Resource benchmarks and their boundaries are
documented in [RESOURCE_GUARD.md](RESOURCE_GUARD.md).

## Maintenance

For each Hermes release: trace the changed host contracts, replay against an
isolated exact checkout, verify both positive delivery and native fallback,
then update this compatibility list with the host/plugin refs and evidence
level. Version ranges in manifests are dependency constraints, not an
upstream compatibility promise. Preserve the previous accepted lane until the
new pairing is qualified; never assume old patches apply unchanged.

Source review, tests, merge, install, enablement, delivery and natural quality
are separate states. This README change does not advance any runtime state.

## Documentation

- [PROGRESS.md](PROGRESS.md): dated acceptance, deployment and observation.
- [PROVENANCE.md](PROVENANCE.md): extracted AsherieSystem lineage, host patch
  identities/digests and intentional omissions.
- [LONG_HISTORY_PROTOCOL.md](LONG_HISTORY_PROTOCOL.md) and
  [LONG_HISTORY_IMPLEMENTATION.md](LONG_HISTORY_IMPLEMENTATION.md): indexing,
  paging, publication and resource contracts; read their dated scope.
- [BLOCK4_TARGET_VALIDATION.md](BLOCK4_TARGET_VALIDATION.md): target validation.
- [DONOR_RECALL_REPAIR_NOTES.md](DONOR_RECALL_REPAIR_NOTES.md): recall repair
  lessons for the original system.
- [SECURITY.md](SECURITY.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md):
  trust, privacy and upstream notices.

## License

[MIT](LICENSE). Retained Hermes/Nous code keeps its upstream notices.
