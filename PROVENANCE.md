# Provenance

Hermes Continuity is an owner-authorized extraction from the private
AsherieSystem revision
`ddfb1e9aeb7c6f7797912e959a0970c621875c83`. The extraction preserves the
tested Thread Continuity algorithms while replacing Asherie-specific storage,
surface routing, and service wiring with narrow Hermes host seams.

The Hermes compatibility lineage is:

- upstream Hermes 0.20.5: `fcbd1076a93841fa88855acce810e342a5b78101`;
- reviewed owner overlay: `c7c36f36ccee592a96f90e8acd9c6401808a02ad`;
- generic PluginLlm finish-reason seam:
  `201fe7756c57c35aaed9af8e9886e10ff4d25cfe`, also exported as
  `patches/hermes-0.20.5-plugin-llm-finish-reason.patch`;
- sequential request middleware and `hermes.middleware.v2`:
  `b7fac683859f5997b4cc63a951078b99c209abbc`;
- profile-scoped service registry:
  `22dd21241f3628e0d25b808012f07874d45310d4`;
- bounded SessionDB time-window reads:
  `20b7b9a3b4f66871686503f222e39f4c55a058a5`;
- final provider-body transport truth and `hermes.transport.v1`:
  `81f8fa21167b1fcd3929b27ee172b6cf7a94ec21`;
- closed finish-state truth across auxiliary/provider adapters:
  `5e1b05f04b193ade4eb16fb28f29198b0ee672a3`;
- host-resolved context provenance, final provider-body filtering, and
  `hermes.transport.v3`:
  `7a5c6ca23b544d73fb37a3a1c7d8b08d1a82938c`;
- verified durable wakeup provenance:
  `7c183e81832c81e29f6d095a15bb7c8cd080ee5c`;
- installer manifest-v2 alignment:
  `113b4ab5285f92a1013c6a494eb33260a7f70140`;
- joint plugin Doctor:
  `969cf5bdbc3a110e475c02ed8e4ee84f64be32ed`;
- shared request overlay ownership and proof:
  `5a680e5e38625fb3275b4bf6973a40d089ec11a7`.

The exported patch SHA-256 values, in application order, are:

1. `7e46190001282848025f65cf7916c3bc9c00dba998755cc465d57303c61a7eee`
2. `c23622949a7db978ff55ac1b72c02825dbcbe9829ea5aec1e672a5d1e8077ab9`
3. `68842a05eaa1eb57ec3cdbf615bae1e6f90a8219cbcc5ba9bc43df5a6a170b2c`
4. `1265304580e505908f5a8af4fcb19b53652ca650fcc766319d6b859c73f05aae`
5. `6be7bad538228bbc48100eb04aa02a45edf07d961b9a7af548c5a66494bfd3d6`
6. `338105b9aaaebd99a6ce267044818495951ec9e46293f98ee61cf3f62cce9a19`
7. `70d2362cbb15b4e8adce356762e1d7c23e705f3bf5e1ca0a901268ff8109f49b`
8. `6b17af93fe29aa1b4fd7ac789dacc3443747e381a1c8bbf1329862e3027b37cb`
9. `f8130812abc94488149be8e196473333465842f01028a0ab30ebdda983a49e4c`
10. `99b4847dc3af412f6a0696735021d8ee0a33f6364bab93c426c12f36332e2cfb`
11. `f3e70e70b0811beb390ef034d1c080497724f3061d93c83ae0329bdd7547f2c6`

## Extraction matrix

