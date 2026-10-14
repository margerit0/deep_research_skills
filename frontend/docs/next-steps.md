# 星图工作台后续任务与交接

更新日期：2026-10-14。1A、1B、计划 2 已实现；GLM / Kimi 实录与下载包已完成整理。最新验收与真实供应商复测见 [验收记录](verification.md) 首节。

## 2026-10-14 实录回放交接（当前入口）

接续聊天 `01a1331f-2648-7900-96dd-a55f40f6b0e0` 中断前的任务：保存真实调用数据、使用同 API key / base URL 试 `moonshotai/kimi-k3`，并按实际覆盖范围替换演示内容。接手时仍为 `chore/public-edits`、`2fc6299`，已有未提交的证据及前端改动已保留；本轮没有新增供应商调用，完成的是实录、导出和验收收尾。

本次交接提交标题为 `feat: replay recorded Atlas research runs`，父提交为 `2fc6299`；具体提交号以交接消息和 `git log` 为准。实录、公开证据、截图和文档一并入库，`.local/` 下的下载包、原始材料及检查点仍只保留在本机。本轮收尾聊天为 `01a1389f-107a-7640-8826-6ccf3e027687`。新窗口先检查实际 HEAD 和工作区，保留后续提交及未提交修改。

**现有数据仍不足以替换一次完整的成功流程。** GLM 增加等待与退避后确认简报失败；Kimi 取得 231 字简报、30 条研究事件、1 份笔记和 8 条检索来源，但报告为空。其两个研究任务一失败一完成，未成功加载 Skills；1950 秒专用后端保护期限到达后退出，最后仍是 `running/writing`，没有确认业务终态。Kimi 与 GLM 记录独立，不能拼接成完整交付。

进入“全流程演示”，通过“数据来源”选择 GLM 或 Kimi 实录。原完整模拟继续保留。实录使用独立内存会话，只读显示实际内容、节点、请求记录及失败 / 中断，退出或刷新恢复原工作区。数据延迟加载，回放不创建 run、不改写历史，也没有实现计划 3 的在线正文流式。

下载包位于 `.local/exports/atlas-real-calls-2026-10-13.zip`，包含四轮调用的安全材料、笔记 / 来源 / 事件、两条回放 JSON、原材料可用性清单与逐文件 SHA-256。临时浏览器材料的缺失、Kimi 浏览器与最终 API 快照的差异均明确保留。详细数据边界见 [真实记录回放](recorded-runs.md)。

后续仍按两条路径安排：供应商稳定后，使用隔离环境补齐真实报告、来源与正文引用核验；如使用 1B 写作恢复，必须验证当前回执 / 精确检查点，恢复会新增有明确身份的 run，不能算作此前“两次 run”的同一验收。计划 3 可按 [实施方案](report-streaming-plan.md) 独立推进，真实流式验收仍需真实报告。下一轮根据新的任务要求选择，本轮未开始计划 3。

继续保留生产后端 `.env`、原默认模型 / 网关、TLS 校验、`NO_PROXY=*`、共享 limiter、结构化 fallback 和 Qwen `/no_think`。Kimi 模型切换及 3 / 6 / 12 / 24 秒退避仅发生在 2026-10-13 的隔离进程中。

## 2026-10-13 首轮复测交接（历史）

本轮从 `chore/public-edits`、`2fc6299` 的干净工作区继续，保留计划 2 提交 `b5b53f4`。只执行真实复测、记录和下一步规划，未实现计划 3，未改变产品代码、视觉、交互与独立演示；这些交接修改尚未提交，接手时先核对 Git，不覆盖后续工作。

**供应商链路仍不稳定，完整真实交付未验收。** 沙箱内请求受到 `WinError 10013` 限制，沙箱外同配置最小请求和实际结构化澄清均返回 HTTP 200（网络耗时分别 1.57 / 54.98 秒）。随后真实 Chrome 首问超过 180 秒期限，原节点依次发生 2 次 HTTP 504、2 次 `RemoteProtocolError`，第 5 次 HTTP 尝试才成功，worker 在约 251.63 秒后记为原生 `success`。这次没有复现证书失败，不直接沿用历史 TLS 结论。

