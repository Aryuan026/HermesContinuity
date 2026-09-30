# Block 3 — bounded long-history implementation

Status: implementation candidate; local verification complete. No external
implementation acceptance, merge, installation, server or real-database action
is implied by this document.

## Scope and owners

- owner_goal: a >2,048-row history can form a bounded bridge, settle and reuse it.
- current_phase: Block 3, implementing the accepted Block 2 protocol `e54472f2`.
- accepted_checkpoint: Block 1 source rollback `1d6f502f2c21636d9f75b31fcc46f109c3bfece6`.
- proposed_product_delta: incremental history proof replaces full-prefix bodies
  only when the new host seam exists; existing summary/chunk policy is retained.
- real_consumer: SessionDB → adapter/group index → donor compiler → final body
  proof → post-delivery conditional CAS → per-use source validation.
- forbidden_surfaces: Global Hot, accepted 0.21.3/0.21.5 lanes, production data,
  target configuration, installation, merge and deployment.
- stop_condition: reproducible source/PR candidate for implementation review.

The host is the existing compatibility lane: upstream `fcbd1076` plus the
unchanged twelve patches, followed by `hermes-0.20.5-incremental-history.patch`
and `hermes-0.20.5-history-value-guard.patch`.
Do not apply it to a different upstream tree by assuming matching filenames.

| Owner | Implementation / responsibility |
|---|---|
| `hermes_state_history.py` in patch 13 | Transactional body-free journal, canonical clone/audit index, epoch/lease, bounded preparation, page/seal/validation, rollback invalidation |
| `history_index.py` | Profile-bound worker, complete-group positions and persistent occurrence counters, bounded window, current retirement eligibility, proof validation |
| `checkpoint_v3.py` | Closed compact schemas, proof-bound prefix/bridge descriptors and revision identity |
| `context_compactor.py`, `thread_continuity_runtime.py` | Explicit v3 path; reuse donor selection, chunk planning/acceptance and provider-budget helpers; v2 preserved |
| `checkpoint_store_v3.py` | Separate v3 table, bounded JSON read/write, conditional revision CAS plus namespaced body-free delivery receipt |
| `runtime.py`, `resource_budget.py` | Freeze/revalidate source proof; process-wide serialized workset/cache admission; existing transport and post-settlement authority |

No transcript, FTS, vector store, search replacement or background model
summarizer is added. Exact-sentence search remains Hermes-owned. The separate
`canonical-source.v2` window service and Global Hot are not converted to v3.

## Runtime and storage contracts

New requests/source misses and committed same-process writer notifications
wake a coalescing worker (32 domains maximum). Cross-process/direct SQL changes
remain captured transactionally; a subsequent source request discovers them.
Notifications are wakeups, never proof. One process-wide preparation lock
serializes finite quanta across profiles. Unload withdraws listeners and waits
for the current bounded page; it prevents late group publication.

Host and group pages share the same eight-page allowance. An unfinished
complete group may continue in the next quantum under one process-wide 8 MiB
reservation; its old prefix is revalidated before those private in-memory rows
are used. It is not persisted as another transcript. Completion, invalidation,
failure or unload releases the reservation. This lets group preparation progress
while small canonical tail writes continue.

Host pages are bounded by 256 rows / 4 MiB before decoding. A group/window is
bounded by 2,048 rows / 4 MiB, preparation serialization by 8 MiB, active
requests by 32 MiB and cold plans by 8 MiB. The host portion uses a 50ms SQL
deadline within the 100ms quantum target. These serialized budgets are not
Python RSS ceilings. A request may wait at most 100ms for the existing worker
to catch up a small delta; it does not scan history in the request thread.
Legacy full-prefix/checkpoint settings can lower the v3 foreground row/byte
and 1 MiB checkpoint limits, but cannot raise these v3 ceilings beyond the
pre-read admission reservation. The v2 configuration contract is unchanged.

Host cache is temporarily 8 MiB with file-backed temporary storage and a SQL
progress deadline. Benchmarks report native-inclusive process peak RSS, SQL VM
work and named temp-schema bytes. Named temp-schema accounting is not a
measurement of peak unlinked SQLite sorter files or a strict disk quota.
Foreground keyset/proof queries must use indexes without a temporary sorter.

`indexed`, `delivered` and `stored_unvalidated` remain independent facts.
Pending/changed source after delivery records a checkpoint conflict; it does
not erase delivery or resend the provider. Successful conditional CAS must be
source-validated again on read, cached reuse and retirement. Source-invalid v3
can rebuild using its bounded revision identity, not its old body. A first v3
built in the presence of v2 starts its own revision chain and keeps v2 intact.

