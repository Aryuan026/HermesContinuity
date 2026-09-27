# Block 1 — 完整入口过渡保护与资源基准

## 合同与代码归属

- 基点：`34780f001cc16b81bcd003127e31ed41693158bc` / 0.4.1。
- 本块：全前缀 Continuity 入口保护、资源基准、正常小会话正向回归。
- 非本块：checkpoint v3、宿主 writer 协议、后台索引、Global Hot 算法、版本升级或部署。
- 源超限仍可明确降级 native。第三块必须实现 >2,048 行 bridge、settlement、下一轮复用；本块不能代替该验收。

| Owner / caller | 本次变化 |
|---|---|
| `read_bundle → read_source`（包括 settlement 的 source reread） | 同一 host read snapshot 内先探测物理行数、全部列 UTF-8 存储字节，再 fetch/decode |
| `read_bundle → read_continuity` | source 不 ready/complete 时零 checkpoint 读取；SQL CASE 和 SQLite value limit 在 payload 返回 Python 前保护 |
| `_checkpoint_outcome → _write_checkpoint` | 旧状态同样受读取预算；候选按同一编码预算校验后才写入，失败保留实际交付回执 |
| 带 session 的 `status_summary` | 只读 revision/字节元数据，不 decode checkpoint；不再把 presence 叫作 ready |

默认预算：2,048 物理行、4 MiB 全列源字节、1 MiB checkpoint+prefix IDs JSON。
SQLite LENGTH 限制额外留 4 KiB record header/固定字段余量；SUM/CASE/写入检查仍执行精确 payload 预算。
这是序列化字节上限，不是 Python RSS 上限。预算可配置，不能通过无限调大它宣称解决超长历史。

复用锁定宿主的 `_read_ctx`、`_dedupe_compacted_message_rows`、`_decode_message_rows`；
不另建 canonical connection/writer，不改变 winner、canonical audit 或 checkpoint-v2 算法。
后续追宿主版本必须重查这三处及 messages schema，不能只看方法名称存在。
短 SAVEPOINT 只保证本次 probe/fetch 一致，不是第二块尚待冻结的 source-validity/CAS 跨库发布协议。

本块未改独立 canonical-window service 的读取协议；其既有行数上限不等于新的字节上限。
metadata 连接明确 closing；schema、owner、原 checkpoint 内容不迁移、不删除。
status 将 checkpoint 标为 `stored_unvalidated` / `byte_limit_exceeded` / `absent`，
不会为了查询状态取回 bridge、prefix/fingerprint 数组。最近 receipt 只投影小型状态字段。

## 正反向验证

- 全部消息列均进入预算，包括 content/api_content/tool_calls/reasoning/display metadata。
- overflow 的完整 read_bundle 不打开 checkpoint store，decoder 不进入。
- SQL 返回大 checkpoint 的 NULL 哨兵，而不是先取回再测长度；status 不调用 decoder。
- Unicode exact / -1 / +1 字节边界；新状态不能写成 applied 后立即不可读。
- 并发 writer 在 COUNT 后改大正文：当前快照保持旧内容，下一次读明确 overflow。
- borrowed connection 的 SQLite limit 和事务状态恢复。
- 小会话与 2,000 clone 同逻辑历史：两轮投影、两条真实 SQLite receipt、checkpoint revision 1、
  仅一次 synthetic summary；第二轮复用上一轮 checkpoint。输入 request 未被修改。
- 超限用例：无 summary、无 projection、无 delivery receipt，最终 native request 保持原样。

本地 Python 3.12.13、compatible host `fcbd1076a93841fa88855acce810e342a5b78101`
顺序应用仓内原有 12 枚补丁：
220 项 unittest，219 pass / 1 existing paired-host conditional skip；
host overlay/middleware：42 passed、15 subtests passed。
早期最小模块 harness 是 220 项含 16 skips，后由上述完整 materialized host 重跑取代；
一次缺少 PyYAML 的环境失败已在独立测试 venv 补齐，未当成产品失败或 Green。
独立只读 diff 复审发现写入预算漏洞，修正后未报告残余 P0/P1/P2；
其测试证据不替代本节主控完整宿主结果。

## 隔离基准（2026-09-27）

实际 SessionDB、adapter、donor compiler、request/execution/post、metadata settlement 与带 session status。
provider/transport 使用既有测试替身；不是 AIAgent.run_conversation、真实 QQ 或网络 provider。
每个 case 的建库和测量分别在独立进程；owner 数据、profile 和服务器不参与。
parent 30 秒外部 timeout；Linux 测量子进程另有 1 GiB RLIMIT_AS。
本机 macOS 本轮所有用例正常结束，无 timeout/内存终止；没有为了比较而把旧代码跑至主机失响应。

两个 lane 的一次本地 Python 3.12 测量，时间受调度影响，不作为速度 SLA或部署内存阈值。
peak 是进程 ru_maxrss，growth 是测量开始后的高水位增量，不是累计 allocation。
读取包含 audit，settlement 包含再次 source read；阶段嵌套，不能把时间或高水位相加。

