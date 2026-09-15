# Hermes Agent 0.21.0 Wave 3 patches

Apply these seventeen patches after the ten Wave 1 patches and the two Wave 2
patches, starting from official Hermes Agent commit
`29112bef099274229cadff79cdff7bf7b99c4b77`.

1. `0001-feat-middleware-port-provider-transport-truth.patch`
   - commit: `5a8608e`
   - SHA-256: `8cc53413084e6e3deb88c54c9ce0380aae00bf78a80823f295e461a89f077900`
2. `0002-fix-llm-port-closed-finish-state-truth.patch`
   - commit: `1b46eef`
   - SHA-256: `55f672e323a9405458f8bd048f34a22a5c34b7ec010127719f9c0d6957dda70d`
3. `0003-feat-middleware-port-final-provider-budget-controls.patch`
   - commit: `39e1e72`
   - SHA-256: `ef2ee82bf82fc2d6c304595e1bc4c5a617c36c8effe9959d55804b2d9e3aed6d`
4. `0004-fix-middleware-settle-provider-overlay-acceptance.patch`
   - commit: `68e192e888827477c7157beff11d33df7fe0db2a`
   - SHA-256: `a6c9c8bf1f79fbe9c0f501a386fcb13543a708be3f0213983193b935d92f57a3`
5. `0005-fix-transport-model-explicit-SDK-fallbacks-as-succes.patch`
   - commit: `98206156a21de08a48e7b12728f5346ea121e36a`
   - SHA-256: `bd063c0dc511715a3323b3c6d6a4bb5cf3763824b457e0e20f4037e5e5b4dbf2`
6. `0006-fix-middleware-certify-and-roll-back-final-provider-.patch`
   - commit: `f99d2480c115cdbe4a9069fe43fc3b161d517c5e`
   - SHA-256: `1ee590339f65345c7887834398ec3c58ab8f72d5bd28c3215f3a16d2a7575a01`
7. `0007-fix-transport-fail-closed-for-native-Gemini-bodies.patch`
   - commit: `a983219186ed1ee40847166f8571b847eaeddb4b`
   - SHA-256: `de986430cf8edc69527e1be01a5bd32ded594f64f501a285e53400647b300b2b`
8. `0008-fix-budget-account-Bedrock-native-tool-and-output-bu.patch`
   - commit: `4e8c41d7e0ca43f9f44715fb16afcda3f482c37b`
   - SHA-256: `3de9cddb94480f515400e692f22c2c0f15dc326222902177af8f8ab402dc9cfb`
9. `0009-fix-transport-reconcile-streaming-retries-with-attem.patch`
   - commit: `bfd311f992f5a3a1d3af32a095469e35576c2c3a`
   - SHA-256: `12b08eeb68d0ca242fdb9bf5559482dad93e5f56b1eb64ff379fbacbc2622e81`
10. `0010-fix-codex-fail-closed-for-SDK-transform-bypass.patch`
    - commit: `40efdba5aaa57ce3911cabef657f3492d8cbdb37`
    - SHA-256: `6a3497331cc39288191d6816dbafd22cd6585ee21eb890603713d58834553240`
11. `0011-fix-budget-account-Anthropic-native-input-schemas.patch`
    - commit: `1ead5fe47818ca3e538da7dde71fa33ca2820d5d`
    - SHA-256: `8893d3fb0fc3e19fb72bc1321cd93bdba3e4697b5d762b2379be4ebab8a5b776`
12. `0012-fix-overlay-remove-owned-context-on-scope-drift.patch`
    - commit: `5c065be82349d5ab6de45261a31debecdaf86a32`
    - SHA-256: `c2008d4a002a739867269468483c9cdc3caf551df4fcc0c8f436bcb8c56f28be`
13. `0013-fix-transport-require-dispatch-certainty-for-stream-.patch`
    - commit: `46e5699fdb44e2ffb58383ccb44ad66e44925a68`
    - SHA-256: `b4ce15bb5cfdc6caff4e9a1f9df3cf7e37be86b2b615f2c1ed2b41faf22c336f`
14. `0014-fix-transport-expose-SDK-extra-body-semantics.patch`
    - commit: `4a70e0f3486b6e5eadc6503d0bd4ea2df7f95bfc`
    - SHA-256: `66cde88bba3b0ee7f1eba8fbca0127f5e6e794098575f572fe42274575413f02`
15. `0015-fix-budget-make-final-tool-estimates-value-stable.patch`
    - commit: `e4676c1e6245fd4296d0cd6540e4b5517ecd9536`
    - SHA-256: `6e814268d652f00737b3dc982d98879b8b78ab981861515fa13603b9e0cdeeb6`
16. `0016-fix-transport-preserve-SDK-controls-and-Anthropic-ex.patch`
    - commit: `4a41ea9834bb41f2ba4dbc8bd3a309c4b0d19c80`
    - SHA-256: `e138da7e55d254dd26c42490855c366e08ce0c4fe9465c729cf0dab9f249be02`
17. `0017-fix-transport-re-encode-semantic-extra-body-lossless.patch`
    - commit / head: `4250b46f2151f413717380475f3496c2e5bdc112`
    - SHA-256: `e9984ac87416ce1db75b625a4880ef0a7a4fdb1281296fb173efa02407c67622`

The accepted Wave 2 parent is
`8ba0825c5f290ab0f1bf23ad22913ca7ade96970`, tree
`14fc4db373d1265c3480fe2956eb12cdc18448f8`. Sequential forward
`git apply --check` and apply from that exact parent reconstructs corrected
candidate tree `226c1f9c9d8a9116445d26bad923e4954a6fcaff` byte-for-byte.

Wave 3 ports only H5, H6, H7, and H12. It establishes final SDK-body capture,
closed provider finish truth, host-owned context provenance, final nonexpansive
budget guards, request-overlay acceptance dispositions, and physical isolation
between native Lean auxiliary summaries and foreground transport settlement.
The thirteen append-only corrections model explicit Bedrock and Anthropic SDK
fallbacks as physical successor attempts, defer overlay dispositions until the
selected SDK attempt returns, require capability-certified changed final
guards, roll back registrations from failed middleware callbacks, fail closed
for unsupported native Gemini body truth, and account Bedrock-native tools and
output reserve. They also make generic and Codex streaming retries obey
open-versus-terminal physical-attempt truth, fail closed before H11 execution
when the Codex SDK would hide semantic input or tools in `extra_body`, account
Anthropic-native `input_schema`, and remove owned context with a certified
`drifted` disposition when scope validation fails but native removal remains
provable. Corrections 13-15 restrict same-record stream retries to
failures proven not to have dispatched, normalize OpenAI-compatible and Codex
`extra_body` semantics before transforms, guards, estimation, and capture, and
make final tool-schema estimates value-stable and CJK-aware.
Corrections 16-17 preserve opaque SDK controls, model Anthropic's Stainless
`extra_body` merge for fast mode, and retain enough key provenance to encode
late provider extensions back through `extra_body` instead of invalid SDK
keywords. Default Codex list/dict production requests remain deliberately
unsupported for provider-body receipts at the earlier conversation-loop gate;
the low-level codec proof does not claim that gate has been removed.
It does not change either public plugin, mint H13 origin proofs, install or
enable the candidate, or touch the live Tencent estate.
