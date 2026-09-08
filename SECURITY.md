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
- Hermes `session_meta`, hidden provider scaffolds, and clean-content-empty
  provider sidecars are excluded from source material. An inbound empty row
  with a platform message identity remains ambiguous rather than being
  silently discarded.
- The canonical-window service may return canonical message bodies only in its
  synchronous in-process response. Its trace and delivery receipts never
  persist those canonical bodies, and the checkpoint store persists only a
  separately generated rolling bridge rather than the service response.
- Canonical-window v2 classifies every complete group only through Hermes's
  host-owned H13 classifier. Dynamic, missing, and pre-H13 proof stays
  `unknown`; session source/title, display metadata, message text, transport
  shell, and plugin configuration grant no authority. Tool and interim
  assistant rows are not returned as visible source bodies, but they and every
  matching superseded physical generation remain proof obligations of the
  complete group. Invalid/conflicting proof makes only that group `unknown`.
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

## Host compatibility

The current revision requires the documented Hermes 0.21 host, including H13
durable origin proof and group classification. Plugin registration fails
visibly when that classifier or another required runtime seam is absent. The
twelve ordered patches under `patches/` remain the reproducible 0.20.5
predecessor record only; applying them to 0.21 is unsupported.

Report vulnerabilities through a private GitHub security advisory. Do not put
conversation content, credentials, local paths, or runtime database excerpts in
a public issue.
