# 星图工作台后续任务与交接

更新日期：2026-10-11。1A、1B 已实现并验收；当前恢复范围和验收结果见本文与验收记录。

## 已核实的起点

- 项目目录：`D:/deep_research_public_preview`。
- 分支：`chore/public-edits`。
- 1B 开发基准：`79e29af`（`feat: persist and replay Atlas research events`）。接手时工作区干净。1B 实现、验收资料与交接说明归入 `feat: confirm Atlas submissions and recover interrupted execution` 提交；后续先用 `git status` 与 `git log` 核对实际提交和工作区，不覆盖新增修改。
- 1B 完成会话：`codex://threads/01a12716-05a4-70f3-846b-4aedeb8982fc`。后续以提交、本文与验收记录为上下文入口。
- 1A 完成会话：`codex://threads/01a126c4-7f0c-7031-a5d6-e084d196f827`。前序为 `codex://threads/01a126a3-b977-7612-ab8c-28bce9dd729b` 和 `codex://threads/01a1256d-d9a1-7c12-a504-e83487b7e7ed`。以本文和验收记录为接手依据，聊天仅用于补充追溯。
- 用户最新决定：供应商问题由供应商后续修复，跳过连接排障，继续独立于供应商的开发。

当前已完成真实后端接口、澄清续问、简报、研究、报告与来源展示，区分等待补充、运行、成功、失败和部分完成。1A 提供持久事件与观察恢复；1B 增加提交对账、服务端幂等受理、冲突保护、持久终态确认和经过验证的检查点恢复。Apple 银白 / 石墨界面和独立全流程演示继续保留。

本轮后端 **107 passed**、Chrome **76 passed / 10 opt-in skipped**；10 项原生 API 验收已另行显式运行并全部通过（1B 8 项，原有 2 项）。构建、类型、格式和静态检查通过。全部模型 / 搜索均使用明确的替身；真实模型完整研究仍待供应商恢复后验收。详细结果见 [验收记录](verification.md) 最新章节。

相关依据：[验收记录](verification.md)、[接口约定](backend-contract.md)、[维护说明](../../docs/maintenance.md)、[架构约定](../../docs/architecture-decisions.md)。验收记录按新到旧排列，较早章节描述的是当时的范围。

## 建议顺序

| 顺序       | 工作                   | 可验收的结果                                                                                 |
| ---------- | ---------------------- | -------------------------------------------------------------------------------------------- |
| 1A，已完成 | 连接恢复与事件持久化   | 断网、刷新及服务重启后可补回已持久化事件；缺失记录明确可见；恢复观察不会新增研究运行         |
| 1B，已完成 | 提交确认与执行中断恢复 | 原提交安全对账与重试；澄清、简报、报告写作可从验证过的检查点恢复；研究子流程中途退出保留成果 |
| 2，下一批  | 按次模型 / Skills 配置 | 后端接受并实际执行所选配置；同轮澄清、并发研究和历史快照保持正确隔离                         |
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

## 2：按次模型 / Skills 配置

当前六个模型角色及绑定工具在模块导入时构造，真实菜单只读。因此这一阶段需要贯通后端配置作用域和实际调用。

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

供应商恢复后补做，当前不继续诊断已暂缓的问题。保留用户指定的模型、网关配置、后端本地 `.env` 和直连要求 `NO_PROXY=*`，保持 TLS 校验。

使用正常后端和前端，启用 `ATLAS_LIVE=1`，清除 `ATLAS_API_FIXTURE`。先完成一条真实研究：澄清 → 同 thread 补充 → 简报 → 实际检索 / Skills 事件 → 报告与来源 → 刷新回读。检查业务状态、报告归属和真实检索来源，并抽查正文引用是否有来源支持。

既有标准验收用例应只有两次 run（首问和一次澄清回答）；其他用例按实际提交次数核对，恢复观察不增加运行。分别记录真实结果、替身结果、失败与未执行检查，API 的 `run=success` 不能代替业务验收。

## 新窗口上下文

