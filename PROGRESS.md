# Progress

- Lifecycle: active, local implementation.
- Manifest version: 0.4.1.
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
  consumer-bound class filtering, explicit custom-frontend source ownership,
  and body-free policy-exclusion trace.
- Host prerequisites: twelve ordered generic patches are recorded under
  `patches/`; the final compatible Hermes core commit is
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
  Public CI replays all twelve patches, installs the materialized host, exports
  `HERMES_SOURCE_ROOT`, and runs the shared-overlay plus real-host plugin tests
  before the Python 3.11/3.12 matrix completes.
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
- Long-history guard: the request path first reads at most 2,049 physical rows.
  Sessions above the default 2,048-row budget now leave the native Hermes
  request unchanged before any complete compacted-history decode or Continuity
  compiler call. The reason is visible as
  `source_physical_row_limit_exceeded`; 211 compatible-host tests pass with one
  existing conditional proof skipped. Checkpoint v3 is still required before
  Continuity itself can serve arbitrarily long sessions.
- Runtime installation and target canary truth are intentionally owned by the
  exact external assembly receipt rather than inferred from this source tree.

## Block 1 complete-entry resource guard (0.4.2 source candidate)

- Builds on merged 34780f0 / 0.4.1. Same-snapshot SQL row/byte probes now precede
  full-prefix payload fetch and the existing host decoder. Source-unavailable
  read_bundle does not open the checkpoint store.
- Old checkpoints are byte-gated before transfer/decoding. New checkpoints use
  the same write budget; physical delivery and publication failure remain
  distinct. Session status reads metadata only, never checkpoint JSON.
- Local Python 3.12 compatible-host run: 220 unittest cases, 219 passed and one
  existing paired-host conditional skip; host overlay/middleware 42 passed plus
  15 subtests. Eight entry-resource regressions and UTF-8 write/read boundaries
  pass. Independent read-only diff review is complete after the write-budget
  correction.
- The disposable benchmark exercises actual source read, audit, compiler,
  request/execution/post, SQLite settlement and status with synthetic transport.
  Small history and 2,000 clones retain two-round projection/receipt readback;
  oversized cases leave the native request unchanged. See RESOURCE_GUARD.md for
  exact baseline, per-phase figures and evidence limits.
- No compiler/checkpoint-v2 schema change, host patch modification, Global Hot
  product change, deployment or observation. This is transitional protection,
  not restoration of >2,048-row Continuity. Blocks 2/3 remain separate.
- After external acceptance, this block's exact SHA becomes the preferred v3
  rollback baseline; 34780f0 is retained as historical recovery only.

## Block 1 accepted / Block 2 protocol review

- Owner external review accepts Block 1 at
  `1d6f502f2c21636d9f75b31fcc46f109c3bfece6`, tree
  `cd27dc86cf53347c94946388025820a97ab620e7`. CI-P2-01 is closed; the successor
  only adds explicit Bash/pipefail to the resource benchmark step.
- Review readback of Actions `36329604375`: both Python lanes pass 42 host
  tests plus 15 subtests, 219 plugin tests plus one existing conditional skip,
  and all seven disposable benchmark cases. These are prior exact-head CI
  evidence, not a new full-suite execution in this docs-only block.
- This accepted SHA is the preferred future v3 **source** rollback baseline.
  PR #3 acceptance does not itself merge, install, deploy or change Assembly pins.
- Block 2 source inspection and its candidate protocol are in
  [LONG_HISTORY_PROTOCOL.md](LONG_HISTORY_PROTOCOL.md). The proposal selects
  conditional storage with per-use source validation, body-free incremental
  preparation and compact v3 proofs. Protocol/concurrency tests remain required
  implementation evidence, not claimed results of this specification.
- Only documentation changes in this block. Block 3 remains unopened pending
  protocol review. Accepted 0.21.3 work, Global Hot and all production code stay
  unchanged; no host upgrade, real database access or server operation occurred.

## Block 2 accepted / Block 3 implementation

- The owner accepted the protocol at `e54472f2f64863c00cf75aa17c29da1b3f969e84`
  and opened Block 3. The preceding "unopened" statement is the historical
  Block 2 receipt, not the current phase.
