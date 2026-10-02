# Block 4 — initial target validation, 2026-09-30

The owner accepted Block 3 source `191853bf424689cb512be56a12cf0358f96a3bfa`
and opened target validation and observation under the existing conditional
deployment authorization. Blocks 1–3 remain accepted; this record does not
reopen their architecture or select another Hermes upstream.

## Target and isolation

| Surface | Observed result |
|---|---|
| Active compatibility host | `5a680e5e38625fb3275b4bf6973a40d089ec11a7`, clean source |
| Active Continuity | `34780f001cc16b81bcd003127e31ed41693158bc`, clean source |
| Global Hot, unchanged | `af605282d3b221e705d1ee47b886f2d054cc3598` |
| Gateway before validation | active/running; zero automatic restarts; main RSS about 490 MiB, service-group memory about 1.27 GiB |
| Interpreter | existing Python 3.11.15; no dependency install |
| Assembly preflight | 22 documents validated, no mutation |
| Accepted patch 13/14 replay | applied only to an isolated copy of current target source; all three resulting files exactly match reviewed files |
| Real-data copies | individual SQLite online backups; canonical copy 2,913,267,712 bytes; Continuity 704,512 bytes; Global Hot 1,097,728 bytes |
| Old Continuity metadata | one v2 checkpoint, 94 receipts, one owner row; full-row fingerprints retained privately for comparison |

Working copies and logs stay in the target's protected task workbench, not in
Git. No message body, session ID, secret or raw log is included here. Each
database backup is consistent individually; no cross-database atomic snapshot
is claimed. The original canonical database was read-only to these probes.

## Confirmed preparation-progress defect

The copied QQ history does **not** reach ready with the current default page.
The externally bounded check stops after 180 seconds: approximately 2,600
preparation quanta return `history_query_budget_exhausted`, with no committed
domain row. Process high-water is approximately 48 MiB. Neither bounded memory
nor repeated `progress` responses constitutes functional success.

A trace of the actual host method shows the initial 256-row page is fetched
and partially inserted before the 50ms deadline interrupts SQL. Its transaction
rolls back, including the first domain/cursor record; the next quantum starts
the same page again. This is target-scale/transaction-granularity evidence,
not an observed production crash or a new provider problem.

Positive diagnostic control: call the same host API on the disposable copy
with `max_rows_per_page=32`, unchanged 50ms deadline and eight-page ceiling.
Five calls commit 529 canonical records and advance the physical cursor.
This establishes a viable smaller work unit, **not** a completed index,
production adaptation, source-valid bridge, settlement or next-turn reuse.

The target plugin suite independently reaches the same boundary: **296 total,
293 passed, two conditional skips, one failed**. The failure is the real-host
long-history entrypoint's preparation convergence assertion. Its provider is
synthetic. The target lacks pytest, so the separate pytest host suite was not
run; no runtime dependency was installed to mask that limitation. Accepted
public CI remains separate evidence, not a replacement for this target result.

## Narrow next step and unchanged boundaries

Adapt the preparation work unit so a successful quantum commits a legal prefix
within the existing budget on this target. Preserve complete logical groups,
proof/CAS, the shared byte caps and the deadline; merely raising the deadline,
disabling protection or reporting permanent native fallback is not this fix.
Add the no-progress transaction case as a regression and review the resulting
bounded correction, then rerun the same target-copy chain.

Old nonempty checkpoint decode/reuse, full receipt readback, two-round bridge
settlement/reuse and production observation remain pending: preparation stopped
the copy chain before those consumers ran. No claim of exact compatibility is
derived from the copies merely containing the old rows.

No install, enablement, source switch, restart, merge, original-database write
or natural QQ/provider traffic was performed. Selected Assembly pins remain
unchanged; no other repository was edited. The source rollback preference
remains accepted Block 1 `1d6f502f2c21636d9f75b31fcc46f109c3bfece6`, with
explicit host epoch/capture invalidation before an old writer handoff. It was
not exercised. A 48–72h observation window begins only after target deployment,
and must include real projection, settlement, reuse and preparation progress,
not merely the absence of a process exit.

## Additive preparation correction