服务端只有 1 个 run；刷新不新增执行，原提交与回执 / 检查点配置一致。未发送第二次澄清回答，简报、研究 / Skills、报告、来源和引用核验均未执行。最后 API 回读和磁盘检查点仍为 `running/clarify`，迟到原生完成的终态业务检查点未确认，不能改记成业务成功或失败。

本轮独立目录 `.local/provider-retest-20261013/browser`、2030 / 5181 服务已停止，端口已释放；原历史未使用。继续保持现有模型 / 网关、后端 `.env`、`NO_PROXY=*`、TLS 校验、`AGENT_RPM=30`、共享结构化 fallback 和 Qwen `/no_think`。详见 [新证据](provider-2026-10-13-evidence.json)；[2026-10-11 证据](provider-step2-evidence.json) 原样保留。

下一步采用两个分支：

- 供应商恢复：先补齐真实标准用例的完整交付，核验两次 run、配置与报告归属、真实来源、正文引用和刷新零新增执行，再安排计划 3。
- 仍未稳定：可独立推进计划 3 的写作尝试身份、正文事件、持久回放、前端草稿归并及故障矩阵，全部替身结果明确标注；真实交付与真实流式验收仍保留为阻塞项。

[计划 3 实施方案](report-streaming-plan.md) 已列出顺序、代码入口和验收矩阵：同 run 内重写也有新写作尝试，重连 / 重试不重复拼接，最终正文以所属检查点校准。**本轮只规划，尚未实施。** 既有替身基线仍为后端 122、Chrome 82、原生 API 14 项，本轮未重跑。

## 计划 2 交接补充（2026-10-11 历史）

本轮从 `acd0813`、`chore/public-edits` 的干净工作区继续。按次配置已接入六个模型角色、自动 / 手选 Skills 允许集合、不可变提交、澄清继承、历史回读和执行恢复。下一项为计划 3 的真实报告流式显示。下文保留 1A / 1B 的实施背景与计划 2 原目标；后续以本节和最新验收记录为准。

新增入口为 `src/deep_research/run_configuration.py`。服务启动时将现有六个角色的模型定义去重为可选目录，所有角色可从此目录选取。相同模型但不同网关、凭据引用或 token 上限是不同配置。没有新增供应商或替换用户本地模型。`configuration_version: 1` 配合原受理能力启用选择；旧后端和非持久化独立图保留原用法。

受理事务保存完整公开快照，服务端 `atlas-configs.sqlite3` 归档对应模型定义和 Skills 正文修订。默认与受理库同目录，可设 `ATLAS_CONFIG_DB`。必须与受理库、原生检查点和事件库一并保留；归档仅存凭据环境变量名，不存密钥。模型默认值或 Skills 文件改变后，历史、澄清和恢复仍使用归档。凭据轮换继续读取本地环境，归档的旧网关须仍可访问。

2026-10-11 用户要求复测供应商：最小请求和结构化澄清曾成功；真实浏览器闭环完成首问澄清和范围补充，随后研究员 / 协调器连接失败，无报告。沙箱外再次复测出现 `CERTIFICATE_VERIFY_FAILED`，供应商尚未稳定恢复。保留 `NO_PROXY=*` 和 TLS 校验，未把替身验收计为真实成功。

后续保持三个父节点恢复白名单，不将配置快照支持理解为任意研究子节点均可恢复。故障验收继续使用独立临时目录，并核对服务端 run 与实际模型 / 工具计数。新窗口先检查 Git 与所有现有修改，再读最新验收；不要覆盖本轮尚未提交的工作。

## 1A / 1B 交接时的起点（历史基线）