- Implementation adds a host-owned transactional journal/canonical index,
  bounded plugin group preparation and checkpoint v3. The original twelve
  patches, checkpoint v2 and the separate canonical-window service remain.
  Donor recent selection, chunk summary/acceptance and budget policy are reused.
- Read the current code map, recovery procedure and evidence limits in
  [LONG_HISTORY_IMPLEMENTATION.md](LONG_HISTORY_IMPLEMENTATION.md).
- A genuine >2,048-row production AIAgent path has exercised final provider
  body, post settlement and manager unload/reload readback with a synthetic
  provider. Repeat testing exposed needless metadata-triggered prefix rebuild;
  independent review also exposed unbounded suffix reset and continuous-append
  starvation. The fixes also preserve changes arriving during a bounded suffix
  reset; an independent real-SessionDB reproduction now rejects the old prefix.
  Those reported findings are closed. The exported host has 40/40 targeted
  tests passing; an earlier individual passing run was not used as acceptance.
- V2 nonempty checkpoint and receipt fields are checked unchanged after v3
  creation. Current tests keep source validity, delivered outcome and conditional
  storage separate; runtime failure does not resend the provider.
- Local candidate verification: 293 plugin cases, 292 pass and one existing
  paired-Global-Hot conditional skip; exported host history 40/40; five indexed
  scale cases each retain two projections/two receipts/one summary; original
  twelve-patch resource-guard benchmark 7/7. Full figures and evidence scope are
  in LONG_HISTORY_IMPLEMENTATION.md. Public exact-head CI is reported on the PR,
  independently of these local results.
- Protocol acceptance is exercised through actual replacement/sidecar/reaction,
  compression-child, deletion/pruning, session, import/branch/API/A2A/recovery
  write owners. Three real subprocess exits cover uncommitted host pages,
  host-committed/plugin-not-published and uncommitted plugin staging. Lease expiry
  is controlled in tests; restore explicitly requires stopped writers and the
  existing invalidation handoff. These are disposable storage/handler tests,
  not complete frontend or live provider tests.
- This remains source-only work on the named 0.20.5 compatibility lane. No
  Global Hot change, 0.21.3/0.21.5 rewrite, target installation, merge, real data
  access, deployment or observation has occurred. Assembly selected pins remain
  unchanged. External implementation review is still required.

## Block 3 external-review correction candidate

- External review held `2cfb512c` for two confirmed defects: SQLite may
  materialize a large value during the size probe; cancelled compilation
  retained process-wide workset admission before plan installation.
- Shared SQLite value guards cover preparation probes and foreground reads,
  with typed overflow and borrowed limit/transaction restoration. The exported
  host correction is patch 14, at `a488b6ebf46765a7323bb3e862bcbb77bccbd172`;
  original thirteen artifacts remain unchanged. Runtime admission now has a
  compile-owned `finally` until successful plan transfer; cancellation still
  propagates and other profile leases remain intact.
- Local Python 3.12: host 42/42; plugin 296 total, 295 pass, one existing paired
  skip; scale 5/5 and original resource benchmark 7/7. Actual-host native value
  benchmark 3/3, with external process deadlines. Real async summary
  cancellation plus manager unload/reload preserves the positive AIAgent
  projection/settlement/reuse path with a synthetic provider.
- Full measurements, prior-source controls and limitations are in
  LONG_HISTORY_IMPLEMENTATION.md. CI now executes and uploads the native
  benchmark on both declared Python versions, using Bash pipefail.
- Next checkpoint is external correction review of PR #5. No merge, target
  mutation, real-data access or promotion to accepted/deployed status.

## 2026-09-30 — Block 3 accepted; Block 4 target validation opened

- Owner relayed external acceptance of correction source `191853bf`; Blocks
  1 and 2 remain accepted. The preceding candidate-only entries are historical.
  PR #5 remains unmerged; acceptance does not imply deployment.
- Existing deployment/observation authorization now applies to Block 4. The
  target still runs the twelve-patch 0.20.5 host and Continuity `34780f0`.
  Target-copy replay matches the three changed host files byte-for-byte.
