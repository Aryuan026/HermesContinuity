# Progress

- Lifecycle: active, local implementation.
- Manifest version: 0.4.0.
- Source extraction: completed from owner-authorized AsherieSystem revision
  `ddfb1e9aeb7c6f7797912e959a0970c621875c83`.
- Hermes adapter: implemented against canonical `SessionDB` reads with raw-row
  collision audit and a generated-checkpoint/body-free-receipt store.
- Request runtime: implemented for request projection, execution proof, and
  final provider-body proof, and `post_api_request` checkpoint CAS.
- Canonical source service: implemented as the profile-local
  `hermes-continuity:canonical-source.v2` service with bounded physical reads,
  compression-lineage union, complete dialogue groups, closed source classes,
  consumer-bound class filtering, explicit custom-frontend source ownership,
  and body-free policy-exclusion trace.
- Host prerequisites: eleven ordered generic patches are recorded under
  `patches/`; the final compatible Hermes core commit is
  `ccd7bf350ca54a44b7351904e079f5ffdb64eec0` (`hermes.transport.v3`,
  manifest-v2 installer, joint Doctor, and shared request overlays).
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
  own block. The exact host suite is 202/202 after this consolidation.
  The public-shaped plugin suite is 187 pass / 15 expected real-host skips;
  public CI also replays all eleven patches and runs the 17 shared-overlay host
  tests before the plugin matrix.
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
- Long-history boundary: checkpoint v2 and the main continuity source read are
  still O(total session history). A stable Hermes prefix-proof seam and compact
  checkpoint v3 remain required before formal long-lived-profile use.
- Runtime status: not installed, not enabled, not deployed, and not validated
  in a live Hermes conversation.

The next review should assess H11's shared ownership boundary, the deleted
plugin copies, and public patch replay. No installation or deployment is
authorized here.
