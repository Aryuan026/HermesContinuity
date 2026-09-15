# Progress

## Current Wave 7 public replay candidate

- Wave 5 Continuity is independently accepted at
  `8eb44f3e8afe5d134691d258607ee67af518d706`, tree
  `61b65180ef0c484657330b63222038dcf26888f6`. Wave 6 Global Hot is
  independently accepted at `01918856aa46f80ca17dd67d079eed1b7261f85f`,
  tree `5650584c434de4ba086e0f40d45a447ee40f9302`.
- Copied the 35 accepted Hermes 0.21 patches byte-for-byte from their reviewed
  Assembly owner into four versioned public directories. A digest manifest and
  materializer require pure upstream `29112bef...`, all 35 exact bytes, and
  assembled tree `5e82789d...` before tests can start. The twelve top-level
  0.20.5 artifacts remain unchanged.
- The public workflow now runs the complete changed-host seam selection, both
  plugin suites, and the paired production `AIAgent.run_conversation` entry.
  The old paired fixture now carries real H13 human proof instead of expecting
  pre-H13 rows to qualify for Global Hot.
- The workflow installs both checked-out exact Git revisions with official
  `hermes plugins install --ref ... --no-enable`, verifies pinned metadata and
  disabled list state, runs Continuity native Doctor and Global Hot joint
  Doctor, removes in dependency-reverse order, and requires no remaining
  plugin directory plus exact metadata `{}`.
- Local replay of the published selection is `2247 passed`, `5` optional
  skips, `1` unchanged upstream OAuth-mock deselection, and `23` subtests. The
  materializer reconstructs the accepted tree exactly; both plugin suites and
  the corrected paired entrypoint are Green against the same host.
- This is a public-workflow candidate pending exact-head Actions and
  independent review. Production plugin algorithms, host source, profile
  configuration, target databases, services, enablement, deployment, network
  providers, and real QQ/WeChat traffic remain unchanged.

## Current Wave 5 candidate

- Lifecycle: active, Continuity-only external-review candidate. Wave 6 is not
  open.
- Manifest version: 0.5.0.
- Accepted host baseline: Hermes Agent 0.21.0 commit
  `13900108780ae712059075200b243aa049c634cf`, tree
  `5e82789d9984f8c338c09bdd0ebb31794af1f0dc`, with Wave 4 assembly receipt
  `455ff4b442e15ee17a1b5ebb96fe4620e6acc322`.
- H13 source authority: the adapter now asks the host classifier to decide each
  complete logical group. Session/source/display labels, visible text, and the
  removed `additional_human_sources` setting cannot mint `human`. Missing and
  pre-H13 proof remains `unknown`.
- Complete-group obligation: user rows, interim assistant/tool rows, the final
  assistant, matching superseded physical generations, and ancestor/tip clones
  all participate in the proof decision. A conflict makes only the affected
  group unknown. An interrupted scheduled user-only tail cannot merge into a
  later human group.
- Runtime proof: the local exact-host suite is 219/219 Green with one expected
  legacy dual-plugin skip. The Continuity-only production
  `AIAgent.run_conversation` test covers primary-provider failure, model/window
  fallback, final-provider delivery, post settlement, next-turn checkpoint
  reuse, and manager unload/reload. The real SessionDB/Lean test covers a
  tool-follow-up group, physical in-place archive, separately constructed
  compression lineage, synthetic-summary exclusion,
  close, and read-only reopen; both the production full-prefix reader and the
  bounded lineage reader recover all 30/30 complete groups.
- Storage compatibility: `ContinuityMetadataStore`, checkpoint v2, receipt
  schema, CAS, and settlement code are unchanged. Existing restart tests read
  back the pre-H13 checkpoint fixture and body-free receipt rows after reopening
  the same database.
- Frozen surfaces: `context_compactor.py`, `thread_continuity_runtime.py`, and
  production `runtime.py` are unchanged; the 72h / 24,000 / 2,048 budgets are
  unchanged. Hermes host code and Global Hot were not modified.
- Public evidence boundary: the repository workflow runs host-independent
  plugin unit tests using a minimal H13 contract fixture plus the accepted
  predecessor request-overlay seam. It does not claim exact 0.21 host replay.
  Publishing the full 0.21 patch chain and replay workflow remains an assembly
  landing-wave task after both plugins are accepted.
- Deployment boundary: the accepted 0.20.5 installation remains the control.
  This Wave 5 revision has not been installed, enabled, deployed, or observed
  on a live channel.
- Long-history boundary: checkpoint v2 and the main continuity source read are
  still O(total session history). A stable Hermes prefix-proof seam and compact
  checkpoint v3 remain required before formal long-lived-profile use.

## Retained predecessor evidence

- Source extraction: completed from owner-authorized AsherieSystem revision
  `ddfb1e9aeb7c6f7797912e959a0970c621875c83`.
- Hermes adapter: implemented against canonical `SessionDB` reads with raw-row
  collision audit and a generated-checkpoint/body-free-receipt store.
