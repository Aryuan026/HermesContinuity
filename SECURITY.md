# Security and privacy

Hermes Continuity runs in process with Hermes and should be treated as having
the same local privileges as the Hermes process. Install only reviewed
revisions.

## Data boundaries

- The active Hermes profile's `state.db` is opened through
  `SessionDB(read_only=True)` and remains the canonical transcript owner.
- Continuity metadata is fixed under the same profile's Hermes-owned
  `plugin-data/<host-owned-plugin-namespace>/` directory. Neither database
  path is configurable by the plugin.
- The plugin does not copy canonical messages, create FTS/search storage, or
  register a search tool. Exact historical sentences remain retrievable through
  Hermes native `session_search`.
- The separate plugin-data database stores the generated rolling-bridge body
  in checkpoint v2, together with source proofs and revision state. It does not
  copy canonical transcript sentences. Delivery receipts remain body-free:
  IDs, hashes, counts, status, and timestamps only. Its receipt schema can also
  validate explicit failure records, but the v1 runtime clears failed attempts
  without minting an `api_request_error` receipt.
- `api_content` may be audited for collision detection but is never used as
  continuity body material.
- The canonical-window service may return canonical message bodies only in its
  synchronous in-process response. Its trace and delivery receipts never
  persist those canonical bodies, and the checkpoint store persists only a
  separately generated rolling bridge rather than the service response.
- Canonical-window v2 classifies every complete group into a closed source
  class. Dynamic/unknown sources stay `unknown`; internal, delegated, and tool
  origins cannot become `human` merely by choosing a platform-looking label.
  Wakeup classification requires durable host provenance.
- Real conversation fixtures, runtime databases and sidecars, configuration,
  logs, credentials, owner/channel identifiers, and private paths must not be
  committed.

## Request safety

The bridge is labeled reference-only and has no persona, style, memory, or
action authority. A dynamic opening marker and exact closing boundary separate
the quoted bridge from the current user instruction. Projection is limited to
the current request and is verified against the final provider body after
provider preflight and Relay rewriting. Unsupported or ambiguous carriers fall
back to the unchanged Hermes request.

The plugin consumes Hermes's resolved context-window tokens, source, and
confidence instead of resolving the model independently. Fallback/unknown
windows remain native. Catalog/cached values use an additional 10% window
margin. Hermes estimates the final SDK body with message, system/instruction,
tool, and image allowances plus a 15% + 64-token framing margin; this is a
heuristic with margin, not a tokenizer proof. If the estimate no longer fits,
the final-body filter removes only the bound Continuity block before the SDK
call. Failure to prove ownership never authorizes deleting user text.

Checkpoint publication occurs only from `post_api_request` after a verified
projected request has physically traversed the provider call. Revision and
source-snapshot CAS prevent a stale compiler result from silently replacing a
newer checkpoint. Ambiguous clone/collision history and source-prefix rewrites
fail closed.

The checkpoint update and its delivery receipt commit in one metadata-database
transaction. Source rereads occur before that transaction, so a long source
scan cannot hold the metadata write lock. The fixed canonical and metadata
paths are derived from the same active profile rather than caller input.
Before any Continuity table is created, the metadata store rejects Hermes
canonical tables, a foreign/malformed owner, and unclaimed nonempty SQLite
schema; a valid store carries one single-plugin owner claim.

`api_mode=codex_app_server` is deliberately unsupported in v1 and receives no
projection. MoA prepared requests remain transport-ambiguous and cannot publish
a checkpoint or delivery receipt.

## Host patch

The plugin distribution records twelve ordered generic host seams in `patches/`:
finish
reason exposure, sequential request middleware, profile-scoped services,
bounded SessionDB time-window reads, provider-body transport truth, closed
finish-state normalization, final provider-body budget controls, and verified
wakeup provenance, followed by manifest-v2 installer alignment and joint
Doctor support, then shared request-overlay ownership/proof and host-accepted
overlay disposition. Review and apply them to the documented compatible Hermes
base before installation. Plugin registration fails visibly when a required
runtime schema or API is absent.

Report vulnerabilities through a private GitHub security advisory. Do not put
conversation content, credentials, local paths, or runtime database excerpts in
a public issue.