## Evidence map and remaining qualification

The runnable checks are in the repository rather than copied log fixtures:

| Protocol surface | Check |
|---|---|
| >2,048 rows, pending user boundaries, changed prefix, physical lifecycle | `tests/test_history_index.py` |
| Incremental occurrences vs existing full projection | `tests/test_incremental_projection.py` |
| Compact schema, source tamper, chunk receipts, current/raw non-retirement | `tests/test_checkpoint_v3.py`, `tests/test_long_history_compiler.py` |
| Conditional store race, competing CAS, failed transaction, legal nonempty v2/receipts exact readback | `tests/test_checkpoint_store_v3.py` |
| Actual canonical edit between source validation and plugin CAS; late old worker after epoch handoff | `tests/test_history_index.py` |
| Actual discovery → AIAgent → final body → post → SQLite → manager reload | `tests/test_real_host_long_history_v3.py` (synthetic provider, not QQ) |
| Shared process admission and worker unload/notification | `tests/test_resource_budget.py`, `tests/test_history_index.py` |
| Partial preparation in a real subprocess, old SessionDB rollback writes, continuous append and two profile admission | `tests/test_history_recovery.py`; old module path explicitly supplied, remaining support modules shared |
| Abrupt process exit inside host page transaction, after host commit/before group read, and with uncommitted group/occurrence inserts | `tests/test_history_recovery.py`; real subprocess exit codes 73/74/75, external timeout, durable-state checks before recovery |
| Host pages, SQL deadline, clone collision, rewind/restore, direct SQL/REPLACE, transactional journal, bounded prune, epoch and rollback | `tests/test_hermes_state_history.py` supplied by patch 13 |
| Import, TUI branch handler, recovery mapper, lost-and-found mapper and stopped-writer quick restore | `tests/test_history_portability.py`; real write owners, synthetic UI/agent construction and recovered-page input, no network frontend |
| Official replacement/sidecar/reaction/delete/prune/marker/session writers, compression-child watermark publication and FTS repair | `tests/test_history_writers.py`; actual SessionDB methods and disposable SQLite, not hand-written replacement SQL |
| API direct create/title/delete and A2A title update | `tests/test_history_portability.py`; actual handlers/write functions, transport/auth/config and optional response container substituted |
| Fixed recent window with 1×/10×/100× history and 2k/20k physical clones | `tests/benchmark_history_index.py`, separate setup/measurement processes with external timeout |
| Original entry guard and budget-limited v2 behavior | original suite and `tests/benchmark_resource_guard.py` on the twelve-patch lane |

The compatibility suite does not establish every frontend's recovery flow,
real provider latency, cross-mouth behavior, production restart or 48–72h
health. Those retain their own target qualification. A local run passing is
not a substitute for exact-head public CI or external implementation review.

### Exported-host scale measurement

Local Python 3.12 final plugin suite: **293 tests, 292 passed, one existing
paired-Global-Hot conditional skip**. The actual long-history AIAgent entrypoint
runs in this suite. Exported-host canonical-history suite: **40/40 passed** via
the host runner with file retries disabled. The original twelve-patch resource
benchmark remains **7/7 passed** on that baseline. A clean baseline-file replay
of patch 13 reproduces all three exported files byte-for-byte.

Local Python 3.12 measurement on host `60a36dda` (five disposable cases):

| History shape | Foreground rows | Approximate read SQL VM steps | Process peak RSS, KiB | Longest preparation quantum, ms |
|---|---:|---:|---:|---:|
| 48 canonical rows | 48 | 11,300 | 48,272 | 28.6 |
| 480 canonical rows | 48 | 11,600 | 50,064 | 81.4 |
| 4,800 canonical rows | 48 | 11,000 | 52,880 | 79.5 |
| Same 48 canonical rows + 2,000 physical clones | 48 | 11,300 | 49,136 | 73.5 |
| Same 48 canonical rows + 20,000 physical clones | 48 | 11,300 | 49,408 | 75.9 |

Every case produced two projections/two receipts with one summary and checkpoint
reuse. First settlement used approximately 5,700–6,200 SQL VM steps. Preparation
total work grows with history; foreground work remains bounded in these cases.
RSS is the entire measurement process high-water mark, including native SQLite,
not a Python-allocation delta or a promised production ceiling. Setup runs in a
separate process. Provider and transport are synthetic. Each subprocess has an
external timeout; Linux also applies a 1 GiB address-space limit. CI reruns the
same script and uploads its structured results with Bash pipefail enabled.

## Block 3 review correction: value probes and cancelled compilation