- 项目目录：`D:/deep_research_public_preview`。
- 分支：`chore/public-edits`。
- 1B 开发基准：`79e29af`（`feat: persist and replay Atlas research events`）。接手时工作区干净。1B 实现、验收资料与交接说明归入 `feat: confirm Atlas submissions and recover interrupted execution` 提交；后续先用 `git status` 与 `git log` 核对实际提交和工作区，不覆盖新增修改。
- 1B 完成会话：`codex://threads/01a12716-05a4-70f3-846b-4aedeb8982fc`。后续以提交、本文与验收记录为上下文入口。
- 1A 完成会话：`codex://threads/01a126c4-7f0c-7031-a5d6-e084d196f827`。前序为 `codex://threads/01a126a3-b977-7612-ab8c-28bce9dd729b` 和 `codex://threads/01a1256d-d9a1-7c12-a504-e83487b7e7ed`。以本文和验收记录为接手依据，聊天仅用于补充追溯。
- 当时决定：供应商问题由供应商后续修复，继续独立开发；2026-10-11 的复测已按新要求执行，结果见首节。

当前已完成真实后端接口、澄清续问、简报、研究、报告与来源展示，区分等待补充、运行、成功、失败和部分完成。1A 提供持久事件与观察恢复；1B 增加提交对账、服务端幂等受理、冲突保护、持久终态确认和经过验证的检查点恢复。Apple 银白 / 石墨界面和独立全流程演示继续保留。

本轮后端 **107 passed**、Chrome **76 passed / 10 opt-in skipped**；10 项原生 API 验收已另行显式运行并全部通过（1B 8 项，原有 2 项）。构建、类型、格式和静态检查通过。全部模型 / 搜索均使用明确的替身；真实模型完整研究仍待供应商恢复后验收。详细结果见 [验收记录](verification.md) 最新章节。

相关依据：[验收记录](verification.md)、[接口约定](backend-contract.md)、[维护说明](../../docs/maintenance.md)、[架构约定](../../docs/architecture-decisions.md)。验收记录按新到旧排列，较早章节描述的是当时的范围。

## 建议顺序

| 顺序       | 工作                   | 可验收的结果                                                                                 |
| ---------- | ---------------------- | -------------------------------------------------------------------------------------------- |
| 1A，已完成 | 连接恢复与事件持久化   | 断网、刷新及服务重启后可补回已持久化事件；缺失记录明确可见；恢复观察不会新增研究运行         |
| 1B，已完成 | 提交确认与执行中断恢复 | 原提交安全对账与重试；澄清、简报、报告写作可从验证过的检查点恢复；研究子流程中途退出保留成果 |
| 2，已完成  | 按次模型 / Skills 配置 | 后端接受并实际执行所选配置；同轮澄清、并发研究和历史快照保持正确隔离                         |
| 3          | 真实报告流式显示       | 写作过程中逐步显示实际正文，重连和写作重试不会重复拼接，最终内容与检查点一致                 |
| 条件触发   | 真实模型联调验收       | 供应商恢复后完成真实澄清、检索、报告与来源核验；可在任何阶段补做，是实际交付能力的验收条件   |

1A 和 1B 分别实现和验收。1B 仅恢复已验证的三个父图节点，不能宣称整个研究已能从任意中断继续。

## 1A：已完成的范围

- 已核实锁定版本的 SSE 缓冲位于内存，原生状态另有约 10 秒刷盘边界。新增事件日志在 SSE 发送前提交，不等待父研究节点返回。
- 默认日志为 `.langgraph_api/atlas-events.sqlite3`，可用 `ATLAS_EVENT_DB` 指定，`ATLAS_EVENT_RETENTION_DAYS` 默认 30。进程停止后同一数据库中的已提交记录可以分页补回；过期、丢失或写入失败明确提示。
- 浏览器将事件与恢复位置一起保存，分别处理原生 SSE 游标和业务事件序号，按后端地址、thread、research、turn、run 隔离。保存失败时保留内存成果，不推进持久化位置。
- 先核对 run / checkpoint，再分页补回，处理缓冲拒绝、重复 / 乱序、旧提交、日志替换和终态缺失。连接失败以最高 30 秒退避重试，聚焦或网络恢复时及时对账，同一 run 保持一个 SSE 观察连接。
- 旧后端、旧本地会话及演示模式保持可用；损坏的恢复位置单独丢弃，不丢弃对话。回放不创建 run，不修改业务成功状态。
- 强制停止验收在检索工具内部中断专用后端；父检查点和浏览器尚无事件时，重启补回此前已提交的记录，并核对仍只有两次运行。旧捕获过程的任务缺少终态时显示“完成状态未确认”。

