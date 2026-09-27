# Block 2 — writer 普查与有界连续性协议

状态：**实现规格候选，待外审；没有实现 v3，也没有部署。**

## 0. 本轮合同与基线

- owner_goal：让超长历史真正有界地形成 bridge、交付、结算并在下一轮复用。
- current_phase：第二块，冻结 writer、变化证明、分页、发布与 checkpoint 格式。
- accepted_checkpoint：Block 1 `1d6f502f2c21636d9f75b31fcc46f109c3bfece6`，
  tree `cd27dc86cf53347c94946388025820a97ab620e7`。
- proposed_product_delta：本轮只交协议；第三块用有界索引替代请求内全前缀展开。
- real_consumer：Continuity adapter → donor compiler → execution/post settlement。
- forbidden_surfaces：本轮不改生产代码、十二枚宿主补丁、Global Hot、实库、服务器或版本选择。
- stop_condition：本规格与并发验收表交外审；不把文档通过记作第三块功能通过。

首选**源码回滚点**已经更新为上述 Block 1 SHA；`34780f0` / 0.4.1 仅作历史恢复点。
安装、部署、Assembly selected pin 另记，不能由源码验收推出。
PR #3 的两个提交保持不动，本规格独立交付。

本次代码普查基于该插件源码和 `.github/workflows/test.yml` 的实际宿主：
upstream `fcbd1076a93841fa88855acce810e342a5b78101` + 仓内原顺序十二枚补丁。
这是 0.20.5 兼容 lane，不是已经接受的 0.21.3 assembly，也不借机迁到 0.21.5。
文中函数名对应这个 materialized tree；后续换宿主须重做 owner 映射，不能套行号。

ProjectContinuity 当前可读，但跨层查询 coverage 不完整，代码图仍是旧 Assembly 快照，
未提供本块协议；它用于找交接，不替代下面的源码依据。

## 1. 当前真实链与 writer 普查

当前全前缀入口是 `HermesSessionAdapter.read_source()`：同 session 物理行 →
`SessionDB._dedupe_compacted_message_rows()` → `_audit_canonical_view()` →
`_project_canonical_source()` → v2 normalizer/compiler。
它不是跨 session 时间窗服务，不能把后者的 lineage 能力冒充本入口已实现。
当前 settlement 在插件库 `BEGIN IMMEDIATE` **之前**调用 `source_reread()`；
源读和插件 CAS 不是跨库原子操作。

下面的“处理”是第三块所需接线，不是已经修改了这些 writer。

