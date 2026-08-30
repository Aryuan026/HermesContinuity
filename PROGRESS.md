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
- Host prerequisites: eight ordered generic patches are recorded under
  `patches/`; the final compatible Hermes core commit is
  `7c183e81832c81e29f6d095a15bb7c8cd080ee5c` (`hermes.transport.v3`).
- Host verification: closed finish-state matrix 537 passed / 6 skipped;
  final-body budget targeted 169/169 and associated 306/306; verified wakeup
  provenance 5/5 over the real loopback API path. These are local exact-tree
  runs, not public-CI claims.
- Plugin verification in this correction block: the compatible-Hermes suite is
  238/238 Green after source-policy and metadata-ownership correction. The
  prior clean replay of all
  eight exported patches passed 229/229; repeat clean replay belongs to the
  final joint-candidate gate. The final-guard test covers both
  execution-middleware registration orders.
- External review: the first public candidate was judged suitable only for a
  disposable canary. Its source-policy findings are incorporated in this
  replacement root; repeat exact-revision review remains the current gate.
- Long-history boundary: checkpoint v2 and the main continuity source read are
  still O(total session history). A stable Hermes prefix-proof seam and compact
  checkpoint v3 remain required before formal long-lived-profile use.
- Runtime status: not installed, not enabled, not deployed, and not validated
  in a live Hermes conversation.

The next status update should record the corrected exact revisions and repeat
external review result. No installation or deployment is authorized here.
