# 新窗口交接：P1 首批完成后的质量改进

> 历史材料（2026-10-29 整理）：本文保留记录当时的状态、约束和后续建议，不作为当前任务或启动授权。相关证据与现状见 [P1 实验归档](p1-experiments-2026-10.md)；不要据此重跑旧批次或自动启动模型实验。

准备日期：2026-10-19，Asia/Shanghai。工作区 `D:\deep_research_public_preview`，PowerShell，分支 `chore/public-edits`。当前聊天 `codex://threads/01a14fe5-b4cd-7e43-8800-a2a5fb7c6586`。用户将自行打开新窗口，本次只准备交接，没有新增模型调用、提交或推送。

## 先核对现场

**当前 HEAD 为 `5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`**，标题 `feat: default Atlas demo to accepted DeepSeek recording`。本地分支目前比远端跟踪分支领先 6 个提交；此为本地 Git 状态，未 fetch 核对远端最新情况。

P0 已完成固定场景验收；DeepSeek 成功实录已设为默认。P1 首批三次原生重复和两组离线单变量配对、P2 同批可靠性统计均已完成。**本批实验完成不等于产品内容质量已解决：原生业务完成 2/3，独立内容验收 0/3。** 不要再按旧交接重做 P0、默认实录接入或启动本批三次基线。

```powershell
Set-Location D:\deep_research_public_preview
git status --short --branch
git log -3 --format="%h %s"
```

本轮 P1 结果尚未提交。当前已修改的跟踪文件为 `docs/maintenance.md`、`frontend/docs/verification.md`；新增未跟踪文件为：

- 本交接文档；
- `frontend/docs/p1-deepseek-plan-2026-10-19.md`；
- `frontend/docs/p1-deepseek-results-2026-10-19.md`；
- `frontend/docs/provider-2026-10-19-deepseek-p1-evidence.json`；
- `frontend/docs/provider-2026-10-19-deepseek-p1-high01-draft.md`；
- `frontend/docs/provider-2026-10-19-deepseek-p1-high02-report.md`；
- `frontend/docs/provider-2026-10-19-deepseek-p1-high03-report.md`。

生产源码、`.env`、前端默认实录与历史原件没有改动。`.local/` 被 Git 忽略，其中的新实验工具、数据库及详细证据仅保存在本机，不会随 checkout 携带。保留上述未提交文件及后续用户改动，不用 reset、清理或旧脚本覆盖它们。

## 阅读顺序

1. [AGENTS.md](../../AGENTS.md)与本文件。
2. [P1 完整结果](p1-deepseek-results-2026-10-19.md)、[P1 冻结方案](p1-deepseek-plan-2026-10-19.md)、[验收记录](verification.md)首节。
3. [机器证据](provider-2026-10-19-deepseek-p1-evidence.json)，包括原生身份、独立逐句判断、来源锚点、请求用量及 `pairedIssueAudit`。
4. [维护说明](../../docs/maintenance.md)、[架构约定](../../docs/architecture-decisions.md)。
5. 需要本机复现工具时读取 [本地 README](../../.local/p1-deepseek-20261019/README.md) 和 [遥测口径](../../.local/p1-deepseek-20261019/telemetry_notes.md)。旧 [P1 开始前交接](handoff-p1-after-deepseek-replay-2026-10-19.md)只用于追溯已完成的准备要求。

## 已完成实验与关键结论

三次原生流程均沿用 `deepseek-v4.1-flash`、原网关／凭据。写作 enabled/high／32000；来源条件选择和候选稿核验 enabled/high／128000。当前源码、原始两轮输入、模型参数、传输和重试固定，失败也计入三次，没有补跑到三次成功。