| 写入族与实际 owner | 已核实的调用方／行为 | 对证明的处理 |
|---|---|---|
| `hermes_state.py::append_message / append_messages_batch / _insert_message_rows` | `run_agent.py` 持久化批次；Gateway `session.py`；TUI server；foreign-session import；mirror；shutdown spool recovery | INSERT 先视为未分类变化。只有 canonical/group 校验后，才能判作纯尾追加；不能由新 row ID 推断 |
| `archive_and_compact` | `agent/conversation_compression.py`、`context_compressor.py`；旧 active→compacted，插入摘要，SQL clone 并发尾部并重新编号 | 完整检查 clone 的可见字段及 sidecar；逻辑不变时保留逻辑摘要，更新物理证明；有冲突时作废受影响前缀 |
| `publish_compression_child` | 同一事务关 parent、建 child、写 handoff、clone 并发尾部；使用 watermark/ceiling 与压缩 lease | 拓扑和物理映射一起变化；不能把 child 新编号当新对话，也不能混入显式 branch |
| `replace_messages(active_only, archive_dropped)` | Gateway transcript rewrite、ACP、TUI retry/edit；删除或归档后重插 | 从旧／新位置的最早依赖组重算，既检查删除前索引映射，也检查重插后的分组 |
| `rewind_to_message / restore_rewound` | TUI tools、Gateway undo；改变 active，旧行仍在 | 消失／恢复的组均影响前缀；不以“正文没变”保留退休证明 |
| `set_latest_user_api_content` | `agent/turn_context.py` 回填当前 user 的 provider sidecar | 可见正文没变仍需更新物理审计；不是无变化追加 |
| `set_latest_matching_message_display_kind / set_message_reaction / take_unseen_reactions` | display kind/metadata 原地更新，包括 reaction 的删除/seen 标记 | 当前 `_signature` 包含这些字段；本块不得悄悄排除它们。重验后再决定逻辑 root 是否可复用 |
| `clear_messages / delete_session(s) / prune_sessions / _delete_delegate_children` | 清空、删除、修剪及 parent 脱离 | 保留删除事件的旧映射；session 消失或 lineage 重挂使对应域证明失效 |
| `purge_stale_tool_call_markers` | 原地把某些 assistant content 清空 | 参与可见性与指纹，必须记录，不归入仅 FTS 维护 |
| `create_session / ensure_session / update_session_meta / patch_session_model_config / reopen_session / end_session / retag_kanban_worker_sessions` | source、parent、end reason、branch/delegate 标志等可改变域／分类；model_config 不全是 UI 信息 | 对被 canonical/lineage/source classifier 消费的字段作变化记录。标题、token 计数、pin/read 等纯 UI/统计更新不改变正文证明 |
| `hermes_state_portability.py::import_sessions` | `hermes_cli/web_server.py` 导入；共享 `_insert_message_rows`，之后更新 parent | 导入不是可信 append；新域 bootstrap，既有受影响拓扑重验 |
| `tui_gateway/methods_session.py::session.branch` | 建带 `_branched_from` 的 child，批量复制历史 | 独立 source domain；父 checkpoint 不能因内容相同自动取得 child 发布权 |
| `gateway/platforms/api_server.py` 直接 session INSERT/DELETE/标题 UPDATE；`plugins/platforms/a2a/adapter.py` 标题 UPDATE | 不全经过 SessionDB 写方法 | 必须有 DB 级捕获；不能只在 Python public methods 打补丁。标题更新允许无语义变化 |
| `hermes_cli/session_recovery.py`、`session_lost_and_found.py` | 动态表名复制 sessions/messages、重建缺失 parent；不只出现字面 `INSERT INTO messages` | recovery 输出是新历史 incarnation；不复制旧证明为 ready |
| `hermes_cli/backup.py` restore、schema repair/reconcile | 可直接替换数据库；`hermes_state_schema.py` 还会迁移 active 等列 | 文件替换／schema 变化不可仅靠 DML journal 证明，必须新 epoch/bootstrap |
| `hermes_state_search.py`、FTS triggers/rebuild | 派生索引维护，正常不改变 canonical rows | 不因 FTS 本身变化触发摘要；若 repair 同时改了 canonical 表，则走前述规则 |

普查方法：检查表写 SQL、动态 copy helper、公共写方法及其调用方、恢复/替换路径，
不是只 grep `append_message`。已核对 Python 核心、agent、CLI、Gateway、cron、tools、
ACP、TUI gateway、bundled plugins、scripts/providers/web 的可用源码。
另外定向核对 desktop API/Electron、bootstrap installer、native 和 ui-tui；桌面 session 操作
走后端，更新前数据库快照不等于 canonical mutation。未把未读取的全部桌面 UI/样例称为全树证明。
第三方插件与 owner 手工 SQL 不作为“已普查的官方 writer”；下节定义其边界。
索引初次安装时还须核对实际 `PRAGMA table_info`，不把当前列名单永久写死。

## 2. 冻结的架构选择

采用 **宿主 DB 内的 body-free 变化记录和 canonical 派生索引 + 插件有界 group 索引**。
不用第二份 transcript、FTS、向量库、外部调度服务或长事务快照。

- canonical 内容仍只在 `state.db`；插件的 SessionDB handle 继续 `read_only=True`。
- 变化捕获与 canonical 索引写入属于宿主。插件只能调用窄的 host preparation/read/validate API，
  不拿 canonical 可写连接、不直接执行索引 DDL/DML。
