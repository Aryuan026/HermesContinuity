# Repository instructions

Preserve these owner and provenance boundaries:

- `state.db` is canonical and read-only to this plugin.
- Do not copy transcripts, add FTS/search storage, or register a replacement
  search tool. Original-sentence retrieval belongs to Hermes `session_search`.
- Checkpoints may store the generated rolling-bridge body and its source proof;
  they must never copy canonical message bodies. Receipts and public traces are
  body-free IDs, hashes, counts, status, and time.
- This is a request-only continuity bridge, not a memory provider and not the
  owner of Hermes context compression.
- Preserve the owner-authorized extraction lineage in `PROVENANCE.md`. Before
  changing retained algorithms, compare the exact donor symbols and tests at
  AsherieSystem revision
  `ddfb1e9aeb7c6f7797912e959a0970c621875c83`.
- Keep the Hermes baseline explicit: upstream `fcbd1076`, owner overlay
  `c7c36f36`, and ordered generic seams `201fe77` through `7c183e8`.
- Do not weaken physical request verification or move checkpoint CAS before
  `post_api_request`.
- Verify delivery against `hermes.transport.v3` final `provider_body`, not the
  earlier middleware request.
- Use only host-resolved context windows with explicit provenance. Never revive
  the plugin-local model resolver or describe the final-body heuristic as an
  exact tokenizer bound.
- Keep `canonical-source.v2` profile-local, read-only, bounded, lineage-aware,
  and body-free outside its synchronous response.
- Keep `codex_app_server` unsupported until a real v1 carrier/proof contract is
  reviewed.
- Keep MoA checkpoint publication disabled while its final provider body is
  transport-ambiguous.
- Runtime dependencies remain standard-library-only. Test with
  `python -B -m unittest discover -s tests -v`; use `HERMES_SOURCE_ROOT` for the
  optional real `SessionDB` integration.
- Never commit real owner/channel IDs, private paths, secrets, config, logs,
  databases, SQLite sidecars, or conversation fixtures.
- Do not describe the plugin as published, installed, enabled, deployed, or
  live-verified until that exact state has been demonstrated and recorded.

Use the smallest compatible change. Update `PROGRESS.md` only when a release or
deployment gate actually changes.