The default row ceiling remains 256, and the plugin still requests eight
pages / 50ms. Patch 15 reserves the second half of that quantum for closing
the transaction and stops between completed rows in building, suffix reset
and physical-prefix finalization. Cursor/member/prefix updates remain in the
same transaction. Genuine expensive SQL is still interrupted by the original
deadline and rolled back; scheduler delays and commit latency are not claimed
to have a hard 50ms wall-clock bound. There is no new setting, retry scheduler
or persistent tuning state. The plugin algorithm and original fourteen host
patches are unchanged.

The new deterministic slow-CPU case failed on the accepted host: its initial
256-row transaction left no domain record. On the correction, completed rows
commit without an early ready proof and eventually produce the complete
256-row source. Additional slow reset and physical-prefix cases converge.
Local host suite: **45/45** (including the retained genuine SQL-interruption
test). Local plugin suite: **296 total, 294 passed, two conditional skips**.
Five retained scale cases pass with two deliveries, one summary and reuse;
the 4,800-canonical-row case keeps a 48-row foreground workset. Native
value-guard benchmark remains a separate retained check.

Target isolated source files match host `9364e363` exactly. With the same
existing Python 3.11.15, the full plugin suite now passes: **296 total, 294
passed, two conditional skips**, about 158 seconds. Its real
`AIAgent.run_conversation` long-history test is synthetic-provider evidence,
not owner-history compatibility or live delivery.

A **fresh** set of individually consistent owner backups was used; the earlier
32-row diagnostic index was not reused. The sole QQ domain contains 67,447
physical rows. The default consumer advances through 458 preparation quanta
in 21.463 seconds, reaches 29,460 canonical records, then returns
`reverification_required / canonical_clone_audit_collision`. Peak process
RSS is 47,288 KiB. This closes the zero-progress timeout reproduction but
**does not** establish ready source, owner-history bridge or settlement.

Bounded two-row diagnosis finds equal semantic keys but unequal raw/semantic
signatures; differing columns are `id` and `display_kind`. No body, row ID or
session identity is published. `display_kind` participates in source
authority, so this correction does not ignore it or modify history to obtain
a Green result. The remaining owner-history conflict is a distinct target
compatibility question; deployment and the observation clock remain unstarted.

The existing nonempty v2 checkpoint passes the candidate's bounded JSON/hash
decoder and retains its v2 schema. This is **not** source-valid reuse,
normalizer/source compatibility or v2→v3 migration evidence. The target chain
stops before provider calls. Full-row fingerprints of the one owner row, one
v2 checkpoint and all 94 legacy receipts remain identical before/after this
copy check; no count-only compatibility claim is used. No production install,
enablement, source change, restart or
database mutation was performed. Gateway main PID and zero restart count
remain unchanged. No pytest dependency was installed on the target.

## External-review integration correction (test-only)

The prior public push run `36703797331`, bound to `a69291477404bb3ab145d4e55869438b7340b7f6`,
is retained as **failure**, not superseded into historical Green. Python 3.11
passed; Python 3.12 passed the 45 host cases but reported 296 plugin cases /
293 passed / two failed / one conditional skip. Its indexed scale and native
value benchmarks were skipped. This correction changes only the two affected
test files and this evidence; patch 15, the original fourteen artifacts and
all production code remain unchanged.

The crash child previously assumed one preparation call must reach its fault
boundary. It now uses the existing host API to force one-row/one-page quanta,
continues only on `progress` within 2,000 quanta and retains the external
30-second child deadline. The real `os._exit(74)` / `os._exit(75)` hooks and
parent return-code, rollback and recovery assertions are unchanged. No ready
result, hook or recovery consumer is mocked into success.

The prior reload failure logged no source/checkpoint reason, so its exact CI
cause is not retrospectively claimed. A controlled run of the previous fixture
through real discovery, persistence and `AIAgent.run_conversation` reproduces
the same missing bridge when the existing preparation lock holds the worker:
the bundle reports `pending / history_source_pending`, checkpoint revision 1
remains stored, and the native response produces no new receipt. The host
persists the new user before request middleware; preparing only before calling
the agent therefore does not establish readiness for that new journal entry.

The corrected single real-host scenario explicitly tests that pending turn:
no bridge, normal provider response, one existing receipt and no extra summary.
After releasing the lock, real bounded preparation completes. Positive turns
prepare at the existing test provider-kwargs boundary, after actual user
persistence and before middleware; they retain exact-once final-body bridge,
one summary, a second settled receipt and checkpoint reuse after manager reload.
Cancellation and provider-error no-receipt controls remain. This synchronization
is a **test prerequisite**, not proof that the automatic worker always finishes
within the production foreground wait. No sleep, production wait extension,
retry-until-projected turn, artificial provider block or checkpoint is added.