- group 规则仍由现有 adapter 拥有；group 索引、checkpoint、receipt 在原 plugin-data realm。
  group 索引只存 ID、位置、hash、计数、状态，不复制原文。
- 初次验证 O(物理历史)，后续工作与变化/受影响后缀相关；磁盘索引可 O(历史)。
  不承诺任意前缀重写也是 O(1)，承诺每次前台、每页及内存不随总历史增长。
- 一个有界 preparation worker 串行推进 host 索引和插件 group 索引；无模型调用。
  宿主 API 在自己的 writer ownership 内短暂执行，不把连接管理复制到插件。

复用宿主 `_read_ctx / _execute_write` 的连接/事务产权，以及
`hermes_state_search.py::fts_rebuild_step` 已有的“固定高水位、事务内领取与推进”模式；
不复用 FTS 内容作连续性证明，不另造通用任务平台。窄 host seam 是第三块拟实现依赖，
本轮没有取得第二个仓的修改权，也没有提前添加第十三枚补丁。

### 2.1 捕获变化：事务内、无正文、老 writer 不靠自觉

在 canonical `messages` 的 INSERT/UPDATE/DELETE 以及被消费的 session 字段上安装
**仅用 SQLite 内建能力**的触发器，写入单调 `change_seq` 和 body-free old/new locator。
同事务提交/回滚，不能异步补日志。没有 Python UDF：旧宿主仍需能正常写数据。
UPDATE 即使只改 sidecar 也记录；主键/session 迁移同时记录旧、新 locator。
INSERT OR REPLACE 的覆盖必须通过 incoming locator 找到旧索引映射，不能依赖隐式 DELETE
必然触发 DELETE trigger。第三块须覆盖 REPLACE、cascade、批量复制和事务回滚。

只记录 locator 和版本，不在 trigger 内 hash 大正文，也不保存 old/new body。
索引还持有旧 locator→bucket/group 的 body-free 依赖，因此 DELETE 后仍知道从哪里失效。
未索引行被删不需要恢复它的正文；已被证明的行被删则不能假装前缀未变。

每个 page/read/validation 检查 schema/trigger contract、epoch 与 journal 连续性。
触发器缺失、schema 不兼容、journal 缺段均返回 `reverification_required`，不降成无界扫描。
保留触发器的普通旧宿主/直接 SQL 写入能被捕获；显式绕过触发器、离线修复、恢复旧镜像
不属于“持续覆盖”。每次失去可信宿主 preparation owner 后重新启动，建立新 activation epoch，
从 canonical 分页重验；不凭 retained v3 文件自动恢复 ready。

数据库 identity 用宿主生成的 incarnation + profile realm binding；文件路径字符串和
`PRAGMA data_version` 都不是 durable revision。合法 restore/import-to-new-DB 生成新 incarnation。
同权限外部程序在线替换文件或删除触发器再复原，不作为本协议可抵御的恶意边界；运维恢复
必须停止 writer，再按新 epoch 重验。不得宣称能从位元相同的旧镜像识别未被记录的历史。

派生日志损坏不能永久阻断 canonical 写入：沿现有 `_execute_write`/FTS fail-open 模式，
宿主只对已确认的 history-index 故障，在一次事务内标记证明失效并停用对应捕获，然后重试原写入；
不能丢掉正文写入、不能继续声称证明有效，也不能把任意数据库错误吞掉。磁盘满等不可写故障仍真实报错。
回滚交接须先由新宿主使 epoch 失效并停用新增捕获，再交给旧 writer；保留数据，不要求旧版认识新表。

### 2.2 Canonical 索引与失效依赖