这些保证面向单进程本地服务。原生后端重启后可能仍将旧 run 标为 `running`，但没有继续执行；事件回放不会恢复执行。数据库丢失、保留期已过或从未提交成功的事件不保证补回，已确认成果继续保留。

验收中还修复了并发首次建库的 SQLite 锁竞争。当前 CLI 对持久化环境变量和顶层配置的传递有差异，普通 API 替身改由 `tests/atlas_fixture_server.py` 在独立目录启动并明确关闭持久化；恢复测试使用独立的持久化目录。命令和版本依据见 [接口约定](backend-contract.md)。

## 1B：已完成的范围

- `/atlas/config` 的 `submission_recovery_version: 1` 启用受理契约。浏览器先保存不可变提交内容与前一 turn；服务端先提交 SQLite 意图及固定 run UUID，再创建原生 run。相同标识和内容回读同一执行；内容变化、并发提交和过时的前一 turn 返回 409。
- 丢失响应时读取提交回执。未开始的受理可由“重试同一提交”继续，仍使用原有标识；读取状态和事件不会自行重新提交。旧缓存和旧后端继续按原 metadata 回读，不擅自升级为可重试提交。
- 每次恢复有独立 attempt UUID 和新 run，归属于原 turn。恢复请求先持久化，再核对服务端最新检查点；响应丢失或恢复受理中再次退出，重试沿用原 attempt。
- 图节点在任何模型 / 工具调用前记录进程归属并持久化原生状态。旧进程的执行不能直接重放原输入。确认终态前持久化检查点，已完成 turn 回读固定检查点，后续 turn 不覆盖其归属。
- 后端重启后，只恢复 `clarify_with_user`、`write_research_brief`、`final_report_generation`。核对 run、research、turn、唯一下一节点、阶段、记录的输入摘要及实际模型标识；只恢复 `input: null`，不重新提交问题。当前节点的模型可能再次调用；写作恢复不重跑已完成的检索与压缩。
- `supervisor_subgraph` 内部中断、记录缺失、检查点不一致或配置改变时不允许恢复。保留检查点、本地缓存和事件中已确认的笔记 / 来源 / 报告，提供新建研究入口。缺少终态的研究任务仍标为未确认。
- 原生故障验收在独立临时目录中覆盖提交响应丢失、创建 run 前后立即退出、三个节点内立即退出、恢复受理再次退出、冲突、会话丢失、完成 turn 重复请求及后续 turn 隔离。检查原生 run 列表和持久替身调用计数，没有等待十秒刷盘再停止。

默认受理库为 `.langgraph_api/atlas-submissions.sqlite3`；可设 `ATLAS_SUBMISSION_DB`，空值沿用默认。受理标识不按事件的 30 天保留期清除。必须一并保留受理库、原生 `.langgraph_api` 检查点与事件库。当前只面向锁定版本的持久化单进程本地服务；版本改变后能力关闭，重新验收后再更新适配。详见 [接口约定](backend-contract.md)。

## 2：按次模型 / Skills 配置（已完成，保留原目标）

本阶段起点是模块导入时构造的六个模型角色和只读菜单；目前已按请求作用域选择模型。下列要求已贯通，独立图及评估仍可使用原默认模型对象。

- 后端公开可用配置目录，使用服务端管理的配置标识；前端选择来自此目录。凭据与网关地址继续留在后端。
- 建议一轮逻辑研究确定一次配置，澄清续问沿用；下一轮研究可以更换。保存实际配置快照，后端默认值变化不会重写历史。
- 配置标识及快照要贯通 1B 的不可变受理内容、重试对账与执行恢复。同一 turn 重试使用原配置；恢复沿用所属研究的快照，不能误用重启后的全局默认配置。相应更新受理内容校验、恢复输入摘要及版本兼容检查。
- 将配置传递到 scoping、supervisor、researcher、网页摘要、compression、final report 六个角色。按请求选择 / 缓存模型，避免运行期间修改进程环境或全局模型对象造成并发串用。
- Skills 保留自动模式；手选模式先定义为“允许自动加载的集合”，限制提示词目录与 `load_skill` 的实际可选项。界面区分所选集合和事件中实际加载的 Skills。
- 未支持的配置明确拒绝；独立图、现有评估、共享限流器和结构化输出兼容路径继续可用。