On assertion failure, body-free diagnostics now include source/checkpoint
status, validation reasons, preparation result, host cursor/phase/counts and
process-wide preparation/active/cold admission counts and bytes. They do not
emit the checkpoint body or canonical transcript.

Local Python 3.12 on the unchanged exported host: 45/45 host cases; 296 plugin
cases / 294 passed / two conditional skips. The seven recovery cases also pass
with the legacy writer module supplied, including all three exact crash exits.
Retained indexed scale 5/5, native value guard 3/3 and original resource guard
7/7 all complete. The scale cases each retain two receipts and one summary.
The resource-guard run uses the preserved pre-index SessionDB module; public
CI independently materializes the complete twelve-patch host before that step.
Successor public dual-version CI must finish all later benchmarks before this
candidate is returned for external acceptance.

Recovery-truth gate: no selected source, artifact, dependency, managed path,
unit, secret, runtime capability or rollback procedure changes in this test-only
increment. Selected Assembly pins remain unchanged; no Assembly landing is
performed. Owner-history `display_kind` conflict, ready source, live settlement
and the 48–72h target observation remain unproven and outside this correction.
No merge, target access, install, enablement, restart or database mutation.

## Accepted preparation correction; owner-copy provenance diagnosis

The owner relayed external acceptance of PR #6's preparation/test correction
at `ce3fb0e10c8e7447d86423ff3e8b478d239e5d77`. Its two reviewed blockers are
closed. Block 4 now continues target-copy qualification; this acceptance does
not establish source readiness for the owner's history or start observation.

A subsequent read-only probe of the retained disposable copy confirms that
the first conflicting row's exact stored-key query finds 39 physical members: one archived
`internal_notification`, 37 archived members with no display kind, and one
active member with no display kind. The bounded earlier/incoming comparison
still differs only in `id` and `display_kind`. These are provenance-affecting
values, not an empty-string/NULL presentation equivalence. No message body or
private locator is published, and the canonical rows were not rewritten.
The count is scoped to that stored-key query, not a census of every semantic
encoding or every conflicting group in the domain.

Current writer tracing finds that Gateway synthetic input supplies the tag,
the conversation reader restores it, compaction message copies retain it, and
the concurrent-tail SQL copy preserves columns. This does not identify which
historical writer lost the tag. The observed missing values cannot by
themselves grant verified human authority.

The frozen clone audit therefore continues to reject this domain. Ignoring
`display_kind` is not a permitted target adaptation. A proposed next step is
complete-group local conflict handling, retaining every physical obligation
while excluding ambiguous material from the bridge and allowing independently
verified history to progress. That changes the accepted source-compatibility
semantics and awaits an explicit owner decision; no such implementation or
original-data repair has been performed.

The target gateway remains active/running with the same main PID and zero
automatic restarts at this readback. No install, enablement, restart, source
switch, merge or natural provider/QQ traffic occurred. Selected recovery pins
and procedures remain unchanged; no Assembly update is required for this
diagnostic/evidence-only increment.

## Owner-approved propagation and evidenced recovery (patch 16)

The owner **rejected** the historical quarantine/exclusion proposal above.
It is not a fallback or an acceptance gate. The approved product delta keeps
all dialogue content, repairs the shared Gateway replay loss, and restores
only proven missing clone provenance in a derived index/view. No canonical
message row is rewritten and no text-based origin inference is introduced.

Current Gateway `_build_gateway_agent_history` routes ordinary messages through
`_build_replay_entry`, which previously omitted both producer display fields.
The fix preserves those fields, including a detached nested metadata copy,
before existing compaction/persistence. Provider-bound copies still strip them.
This is a reproduced reachable loss mechanism, not a retrospective assertion
that this writer created every historical missing value.

The indexed recovery requires an earlier archived `internal_notification`
user row, a later user clone whose kind is NULL, and complete raw-key,
semantic-key, raw-signature and semantic-signature equality after restoring
only that tag. Other content/metadata/API/provider-field conflicts, explicit
contradictory kinds, invalid lifecycle and active collisions remain errors.
Raw physical signatures remain distinct and are reverified. The recovered
label counts toward page bytes. Canonical rule v2 rejects old tokens and
seals until the existing finite worker rebuilds their derived index; schemas,
checkpoint storage, compiler, CAS and provider budgets are unchanged.
The separate legacy/recent-window path used by Global Hot remains strict;
this candidate does not claim to repair every independent reader.