索引至少持有：physical locator/version、raw dedupe-key digest、decoded semantic-key digest、
审计 signature、active/compacted 状态、bucket 的 earliest/winner、冲突状态、逻辑顺序和 prefix hash。
raw key 与 decoded key 不合并成一项：当前宿主 raw dedupe 与 adapter semantic audit 都要保留。
bucket 用索引化的成员/签名计数、min/max locator 维护；不能每次把全部 clone 拉回 Python。

canonical anchor 是 domain + 规范化 key 的 versioned digest，**不是 physical row ID**。
物理排序 locator 仅复现当前 earliest-origin 顺序；删除最早成员、winner 切换或插入旧 key
须重新比较顺序与 signature，不能因为 anchor 文本相同就复用 root。
同 session 多 active、sidecar 冲突、未知 lifecycle 仍按现有 audit 拒绝，不放宽 donor 判据。

group 索引复用 `_project_canonical_source` 的过滤、完整组和 occurrence 语义；分页 continuation
把 occurrence 计数落在索引，不积累整段历史的 Python dict。跨页 pending user 只允许有界暂存，
缺 assistant 不 mint 完整组。逻辑前缀 hash 链按顺序计算：

`P0 = SHA256(domain + rule_version)`；`Pi = SHA256(Pi-1 + canonical_record_digest_i)`。

使用规范化、长度无歧义的编码；body、全部被审计 sidecar、可见性/来源规则、排序与域都在证明内。
不是把 v2 的“全数组 JSON hash”改名继续使用；v3 有独立算法版本，不混淆两种 digest。
group root 同样绑定有序 group ID/fingerprint 与它覆盖的 canonical prefix token。
physical audit version 与逻辑 root 分开：clone 的物理 active/compacted 迁移要重验，
但不必让同一逻辑内容的 group root 改变。退休资格仍须由当前已审计的 lifecycle 单独确认，
不能用“逻辑 root 相同”绕过 archive/rewind 区别。`indexed_change_seq` 是水位而非永远相等的锁；
新版水位覆盖旧 token 后，可在目标 anchor 的 prefix 未变且无遗漏时继续验证旧 token。

变化从旧／新归属中最早受影响的完整组边界重新验证；必要时包含前一未闭合组。
前缀依赖后的 roots 全部失效，直到重算到新的稳定边界；不能只删被编辑 leaf。
clone 原文和 sidecar 完全一致且逻辑顺序不变时只刷新 physical audit，逻辑 group/摘要可保留。
反例（旧 clone 冲突、api_content 变化、迟到 user、rewind/redo）不能被“压缩优化”吞掉。

本 lane 的首个 source domain 仍为现有 full-prefix session；不顺手扩大成跨嘴或所有祖先内容。
宿主 topology token 必须区别 compression continuation 与 branch/delegate；改变归属时旧域失效。
未来接回 0.21.3/H13 lane 需独立 rule version 和已接受的 complete-group/physical-obligation 测试，
本规格不把旧 source/display classifier 升格为 H13 proof。

## 3. 分页、完成与资源合同

### 3.1 四个窄操作

| 操作（协议名，尚未成为生产 API） | 输入/输出与 owner |
|---|---|
| `prepare_history_step` | host 接受 domain/epoch/lease + 有界额度；短事务更新 canonical 派生索引与水位，返回 progress，不返回全历史正文 |
| `read_history_page` | read-only：opaque cursor、固定 target、行/字节额度；返回有界 rows、page token、next cursor 或明确拒绝 |
| `seal_history_prefix` | host 确认固定 target 以内全部物理义务、变化和排序已核验，返回 prefix token；不 mint delivery/retirement |
| `validate_history_prefix` | read-only：验证 token 对当前一次 source snapshot 的适用性；`valid / changed / pending / incompatible`，不隐式启动模型 |

