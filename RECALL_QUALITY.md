# Recall-quality candidate — 2026-10-23

Scope: improve question-driven recall locally before resuming Hermes upgrades.
Primary repository: HermesContinuity. Mother AsherieSystem is read-only. No
merge, deployment, production configuration, live corpus, provider/QQ traffic
or GitHub Actions is part of this change.

## Exact comparison points

- Plugin baseline: accepted H13-v3
  `75aecd6d6544f3dcb313c42bf917c4a015a31cea`, not the older public `main` tree.
  A PR against public main consequently also carries that previously accepted
  prerequisite; the new recall delta is the diff after `75aecd6`.
- Mother remote release branch readback:
  `9e4ca4bd82c9cd1f5293193f5d14bb8d22a59b3e`. Remote default `main` still points
  to older `a80850bd`; it is not the current recall implementation.
- Test host: exact accepted 29-artifact 0.21.5 source
  `06501c37567a50f8c3ee65bc359a1caae921d74f`. No host source was changed.
- The old graph guide is sealed at `0adda1b4` and is navigation ancestry only;
  the portable graph index is absent in this local brain checkout. Current
  donor Git objects, source and neutral tests supply this comparison.

## Retain / adapt / do not port

| Mother behavior | Hermes correspondence |
| --- | --- |
| Optional auxiliary recall, working lexical OFF path | `recall_auxiliary_enabled=false` by default; explicit true retains the accepted two-call path. Rolling summaries remain enabled. |
| Source-text Chinese/ASCII terms and recent-topic continuation | Adapt term extraction and pronoun hints from the original visible user carrier, bounded to 600 characters. No tool, notice or native summary becomes the hint. |
| Preserve relevance across query routes | Native queries share the existing bounded group pool, then bounded BM25-style relevance chooses output. Equal scores preserve existing owner order. No newest-weak-hit promotion. |
| Original role-aware passages instead of leading truncation | Allocate 220 characters per group before locating matching sentences, preserve short answers/negations and mark omitted text. At most four quoted groups. |
| Exact source readback | Existing canonical proof checks at plan, execution and post-settlement stay authoritative. Recall never retires or CASes a checkpoint. |
| Warm coverage reuse, memory hint aliases, Home UI and other organs | Not ported: Hermes has no equivalent owner-bound Warm coverage carrier here. No shadow store, second memory/search service or fabricated aliases. |
| Pending temporal/follow-up successor PR #388 | Not ported. OFF mode does not claim model-planned synonym/date interpretation. `reference_at` is the as-of upper bound; retrieval is lexical, not a semantic answer. |

The predecessor's source/output/shared workset limits remain: 24 complete
candidate groups, 2,048 rows / 4 MiB, 24k estimated source tokens, shared 2,048
output tokens, three native queries of at most 80 characters / 64 hits / 50-ms
SQL progress deadline each. These limits are not exhaustive recall or a hard
wall-clock/tokenizer guarantee.

## Integration defects found while testing

1. Native CJK/trigram search owns quoting. Pre-quoting every token changes that
   grammar; query terms now use only letters/digits/CJK and let Hermes quote.
2. Without an available CJK index, two-character fragments can take a LIKE
   path. A 16-MiB historical image correctly trips SQLite's value guard. Only
   explicit resource-limit outcomes (`SQLITE_TOOBIG`/`SQLITE_INTERRUPT`) may
   coexist with separately successful verified queries in lexical mode. The
   projected body says coverage is incomplete. All failed/no-result queries
   stay unavailable; changed sources/corruption are never skipped. No larger
   SQL value budget or new retry/store is introduced. Legacy auxiliary mode
   remains atomic.
3. The existing group owner already withholds the unfinished current user row.
   A focused regression verifies completed history still wins and its proof
   survives answer storage. No new tail field or identity protocol is added.
   The real Agent fixture now also reuses the already accepted .21.5 registry
   writer pattern (M5 `continuity-shared-writer.patch`), with the released
   .20.5 direct-writer fixture retained where that registry does not exist.
   This is test ownership alignment, not a runtime algorithm repair or a manual
   preparation join. Earlier intermittent source-change receipts remain failed
   evidence; they are not counted as successful delivery.