Host `ff67db0d2fdf1a08c02aedccedb77f29a7549a24`, tree
`d9553785cda565b177b077f7784309bd116264cf`, is a direct child of patch 15.
All first fifteen exported artifacts remain byte-identical. Local Python 3.12:
55 history tests, 11 actual Gateway tests, and 42 overlay/middleware tests
(15 subtests) pass. Plugin: 297 cases / 295 passed / two existing conditional
skips. Its actual discovered AIAgent long-history entry now includes archived
missing-tag clones, retains those physical rows, and still verifies settled
delivery, next-turn reuse, manager unload/reload and error/cancellation behavior.
Scale 5/5 and native-value 3/3 benchmarks retain their positive controls.

A new individually consistent copy of the previously retained owner snapshots
was made inside the protected task workbench; the production originals were
not accessed for this copy. Under the existing Python 3.11.15, rule-v1 index
rebuild passes the former label collision and advances to 46,856 canonical
records, then stops: `overflow / history_row_byte_limit_exceeded`. The 67,447
physical-row domain takes 990 quanta / 42.729s with peak RSS 42,288 KiB.
A size-only, at-most-256-row probe finds one row over 4 MiB: its content is
22,596,510 encoded bytes. No body, row ID or session identity is emitted.
This is a distinct giant-row read boundary, **not ready source, owner-history
projection, settlement or reuse evidence**. No protection is disabled and no
group is excluded to turn this result Green.

After the stopped preparation, full-field fingerprints of the copied owner
row, nonempty v2 checkpoint and all 94 legacy receipts still match their
retained baseline. This proves preservation of those old records, not their
source-valid reuse or a v2-to-v3 migration.

Recovery-truth axes: candidate source/artifact and acceptance truth change;
managed runtime paths, units, secrets, production dependencies and selected
rollback do not. Missing local HTTP dependencies were added only to a
disposable test venv for actual Gateway tests, not the server or repository.
The candidate is unselected: no Assembly relock, deployment, enablement,
restart, merge, upstream upgrade, Global Hot change or observation start.
Public successor CI and external review must be recorded separately. Handling
the giant row without losing memory or returning to unbounded reads remains
the next qualification problem, not an implemented product change here.

## Giant-value implementation work, not accepted/selected

- owner_goal: finish the actual owner-history chain without dropping or
  quarantining complete groups and without increasing the established worksets.
- current_phase: Block 4 giant-value correction; Blocks 1–3 remain closed.
- accepted_checkpoint: origin correction `64074b89ec37e32558fa15be63f6254365d46dbc`;
  preferred code rollback remains Block 1 `1d6f502f`.
- proposed_product_delta: native bounded value reads and complete raw/semantic
  identity validation through preparation, grouping and compiler consumers.
- real_consumer: existing host preparation → group index → recent bridge →
  final provider-body settlement → next-turn reuse, not a separate memory pool.
- forbidden_surfaces: original database writes, quarantine/exclusion, larger
  budgets, Global Hot changes, upstream upgrade, merge/deployment or observation.
- stop_condition: positive/negative local and disposable-copy evidence plus a
  reviewable ordinary PR update; no source/runtime selection by this work alone.

A read-only structural probe identifies the over-budget record as an archived
user message with JSON-encoded multimodal content. Two data-URI string leaves
account for approximately 5.1 and 17.5 MB. Neither raw bodies nor private
locators are emitted. A native 64 KiB blob reader completes 345 chunks with
approximately 0.9 MiB measured RSS high-water increment; this is read-only I/O
evidence, not complete-source or compiler evidence.

A separate bounded JSON/hash probe on that same copy completes parsing and
both full canonical ASCII/UTF-8 JSON hashes in about 3.5 seconds, in 345
scheduling boundaries. Largest measured parser boundary is about 5.1 ms;
process peak is about 20 MiB. It retains 245 small-string bytes and 12 parsed
value nodes, not the giant leaves. The source host/plugin and production
remain unchanged. These isolated measurements do not establish hard timing
bounds, snapshot/publication validity or end-to-end memory safety.