token schema=`hermes.canonical_history_prefix.v1`，闭字段：`schema, realm_id, incarnation, activation_epoch, domain_id, topology_revision,
canonical_rule_version, indexed_change_seq, end_anchor, canonical_count, prefix_hash`。
cursor 另含 keyset locator、bootstrap target、pending-boundary locator；不允许客户端把 count 或 row ID
当作证明。schema/type、边界、realm、rule version 不匹配均拒绝。
marker/ID 使用现有闭格式与长度约束；计数/版本为非负整数且拒绝bool，digest为SHA-256；
空前缀只能 count=0、空anchor、对应P0，不能冒充可退休组。
journal 有明确 retained-floor/consumed-through，正常已证明前缀不重放全部日志；
按 domain/seq 的索引查待处理变化，按 anchor 查 prefix root。合法清理水位以下的旧日志
不算缺段，超出已验证水位的缺失才要求重验；其他domain写入不能让本domain全局重启。

### 3.2 一致性：固定目标，不冻结整库

1. bootstrap 捕获有限 physical upper bound 和起始 change sequence；使用 `(session_id,id)`
   keyset 分页，不用 OFFSET、完整 lineage list 或全表 DISTINCT 临时排序。
2. 每页在短事务快照中先查询固定字段与全部存储列字节预算，再取 payload、decode/audit。
   index 内容、该页 progress/依赖映射在所属库的同一事务内提交，不能先推进水位。
3. 分页期间的 UPDATE/DELETE/old-key INSERT 由 journal 标脏已经读过的范围；先重验受影响范围，
   才能 seal。不能把“每页分别一致”误称整段一致。
4. 后续普通 append 不移动本次 bootstrap target，不从第一页重来。新行先进入待分类增量；
   它是否影响旧 bucket/组只能审计后决定。未分类增量不允许直接越过 seal/validation。
5. seal 的短事务捕获一个有限 `change_seq`，将这个截面以前的变化处理完，再比较 target prefix。
   处理超预算就持久化进度、让出，不无限持锁。截面以后的变化使后续 validation 返回 pending，
   但不抹掉已完成 bootstrap。正常持续追加必须在工人吞吐足够时追平并首次 ready；不能要求用户停聊。
6. plugin group 索引记录其输入的 host token 和计算出的 rolling prefix。host 页间改动后，
   未通过最终 seal 的 group index 只算 staging；不用于 compile。两个库不靠 ATTACH 假造原子提交。

新准备任务、后续 source miss、宿主写入通知是触发点；一个活动 worker 以有限 quantum 继续推进，
同 domain 请求合并。进度存在数据库，manager reload 可恢复；运行中的旧 manager generation
失去发布/继续推进权。跨进程采用宿主已有 lease/ownership 模式，失去 lease 不接受迟到结果。
不新增常驻轮询 daemon，不在每个 request 起一个线程，不把 full scan 移到 post hook。
manager unload 只撤销该 manager 的 worker 权，不等同于宿主历史 epoch 丢失；同一可信 host
activation 内可以续已提交水位。宿主 preparation ownership 真正丢失/重启才按2.1重验，
这是后台重新验证成本，不是每次 manager reload 都从零，也不宣称跨宿主重启立即 ready。

### 3.3 初始限额（第三块必须实测，调参不改变协议）

| 资源 | 初始上限与耗尽行为 |
|---|---|
| 单物理页 | 256 rows、4 MiB 全存储列字节；先 SQL probe，再 decode，保持原有预算内大消息正向能力 |
| 单完整组 | 2,048 physical visible constituents、4 MiB 序列化输入；超限整组拒绝，不能截断后推进 retirement |
| 前台总 source workset | 2,048 rows、4 MiB（包括桥接输入和边界 lookaround）；不是每页重新发一份无限额度 |
| bridge | 保留 72h / 24,000 source tokens / 2,048 output tokens；组数受上述总 workset 限制，不因索引 ready 扩大窗口 |
| checkpoint + proof JSON | ≤1 MiB UTF-8，读写同编码计量；状态查询仍不 decode 大字段 |
| 准备并发 | 每 profile 一个活动 preparation owner；进程总最多一个执行中的准备 quantum；待唤醒 domain 最多32个，满时返回可重试状态，不复制 payload |
| quantum | ≤8 pages，时间目标100ms；页间让出；SQL progress handler/超时用于中止超预算语句，不是仅在耗时后打日志 |
| memory/cache | 仅当前页/当前组/当前请求 workset；无全历史 Python cache；SQLite page cache/临时空间按 worker 限定，测试计入总 RSS |

