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