The implementation draft keeps unfinished byte/hash state private to the
existing worker; a byte boundary cannot advance a complete physical/group
cursor. Restart must discard unfinished state and reverify canonical bytes.
Sparse character/byte positions support bounded text fragments without
joining the complete value. The initial seven local primitive regressions
pass, including exact old JSON hashes, Unicode/escape boundaries, restart
without a partial proof, malformed input, and late giant-text fragments.
This is not yet integrated into the accepted host APIs or plugin consumers.

The real sample does not remove the giant-text positive contract. The owner
subsequently selected and authorized a pixel-free continuity representation:
stickers are not repeatedly collected into the bucket (their conversational
meaning remains dialogue); informational images retain recorded semantic
interpretation, without thumbnails or default saving; deliberately saved
images additionally retain their actual successful-save index. These are uses,
not a classifier based on filenames or visual appearance. No historical original
is deleted or rewritten, no asset pool is created, and no historical bulk vision
job is authorized. A cache path or invented number is not a save receipt.

The shared summary/chunk prompt boundary now omits historical image parts before
prompt estimation and input hashing, while retaining all supplied text and
canonical source identities/fingerprints. The runtime repeats the same idempotent
projection before copying/hashing or invoking PluginLlm. This does not generate
missing image interpretations: omitted pixels are explicitly unavailable, and
recorded assistant statements remain dialogue, not independently verified vision
results. The actual folder-based save consumer and giant-value read/index chain
are still being connected; this small projection alone is not whole-owner-history
readiness or complete three-category implementation.

Local working-diff validation uses the clean accepted host `ff67db0d` (tree
`d9553785cda565b177b077f7784309bd116264cf`), not the unfinished giant-value
host draft. The plugin suite completes 300 tests: 298 pass and two existing
conditional skips. The retained host history/replay/overlay/middleware selection
completes 108 tests and 15 subtests. The history-index, value-guard and original
full-chain resource benchmarks complete five, three and seven cases respectively.
Oversized value-guard cases remain explicit rejection, not giant-history success.

The real discovery/`AIAgent.run_conversation` regression retains recorded image
meaning in the settled bridge and next-turn manager-unload/reload reuse. It
checks original SQLite image rows remain exact; its provider and image meanings,
including `PIC-007`, are synthetic. This is not independent image recognition,
real saved-file/number validation, real network delivery or natural QQ evidence.
The current-turn attachment control retains the legitimate bridge prefix and
the original text/image parts. An initial assertion incorrectly omitted that
prefix and failed; after correcting the assertion, the full 300-test rerun passes.

The owner clarified that deliberate saving was requested conversationally and
Hermes moved files into a server folder. Bounded read-only tool-record/path
checks have not established that actual save folder or numbering consumer.
No candidate private locator or conversation body is published here, and no
cache/test image is adopted as a saved asset. Semantic generation and verified
saved-index linkage remain pending rather than being replaced with a new pool.

Recovery truth: this changes candidate plugin source and summary representation,
not the selected Assembly artifact. Dependencies, managed runtime paths, units,
secrets, canonical data and selected rollback remain unchanged. No host patch
is exported from the giant-value draft. Ordinary PR delivery of this partial
trial does not select it for runtime, reopen accepted Blocks 1–3, or authorize
merge, deployment, restart or observation. Successor public CI and external
acceptance must be recorded separately before any selected-artifact reconciliation.

## Recent-bridge selection representation correction, 2026-10-02

The owner authorized recall repair, conditional target deployment after
qualification, and a donor-facing Markdown explanation after deployment. This
increment closes one reproduced shared-selector defect, not that whole task.

The retained donor selector estimated original multimodal content before its
token admission. The accepted historical-image policy removes pixels only at
the later summary boundary. The selector can therefore reject a recent group
that fits its actual summary representation, leaving an empty bridge. It now
uses the existing `_summary_source_content` for estimation as well. Both v2
and compact v3 reach this selector; source groups, fingerprints, retirement
contiguity, time horizon and genuine text limits remain unchanged. No budget
increase, new estimator, dependency or query/search store is introduced.

The new six-test selector selection first failed on the old implementation
(expected two complete groups, received none), then passed. The real-host
regression uses actual plugin settings of 1,000 source tokens and three
64-KiB synthetic image payloads. It preserves their recorded interpretation,
one summary, settlement, next-turn reuse, manager unload/reload and original
SQLite rows; provider and save-number text remain synthetic.