还须增加**进程总量**准入，而非仅靠现有128个 turn 的计数上限：在途 source/compile workset
合计最多32 MiB，冷缓存最多8 MiB，preparation 暂存最多8 MiB（均按序列化字节计量）。
已有 attempt count/600s lease 上限保留。活跃 attempt 的预算直到 settlement/error/expiry 才释放，
不能通过清 cache 偷删正在履行的交付义务；冷 cache 按字节逐出，可重新验证再读。
容量暂不可用时本轮明确 native/资源忙，释放后正常回合必须恢复；测试包括多profile并发，
不能把这些数字冒充严格 RSS 上限。Python放大率、SQL缓存和模型请求对象仍需隔离基准测总峰值。

journal 可按已验证水位清理，不能删尚未消费的证明缺口；派生索引 disk=O(历史)，不承诺常数磁盘。
磁盘不足明确停止索引推进并保留原文/旧 checkpoint，不进行自动历史修剪。
只读大值仍受 Block 1 SQL length 限制；“已知总字节小”不能绕过单字段和 pending-group 限额。
前台 query 必须 EXPLAIN 证明走 keyset/anchor 索引；测试同时记 SQL work、临时空间、wall time、RSS，
不能只报 Python 返回256行。大量 clone 的工作应在有界准备页中摊销，不在每次 read/settlement 重扫。

## 4. 发布保证：唯一选择为条件性存储、每次使用前验证

**不承诺“过期 candidate 永不写入插件库”。承诺“没有当次源验证的 candidate 不得被复用”。**
这是 snapshot-valid，不是一直锁住历史直到网络请求完成的 linearizable freshness。

1. source-ready 后读取 bounded checkpoint；先校验格式/存储 hash，再用 host token 验证源，
   同一个 source snapshot 中读取本轮有界 suffix/bridge。pending/changed 不得当 ready。
2. plan 冻结 reference time、完整组边界、source token、manager generation、预算及摘要 policy。
   provider 运行期间无 canonical 或 metadata 锁。已有 transport/final-body/finish 证明不改。
3. 只有真实 post-settlement delivery 才能进入 checkpoint settlement。先做有界 source 验证；
   已发现 changed 则记真实 delivery + checkpoint conflict；不重新发 provider。
4. metadata 短事务同时完成 expected revision CAS 与 delivery receipt。CAS 成功只说明
   **stored_unvalidated**：即使第3步 valid，紧接着源已变，候选仍可能落盘。
5. 任何 consumer（下一轮、manager reload、缓存复用、继续摘要、退休判断）都回到第1步。
   源在第3步与CAS之间变更，下一次 validation 必须拒绝；状态接口不能把 stored 等同 ready。
6. validation 返回 valid 的精确时点是其 source snapshot。随后发生的新变更不会把已经交付的
   请求改写成“未交付”，也不保证已在途请求撤回；下次消费必须重新检查。

三本账不能合并：`indexed`=验证工作完成；`delivered`=final provider body 已真实交付；
`checkpoint stored`=plugin CAS 成功。任何一项都不能自动推出另外两项。
并发两个 candidate 只有一个 CAS 成功；失败方保留 delivery evidence，不能重发模型争抢 revision。
跨库 crash 可以留下 staging/index或条件 checkpoint；重开验证处理，不声称 WAL 跨库 crash atomic。

## 5. checkpoint v3 规格

保留 v2 表和内容，v3 使用独立 `continuity_checkpoints_v3`；receipt 沿用现有 owner 和存储，
新增 v3 状态要与旧 decoder 做兼容测试。不是新 transcript 或第二个 delivery ledger。