验收重点：两条并发研究使用不同配置、澄清保持原配置、后端重启后历史快照不变、非法配置被拒绝、实际调用与界面显示一致。模型和搜索替身可验证参数与隔离，真实提供商行为仍需真实联调。

建议从 `src/deep_research/model_config.py`、`research_agent_scope.py`、`multi_agent_supervisor.py`、`research_agent_skills.py`、`utils.py`、`skills_loader.py` 阅读模型与工具绑定，再核对 `submission_api.py` / `submission_journal.py` 的受理与恢复。前端入口为 `frontend/src/components/BackendControls.tsx`、`Composer.tsx`、`src/state/useLiveResearch.ts`、`src/data/liveSchema.ts` 和 `src/api/submissions.ts`。

## 3：真实报告流式显示

- 只接收最终报告写作节点的正文增量，按研究、提交、run 和写作尝试隔离；不展示模型推理或其他节点输出。
- 区分正在生成的草稿与确认完成的报告。写作重试清楚区分尝试，避免把失败尝试与新正文拼接。
- 处理断流、刷新、Markdown 半成品和写作失败；最终以所属检查点的报告、来源和业务状态校准。
- 验收首段在写作结束前可见，最终正文一致；重复增量、重试、断线、部分完成及演示切换均不串内容。

报告导出、引用跳转增强、跨设备会话发现和部署可作为后续候选，待以上能力稳定后另定范围。

## 真实联调的触发条件

供应商稳定恢复后补做。2026-10-13 已重新测量，前置探针通过，真实浏览器首问超时，完整交付仍未验收；详情以本文首节为准。保留用户指定的模型、网关配置、后端本地 `.env` 和直连要求 `NO_PROXY=*`，保持 TLS 校验。

使用正常后端和前端，启用 `ATLAS_LIVE=1`，清除 `ATLAS_API_FIXTURE`。先完成一条真实研究：澄清 → 同 thread 补充 → 简报 → 实际检索 / Skills 事件 → 报告与来源 → 刷新回读。检查业务状态、报告归属和真实检索来源，并抽查正文引用是否有来源支持。

既有标准验收用例应只有两次 run（首问和一次澄清回答）；其他用例按实际提交次数核对，恢复观察不增加运行。分别记录真实结果、替身结果、失败与未执行检查，API 的 `run=success` 不能代替业务验收。

## 新窗口上下文

下次接手先读本文和验收记录最新章节，再核对实际监听服务与配置。正常后端默认 2024，前端以启动输出为准；普通替身默认 2025 / 5175，1A 默认 2026 / 5176，1B 默认 2027 / 5177。强制停止由测试器管理独立后端；端口占用时换专用端口，不停止不属于测试的进程。不要复用测试数据作为正常研究历史。

建议阅读顺序：

1. `D:/deep_research_public_preview/AGENTS.md`
2. `D:/deep_research_public_preview/frontend/docs/next-steps.md`
3. `D:/deep_research_public_preview/frontend/docs/verification.md` 的最新章节
4. `D:/deep_research_public_preview/frontend/docs/provider-2026-10-13-kimi-evidence.json` 与 `provider-2026-10-13-backoff-evidence.json`；其他供应商证据按各自日期作历史对照
5. `D:/deep_research_public_preview/frontend/README.md`
6. `D:/deep_research_public_preview/frontend/docs/backend-contract.md`
7. `D:/deep_research_public_preview/docs/maintenance.md`
8. `D:/deep_research_public_preview/docs/architecture-decisions.md`
9. `D:/deep_research_public_preview/frontend/docs/report-streaming-plan.md`
10. `D:/deep_research_public_preview/langgraph.json`、`pyproject.toml` 和相关锁文件
11. `D:/deep_research_public_preview/frontend/docs/recorded-runs.md`

恢复相关代码入口：