The public baseline was fetched at `fcbd1076a93841fa88855acce810e342a5b78101`
and the existing sixteen artifacts replayed without modification. The staged
host source tree equals accepted `d9553785cda565b177b077f7784309bd116264cf`;
this is tree-identity evidence, not a claim that Git HEAD was `ff67db0d`.
Local Python 3.12.13: 301 plugin tests / 299 passed / two pre-existing
conditional skips; retained host history/replay/overlay/middleware 108 passed;
indexed scale five cases passed, each with two receipts and one summary.
The skips require the preserved legacy writer and paired Global Hot checkout;
neither is silently counted as passed. Resource measurements were run locally
alongside other regressions, not as a controlled latency comparison.

Independent read-only intent audit: this is a source-candidate budget
consistency correction only. No production install, enablement, source/DB
change, restart, merge or observation occurred. Selected Assembly pins and
rollback preference remain unchanged. The real 22,596,510-byte source value,
whole-owner-history readiness, query-driven relevance recall and 0.21.5
adaptation remain open. This correction neither makes chronological continuity
semantic retrieval nor qualifies the unfinished streaming draft for runtime.

## Integrated giant-value source candidate, 2026-10-02

- owner_goal: complete the actual long-history/recall repair, not stop after a
  one-line selector correction.
- current_phase: Block 4 target-copy qualification of the integrated source.
- accepted_checkpoint: accepted image representation `b7bc7bb...`, selector
  successor `f8b2778...`, unchanged first sixteen host artifacts.
- proposed_product_delta: additive streamed-value host seam and consumer
  adaptation; retained budgets and canonical data remain unchanged.
- real_consumer: host preparation/page -> group index -> compiler -> final
  transport -> post-settlement -> next-turn and manager unload/reload.
- forbidden_surfaces: canonical edits/exclusion, increased budgets, production
  install/enable/restart, Global Hot algorithm or .21.x changes.
- stop_condition: replayable reviewed source plus a precise target result;
  changing retirement/recall ownership requires an explicit owner decision.

Patch 17 is now integrated, not merely a byte-read probe. Complete raw and
decoded hashes cover every stored byte before a record can enter the index.
Checksummed range descriptors contain no transcript; bounded deferred reads
validate the fixed source token. A byte-work step closes its SQLite blob and
connection before yielding. Same-row captured edits restart work; unrelated
appends do not. Completed proofs survive a quantum that cannot yet commit.
Body-free native shape caching avoids repeatedly walking a giant SQLite
record. No larger window, dependency or alternative transcript store is added.

Continuity no longer rejects an entire unclassified dialogue merely because
consecutive user rows have different display provenance: that unused check is
limited to the separate typed window. The strict Global Hot classifier still
rejects the same mixed group. No notification becomes verified human, no row
or group is removed, and no provenance field is rewritten.

The exported host commit is `e654daaa11d5f960b26edc40cabc58f44e7b53fc`, tree
`dadd41d44e0418d601c7d9c4bdf8267ca667fb7d`. Its parent materializes the
accepted sixteen-patch tree `d9553785...`. A fresh baseline archive plus patch
17 reconstructs the complete final tree exactly. Its local 67 history/stream
tests pass; retained overlay/middleware/Gateway cases are 53 passed plus
15 subtests. The exact compatible-host plugin suite is 303/303 with the
preserved legacy module and exact Global Hot `af605282...`, including actual
discovery/AIAgent entry, indexed dual overlay, giant-image settlement, next-turn
reuse, manager unload/reload and failure/cancellation controls. A later
live-hole regression is recorded separately rather than folded into 303.
The final index selection passes 23/23, including that live-hole regression;
the fresh exported-host replay passes 67/67 and its paired entrypoint 1/1.

Final isolated Python 3.12 streamed benchmarks both pass with 24 complete
groups, 48 foreground rows, two receipts and one summary. 16 MiB: preparation
1.715s, peak 59,360 KiB, measurement high-water delta 12,832 KiB. 64 MiB:
preparation 7.771s, peak 60,080 KiB, delta 13,808 KiB. These are synthetic
SQLite/plugin/provider chains, not service RSS or natural QQ timings. Earlier
64-MiB drafts timed out at 180s and are retained as failed drafts; caching
verified native shape fixed the reproduced progress bottleneck. A 50ms SQL
quantum is not a strict native-I/O/commit wall-clock guarantee.