| 目录后缀 | 业务结果                                     | 内容与失败分类                                                                             | 首次提交至业务终态 |
| -------- | -------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------ |
| `high01` | `partial/writing`，无最终报告；草稿 556 汉字 | 条件选择 `stop` 后 schema `too_long`，未进入候选稿语义核验；独立审查草稿也不通过           | 491.821 秒         |
| `high02` | `succeeded/complete`，512 汉字               | 机械与模型核验均通过，但遗漏扩展内部状态／并发安全审查及开关生效时机的证据缺口，属于误放行 | 361.141 秒         |
| `high03` | `succeeded/complete`，590 汉字               | 机械与模型核验均通过，但保护条件、数值基线、操作缺口及回退影响范围不完整，属于误放行       | 553.175 秒         |

目录前缀均为 `.local/p1-deepseek-20261019-`。high01 的 `too_long` 只保留错误类型，没有字段位置；不能断言一定是某个列表超长，也不能从 128000 上限推断这是 token 截断。high02 的条件选择将“声明支持”放进实质前提，却遗漏实际安全适配；high03 保留了内部状态审查，但仍误放行其他实质缺陷。三次各生成一稿，没有语义修订样本。

两组离线对照固定 high02／high03 的首个实际受核验候选稿、原始要求、实际来源、条件与生产提示。准备时验证重建消息哈希，实际请求每对只有 `reasoning_effort` 不同，同为 enabled／128000。条件固定为原生 high 的选择，因此不比较来源条件选择能力，也不替代原生验收。

| 案例      | 顺序／等级 | 结果                                                   | arm 耗时   | 报告总 token |
| --------- | ---------- | ------------------------------------------------------ | ---------- | ------------ |
| high02 稿 | high       | HTTP 200 后 `APIError`，没有可用语义决定／用量         | 601.604 秒 | 未知         |
| high02 稿 | low        | 抓住实质安全审查遗漏并拒绝，另有额外细节要求           | 90.699 秒  | 20,549       |
| high03 稿 | low        | 拒绝，但理由未覆盖预先确认的主要缺陷，含误报／过严要求 | 112.741 秒 | 26,030       |
| high03 稿 | high       | 误放行，`passed=true`                                  | 340.498 秒 | 52,605       |

不要只按拒绝次数宣布 low 更可靠。low 第二组误将已经限定并发修改的借用引用描述当成错误，未抓住独立确认的主要缺陷；具体理由审查在 `paired/issue-audit.json` 和公开机器证据中。两份稿都不合格，**没有合格正例，不能估计错误拒绝率**。high 第一组约 601 秒失败也不足以证明固定 600 秒网关上限，没有 `length` 或底层正文传输异常诊断，根因尚未确认。

P2：原生共 78 次模型 HTTP 尝试，69 × 200、2 × 429、7 × `ConnectError`；搜索 10 × 200。四个离线 arm 各一次请求，均 HTTP 200，其中一例 SDK 错误。原生已报告 token 602,931，离线已报告 99,184；其他尝试用量未知，费用未估算。没有新增连接探测，`diagnose_direct.py` 仅准备、未执行。

## 后续继续顺序（建议，尚未执行）

1. **先补齐安全诊断，验证后冻结新 harness。** 针对 schema 校验，记录有界字段路径、错误类型等白名单信息；针对 HTTP 200 后的 SDK／流内错误，记录安全类型／代码、发生时点和完成状态。不要直接保存异常正文、私有端点、凭据或推理。用无真实模型的案例检查超长字段定位、错误事件与正常结束，再开始新实验。旧 `too_long` 和 `APIError` 证据仍保留未知边界，不靠新诊断伪造旧事实。
2. **选一个质量变量。** 优先来源实质前提选择，或候选稿核验提示二选一；按当前结果设计通用改进，不把 Python 场景答案清单注入生产流程。不要同时改写作提示、核验提示、思考等级、模型和 token 上限。先定位为什么形式性声明会被当成实质前提、为什么已有条件仍被误判，而非继续盲目提高输出上限。
3. **先建立新的有界评价集与冻结清单。** 加入独立通过的正例、已知实质缺陷反例和每案例重复，先保存独立内容判断，再运行核验，分别评价决定和理由。旧 P0 已通过报告及其当时实际来源可以作为明确标注的离线正例；须复制到新的实验输入，不改旧原件，也不能计作新的原生通过。具体新批次数尚未确定，应在新清单中预先写明并计入失败，禁止跑到满意才停止。
4. 改动后运行与变更相关的必要测试，再以新身份做有界原生复验；离线核验改善不替代端到端内容验收。维持 400–650 汉字及原固定场景，核对全部关键前提、例外、引用支持和操作证据缺口。没有修订样本时继续标为不可评价。
5. 据正反例和重复性结果提出日常配置方案。当前 high 和 low 都不足以直接推广可靠默认，生产 `.env` 与归档不自动改变。P2 持续区分建连、HTTP、流内 SDK 错误、`length` 和语义错误；仅当连接确实阻断时做必要的有界诊断。

