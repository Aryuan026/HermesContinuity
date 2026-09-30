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
