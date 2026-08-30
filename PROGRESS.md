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
- Host prerequisites: ten ordered generic patches are recorded under
  `patches/`; the final compatible Hermes core commit is
  `969cf5bdbc3a110e475c02ed8e4ee84f64be32ed` (`hermes.transport.v3`,
  manifest-v2 installer, and joint Doctor).
- Host verification: closed finish-state matrix 537 passed / 6 skipped;
  final-body budget targeted 169/169 and associated 306/306; verified wakeup
  provenance 5/5 over the real loopback API path. These are local exact-tree
  runs, not public-CI claims.
- Plugin verification in this correction block: the compatible-Hermes suite is
  239/239 Green after source-policy, metadata-ownership, and real-host wiring
  correction. The prior clean replay of the eight runtime patches passed
  229/229; repeat clean replay belongs to the final joint-candidate gate. The
  final-guard test covers both execution-middleware registration orders.
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

The next review should assess practical installation, patch replay, upgrade and
rollback behavior, then record the corrected exact revisions. No installation
or deployment is authorized here.