```text
schema = thread_continuity_checkpoint.v3
revision, predecessor_revision, revision_id, predecessor_revision_id
lineage_status = initial | continued | rebuilt
source_proof = {host_token, grouping_rule_version, group_count, group_root}
retirement_cursor:
  schema = thread_continuity_retirement_cursor.v2
  relation = retired_from_foreground
  through_anchor, canonical_count, group_count, prefix_hash, group_root
recent_bridge:
  schema = thread_continuity_recent_bridge.v1
  原有 status/relation/source_group_ids/source_group_fingerprints/source_slice_fingerprint
  reference_at/recent_horizon_hours/source_token_limit/output_token_limit/body/body_sha256
  （只允许本次有界 recent slice，不携带全前缀数组）
storage_state = stored_unvalidated
```

`revision_id` 对不含自身的完整规范化 v3 payload（含 predecessor）做带 schema/domain 分隔的 SHA-256；
整数拒绝 bool/负数，hash/anchor 闭格式，缺字段/未知 schema/版本不匹配拒绝。
空 bridge 保留 v1 的 empty/body/empty hash 合同；body 仍仅是生成摘要，不是原话副本。
v2 中仍在使用的 nested-v1 不删除；退休游标改变语义才另定 v2，不能悄悄改 nested-v1。

normalizer 必须证明：retirement 是 source 的完整连续前缀；bridge 是该前缀的连续有界 slice；
ID/指纹/正文 hash/policy 和 source/group proof 一致。`continued` 必须维持 predecessor 和退休单调性；
发生前缀变更走 `rebuilt`，不能只改 root 然后复用旧摘要。group_count 是验证结果，不是外部传入即可信。
旧全数组校验替换成经 host 验证的 compact prefix + 有界 slice 校验，不能在 adapter 内偷偷再展开全历史。

v3 delivery receipt 不列全历史 source IDs：仅 bounded bridge IDs，并存 proof hash、prefix/group counts、
实际交付 hash 与 checkpoint outcome。新状态区分 `delivered_checkpoint_stored_unvalidated`、
`delivered_checkpoint_conflict`、`delivered_checkpoint_failed`；既有 v2 receipt 原样保留。
receipt identity 加版本域，避免旧版幂等查询把新 outcome 当成旧 applied。

### 5.1 Compiler 对接边界

不能只改磁盘格式后仍把全历史数组递给 compiler。第三块的调用方按以下归属适配：

| 当前 owner | v3 输入/输出变化 | 必须保留 |
|---|---|---|
| `read_bundle / read_source` | verified compact prefix + bounded recent/current完整组；不是伪装成全量的截断list | source失败不读大checkpoint；完整组/冲突审计 |
| `normalize_thread_continuity_checkpoint` 及 builder | 新增显式v3分派、compact-proof校验；v2独立保留 | lineage、正文hash、政策、退休单调性与严格schema |
| `_build_thread_continuity_fold_plan / normalize_thread_continuity_fold_plan` | old retired prefix用已验证descriptor；仅本次delta/bridge有ID数组 | currentness、source ownership、单次冻结generation、原摘要选择与chunk行为 |
| `plan_next_summary_attempt / build_thread_continuity_checkpoint_from_attempts` | 只处理有界目标slice，不为满足旧数组形状重展开历史 | 原预算/接受回执/summary provider失败语义 |
| `runtime.py` request/execution/post | 缓存key和settlement携带compact token，v3 CAS明确分支 | final-body/finish/overlay proof，post之后才发布，失败不重发 |

这些是必要的数据表示适配，不是宣称 donor compiler 可以一行不动接入 v3，也不是重写其摘要策略。
实施前按 PROVENANCE 的母本符号逐项比对，旧、新小会话同输入做行为等价对照；
“只验证索引就直接退休全部历史”不合法，退休仍须满足既有 foreground ownership/compacted 边界。