下次接手先读本文和验收记录最新章节，再核对实际监听服务与配置。正常后端默认 2024，前端以启动输出为准；普通替身默认 2025 / 5175，1A 默认 2026 / 5176，1B 默认 2027 / 5177。强制停止由测试器管理独立后端；端口占用时换专用端口，不停止不属于测试的进程。不要复用测试数据作为正常研究历史。

建议阅读顺序：

1. `D:/deep_research_public_preview/AGENTS.md`
2. `D:/deep_research_public_preview/frontend/docs/next-steps.md`
3. `D:/deep_research_public_preview/frontend/docs/verification.md` 的最新章节
4. `D:/deep_research_public_preview/frontend/README.md`
5. `D:/deep_research_public_preview/frontend/docs/backend-contract.md`
6. `D:/deep_research_public_preview/docs/maintenance.md`
7. `D:/deep_research_public_preview/docs/architecture-decisions.md`
8. `D:/deep_research_public_preview/langgraph.json`、`pyproject.toml` 和相关锁文件

恢复相关代码入口：

- 前端：`frontend/src/state/useLiveResearch.ts`、`frontend/src/api/researchStream.ts`、`frontend/src/api/eventReplay.ts`、`frontend/src/state/useWorkspace.ts`、`frontend/src/data/eventRecovery.ts`、`frontend/src/data/liveSchema.ts`、`frontend/src/data/researchEvents.ts`。
- 后端：`src/deep_research/event_journal.py`、`src/deep_research/research_events.py`、`src/deep_research/research_agent_full.py`、`src/deep_research/atlas_api.py`、`src/deep_research/state_scope.py`。
- 验收：`tests/test_event_journal.py`、`tests/test_full_workflow.py`、`tests/atlas_fixture_server.py`、`tests/atlas_recovery_fixture.py`、`frontend/tests/live-recovery.spec.ts`、`frontend/tests/recovery-api.spec.ts`、`frontend/tests/live-api.spec.ts`。
- 1B：`src/deep_research/submission_journal.py`、`submission_api.py`、`atlas_runtime.py`；前端 `src/api/submissions.ts`、`src/data/executionRecovery.ts`；验收 `tests/test_submission_journal.py`、`tests/atlas_submission_server.py`、`tests/atlas_submission_fixture.py`、`frontend/tests/live-submissions.spec.ts`、`frontend/tests/submission-api.spec.ts`。

可复制到新窗口的任务说明：

```text
继续「星图工作台」，从计划 2：按次模型 / Skills 配置开始。

项目：D:/deep_research_public_preview
预期分支：chore/public-edits
1B 已归入 feat: confirm Atlas submissions and recover interrupted execution 提交。
先核对交接提供的提交号；若已有更新提交，保留后续工作。
先用 git log -1 和 git status --short 核对状态，保留所有现有修改。
读取 AGENTS.md、frontend/docs/next-steps.md、
frontend/docs/verification.md 最新章节及接口、维护与架构文档。

1A 观察与记录恢复、1B 提交确认与受限执行恢复均已完成。
受理意图与固定 run ID 先持久化，恢复 attempt 与原 turn 分开。
只从验证过的澄清、简报、报告写作检查点恢复；研究子流程中断不盲目续跑。
模型节点可能再次调用，报告恢复不重跑已完成检索；真实模型仍待验收。
验收基线：后端 107、Chrome 76、原生 API 10 项通过；模型和搜索均为替身。

下一批贯通后端配置目录、同轮澄清和所有模型角色 / Skills 的实际执行，
保持并发研究隔离及历史配置快照。不要改变已验证的提交与恢复契约。
所选配置同时进入不可变受理内容、澄清续问和执行恢复，重试沿用原配置。
测试需核对服务端 run 和替身调用次数，并使用隔离临时目录。
当前 CLI 的持久化开关存在传递差异，按文档使用专用测试启动器。

用户已决定跳过供应商故障；保持现有模型 / 网关配置、
后端本地 .env、NO_PROXY=* 和 TLS 校验。
真实模型完整闭环待供应商恢复后验收，替身结果明确标注。
保留 Apple 银白 / 石墨视觉、交互与独立演示；
继续遵守共享 structured_output_fallback 和 Qwen /no_think 约定。
直接推进实现与验收。
```