- 前端：`frontend/src/state/useLiveResearch.ts`、`frontend/src/api/researchStream.ts`、`frontend/src/api/eventReplay.ts`、`frontend/src/state/useWorkspace.ts`、`frontend/src/data/eventRecovery.ts`、`frontend/src/data/liveSchema.ts`、`frontend/src/data/researchEvents.ts`。
- 后端：`src/deep_research/event_journal.py`、`src/deep_research/research_events.py`、`src/deep_research/research_agent_full.py`、`src/deep_research/atlas_api.py`、`src/deep_research/state_scope.py`。
- 验收：`tests/test_event_journal.py`、`tests/test_full_workflow.py`、`tests/atlas_fixture_server.py`、`tests/atlas_recovery_fixture.py`、`frontend/tests/live-recovery.spec.ts`、`frontend/tests/recovery-api.spec.ts`、`frontend/tests/live-api.spec.ts`。
- 1B：`src/deep_research/submission_journal.py`、`submission_api.py`、`atlas_runtime.py`；前端 `src/api/submissions.ts`、`src/data/executionRecovery.ts`；验收 `tests/test_submission_journal.py`、`tests/atlas_submission_server.py`、`tests/atlas_submission_fixture.py`、`frontend/tests/live-submissions.spec.ts`、`frontend/tests/submission-api.spec.ts`。

可复制到新窗口的任务说明：

```text
继续「星图工作台」，先读取 2026-10-14 实录交接、验收和计划 3 方案。

项目：D:/deep_research_public_preview
预期分支：chore/public-edits
实录回放提交标题为 feat: replay recorded Atlas research runs，父提交为 2fc6299。
具体提交号以交接消息和 git log 为准；计划 2 提交为 b5b53f4。
2026-10-13 完成多轮真实复测，2026-10-14 完成实录 / 导出收尾。
计划 3 的在线报告正文流式仍未实施。
先核对交接提供的提交号；若已有更新提交，保留后续工作。
先用 git log -1 和 git status --short 核对状态，保留所有现有修改。
读取 AGENTS.md、frontend/docs/next-steps.md、
frontend/docs/verification.md 最新章节及接口、维护与架构文档。

1A 观察与记录恢复、1B 提交确认与受限执行恢复均已完成。
受理意图与固定 run ID 先持久化，恢复 attempt 与原 turn 分开。
只从验证过的澄清、简报、报告写作检查点恢复；研究子流程中断不盲目续跑。
模型节点可能再次调用，报告恢复不重跑已完成检索；真实模型仍待验收。
本轮 Chrome 86 passed / 14 opt-in skipped；演示专项 11 项通过。
后端 122、原生 API 14 项是此前替身基线，本轮没有重跑。

计划 2 已贯通六个角色、Skills 允许集合、受理 / 澄清 / 恢复和历史快照。
先读本文首节和最新验收记录，保留现有未提交修改。
下一批按新任务要求安排真实报告补验或计划 3；流式方案要求按写作尝试隔离。
保留已验证的配置与受理契约，同一提交重试沿用原配置。
测试需核对服务端 run 和替身调用次数，并使用隔离临时目录。
当前 CLI 的持久化开关存在传递差异，按文档使用专用测试启动器。

GLM 延长澄清并增加退避后仍在简报阶段失败。
同 key / base URL 的 Kimi 隔离测试取得 231 字简报、30 条事件、
1 份笔记及 8 条来源，两个 run；1950 秒保护期限在写作中触发。
最后 running/writing、报告为空，业务终态未确认；未成功加载 Skills。
实录不新建执行、不拼接 GLM / Kimi 或模拟结果，保持原视觉与完整模拟。
下载包在 .local/exports/atlas-real-calls-2026-10-13.zip；不进入 Git。
新的真实测试第二阶段使用 30 分钟总预算的剩余时间并预留 30 秒回读，
旧 Kimi 的 1140 秒观察超时记录保持不变。保持现有模型 / 网关配置、
后端本地 .env、NO_PROXY=* 和 TLS 校验。
真实模型完整闭环待供应商恢复后验收，替身结果明确标注。
保留 Apple 银白 / 石墨视觉、交互与独立演示；
继续遵守共享 structured_output_fallback 和 Qwen /no_think 约定。
下一轮先核对新指令和 Git 状态，保留所有现有修改。
```
