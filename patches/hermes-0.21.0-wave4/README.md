# Hermes Agent 0.21.0 Wave 4 patch series

Apply these patches after the seventeen Wave 3 patches, starting from accepted
Wave 3 head `4250b46f2151f413717380475f3496c2e5bdc112`.

1. `0001-feat-provenance-persist-closed-message-origins.patch`
   - commit / candidate head:
     `571e397833874c1a3445d3983ef23510e1d0aa98`
   - SHA-256:
     `244f3b802f0b29dd891ac81aeeca4a26f69e517bfd191c8e0105af65d68a1279`
2. `0002-fix-provenance-split-cross-origin-busy-input.patch`
   - commit / candidate head:
     `d4a8949637c05175cd27c38e7edb67adfe736592`
   - SHA-256:
     `c2eab2af373d066c119228e88ae188694860c8adf7137a756cc08534034decb1`
3. `0003-fix-provenance-preserve-CLI-queued-input-origins.patch`
   - commit / candidate head:
     `a748f62eaebc5e5353696fa260994a652cf155c2`
   - SHA-256:
     `c78596ffdddc9726dd015a6324735b593f7cc790d4a2935974e6693c8f8399c2`
4. `0004-fix-provenance-bind-CLI-turn-origins-before-busy-sta.patch`
   - commit / candidate head:
     `b4587a9c9b6a3dc865cd4f7fc14ba4849a7dbbac`
   - SHA-256:
     `dda033659e2427d59aa0fbf0aae7d8127dbb4e1d06f696bbf160a1dfdeaf5daf`
5. `0005-fix-provenance-keep-host-queued-CLI-messages-literal.patch`
   - commit / candidate head:
     `2cac00e0fdee2a0aeca8084439159d77625a5663`
   - SHA-256:
     `c9c077ea2fc640f186c0f31460c8091bc7587069511a9c33ed7356f79d501b94`
6. `0006-fix-provenance-keep-host-injected-context-refs-liter.patch`
   - commit / candidate head:
     `13900108780ae712059075200b243aa049c634cf`
   - SHA-256:
     `02e857578d67b0f5583850d78771e5b6eb9f74db65b2d99907ee9d7800b4b029`

The accepted Wave 3 parent tree is
`226c1f9c9d8a9116445d26bad923e4954a6fcaff`. Sequential forward
`git apply --check` and apply reconstructs Wave 4 candidate tree
`5e82789d9984f8c338c09bdd0ebb31794af1f0dc`.

Wave 4 ports H8 and completes the H13 writer layer over Wave 2's opaque
per-message storage substrate. It adds a closed host-owned origin proof for
human, scheduled, internal, and delegated turns; threads it through the real
QQ/WeChat and other gateway mouths, CLI/TUI, cron, Bot Chat, peer/room, wake,
compaction, branch-copy, shutdown-recovery, and restart paths; and keeps
synthetic Lean summary shells unproved.

The second patch closes the busy-turn provenance boundary. A new input may
mutate a running turn only when its closed proof exactly matches the running
turn proof. Cross-origin or unproved gateway, CLI, TUI, API, or ACP input is
queued as a separate turn (or rejected by the run-steer endpoint with an
explicit instruction to submit a new run). Human input may still interrupt a
scheduled turn, but its text is never folded into that turn's user or tool row.
Durable stamping is idempotent for the same proof and rejects relabeling.

The third patch closes the official plugin-to-CLI queue bypass. CLI queue
entries may now carry a host-owned producer proof, including an explicit
unclassified result. `PluginContext.inject_message()` therefore stays
unclassified instead of acquiring `cli.user / human` authority merely because
the CLI transports it. The envelope survives interrupt rejection, requeue,
pending-input staging, and persistence. Keyboard and voice input keep their
human proof; scheduled, delegated, and other host-produced notifications keep
their own classification.

The fourth patch binds the selected agent's queued proof before publishing
the new turn as running, so a CLI steer can never pass its fence against the
previous turn's cached proof. It also classifies only real
`async_delegation` process events as delegated; ordinary main-agent completion
and watch events remain explicitly unclassified.

The fifth patch makes every host-produced `QueuedInput` literal message data,
not CLI control text. Enveloped payloads bypass voice-stop, resume selection,
file/paste expansion, bang-shell execution, and slash/alias/skill dispatch
while retaining their exact proof. Bare keyboard and voice commands keep the
existing CLI behavior.

The sixth patch carries that explicit content boundary through the final CLI
`chat()` call. Host-enveloped `@file`, `@folder`, `@diff`, `@git`, `@url`, and
plugin context references remain literal while keyboard, voice, and single-
query expansion stays enabled. Gateway events that already declare
`allow_gateway_control=False`, including official plugin injection, now use the
same existing boundary for context-reference expansion.

This is a source-review candidate. It does not change either public plugin,
backfill pre-H13 rows, install or enable the 0.21 host, exercise a real network
provider, or touch the live Tencent estate.