P3 的默认成功实录已经完成，保留原 P0 成功实录。当前三次材料是评价证据，不替换默认演示。新 ZIP、报告阅读体验、真实事件时序回放尚无新增范围，不自动扩张实施。

主要源码入口：`src/deep_research/report_review.py` 的 `ReportReviewFormatError`、`read_review_json`、`select_source_conditions`、`review_report`；相关 `source_evidence.py`、`research_agent_full.py`、`research_requirements.py`、`model_transport.py`。现有严格来源定位／条件覆盖只证明机械覆盖，不证明语义正确。共享 Qwen fallback 和 LangSmith 反馈契约继续按 AGENTS 执行。

## 必须沿用的调用、预算和保留约束

- 使用现有 `deepseek-v4.1-flash`、原网关、原凭据。模型同步、异步及共享结构化回退客户端均显式 `proxy=None`、`trust_env=False`，保持 TLS；搜索独立沿用原配置。导入图之前加载本地环境，不能打印密钥或私有网关。
- high 写作／32000、high 核验／128000 是隔离实验覆盖，**没有成为生产默认或原按次配置归档的一部分**。其他角色没有全局开启思考，工具调用 `reasoning_content` 回传兼容性未验证。
- 每个写作节点最多三次生成、四次条件选择／核验读取、一次语义修订；SDK 每次最多五次 HTTP 尝试，写作节点上界仍为 35 次，其他角色／搜索另计。原生观察约 1800 秒，专用后端保护期限 1950 秒；不要静默放宽。
- 所有新运行都建立新目录、端口、thread／research／turn／writing attempt；本批全部身份和四个离线 arm 已使用，不重启、不追加执行。原始两轮输入在各轮 `inputs.json`，也可与 `frontend/src/data/deepseek-p0-recording.json` 的 `research.turns[*].text` 核对，不能自行改写。
- 保留报告、草稿、数据库、配置、旧实录、保护清单及失败结果。不要重跑旧验证／汇总脚本回写历史，尤其不能运行旧 `prepare.py`／`run.mjs`／`paired_review.py run` 去复用本批。
- 准备 P1 时增加了 `stream_usage=True`，各 P1 条件一致；P0 没有相同遥测，不纳入这批三次分母。`headersSeconds` 只到响应头；SDK 收到 `[DONE]` 后可能关闭而不消费 EOF，此时用正常关闭耗时，不能把 `bodyEof=false` 单独判为断流。非流式底层压缩字节解析失败也不等于模型格式失败，应看 HTTPX 解码后的 usage。
- token 只取最后一个真实累计 usage 事件，不重复相加；无 usage 保留 `null`，不估算费用，不从 chunk／字节估算 token。遥测只存计数和时间，不存推理内容。

## 本地证据入口与已用身份

