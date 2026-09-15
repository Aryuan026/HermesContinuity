# Hermes Agent 0.21.0 Wave 2 patches

Apply these patches after the ten files in `../hermes-0.21.0-wave1/`, starting
from official Hermes Agent commit
`29112bef099274229cadff79cdff7bf7b99c4b77`.

1. `0001-feat-sessions-add-bounded-origin-aware-history-reads.patch`
   - commit: `ea71085f7c1cfe07b836491c62d14309be94f405`
   - SHA-256: `a14d71ec5ef841841b3ad26681ba0b1efc0ec5262e9a33a6806fb8a8518167b6`
2. `0002-feat-plugins-port-joint-runtime-doctor.patch`
   - commit: `8ba0825c5f290ab0f1bf23ad22913ca7ade96970`
   - SHA-256: `db8aeab2a327eeeee23ba08f64e25eb13887687f6c70c4be8ca0d9dd8fcc2992`

The resulting candidate tree is
`14fc4db373d1265c3480fe2956eb12cdc18448f8`. A disposable replay applied both
Wave 2 patches with sequential `git apply --check` on the exact accepted Wave 1
parent; its staged tree was byte-identical to that candidate. The ten Wave 1
artifacts remain byte-exact.

Wave 2 adds only H4 and H10. H13 contributes an opaque durable per-message
origin-proof storage substrate here, not any writer classification. H5-H7,
H12, both public plugin algorithms, runtime configuration, and the live estate
remain unchanged.

H4's bounded views reuse the 0.21 compressor grammar to project genuine live
content out of composite Lean handoff carriers. Rotation-child assistant
carriers remain synthetic because their closed parent owns the original turn;
user-leading carriers remain live for the child response. The physical wrapper
survives only as a body-free digest in Continuity's projection namespace, so
same-session wrapper conflicts still fail closed while legal lineage generations
collapse. Persisted `api_content` follows the same ownership rule in bounded
views: its body-free digest remains a same-session audit fact, but the original
provider-side body is not exposed or treated as cross-lineage dialogue identity.
Exact empty user/hidden provider scaffolds additionally keep a fixed body-free
presence sentinel, allowing the unchanged reader to exclude them without
recovering the provider payload.