## Local verification

Commands use the existing Python 3.11.15 interpreter/test dependencies and
Python 3.12.13 with those already installed Python dependencies on `PYTHONPATH`.
`HERMES_DISABLE_LAZY_INSTALLS=1` prevents unrelated provider SDK downloads.
Test databases and provider responses are disposable/synthetic. No real chat
was read or used as a fixture.

| Final focused selection | Python 3.11.15 | Python 3.12.13 |
| --- | --- | --- |
| New lexical checks, old opt-in recall, registration, H13-v3, real Agent recall | 39/39, 63.529 s | 39/39, 65.368 s |
| Conditional skips in this final selection | 0 | 0 |

The ten new lexical checks cover short Chinese objects, English terms,
pronouns versus newly named topics, original negations/conditions, sentence and
length boundaries, unrelated/empty queries, oversized groups, native search,
partial query failure, source rewrite, pending user rows and answer readback.
The real entrypoint includes a 16-MiB historical image, an old live hole, actual
discovery and `AIAgent.run_conversation`, final provider-body capture, two
body-free delivery receipts across manager reload, and a synthetic provider
error that adds no delivery. Recall auxiliary call count is zero; no pending
tail field, weakened assertion or manual post-settlement call is used. The
retained opt-in mode still passes its eight original recall regressions.

Reproduce against the exact host with the existing test dependencies available:

```sh
HERMES_DISABLE_LAZY_INSTALLS=1 \
HERMES_SOURCE_ROOT=/absolute/exact-06501c3 \
PYTHONPATH=/absolute/exact-06501c3:/absolute/existing-test-dependencies:tests \
python -B -m unittest test_lexical_recall test_recall test_plugin_registration \
  test_h13_v3_adapter test_real_host_recall -v
```

Two initial offline test starts attempted the host's optional Bedrock package
installer before the existing isolation flag was restored. The identified test
and installer processes were terminated; final runs use the flag and do not
install provider dependencies. An upstream CJK extension was also compiled and
load-probed only as a temporary local diagnostic, not installed or required by
the final selection. Successful partial-query delivery is tested with the
original resource guards, without an enlarged value limit.

The broader non-entrypoint run initially executed 326 tests, with 1 failure,
3 errors and 22 conditional skips. Each of those same four outcomes was then
reproduced on the untouched `75aecd6` control with the same host:

- `test_history_portability.HistoryPortabilityTests.test_a2a_direct_title_writer_preserves_proof_including_noop`
- `test_history_portability.HistoryPortabilityTests.test_api_session_handlers_capture_direct_insert_delete_and_ignore_title`
- `test_history_portability.HistoryPortabilityTests.test_tui_branch_writes_real_child_but_cannot_borrow_parent_proof`
- `test_runtime.ContinuityRuntimeTests.test_replaced_original_carrier_fails_open_current_without_settlement`

The first three are old fixture/API differences; the fourth is an existing
overlay expectation. They remain red, not a newly created Green allowlist.
No claim of an all-Green host/plugin suite follows from focused recall checks.

## Assembly impact and stopping point

Eight-axis check: source identity **yes** (candidate only); artifact publication
**yes** when this review branch is pushed; runtime dependencies **no**; managed
production paths **no**; units **no**; secrets **no**; capability contract **yes**
(explicit lexical/auxiliary modes); rollback **no** (no schema/store mutation).
This impact is recorded here only. HermesPrivateAssembly is not written and no
selected production pin is advanced. Installation/deployment later needs its
own source/config receipt and assembly synchronization.

Stop after local verification and review publication. Local quote delivery and
real `AIAgent` code with a synthetic provider are not natural recall quality,
live latency, model output quality or owner acceptance. Hermes version tracking
does not resume automatically.

Independent intent audit: PASS after confirming there are no cross-repository
writes. All source-delivery commits use `[skip ci]`; no Actions run, merge or
deployment is requested. External review and natural-quality acceptance remain
separate from this local candidate.