### Actual owner copy: ready index, remaining foreground barrier

The protected consistent copy contains 67,447 physical records. The integrated
source now reaches **ready** after 5,223 bounded quanta / 255.553s, peak process
RSS 122,836 KiB. It does not call a model during preparation. This passes the
real 22,596,510-byte record instead of dropping it or returning permanent
overflow at that row. Foreground read nevertheless returns overflow: the
existing continuous-retirement gate requires the whole suffix after the first
uncompacted group to fit the foreground workset.

Body-free index diagnosis: 6,264 complete groups; first uncompacted group at
ordinal 2,973. Its suffix contains 3,292 groups / 4,225 canonical rows /
27,455,617 admitted bytes: only 139 groups are uncompacted, while 3,153 later
groups are compacted. The newest recorded group is about 45 hours old. Thus
this is not simply a stale 72-hour window, and relabeling those old groups or
raising 2,048-row/4-MiB limits would manufacture retirement authority.
A second fresh-process run reaches the same result in 5,134 quanta / 240.628s
with peak 120,896 KiB and explicitly reports `foreground_group_limit_exceeded`.

This target result is **not** owner-history bridge, settlement or reuse. The
proposed next narrow product decision is independent bounded query recall
without moving the continuous retirement cursor; it can use verified later
compacted groups without pretending the earlier live holes were retired.
Owner approval of that ownership separation is pending. Canonical history is
not quarantined, deleted or silently relabeled. Public successor CI and
external review remain separate from local evidence. No production deployment,
natural provider/QQ call, merge or observation start is claimed; selected
Assembly/rollback identities remain unchanged.

### Owner-approved independent recall: protected-copy qualification

The owner subsequently approved separating recall from retirement. The new
path reads complete verified groups through native bounded search, without
changing the old live holes or checkpoint retirement cursor. The initial
protected-copy attempt reached ready at 5,478 quanta / 256.758s, peak RSS
121,008 KiB, then failed with `native_search_sqlite_interrupt`; no delivery was
recorded. That failure remains evidence, not a successful run.

Body-free native query-plan probes showed domain-first repeated FTS lookups
and a global physical-clone BM25 sort. A FTS-posting-first winner seek with
native newest-posting order removes the repeated scan and temporary score
sort. It uses the existing `idx_hermes_history_buckets_winner`, no new table,
writer, repair pass, increased deadline or full-body decode. SQL error class
is now visible rather than confused with empty relevance.

On the same already prepared consistent copy, ordinary source/proof validation
plus search returns **24 complete groups / 80 canonical rows / 365,198 admitted
bytes in 0.065s**, with `retirement_authority=false`. The rolling reader still
honestly returns `foreground_group_limit_exceeded`. Two fresh request runtimes
then deliver and settle selected context with two auxiliary calls each,
0.109s / 0.085s for the synthetic chains, peak process RSS 50,584 KiB. Their
body-free outcomes are `delivered_recall`; no v3 checkpoint is published.
All fields of the existing nonempty v2 checkpoint and the first 94 delivery
receipts remain equal before/after; two recall receipts are appended only in
this disposable plugin store. The preparation peak and foreground peak come
from separate processes, not one shared service-RSS measurement.

The auxiliary planner/selector and foreground provider/transport are
substitutes. This proves real owner-copy search/hydration plus synthetic
projection/post settlement and fresh-runtime reuse, not natural semantic
accuracy or live QQ. Real discovery/manager unload-reload is independently
covered by the synthetic 16-MiB/live-hole AIAgent test. No original database,
production installation, enable, restart, source switch or .21.x update is
part of this result. PR/source review and live canary remain later gates.

### B4-GIANT-REWIND-01: actual-host source correction

- owner_goal / current_phase: close the reviewed giant-value rewind write
  defect in this Block 4 source candidate; retain question-recall positives.
- accepted_checkpoint: Blocks 1–3 and the previously reviewed preparation,
  provenance and image-policy contracts remain closed. `2fdc6ec` is the
  reviewed HOLD source, not an accepted installation or selected rollback.
- product_delta / real_consumer: the existing history preparation loop writes
  a value proof only when its actual `hermes_history_members` parent exists.
  Legal `(active,compacted)=(0,0)` rows remain durable, skip canonical indexing,
  and advance the scan without a foreign-key failure; restoration remains live.