- Real owner databases were consistently backed up to a protected disposable
  workbench. The copied metadata has one nonempty v2 checkpoint and 94 receipts.
  No original database, runtime source/config or gateway lifecycle was changed.
- Target validation found a preparation-progress blocker: the 256-row page
  repeatedly exhausts the 50ms transaction budget before its first commit.
  A 180-second copy-only run never creates a committed domain progress row.
  Five diagnostic 32-row quanta with the unchanged 50ms budget commit 529
  canonical records. This is a diagnostic parameter control, not a production
  fix or completed target replay.
- Target plugin suite: 296 total, 293 pass, two conditional skips, one failure
  in real-host history preparation convergence. Target pytest is absent; the
  pytest host suite was not executed and no dependency was installed.
- See BLOCK4_TARGET_VALIDATION.md. Next work is the bounded preparation-page
  target adaptation and its regression/review, then the same copy validation
  and authorized deployment. No macro-plan reopening, Global Hot change or
  newer Hermes baseline. The 48–72h observation clock has not started.

## 2026-09-30 — Block 4 bounded preparation correction candidate

- The owner authorized this target-granularity fix. Additive patch 15 exports
  host `9364e363b0d57a17399972e0a094d55369e8fd41`, tree
  `87846e90406265717a904fc7e0a581e41c032579`; original fourteen artifacts and
  plugin production code are unchanged. It stops building/resetting/physical
  pages between completed rows with transaction-close reserve, without
  changing the default 256 rows / eight pages / 50ms or SQL interruption.
- The new slow-CPU regression first reproduced zero durable progress on the
  accepted host. Corrected host 45/45 via the real upstream test runner;
  local plugin 296 total / 294 pass / two skips. Retained scale 5/5 and native
  byte-guard 3/3 pass. Public exact-head successor CI is pending at commit time.
- Target isolated source hashes match this host; existing Python 3.11.15 runs
  the plugin suite with 296 total / 294 pass / two skips, about 158s. This
  includes real-host synthetic projection/settlement/reload/reuse, not live QQ.
- Fresh owner copies, without the diagnostic index, now commit default
  preparation progress: 67,447 physical rows; 458 quanta / 21.463s to a
  `canonical_clone_audit_collision` at 29,460 canonical records; peak RSS
  47,288 KiB. Thus the timeout reproduction closes, but owner source readiness
  remains blocked by a distinct persisted `display_kind` conflict. Bounded
  diagnosis outputs column names only. No source authority was relaxed.
- One existing nonempty v2 checkpoint passes bounded JSON/hash/schema decode;
  full-row fingerprints of the owner row, v2 checkpoint and all 94 receipts
  remain identical. No source-valid v2 reuse/migration is claimed, and this
  owner-copy path invoked no provider. See BLOCK4_TARGET_VALIDATION.md.
- Deliver the bounded fix as a reviewable PR. The owner-history conflict
  remains a target qualification question; no merge/deploy/restart/original DB
  write occurred. Gateway PID/restart count are unchanged, Global Hot and
  0.21.x lanes untouched, selected Assembly pins unchanged. Observation has
  not started. Preferred source rollback remains accepted Block 1 `1d6f502f`.

## 2026-09-30 — Block 4 external-review test correction

- Prior push CI `36703797331` at `a692914` remains recorded as failure: 3.11
  passed; 3.12 retained host 45/45 but had two plugin failures and skipped later
  indexed/value benchmarks. This successor does not relabel that evidence.
- Only test fixtures/diagnostics and the existing evidence docs change. Crash
  children force real multi-quantum progress via the existing host API, retain
  exact 74/75 exits and recovery readback, and stop at finite quantum/process
  bounds instead of assuming one call reaches the fault boundary.
- Real-host reload now separates legitimate pending/native with no new receipt
  from ready/prepared exact-once bridge, summary reuse and settlement. Positive
  synchronization happens after actual user persistence; no production wait or
  budget changes. Body-free source/checkpoint/cursor/admission diagnostics are
  retained. The controlled pending reproduction is not claimed as the proven
  reason for the earlier undiagnosed CI failure.