| 路径                                                                        | 内容                                                                        |
| --------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `.local/p1-deepseek-20261019/plan.json`                                     | 调用前冻结的三次原生计划、预算和源码哈希                                    |
| `.local/p1-deepseek-20261019-high01/`、`high02/`、`high03/`（后两项同前缀） | 各自的 `final.json`、实际来源／模型输入、报告事件、数据库、请求及浏览器证据 |
| 各轮 `independent/`、`independent-review.json`                              | 从事件导出的原始草稿、预先独立判断、逐句来源锚点                            |
| `.local/p1-deepseek-20261019/paired/`                                       | 冻结案例、顺序、四个已结束 arm、`issue-audit.json`                          |
| `.local/p1-deepseek-20261019/summary.json`                                  | 本轮派生汇总；不是新的模型结果                                              |
| `.local/p1-deepseek-20261019/preservation-baseline.json`                    | 6,987 个历史文件的原始保护清单                                              |
| `.local/p1-deepseek-20261019/export-verification.json`                      | 四个公开原件的 SHA-256 与保留／端口核对结果                                 |
| `.local/p1-deepseek-20261019/final-artifact-checks.json`                    | 最终计数、导出一致性、直连、链接与无占位符检查                              |

三条 thread 分别为 `3c1e9613-0def-4edf-910f-5c023861eb04`、`01e38574-3602-4cbc-98a2-1f3fbc27454d`、`ea1513e4-28da-45c1-a1d1-dc466f452822`。high01 没有已接受的最终报告身份，失败草稿 writing attempt 为 `6f64d067-c456-40a3-9c70-cdca3deb8355`；不要把空的最终 writing 字段当成未执行写作。

## 已验证状态及 Windows 注意事项

收尾确认 6,987 个历史保护文件、103 个冻结文件未变；七项遥测预检通过，两份已交付报告的机械检查全部通过，但独立内容不通过。公开报告／草稿与原件字节一致，公开证据过滤了本地密钥／私有端点值及推理字段。生产代码没有变化，本批没有重跑历史 222 项后端或前端全量套件。

本次准备交接又核对了四个导出文件哈希与原生计划的冻结文件，仍一致；专用端口 2101–2103、5261–5263 仍为空闲，四个离线 arm 均已有终态结果。没有本聊天遗留的运行或自动化需要续看。新窗口开始时重新确认现场，旧 `running` 快照不能证明进程尚在运行。

Windows 沙箱曾允许读取旧证据却拒绝新公开文档写入；获准的外部进程能写文档，却不能读取某个旧 pytest cache。最终拆分为沙箱内核对／安全过滤并暂存 `prepared-public/`，再经批准的 `export_evidence.py publish` 逐文件验哈希创建公开文件。没有修改 ACL 或删除旧缓存。导出已完成，**不要再次运行准备阶段覆盖暂存／证据**。

Prettier 写入同样需要获准的外部执行，已批准前缀为 `node.exe frontend/node_modules/prettier/bin/prettier.cjs`。只格式化说明文档，不格式化要求字节一致的原始报告／草稿。手工修改优先 `apply_patch`，如遇 Windows refresh 错误按 AGENTS 的可写核对和最小 PowerShell 回退处理。

## 可复制的新窗口开场

```text
在 D:\deep_research_public_preview 继续。先读取 frontend/docs/handoff-after-p1-baseline-2026-10-19.md，再核对 AGENTS.md、Git 状态、P1 结果与维护说明。

当前 HEAD 5cf597d，P1 文档和证据尚未提交，请保留。P0 固定场景验收及 DeepSeek 默认成功实录已完成；P1 三次有界原生重复和两组 high/low 离线配对也已完成，不要重跑旧身份。原生业务完成 2/3，独立内容通过 0/3；high 有误放行和 APIError，low 也有不可靠拒绝理由，不能直接改生产默认。

请按交接继续下一阶段：先补齐安全诊断并验证、冻结新的实验工具，再选择来源实质前提选择或候选稿核验中的一个变量做通用改进；加入独立正反例和有界重复，分别审查判断与理由，再做必要的原生复验。继续使用现有 DeepSeek、原网关与凭据，模型直连并校验 TLS，搜索沿用原配置。保留所有历史证据，不注入场景答案清单，不把离线改善当成原生通过，不无界重跑。
```