External review held candidate `2cfb512c` for a SQLite native-allocation P1
and a cancelled-compiler admission P2. The correction retains the accepted
protocol and original thirteen patch bytes; patch 14 is additive. Its host is
`a488b6ebf46765a7323bb3e862bcbb77bccbd172`, tree
`fa9a9030295b769c0e391ca860e3ebe1cd1e3b46`.

Both the physical size probe and foreground page read apply a temporary
`SQLITE_LIMIT_LENGTH` before touching message values. The limit respects a
stricter borrowed limit, includes 4,096 bytes for row encoding, and is restored
on every exit. Oversized SQLite values return the existing typed row-overflow
state without decoding. Foreground reads use a savepoint, preserving an outer
transaction on success and failure.

Compilation owns its admission until the plan is installed under the runtime
lock. A `finally` releases untransferred admission on cancellation, ordinary
exceptions and unload. In-flight compilation retains its reservation during
`clear()` until it unwinds; other profiles' leases are untouched. Cancellation
continues to propagate. The P2 was an admission-ledger leak, not evidence of
8 MiB of permanently retained transcript per cancellation.

Local Python 3.12.13 verification: host history **42/42**, plugin **296 total /
295 pass / one existing paired-Global-Hot skip**. A real async summary cancels
through AIAgent/discovery, leaves no installed plan or lease, then actual
manager unload/reload permits normal projection, settlement and next-turn
reuse. A separate four-cancellation test preserves another profile's lease;
normal/exception and compile-in-progress unload controls pass. These use
synthetic provider/transport, not gateway `/stop` or real channel traffic.

`tests/benchmark_history_value_guard.py` runs setup and measurement in separate
processes with a 45s external deadline. It calls the actual SessionDB probe,
preparation and recovery read. Local native-inclusive high-water measurements:

| Stored API field | Prior patch-13 probe delta, KiB | Corrected probe + preparation delta, KiB | Result |
|---|---:|---:|---|
| 1 MiB | not measured | 23,280 | Ready, original bounded body retained |
| 16 MiB | 16,672 | 336 | Overflow before decode; small session recovers |
| 64 MiB | 65,792 | 336 | Overflow before decode; small session recovers |

Prior-source controls load the exact `60a36dda` history module and invoke its
actual probe; their measurement stops before preparation. Corrected oversized
process peaks are about 38 MiB, not 336 KiB. The positive 1 MiB case peaks near
61 MiB: encoded budgets do not guarantee an RSS ceiling. No real DB or server
incident is reproduced here. CI runs the corrected checks on Python 3.11/3.12
and uploads JSON, with explicit Bash pipefail.

Retained scale checks **5/5** still produce a 48-row foreground workset,
two projections/two receipts and one summary at 4,800 canonical rows and
20,000 clones. Original twelve-patch resource checks **7/7** remain passing.
These local results await public CI and external re-review; Block 3 remains
an implementation candidate. Preferred source rollback remains `1d6f502f`.

## Rollback procedure

1. Stop accepting new work and unload the plugin worker before handing writers
   to old code; preserve the canonical database, including candidate-window data.
2. While the new host is still available, call
   `SessionDB.invalidate_history_for_rollback()` on the affected profile. It
   invalidates the epoch and detaches added capture triggers; repeated calls
   are safe. This is an operator handoff, not an automatic plugin-unload action.
3. Select accepted Block 1 source `1d6f502f…`, not the older incomplete guard.
   V2 checkpoint rows and old receipts remain in their original tables. V3 and
   body-free indexes may remain; they do not grant the old host any proof.
4. Re-entering the new host requires a fresh trusted activation and canonical
   revalidation. Never label retained v3 files as ready merely because present.

No rollback instruction here has been executed against the owner database.
File-copy restore is supported only with stopped writers and the explicit
invalidation/activation handoff. A backup helper copying bytes does not itself
grant a restored derived index a fresh proof.

## Recovery-truth gate

| Assembly axis | Candidate change |
|---|---|
| Source / overlay | Yes: plugin v3 and additive host patch; not a selected runtime pin |
| Artifact | Yes: thirteenth patch plus additive value-guard correction and source PR, digests recorded in PROVENANCE |
| Runtime dependency | No: standard library and existing compatible Hermes |
| Managed paths / preservation | Yes: additional derived tables inside existing profile-owned databases; v2/raw data retained |
| Persistent units | No |
| Secrets | No |
| Capability / acceptance | Yes: bounded v3 candidate, still awaiting implementation review and target qualification |
| Rollback / restore | Yes: explicit host epoch/capture invalidation before old writer handoff |

These changes require a future Assembly candidate relock, not an overwrite of
its selected deployment pins. This main-repository task records the new source
and rollback obligations; it does not mutate the second repository or label a
source-only candidate as installed.