- Local unchanged host 45/45; plugin 296 / 294 pass / two conditional skips;
  focused legacy-writer/recovery 7/7; indexed scale 5/5, native value guard 3/3,
  pre-index resource guard 7/7. Public successor results are pending at commit
  time. See BLOCK4_TARGET_VALIDATION.md for the test-only evidence boundary.
- PR #6 remains reviewable/unmerged; no Assembly pin or target mutation. The
  owner-history conflict and deployment/observation qualification remain open.

## 2026-09-30 — accepted PR #6; Block 4 owner-copy qualification continues

- Owner relayed external PASS at `ce3fb0e`; the preparation/test correction's
  two blockers are closed. Blocks 1–3 remain accepted.
- Read-only bounded diagnosis on the retained owner copy identifies 39
  exact stored-key physical members: one archived `internal_notification`, 37 archived
  untyped copies and one active untyped copy. This is a real provenance
  mismatch, not a NULL/empty-string representation difference. No body,
  private locator or canonical-row modification is part of this receipt.
- Existing reader/compaction paths preserve the field; the original historical
  loss is not attributed to an unproven writer. Ignoring the field is rejected.
  Complete-group local conflict handling is proposed for owner confirmation,
  not silently implemented under the frozen strict clone-audit contract.
- Target remains active/running with unchanged PID and zero restarts. No
  deployment or observation starts; no Global Hot, upstream, original DB or
  selected recovery change. See BLOCK4_TARGET_VALIDATION.md.

## 2026-09-30 — owner-approved evidenced clone recovery candidate

- The owner rejected quarantine/exclusion: preserve dialogue content, repair
  producer metadata propagation, and recover only clones with explicit earlier
  evidence. The former isolation proposal is not an implementation or fallback.
- Additive patch 16 fixes shared Gateway replay and the indexed history view;
  canonical rows, raw physical signatures, compiler/checkpoint/CAS/budgets and
  Global Hot remain unchanged. Existing v1 index proofs are rejected and their
  derived state rebuilt under rule v2 before any new proof is accepted.
- Local exact host: 55 history tests and 11 actual Gateway tests pass. Plugin:
  297 cases, 295 passed, two existing conditional skips. The real discovered
  AIAgent test now includes old missing-tag clones, retaining original rows,
  post-settlement, next-turn reuse, unload/reload and error/cancellation checks.
  Indexed scale 5/5 and native value guard 3/3 remain Green.
- Real owner-copy qualification crossed the prior tag collision but stopped at
  `overflow / history_row_byte_limit_exceeded`: 67,447 physical rows, 46,856
  indexed canonical records, 990 quanta / 42.729s, peak 42,288 KiB. This is not
  a ready source or owner-history bridge/settlement/reuse result. No body or
  private locator is published; the next byte boundary is diagnosed read-only.
- No canonical exclusion, budget increase, production install/enable/restart,
  merge, upstream upgrade, Global Hot change or observation start. Public
  successor CI and external review remain pending; selected Assembly pins
  remain unchanged. See BLOCK4_TARGET_VALIDATION.md for evidence boundaries.

## 2026-10-02 — integrated streamed-value candidate, target recall barrier

- Additive patch 17 carries bounded giant-value verification through the real
  source/index/compiler consumers. First sixteen artifacts are unchanged.
  Local host 67/67 plus retained 53 tests/15 subtests pass; complete compatible
  plugin suite 303/303 includes giant real-host and exact paired entrypoints.
  Independent fresh patch replay matches host tree `dadd41d4...` exactly.
- 16/64-MiB full-chain benchmarks pass: two receipts, one summary, next-turn
  reuse, about 12.5/13.5 MiB measurement-peak increments, not service totals.
- Owner copy now prepares all 67,447 physical records to ready; its foreground
  still rejects 4,225 rows after an early uncompacted group. There are 139
  uncompacted groups interspersed before 3,153 later compacted groups. This
  exposes a retirement/recall ownership barrier, not another giant-value read
  failure. No memory is removed or marked retired to make it pass.
