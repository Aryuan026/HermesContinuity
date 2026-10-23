# Hermes Continuity

**给压缩后的对话留一段近期上文，并按当前问题召回相关旧片段，不把整段历史反复塞回模型。**

这是一个实验性的 Hermes 工作上下文插件，不是永久记忆库，也不替代原生压缩器。
它读取 Hermes 已有历史，只向本轮请求递送有界的连续性桥和相关片段；另为
[Global Hot](https://github.com/Aryuan026/HermesGlobalHot) 提供只读来源服务。
简单区分：**Continuity 接同一段对话的过去，Global Hot 接其他会话的近期动静。**

## 支持版本与当前状态

核对日期：**2026-10-23**。插件版本为 **0.4.2**；同一版本号下仍须固定 Git 提交。
这里的“适配”指经过验证的**插件＋补丁宿主配对**，不是纯上游 Hermes 开箱即用。

| Hermes 版本 | 对应代码与使用条件 | 状态 |
| --- | --- | --- |
| **0.20.5** | 本仓公开主线；从上游 `fcbd1076` 按顺序应用 [host patches](patches/) | 可重放的公开基线：前 12 枚为基础，13–19 为长历史与问题召回增量 |
| **0.21.3** | 单独移植的历史装配线，不能套用 0.20.5 补丁安装 | 已有阶段验收，保留为历史参考 |
| **0.21.5** | 固定插件 [75aecd6](https://github.com/Aryuan026/HermesContinuity/commit/75aecd6d6544f3dcb313c42bf917c4a015a31cea) ＋对应已补丁宿主 | 已验证的维护线；适配层不同于 main，本仓尚未提供完整公开宿主安装包 |
| **0.22.0** | 仅开始本机宿主插件底座迁移 | **尚未取得本插件运行支持** |

其他版本未验证；0.21.0 的历史验收仅作回归参考。不要用 main 代替固定的
0.21.5 适配提交，也不要把旧补丁直接贴到新宿主上。详细身份见
[PROVENANCE.md](PROVENANCE.md)，阶段记录见 [PROGRESS.md](PROGRESS.md)；
其中旧的候选／未部署状态属于各自记录的时间和代码，不覆盖另一条适配线。

## 最近维护了什么

- **长历史不再每轮整库搬进内存**：索引分批准备，前台只读预算内的完整组；消息和
  checkpoint 在大字段解码前受字节保护。仅基础 12 枚补丁仍是受限的全前缀读取。
- **召回会自动参与本轮上下文**：公开主线通过关键词候选、完整组校验和辅助 AI
  选择／摘要递送旧片段，不只是开放一个搜索工具；目前可能增加两次辅助调用。
- **新召回候选在 [PR #10](https://github.com/Aryuan026/HermesContinuity/pull/10)**：
  默认停用这两次召回辅助调用，改用中文短词、指代续问、相关性排序和带角色的原话
  片段。**尚未合并／部署**；不关闭滚动连续性摘要，不宣称向量语义检索或自然效果已通过。

## 宿主前提

Required host contracts include `hermes.middleware.v2`,
`hermes.transport.v3`, `hermes.request_overlay.v2`, profile-local services,
closed completion states and provenance-bearing context windows. Registration
rejects missing contracts. A pure upstream install is not the patched host.

## Highlights

- **Rolling continuity, not an eternal transcript.** A recent bridge survives
  context compression while Hermes keeps ownership of history and compression.
- **Automatic question-driven recall.** Bounded keyword candidates from native
  FTS/LIKE are verified as complete groups, then selected and summarized for
  the current question. This is semantic delivery, not merely an enabled
  search tool, and not embedding-based similarity search.
- **Long history with a bounded foreground.** Incremental, body-free source
  proofs and finite background preparation replace repeated full-history
  loading when the indexed host seam is available.
- **Delivery-backed publication.** A checkpoint can advance only after the
  final provider body is verified and the successful request is post-settled.
- **One profile, one source realm.** The read-only canonical service can supply
  peer plugins without exposing private storage internals or borrowing another
  profile's databases.

## How it works

1. The compatible host maintains canonical lineage, change and source proofs.
   Background preparation verifies finite pages without calling a model.
2. The foreground admits a bounded complete-group window and compiles the
   rolling bridge; question recall separately selects relevant verified groups.
3. Both share the output budget and project into the real current-user carrier,
   without creating a new conversation role.
4. Hermes estimates the final SDK body after provider transforms. If needed,
   the host removes only the owned overlay; the native request remains usable.
5. `post_api_request` may conditionally publish a checkpoint and write a
   body-free receipt. Subsequent reuse revalidates its source proof.

Recall-only delivery never advances retirement or checkpoint CAS. A successful
store write is `stored_unvalidated`, not proof that the next turn can reuse it.
Ambiguous, changed, incomplete or over-budget material does not acquire delivery
authority.

## Installation

Choose the exact **0.20.5** host/plugin pairing from
[PROVENANCE.md](PROVENANCE.md) and [PROGRESS.md](PROGRESS.md) first.
Apply the ordered patches to that host; the baseline twelve alone do not
provide the indexed long-history/recall path.

With an initialized Hermes profile and the compatible host:

```bash
hermes plugins install Aryuan026/HermesContinuity \
  --ref <reviewed-40-character-plugin-commit> --no-enable
hermes plugins doctor hermes-continuity
hermes plugins enable hermes-continuity
```

The placeholder must be replaced with the reviewed full SHA. Install disabled,
check Doctor, then enable in the intended profile. Original-sentence search
remains Hermes's native `session_search`. No replacement memory backend or
search tool is installed.

## Configuration and limits

Defaults in [plugin.yaml](plugin.yaml):

- Recent bridge horizon: **72 hours**.
- Canonical source input: **24,000 estimated tokens** per build.
- Accepted bridge plus recall output: **2,048 estimated tokens**.
- Full-prefix fallback: **2,048 physical rows / 4 MiB** before decoding.
- Stored checkpoint budget: **1 MiB**.
- Indexed foreground groups/window: **2,048 rows / 4 MiB**; recall admits at
  most **24 groups**, from up to **three** keyword queries.
- Recall auxiliary calls share `summary_timeout_seconds`; they do not each
  acquire a new full timeout. Empty or failed recall preserves a valid bridge.
  Planning adds one bounded auxiliary call; nonempty candidates may add a
  second, besides the rolling summary. This is not a token-saving guarantee.

These are work/serialized-payload bounds, not hard Python RSS limits or exact
provider-tokenizer guarantees. The horizon controls delivery, **not automatic
history deletion**. Index completion does not trigger whole-history summaries.

Canonical history remains in the active profile's `state.db`. Derived metadata
is fixed under `plugin-data/<host-owned-plugin-namespace>/continuity.sqlite3`;
there are no arbitrary database-path settings. Checkpoint v2 and compact v3
have separate storage; checkpoints contain generated bridge material and
source proof, not another transcript. Receipts/status are body-free.

This is an experimental working-context component, not a permanent memory
archive or a guarantee of perfect recall. Historical image pixels are not
repeatedly injected; recorded image meanings are used by the bounded path.
`codex_app_server` is unsupported; ambiguous MoA transport cannot publish a
checkpoint. Natural relevance, latency and sustained stability need their own
runtime evidence.

## Verification

Use a Python environment with the dependencies of the exact patched host:

```bash
PYTHONPATH=/path/to/patched/hermes \
HERMES_SOURCE_ROOT=/path/to/patched/hermes \
python -B -m unittest discover -s tests -v
```

For the paired production-entrypoint test, also set
`HERMES_GLOBAL_HOT_ROOT=/path/to/reviewed/HermesGlobalHot`. Real-host tests are
conditional without these roots; inspect skips rather than calling them a
host pass. Fixtures/provider responses are synthetic, not live QQ/WeChat or
a measured token-saving result. Resource benchmarks and their boundaries are
documented in [RESOURCE_GUARD.md](RESOURCE_GUARD.md).

## Maintenance

For each Hermes release: trace the changed host contracts, replay against an
isolated exact checkout, verify both positive delivery and native fallback,
then update this compatibility list with the host/plugin refs and evidence
level. Version ranges in manifests are dependency constraints, not an
upstream compatibility promise. Preserve the previous accepted lane until the
new pairing is qualified; never assume old patches apply unchanged.

Source review, tests, merge, install, enablement, delivery and natural quality
are separate states. This README change does not advance any runtime state.

## Documentation

- [PROGRESS.md](PROGRESS.md): dated acceptance, deployment and observation.
- [PROVENANCE.md](PROVENANCE.md): extracted AsherieSystem lineage, host patch
  identities/digests and intentional omissions.
- [LONG_HISTORY_PROTOCOL.md](LONG_HISTORY_PROTOCOL.md) and
  [LONG_HISTORY_IMPLEMENTATION.md](LONG_HISTORY_IMPLEMENTATION.md): indexing,
  paging, publication and resource contracts; read their dated scope.
- [BLOCK4_TARGET_VALIDATION.md](BLOCK4_TARGET_VALIDATION.md): target validation.
- [DONOR_RECALL_REPAIR_NOTES.md](DONOR_RECALL_REPAIR_NOTES.md): recall repair
  lessons for the original system.
- [SECURITY.md](SECURITY.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md):
  trust, privacy and upstream notices.

## License

[MIT](LICENSE). Retained Hermes/Nous code keeps its upstream notices.