- Real-history compatibility preflight: the full Tencent QQ source projected
  302 complete visible groups / 471 messages in 0.79 seconds without exposing
  message bodies. Known `session_meta` and API-only scaffold rows are excluded;
  host-equivalent consecutive user merging and typed assistant continuations
  preserve the remaining visible role runs. This is body-free read-only
  source evidence, not conversational behavior proof.
- Request runtime: implemented for request projection, execution proof, and
  final provider-body proof, and `post_api_request` checkpoint CAS.
- Canonical source service: implemented as the profile-local
  `hermes-continuity:canonical-source.v2` service with bounded physical reads,
  compression-lineage union, complete dialogue groups, closed source classes,
  consumer-bound class filtering, and body-free policy-exclusion trace.
- Predecessor host prerequisites: twelve ordered generic patches are recorded
  under `patches/`; the final compatible 0.20.5 Hermes core commit is
  `5a680e5e38625fb3275b4bf6973a40d089ec11a7` (`hermes.transport.v3`,
  manifest-v2 installer, joint Doctor, and shared request-overlay v2 host
  acceptance).
- Host verification: closed finish-state matrix 537 passed / 6 skipped;
  final-body budget targeted 169/169 and associated 306/306; verified wakeup
  provenance 5/5 over the real loopback API path. These are local exact-tree
  runs, not public-CI claims.
- Plugin verification in this correction block: the compatible-Hermes suite
  was 239/239 Green after source-policy, metadata-ownership, and real-host
  wiring correction. After removing the unregistered donor gateway,
  context-epoch/fixed-finalizer, and standalone metadata inspection/write
  paths, the remaining real-host suite is 221/221 Green. A before/after probe
  against exact pre-cleanup revision `5c0b84e` produced byte-identical
  wrapper-consumed compiler, bridge, request projection, provider request, and
  settlement output for raw, retirement-only, and summarized fixtures. The
  final-guard test still covers both execution-middleware registration orders.
- Checkpoint-v1 retirement candidate: body-free census receipt
  `HermesPrivateAssembly@0a7e0c648ff37c16025ec874c3508640716e8793`
  found zero top-level `thread_continuity_checkpoint.v1` rows and zero malformed
  checkpoint JSON across the known local and Tencent owner-managed estate. The
  corresponding top-level builder, normalizer, migration projection, and
  legacy physical-owner relation are removed in this review candidate;
  unexpected top-level v1 now fails closed without projection or migration.
  Checkpoint v2 and the nested retirement/recent-bridge v1 schemas remain.
- Fixed profile-realm candidate: canonical reads are pinned to the active
  profile's `state.db`, Continuity metadata is pinned to that profile's
  host-owned plugin-data namespace, and the obsolete `state_db` / `metadata_db`
  settings are removed. A real two-profile `PluginManager` test keeps the two
  read-only SessionDB handles and receipt stores separate after ambient profile
  overrides are reset; the complete compatible-Hermes suite remains 221/221.
- Shared-overlay candidate: provider carrier selection, exact projection,
  scoped removal, canonical request hashing, and final-budget dispositions now
  live in the generic Hermes host seam. Continuity's duplicate projector and
  its mirror test file are removed; execution proof remains strict while the
  final SDK guard can compose with another owner that has already removed its
  own block. The v2 overlay contract additionally forbids byte-derived
  ownership reminting, commits budget dispositions only after host acceptance,
  and records final-body estimates even when no filter is registered. The
  exact host plus paired Global Hot suite is 205/205 after this correction.
  That exact-host replay was valid for the accepted 0.20.5 generation; it is
  not evidence for the current 0.21 candidate.
- Plugin lifecycle proof: exact public candidates `698fd4d` and `9f01f61`
  installed through the official CLI into a disposable profile with full
  commit pins and remained disabled; Continuity passed native Doctor, Global
  Hot passed joint Doctor with Continuity, and official removal left no plugin
  directory or install-metadata entry. This is reversible local installation
  evidence, not target-profile deployment.
- Real-host wiring proof: actual Hermes plugin discovery loaded Continuity and
  Global Hot, two production `AIAgent.run_conversation` turns delivered both
  blocks exact-once, Continuity and Global Hot settled to their real SQLite
  stores, and a manager unload/reload read back checkpoint revision 1. A real
  provider-error turn produced no new delivery receipt. The two successful
  turns used CLI and gateway-tagged platform contexts; this is synthetic local
  host proof, not a live channel canary.
- External review: the first public candidate was judged suitable only for a
  disposable canary. Its source-policy findings are incorporated in this
  replacement root; repeat exact-revision review remains the current gate.
- Runtime installation and target canary truth are intentionally owned by the
  exact external assembly receipt rather than inferred from this source tree.

The current review gate is Wave 5 Continuity H13 consumption. Target
installation, canary authorization, and runtime evidence remain owned by the
external assembly rather than inferred from this source tree.
