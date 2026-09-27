# Plan

## Product boundary

Hermes remains the owner of canonical transcript storage, original-sentence
retrieval, native `session_search`, and context compression. Hermes Continuity
owns only:

- a read-only projection from `SessionDB` into complete visible interaction
  groups;
- bounded checkpoint and recent-bridge construction;
- request-only bridge projection and physical-delivery proof; and
- a profile-local canonical-window service for trusted peer plugins; and
- generated rolling-bridge checkpoints plus body-free delivery metadata in
  plugin data. Checkpoints do not copy canonical transcript sentences. The
  receipt schema accepts bounded failure receipts, but the v1 runtime does not
  mint them from `api_request_error`.

It must not become a second transcript store, an FTS/search subsystem, a memory
provider, or a replacement compressor.

## Current implementation gate

- Preserve the extracted Thread Continuity algorithms and authority carriers.
- Adapt source ownership to Hermes `SessionDB` without using row IDs as stable
  message identity.
- Keep the recent bridge bounded at 72 hours / 24,000 source tokens / 2,048
  output tokens.
- Project only into a supported current-user request carrier.
- Require execution-stage proof before `post_api_request` may CAS a checkpoint.
- Bind that proof to the final provider body after provider-specific preflight
  and Relay rewriting.
- Accept only host-resolved context windows with explicit provenance; leave
  fallback/unknown resolutions native and apply the owner-bound final-body
  filter before the SDK call.
- Keep canonical-window scans physically bounded, compression-lineage aware,
  and atomic on ambiguous or incomplete source reads.
- Let trusted consumers request a closed source-class subset. Exclude clearly
  disallowed classes before returning bodies without turning policy exclusion
  into source ambiguity; bind the policy into the source revision.
- Leave `codex_app_server` unchanged in v1.
- Leave MoA prepared requests unchanged and unpublished until Hermes can expose
  an unambiguous final provider body for that path.
- Require all twelve generic Hermes host seams documented in `README.md`.
- Keep attempts that miss both post/error hooks under a strict count cap and
  TTL. Expiry revokes settlement authority. Execution may remove an expired
  carrier only while it still holds the exact bound proof; if another entry
  point has already swept that proof, it preserves the request unchanged
  rather than guessing that user-authored text is plugin-owned.
- Bind the read-only canonical handle to the active profile's `state.db` and
  metadata to that profile's Hermes-owned plugin-data realm. Reject Hermes
  canonical schema, files claimed by a different plugin owner, and unclaimed
  nonempty SQLite rather than accepting path overrides.

## Long-history gate

Block 1 is **complete-entry transitional protection and resource baseline**:
guard full-prefix messages and checkpoint loading before payload transfer,
preserve small-session compile/settlement, and measure the full plugin chain in
disposable processes. Source overflow may still leave native Hermes unchanged.
It does not prove continuity for sessions exceeding 2,048 physical rows.

Block 2 must freeze the writer census, host pagination/source-validity protocol,
publication guarantee and checkpoint-v3 format before Block 3 implements them.
The accepted specification is [LONG_HISTORY_PROTOCOL.md](LONG_HISTORY_PROTOCOL.md):
host-owned change capture and bounded indexes, conditional checkpoint storage
with validation on every use. The owner accepted Block 2 at `e54472f2` and
authorized Block 3 implementation. Current work adds a thirteenth host patch,
compact v3 storage/compiler input and bounded preparation; implementation
review and deployment remain distinct. See LONG_HISTORY_IMPLEMENTATION.md.
Index progress, provider delivery and checkpoint publication remain separate
facts. Index completion must not trigger whole-history model summarization.
Block 3 must positively prove a >2,048-row bridge, actual settlement and next-turn
reuse. The accepted Block 1 exact SHA becomes the preferred v3 rollback target;
`34780f0` / 0.4.1 remains a historical recovery point, not an equivalent guard.
The accepted source rollback SHA is now
`1d6f502f2c21636d9f75b31fcc46f109c3bfece6`; this does not select a deployed pin.
Retained v3 data alone cannot prove writes performed by an older host.

This block changes neither the accepted 0.21.3 migration lane nor Global Hot's
product algorithm. Its byte guard applies to the full-prefix Continuity entry;
the separate canonical time-window service retains its existing row budget.

Checkpoint v2 still reads and proves the complete canonical prefix and stores
full-prefix identity/fingerprint arrays. Work, memory, and checkpoint bytes
therefore grow with total history while the physical row count remains within
the configured full-prefix budget. Larger sessions leave the request on the
native Hermes path before the complete compacted view is decoded. Providing
Continuity bridges for those sessions still requires a Hermes-owned stable
logical anchor/prefix digest seam and a compact checkpoint v3 that proves
bounded suffix growth and detects prefix rewrite. The existing bounded
time-window API is sufficient for the cross-mouth window service, but cannot
honestly replace this full-prefix contract.

## Release gates

1. Keep the full standard-library suite Green and pass the opt-in real-host
   entrypoint proof: actual plugin discovery, `AIAgent.run_conversation`, final
   provider body, post/error settlement, SQLite readback, and manager
   unload/reload.
2. Replace the obsolete repository history before public push.
3. Push the reviewed revision for external web review.
4. Address external findings and record the exact reviewed revision.
5. Only then perform a reversible disabled installation in the target Hermes
   profile.
6. Enable and run synthetic/live canaries only under a separate deployment
   authorization.

Gates 1-3 completed on 2026-08-30. External review returned required changes;
their implementation and repeat review are the current gate. The long-history
gate above must also close before formal deployment. Installation, enablement,
deployment, and live behavior remain outside this block.