- Independent query recall without retirement authority is proposed, pending
  owner agreement. Source-candidate PR/public CI, target qualification,
  deployment and 48–72h observation remain distinct. No live change, Global Hot
  algorithm change or .21.x adaptation occurs in this candidate.

## 2026-10-02 — owner-approved bounded question recall candidate

- Owner approved independent query recall after the preceding retirement
  barrier; that earlier pending decision is now superseded, not a deletion or
  relabeling of live groups. Patch 18 reuses native FTS/LIKE for bounded IDs.
  Complete groups reuse the existing page/occurrence/fingerprint proof path;
  donor compiler, checkpoint-v2/v3 and CAS are unchanged.
- Existing auxiliary LLM completion plans up to three keywords and, for
  nonempty admitted candidates, selects/summarizes complete relevant groups.
  Recall is ephemeral; it shares the existing overlay/output/final-provider
  budget, and post-settlement records IDs/hashes/counts only. Recall-only
  delivery cannot publish or retire a checkpoint. Invalid selection, source
  rewrite, late expansion, provider error and reload are covered.
- The initial owner-copy attempt failed honestly at
  `native_search_sqlite_interrupt`; no receipt was written. Query-plan probes
  found domain-first FTS rescans and global clone scoring. Native newest
  postings plus the existing winner index close that reproduced bottleneck
  without increasing the 50-ms SQL deadline or creating another index store.
- The same protected copy then returns 24 complete groups / 80 canonical rows /
  365,198 admitted bytes in 0.065s. Two fresh runtimes deliver and settle with
  two auxiliary calls each (0.109s / 0.085s synthetic chains), peak 50,584 KiB.
  All fields of the existing v2 checkpoint and 94 receipts remain equal;
  v3 checkpoint count remains zero. Earlier full preparation was 5,478 quanta /
  256.758s, peak 121,008 KiB. These phases are separate: the final probe reuses
  the prepared index but revalidates its real token. Models/providers/transport
  are substitutes, not natural relevance, QQ latency or deployment evidence.