| Decision | AsherieSystem donor | Hermes Continuity target | Treatment |
| --- | --- | --- | --- |
| Retain | `services/home/app/context_compactor.py`: `_ThreadContinuityPhysicalOwnerSidecar`, `_content_to_text`, `_normalize` | `context_compactor.py` | Retained the physical-input authority used by compilation and checkpoint-candidate validation. The prompt-plan/fixed-selection capabilities were initially retained for donor parity, then excluded because the Hermes product has no finalizer registration or consumer. |
| Adapt | `services/home/app/context_compactor.py`: the continuity compactor section through `accept_summary_chunk_attempt` | `context_compactor.py` | Retained checkpoint v2, its nested retirement/recent-bridge v1 schemas, fold planning, physical-owner proof, summary/chunk planning, acceptance receipts, and bounded validation. Removed the top-level `thread_continuity_checkpoint.v1` builder, normalizer, legacy bridge projection, and physical-owner relation only after the body-free owner-store census found zero v1 rows and zero malformed rows across the known local and Tencent estate. Unexpected top-level v1 now fails closed and is never projected or migrated. |
| Retain | `services/home/app/thread_continuity_runtime.py`: live compilation, summary/chunk acceptance, and physical-input validation path | `thread_continuity_runtime.py` | Retained the compiler used by `ContinuityRuntime`. The fixed-prompt finalizer and token-watermark context-epoch planner were initially retained for donor parity, then excluded because Hermes registered no policy, configuration, caller, or result consumer for them. |
| Do not port | `services/home/app/thread_continuity_gateway.py`: linker validation/projection and capture trace functions | none | Initially retained for donor parity, later excluded from the Hermes product artifact because no production registration or consumer existed. Exact donor revision and symbols remain recorded here. |
| Retain | `services/home/tests/test_thread_continuity_compactor.py`, the production-compiler cases from `test_thread_continuity_runtime.py`, and the first five pure-algorithm cases from `test_thread_continuity_recent_bridge.py` | matching files under `tests/` | Ported live compiler behavior tests; removed tests that only exercised the unregistered context-epoch/fixed-finalizer paths. Asherie host token/cache helpers remain replaced with test-local equivalents. |
| Do not port | `services/home/tests/test_thread_continuity_gateway_carrier.py`: the five linker-only cases | none | Initially retained for donor parity, later excluded with the unregistered gateway/linker projection they tested. The donor revision and original case names remain recorded here. |
| Adapt | `services/home/app/conversation_cache.py`: `read_thread_continuity`, `read_thread_continuity_bundle`, `read_exact_thread_source`, `_thread_source_projection`, `_thread_source_group`, `compare_and_swap_thread_continuity`, and publish helpers | `hermes_adapter.py`: `HermesSessionAdapter`, `ContinuityMetadataStore` | Replaced JSONL/cache ownership with read-only canonical `SessionDB.get_messages` views and a separate derived-checkpoint/body-free-receipt SQLite store. Clone order/collision checks follow Hermes canonical semantics; transcript bodies are not copied. |
| Do not port | `services/home/app/hot_context/store.py`: `canonical_aliases` as a standalone helper for the linker-only projection | none | Initially adapted into `identity.py`, then excluded when its sole unregistered consumer was removed. Live canonical identity remains owned by the compiler and Hermes adapter paths. |
| Adapt | Asherie mouth preflight/transport integration around Thread Continuity | `runtime.py`, `__init__.py`, and the two `patches/hermes-0.20.5-request-overlay-*.patch` artifacts | Replaced Home/mobile/public-gateway carriers with a Hermes request-only projection, execution-stage proof, post-API CAS, and plugin registration. H11 moves generic carrier/proof/final-budget behavior into Hermes and deletes the plugin copy; Continuity retains only its marker, frozen current-user identity, checkpoint, and settlement policy. This is host integration, not a rewrite of the retained compiler. |
| Adapt | Hermes PluginLlm result boundary | `patches/hermes-0.20.5-plugin-llm-finish-reason.patch` | Adds generic finish-reason exposure needed to reject incomplete summaries. It is a Hermes core prerequisite, not plugin-owned monkey-patching. |
| Adapt | Hermes request middleware, service registry, bounded SessionDB read, transport truth, closed finish-state truth, final-body budget filtering, and wakeup provenance | the seven subsequent ordered patches under `patches/` | Adds generic host composition, profile-local peer services, physically bounded canonical reads, final provider-body evidence/filtering, provider-complete finish normalization, and an unforgeable durable wakeup sidecar. These seams contain no Continuity algorithm. |
| Adapt | Hermes plugin installation, Doctor lifecycle, and request overlay ownership | `patches/hermes-0.20.5-installer-manifest-v2.patch`, `patches/hermes-0.20.5-joint-plugin-doctor.patch`, and the two `patches/hermes-0.20.5-request-overlay-*.patch` artifacts | Reuses the runtime manifest-version authority in CLI/dashboard installation, lets Doctor load companion plugins in one temporary profile, and gives request plugins one shared carrier/proof/final-budget contract whose disposition is committed only after host acceptance. These are generic host seams, not Continuity exceptions. |
| Adapt | Asherie cross-mouth recent-source ownership | `hermes_adapter.py`: `ContinuityCanonicalSourceService` | Replaced Home cache/window ownership with a neutral, read-only, profile-local canonical service over complete Hermes dialogue groups. v2 adds a closed Hermes source classification instead of disguising all origins as donor `home_gateway`. The service exposes no Global Hot material schema and persists no bodies. |
| Do not port | `ConversationCacheStore` JSONL buckets, append/capture paths, recent/time-window query and ranking, query scoring, filesystem repair ledgers, and cache search/storage | none | Hermes `state.db` remains the only transcript archive; original sentences remain searchable through native `session_search`. |
| Do not port | `thread_continuity_gateway.py` Home/mobile/public-gateway preflight, transport reconciliation, `runtime_admin`, and capture-surface ownership | none | Those contracts belong to AsherieSystem surfaces and are not valid Hermes plugin APIs. |
| Do not port | Home service startup, Bridge/mobile/chatbox wiring, provider-cache ownership, and Asherie capture workers | none | The plugin registers only Hermes request/execution middleware and post-API/error hooks. |
| Do not port | Asherie memory-provider registration or any replacement compressor behavior | none | Hermes Continuity is neither a memory provider nor a compressor owner. |

## Storage and retrieval ownership

`HermesSessionAdapter` reads `content` from Hermes canonical rows and never uses
`api_content` as continuity material. The plugin database stores checkpoint
state, including the generated rolling-bridge body, plus body-free receipts.
It contains no copied canonical transcript, FTS table, or search index and the
plugin registers no search tool.

The profile-local canonical-window service returns bounded canonical bodies only
to a synchronous in-process caller. Its source revision covers request bounds,
session snapshots, stable identities, and content hashes. The service trace and
delivery receipts remain body-free; the separate checkpoint row persists the
generated rolling-bridge body as stated above.

Consequently, searchable exact history and original-sentence retrieval stay in
Hermes `state.db` and native `session_search`; the recent bridge is only a
bounded request carrier.

The compatibility patches retain the upstream Hermes/Nous MIT notice in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