v2→v3：预算内可读 v2 经实际 source 重新验证后才可做有界转换；不得仅信旧 source ID 数组。
超大旧 v2 不加载、不删除；完成新索引后只按最近窗口建立 v3，不全历史重新摘要。
跨格式首次 v3 revision 自己起链并标 rebuilt，不能伪造 continued；旧 v2 仍供回滚读取。
旧源码在回滚期间新增消息必须保留；再次启动 v3 重验 epoch/所有变化，不把“v3 文件仍在”当证明。

## 6. 第三块必跑的时序与正向验收

以下是待执行合同，不是本轮 Green；provider 是否替身、真实 host/数据库/进程入口分别记账。

| 场景 | 必须观察的结果 |
|---|---|
| 固定 recent workset，历史10×/100×，以及固定逻辑历史、clone/lineage物理规模扩大 | 准备总工作可以增长；foreground/settlement不再重扫总历史，RSS/SQL工作有界；实际 bridge 非空、真实 SQLite settlement、下一轮复用 |
| >2,048普通历史；持续追加期间bootstrap | 不要求停聊；有限target取得首次ready；两轮投影/receipt/复用，不以长期native算成功 |
| 少量超大字段、超大完整组、巨大旧checkpoint | SQL/预算在decode前拒绝；不截断、不过退休边界；状态能解释原因；其他预算内会话照常工作 |
| 页A读完→编辑/删除A→读B→seal；另测旧key高row-ID插入 | 不产生混合证明；从真实依赖边界修复，不把新ID误判纯追加 |
| 正常尾追加与跨页pending user完成 | 保持已闭合前缀；未闭合组不能早退；组闭合后能正常推进 |
| 压缩clone、sidecar回填、rewind/redo、branch/import、recovery/restore | 对照普查表逐个穿真实writer；逻辑不变复用，真实变化失效；分支不借父权 |
| source validation r7→canonical edit r8→plugin CAS成功 | 允许stored_unvalidated；下一轮/摘要复用/退休判断必须拒绝旧证明；delivery仍真实，provider只调用一次 |
| 两candidate相同expected revision；CAS失败/磁盘失败 | 一次成功CAS；另一条交付不被抹掉，不为发布失败重发provider |
| page/index写到一半crash；journal已写但index未写；group已staging但seal未过 | 重启无越过水位/重复组，恢复后能ready；两个库故障顺序分别覆盖 |
| manager unload/reload；worker lease转移后旧worker返回 | 旧generation不发布，完成的持久进度可续；不是永远重头跑 |
| 正常旧writer、REPLACE/cascade、缺trigger、离线恢复、rollback再回来 | 能捕获的增量验证；不可证明的epoch失效；保留新增canonical数据；非空v2/v3与receipt逐字段readback |
| 派生journal故障/捕获停用；多profile并发workset | canonical写入成功或报告真实原始错误，不静默丢消息；证明失效可恢复；总准入有效且预算释放后正常回合恢复 |
| 窗口过期、summary缓存与prefix变更 | cache key含完整proof/policy/时间slice；过期摘要不借相同session ID复活；索引准备零模型调用 |

完整入口基准继续覆盖 read/audit/compile/settlement，保留 Block1 正向和字节防线；
执行前查 query plan、记录原始进程退出事实，用外部子进程 timeout 防卡死，不在生产机顶内存。
实现自审和外审通过后才按既有条件 PR/部署/观察；48–72h 除进程健康还要看到实际投影、
结算、复用及索引进度。主机退出与连续性降级分别报告，不把这份协议称为已消除所有卡死。

## 7. 本轮交付边界

本文件冻结一条候选实现路线，而非多个互斥方案：DB级变化捕获、有界派生索引、条件性发布。
源码依据已读；具体 host API、DDL、worker、v3 normalizer 与上述测试均留给第三块实现。
源码/恢复八轴：本轮 source=文档，artifact=规格，runtime依赖/路径/unit/secret/capability无变更；
rollback只登记已接受源码基点，不修改 Assembly 的安装选择。没有服务器动作。