- Final-source copy rerun admits the same 24 groups / 80 rows / 365,198 bytes
  in 0.065s; two fresh synthetic runtime chains take 0.106s / 0.086s, peak
  50,588 KiB. All fields of the then-existing 96 receipts (the original 94 plus
  the first probe's two) and the nonempty v2 checkpoint remain equal. Two new
  body-free recall receipts are appended only to that disposable copy.
- Local retained product suite is 314/314 with the accepted old module enabled;
  the final page-status preservation is also checked by 24/24 history-index tests;
  exact host search/history/overlay suite is 111 plus 15 subtests. Real
  AIAgent recall passes across a 16-MiB historical image, live hole, final-body
  post-settlement, next-turn manager unload/reload and provider error. Public
  successor results are pending at commit time; old c0 CI is not its evidence.
- No original database, Global Hot, donor source, .21.x lane, selected Assembly
  pin, install/enable/restart/merge or natural observation is changed. Review
  candidate and live-use acceptance remain separate. The requested donor
  reference Markdown follows actual reviewed deployment, not this source receipt.

## 2026-10-02 — B4-GIANT-REWIND-01 source correction

- External review of `2fdc6ec` keeps recall positives but reports one new P1:
  streamed proof insertion follows a successful audit even when a legal rewind
  creates no parent member. The candidate remains HOLD pending this increment's
  independent re-review; Blocks 1–3 are not reopened.
- Actual compatible-host red matrix: giant plain text and encoded multimodal
  rewinds fail with SQLite FK errors, while five ordinary/active/compacted
  controls pass. Patch 19 changes only that proof INSERT to select its actual
  member in the same transaction. No exception suppression, fake parent,
  canonical-row change, schema or budget expansion.
- Seven real-host cases now pass, with an external timeout per child and two
  separate interpreters: first-prepare rewind, reopen/rollback rebuild, raw
  field preservation, original-byte hash verification, restore and a further
  indexed rewind/redo. The retained host suite is 118/118; complete compatible
  plugin suite is 314/314, including positive recall and real AIAgent delivery.
- Fresh exported-patch replay reconstructs host tree
  `d212962d9c0a0a49000d1132fe9e5b68d739821a` and independently passes the seven
  new lifecycle cases. Host commit `964c65ab` directly follows `69baf5ef`.
  First eighteen artifacts and all plugin production code remain unchanged.
- Public successor CI is pending at commit time and is recorded separately in
  the PR receipt. Read-only intent audit: PASS. No owner/copy database,
  server, Global Hot, donor, .21.x, selected Assembly/rollback pin, merge,
  install, enable, restart or observation is changed. Source/artifact candidate
  identity changes only; selected runtime recovery truth is not promoted.

## 2026-10-02 — accepted source target qualification; native FTS obstruction

- The owner relayed external acceptance of `d549c95a`, including successful
  Python 3.11/3.12 CI and synthetic merge-tree identity. Blocks 1–3 and recall
  positives remain closed; PR #6 is still open and unmerged.
- The target workbench reconstructs all seven additive patches over the actual
  clean twelve-patch host. The accepted history/content files match their
  source digests. With corrected host locators, the existing target interpreter
  passes 314/314 plugin tests with no skips; native joint Doctor also passes.
  The initial old-locator run's eleven skips are retained, not counted as new
  capability evidence. No dependency was installed.
- On the authorized prepared owner copy, controlled recall admits 24 groups /
  80 rows / 365,198 bytes in 0.139s. Two fresh synthetic runtime chains settle;
  every field of the existing nonempty v2 checkpoint and 98 receipts is
  preserved, and two recall receipts are appended only to the disposable copy.
  Retirement is unchanged. This is not natural relevance or real QQ delivery.
- Two preceding copy attempts hit the unchanged 50ms native-search deadline
  during load and remain failed results. Standalone diagnosis finds prefix
  validation at 0.5–1.7ms and successful complete searches at 1–4ms. No budget
  increase or production search change was used to obtain the controlled pass.
- The authorized maintenance attempt stops the old gateway and verifies zero
  open handles for the three databases. The existing unit reaches its stop
  timeout; a consistent 2.8-GiB state preimage then fails integrity validation.
  Source/config/install/enablement never change. The failure path starts the
  old gateway; both QQ and LightClawBot report connected under its current
  process. This is a restored control, not candidate deployment.
- Bounded examination of the frozen copy reports a malformed inverted index
  in Hermes-owned `messages_fts_trigram`. Canonical-message damage is not
  established. The host's existing native rebuild command is attempted on a
  separate byte-identical disposable copy with canonical-write guards, a
  512-MiB process limit and a 300s SQLite deadline. Rebuild reaches that deadline
  and returns `sqlite3.OperationalError: interrupted`; repair is not proven.
  Original-index repair requires the requested owner authorization. No
  original canonical row, checkpoint or receipt is rewritten.
- Independent intent audit: PASS. Selected Assembly pins remain unchanged;
  Assembly reconciliation authorization was requested separately. The 48–72h
  observation clock and post-deployment donor Markdown remain unstarted. The
  next checkpoint is native-index qualification/authorization, then resume the
  existing reversible deployment; no new architecture, Global Hot or .21.x work.

## 2026-10-02 — reviewed candidate deployed; observation started

- The owner's correction supersedes the preceding premature stop. The existing
  Block 4 maintenance proceeds through native-index qualification, original
  derived-index repair, exact disabled installation, Doctor, enable and start;
  no algorithm, PR merge or .21.x upgrade is introduced.
- Copy qualification retains the earlier failed deadlines. A longer bounded
  native rebuild completes; a separate verification-only pass reports full
  SQLite integrity `ok`, unchanged canonical counts, 199.072s elapsed and
  107,904 KiB process peak. This is repair qualification, not recall latency.
- Stopped-writer maintenance creates current backups of all three stores,
  config, installation metadata and the old plugin source. It rebuilds only
  Hermes' native `messages_fts_trigram`. TEMP guards prohibit canonical
  messages/sessions writes. Full original integrity is `ok`; canonical counts
  and all pre-existing checkpoint/receipt fields remain unchanged. No history
  is deleted or replaced with a pre-upgrade snapshot.
- Actual installed host: `34cccb142642d1035538ca998b3fdce154ad9e3b`, tree
  `70515f3669d8df2b4318af89e4158023af6707a1`, retaining upstream 0.20.5 and
  the existing QQ overlay. The three deployed history/content production files
  match the qualified target artifact. Target-base identity is not advertised
  as equality with the separately exported patch-replay commit/tree.
- Actual installed Continuity: `d549c95adc967672e642f69951860079b99a3e7f`,
  tree `2363d06e8496548412c192d60938602a13fd37f1`, version 0.4.2. Official
  exact-ref `--no-enable` installation and native joint Doctor succeed, then
  the plugin is enabled. The installer honestly records a retained task-local
  Git mirror; its exact objects must remain available for recovery.
- Global Hot stays `af605282d3b221e705d1ee47b886f2d054cc3598`. No dependency,
  unit definition, secret contract or other product algorithm is changed.
- Deployment receipt is written at 2026-10-02 08:26:34 UTC. Fresh readback
  confirms the new gateway process uses the selected host, is active/running,
  and both QQ and LightClawBot are connected under its current PID/start-time
  writer identity. Automatic restart count is zero; service memory is
  613,732,352 bytes at that readback, not a measured improvement or stability
  conclusion. Maintenance includes an explicit stop/start.
- A six-hourly read-only heartbeat covers the next 72 hours. It observes
  connection, restart/memory/disk trends and bounded preparation/receipt
  evidence without sending traffic or scanning all history. Missing samples
  remain missing; initial connectivity does not prove natural recall quality,
  real post-enable provider settlement or three-day stability. The old live
  hole still blocks rolling retirement; accepted independent recall is not
  whole-history retirement. Upgrade work remains deferred during observation.
- Preferred guard-only source rollback remains `1d6f502f`; preserve current
  canonical data, invalidate incompatible history proofs on host rollback,
  and never overwrite candidate-window messages from a preimage. The previous
  FTS-broken preimage and failed probes remain private forensic evidence.
- `DONOR_RECALL_REPAIR_NOTES.md` now provides the requested mother-repository
  reference. It does not modify the donor. PR #6 remains open/unmerged;
  selected Assembly reconciliation is tracked separately, not presumed done.

## 2026-10-04 — completed-prefix checkpoint validation correction

- The owner requested investigation/repair of the separately recorded
  `checkpoint_index_pending` replay failure. Current main is `284ff1f2`, with
  the same production tree as the accepted/installed `d549c95a`; this is source
  maintenance, not deployment or an upstream-version transition.
- A deterministic real-SQLite regression reproduces a false publication
  conflict: the host audits a physical API-sidecar edit on a trailing incomplete
  user, but the group worker has not refreshed that row. The completed checkpoint
  prefix remains valid; validation previously demanded the longer physical head.
  The same staged delivery now stores one conditional v3 checkpoint/receipt by
  validating the existing complete-group prefix instead. An unaudited journal
  and an edit inside that prefix still reject; no deadline, budget, readiness,
  schema, CAS or provider-delivery requirement is relaxed.
- Local Python 3.11 against exact nineteen-patch host `964c65ab` / tree
  `d212962d...`: focused history/v3/real-entry suite 45/45; complete plugin suite
  315 tests, 313 pass / 2 conditional skips; exact old Global Hot `af605282`
  paired production entrypoint separately 1/1. Ruff and diff-check pass.
  Providers are substitutes and databases disposable. No Tencent access,
  install, enable, restart, merge, selected Assembly pin or .21.5 change occurs.
- Original intermittent CI scheduling has not been recreated wholesale locally:
  the unchanged giant entry test also passed before this correction. Successor
  public replay remains necessary; a pending index is not generally a bug and
  must not be marked applied. Its existing failure assertion now emits the
  already-bounded host/group/preparation diagnostics instead of status alone.
  The independent 50-ms streamed-value test assumption remains separately
  recorded and untouched. No natural relevance/stability claim is added.