| Case | Control peak / growth KiB | Candidate peak / growth KiB | Control / candidate seconds |
|---|---:|---:|---:|
| small | 59968 / 336 | 60208 / 320 | 0.0092 / 0.0149 |
| large_message | 208048 / 148160 | 59696 / 144 | 0.2784 / 0.0011 |
| near_byte_budget | 76384 / 16864 | 73280 / 13296 | 0.3567 / 0.4481 |
| large_checkpoint | 93168 / 33120 | 62368 / 2544 | 0.0340 / 0.0167 |
| overflow_checkpoint | 93328 / 34656 | 59008 / 96 | 0.0336 / 0.0028 |
| clones_2000 | 63184 / 3536 | 62416 / 3664 | 0.1170 / 0.0991 |
| clones_20000 | 61648 / 1808 | 59584 / 128 | 0.0206 / 0.0014 |

- small：4 行 / 2 个逻辑组；clones_2000 / clones_20000 分别增加 2,000 / 20,000 个物理 clone，逻辑历史保持相同。
- large_message：4 行，其中 api_content 16 MiB；证明少量行也必须在 decode 前拒绝。
- large_checkpoint：小 source + 16 MiB 旧 checkpoint_json 字段。
- overflow_checkpoint：20,004 行 source + 同样的大旧字段；旧版虽报 source overflow，仍读取大状态。
- 大旧字段是故意构造的不可解码持久化字段，不冒充真实 owner checkpoint；合法 checkpoint 正向与字节边界另有测试。
- near_byte_budget：4 行合计约 3 MB 正文，位于 4 MiB 入口预算内；
  两版都保留现有 retirement-only 语义（无 bridge、无 summary、一次 settlement），不是全历史摘要。
- 对照是 0.4.1，没有拿未做 2,048 行止血的更旧版本夸大收益。

### 分阶段实测

| Case | Lane | Read ms | Audit ms | Checkpoint read ms | Compile ms | Settlement ms | Status ms |
|---|---|---:|---:|---:|---:|---:|---:|
| small | control-0.4.1 | 0.989 | 0.333 | 0.384 | 2.104 | 1.409 | 0.148 |
| small | candidate | 1.331 | 0.397 | 0.533 | 3.098 | 2.203 | 0.151 |
| large_message | control-0.4.1 | 263.671 | 228.460 | 2.126 | 3.100 | 74.642 | 0.282 |
| large_message | candidate | 0.162 | not entered | 0.002 | not entered | not entered | 0.120 |
| near_byte_budget | control-0.4.1 | 186.939 | 93.905 | 7.495 | 152.025 | 66.646 | 0.186 |
| near_byte_budget | candidate | 240.267 | 125.357 | 9.064 | 187.014 | 84.312 | 0.208 |
| large_checkpoint | control-0.4.1 | 1.294 | 0.384 | 21.797 | 0.061 | not entered | 7.809 |
| large_checkpoint | candidate | 2.284 | 0.551 | 10.482 | 0.090 | not entered | 0.924 |
| overflow_checkpoint | control-0.4.1 | 18.430 | not entered | 9.977 | not entered | not entered | 3.660 |
| overflow_checkpoint | candidate | 0.579 | not entered | 0.004 | not entered | not entered | 0.354 |
| clones_2000 | control-0.4.1 | 104.629 | 64.065 | 0.716 | 2.275 | 41.043 | 0.228 |
| clones_2000 | candidate | 89.069 | 55.591 | 0.734 | 2.233 | 30.492 | 0.144 |
| clones_20000 | control-0.4.1 | 18.630 | not entered | 0.533 | not entered | not entered | 0.126 |
| clones_20000 | candidate | 0.241 | not entered | 0.003 | not entered | not entered | 0.192 |

各阶段 process high-water 原始值由脚本 JSONL 输出；CI 保存为 resource-guard artifact。
本表保留可审阅的时间与总内存摘要，不提交大型 benchmark 日志。

### 重跑

```sh
PYTHONPATH=/path/to/compatible-host HERMES_SOURCE_ROOT=/path/to/compatible-host \
  python -B -m unittest discover -s tests -v
PYTHONPATH=/path/to/compatible-host python -B tests/benchmark_resource_guard.py
CONTINUITY_BENCH_CONTROL=/path/to/34780f0-source \
  PYTHONPATH=/path/to/compatible-host python -B tests/benchmark_resource_guard.py
```

CI 已接入 candidate benchmark，完整宿主重放继续沿原来的十二补丁链；
本文件本地结果不提前声称新 exact-head Actions 已成功。

## 交付与回滚

Assembly 八轴收尾：source=yes（本 PR 候选）；artifact=yes（源码发布，非安装包）；
runtime dependency=no（仅临时测试 venv）；managed path=no；persistent unit=no；secret=no；
capability=yes（入口字节保护，未部署）；rollback=yes（验收后首选基点更新）。
本轮只在主仓记录候选，不修改另一仓的现网 selected pins。
Assembly relock 待 exact-head 外审接受及已有部署条件满足时执行；不把本地测试记成现网升级。

本块验收通过的 exact SHA 才能替换 34780f0 成为后续 v3 优先回滚点。
当前提交不改变服务器、配置、plugin enable 状态；没有 v3 格式或源证明迁移。
主机退出原因和连续性阻塞分别跟踪；本基准不证明消除了全部卡死。
第二块协议待冻结，第三块功能待实现；部署和观察按既有条件另行执行。