- forbidden_surfaces / stop_condition: no FK disable, fabricated member,
  message rewrite/deletion, budget change, recall redesign, original/copy DB
  operation, Global Hot, donor, .21.x or target mutation. Publish the corrected
  source/CI for external re-review; no merge/deployment/observation starts.

Before the correction, the new actual-host subprocess matrix reproduces two
`FOREIGN KEY constraint failed` exits: giant plain text and encoded multimodal
rows rewound before their first preparation. Five positive controls pass.
This is real `SessionDB`/stream verification/SQLite execution, not the review's
small material/proof substitute. Each child has an external 90-second timeout.

The correction uses INSERT-from-member in the same existing transaction.
The seven cases then pass, including a second fresh interpreter, actual
rollback invalidation/rebuild, restore and a subsequent indexed rewind/redo.
They assert FK enforcement, original message fields, normal dialogue pairs,
absence of parent/child rows for legal rewinds, reconstructed real raw hashes,
and deferred canonical reads after restore. No parser or proof is mocked.

The retained five-file host suite passes 118/118. Exported patch 19 reconstructs
host tree `d212962d9c0a0a49000d1132fe9e5b68d739821a` after the unchanged eighteen
artifacts. Whole product and successor public CI results are recorded
separately in PROGRESS / the PR receipt; old exact-head Green is not substituted.
No owner database or service was accessed in this correction. The earlier
owner-copy recall results remain evidence at their original scope and identity.

### Accepted `d549c95a`: target qualification and interrupted maintenance

The owner accepted the exact source increment and authorized continuation of
the existing conditional Block 4 deployment. No product algorithm is changed
in this target pass, and source acceptance is not promoted to live acceptance.

The actual target workbench materializes patches 13–19 over its clean retained
twelve-patch host. Corrected environment locators execute 314 tests without
skips; real native joint Doctor succeeds using the current Global Hot companion.
The earlier run against the old workbench locator has eleven skips and remains
separate. No target pytest or other dependency is installed.

Controlled copy qualification reuses the previously prepared 67,447-row owner
history and revalidates its source token. Recall returns 24 complete groups,
80 rows and 365,198 bytes in 0.139s; process peak reaches 50,444 KiB across two
fresh synthetic projection/execution/post chains. All fields of the existing
v2 checkpoint and 98 receipts remain equal; only the copy receives two new
body-free recall receipts. Rolling retirement remains explicitly unavailable
across the old live hole. Neither that limitation nor synthetic model/provider
results are relabeled as whole-history retirement or natural QQ accuracy.

Two preceding copy attempts return `native_search_sqlite_interrupt` and remain
failed evidence. A standalone phase probe after the target suite completes
reports 0.5–1.7ms prefix validation and 1–4ms successful searches. The existing
posting-first, rowid-ordered plan is retained, along with the 50ms deadline;
the older rank-sort diagnostic remains interrupted. The controlled positive
does not prove latency under simultaneous pressure.

Before promotion, the old gateway is stopped and the original three database
paths have zero open handles. The current systemd unit reaches its stop timeout.
SQLite's backup API produces a consistent 2.8-GiB canonical preimage, but its
integrity check is non-OK. The maintenance exception path restarts the unchanged
control. Runtime status confirms QQ and LightClawBot connected with the new
control process as writer. No source switch, plugin install/enable, original
database repair, snapshot restoration or PR merge occurs.

The failed preimage is retained privately for diagnosis, not declared a complete
validated estate rollback pack. A 16-MiB-cache, bounded read-only check reports
`malformed inverted index for FTS5 table main.messages_fts_trigram`; it does not
establish missing or damaged canonical messages. A second disposable copy tests
the existing native FTS rebuild statement, with TEMP guards forbidding all
messages/sessions writes, a 512-MiB process limit, a 16-MiB SQLite page cache
and a 300s SQLite deadline (360s outer process limit). The rebuild statement
returns `sqlite3.OperationalError: interrupted` at the SQLite deadline; no
repaired-copy integrity or canonical-count success is claimed. Owner
authorization has been requested before any original-index repair. The old
gateway is checked again after this failed probe and remains active/running.

Selected runtime source and Assembly pins remain unchanged. The observation
clock has not started. The accepted source rollback preference stays Block 1
`1d6f502f`; the source bundle also stages that exact guard rollback. The next
action is narrow native-index qualification and authorized repair, then the
same reversible deployment and real canary, not a new continuity design phase.
