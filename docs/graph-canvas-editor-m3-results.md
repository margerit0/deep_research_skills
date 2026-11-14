# Graph 流程编辑器 M3 实施与验证

日期：2026-11-15（Asia/Shanghai）。分支：`codex/graph-canvas-editor`；M2 基线：`574e655`。M3 实现、测试和本记录同批提交，未推送。

## 已交付

- [真实节点适配](../src/deep_research/workflow_nodes.py) 将旧父节点的固定路由转换为业务结果。[编译器](../src/deep_research/workflow_compiler.py) 只按发布定义选择唯一后继；仅 START 使用静态边。原 `research_agent_full`、Scoping 和独立评估入口保留。
- 计划优化复用 SCOPING 与共享结构化输出 fallback，同时替换简报和 `Overwrite(supervisor_messages)`。材料整理复用 COMPRESSION，写入独立 `organized_notes`；原始笔记、来源和证据保持原样。完整来源正文和短报告路径也使用整理结果；显式空结果失败。
- [生产工厂及发布上下文](../src/deep_research/workflow_runtime.py) 核对真实处理器、运行时版本、模型与 Skills 目录及归档。新入口 `research_workflow` 使用模块路径注册。能力发现还核对原生服务实际注册的是本工厂，测试原型或同名其他图不能声明生产能力。
- [受理存储](../src/deep_research/workflow_store.py) 在同一受理 SQLite 连接、同一 `BEGIN IMMEDIATE` 中核对不可变修订，并提交 thread 绑定、逐提交绑定副本、有效配置、原 payload／摘要及固定 run UUID。模型／Skills 内容归档仍在事务前完成，属于另一份数据库。
- [受理及恢复](../src/deep_research/submission_api.py) 支持可选 `workflow_ref`。省略或 `null` 不改变旧摘要；同 thread 永久使用原版本。旧图历史不能升级，归档只阻止新绑定。创建原生 run 前校验可执行性。三个安全恢复边界仍是澄清、简报和最终报告。
- [父节点事件](../src/deep_research/workflow_events.py) 以 `atlas.workflow_event` 投递，先持久化再发送；事件核对 thread／research／turn／run／attempt／修订／节点及连续序号。动态研究员继续使用原事件体系。
- 已发布页提供“使用此版本发起研究”，创建新的本地会话并等待用户输入问题。提交前核对原发布文档和后端能力，缺失能力不会运行内置图。[运行视图](../frontend/src/components/workflow/WorkflowRunGraph.tsx) 按发布链展示父节点，状态来自已核对事件及检查点；动态研究员在协调器下单独展示。运行视图使用纵向排列，发布版编辑布局仍保存在原快照中。

## 存储与观察边界

工作流迁移从 `workflow_schema.version=1` 升到 **2**，受理库 `PRAGMA user_version` 仍为 **2**。新增 `workflow_submission_bindings`、`workflow_event_runs`、`workflow_node_events`；逐提交绑定副本可以发现丢失的 thread 绑定，避免回落到旧默认图。修订、绑定和父节点事件采用不可变约束。

父节点事件放在受理库，随受理记录保留，不使用动态研究员事件的 30 天清理策略。一个首版执行最多 28 个业务节点、56 个父节点事件；恢复创建新 attempt 和新 run，各自从序号 1 开始。父事件存储失败时不投递未持久化内容，执行按失败／安全恢复规则处理。SSE 断开只影响观察；回放接口不创建或恢复 run。

原生状态／历史读取从 thread 原绑定建立同拓扑、不可执行的观察图。完整 v1 归档在某个处理器缺失时仍可查看；运行或恢复拒绝缺失实现。安全恢复包含原绑定和整理结果的输入摘要；旧检查点缺少这两个字段时保持原摘要。测试固定了由 M2 提交计算的旧摘要样本。

只有管理存储就绪才声明 `workflow_editor_version: 1`；生产工厂、受支持运行时及实际实现就绪后才声明 `workflow_execution_version: 1` 和 `workflow_events_version: 1`。`ATLAS_WORKFLOW_EXECUTION_ENABLED=false` 可关闭新执行，完整旧归档仍可读。

## 验证结果

所有模型、搜索和网关请求均使用替身；没有进行真实研究质量或费用验收。原生故障与浏览器验收使用专属目录和本机端口，只终止测试自己启动的进程。

| 范围 | 结果与主要证据 |
| --- | --- |
| 后端确定性及相关回归 | **226 项通过**：M3 26、旧完整图 26、Store 26、管理 API 19、契约 78、受理日志 24、配置 15、M0 编译原型 12；分批执行 |
| 原生 API | **14 项通过**：v1／v2／v3 路径、澄清期间发布、受理事务中退出、意图提交后退出、响应丢失、3 个安全与 3 个不安全中断点、缺失实现、六角色／Skills 隔离、旧请求与归档兼容 |
| 前端及相关回归 | **230 项通过**：M3 12 项，既有编辑器／契约／研究／事件／报告／演示 218 项；分批执行 |
| 原生浏览器 | **1 项通过**：在正式编辑器发布 v1 并运行，删除材料整理后发布 v2，再运行并回读旧会话；两次研究各一个原生 run |
| 静态与生成物 | TypeScript、生产构建、Ruff、Prettier、生成契约核对及 Git diff 检查；命令见下文 |

关键业务断言：

- 多个扩展实例按定义顺序各执行一次；删除澄清后其模型调用为 0。协调器只收到最后优化后的简报，写作实际收到整理材料。
- 整理前后的 `notes/raw_notes/sources/source_evidence` 相同；无材料、优化失败、空整理结果均不生成成功报告。
- v1 等待回答时发布 v2，回答仍用 v1；显式切换返回 `workflow_binding_conflict`。新 thread 可使用 v2，归档后新绑定拒绝，原澄清继续成功。
- 事务中退出无孤立绑定或受理；提交意图后退出和丢失响应均沿用同一个 run 身份。修复测试清理对 Windows 已退出进程的识别后，两项退出用例重跑通过。
- 澄清、简报、写作恢复使用精确 checkpoint 与 `input: null`；写作恢复不重跑检索或整理。优化、整理和检索内部中断拒绝续跑。重启改变当前模型默认值后，恢复仍使用原归档。
- 缺失计划优化实现时旧定义、检查点可读；新请求在创建 run 前被拒绝。刷新、状态／历史读取与事件分页不增加模型调用或 run。
- 前端拒绝错误修订检查点和事件、跨 attempt 事件、序号缺口及冲突 UUID；旧后端不支持所选流程时保留问题。1440 浅色、1024 深色、390 浅色、320 深色及减少动画完成查看验证。

本地证据根目录为 `.local/graph-canvas-m3/`，原生用例各保存 `case-*/evidence.json` 和服务日志；浏览器最终截图在 `browser-final/`，实际服务截图与两份运行状态在 `browser-native/`。目录属于本地证据，不作为后续实现计划。

**默认库隔离纠正：** 一项既有 `test_full_workflow.py` 配置能力测试最初使用了默认受理库，触发空工作流表的追加迁移。只读核对显示流程／修订／绑定／父事件均为 0，原有 2 条受理和 2 次尝试的最新时间仍在 2026-10-13，原生持久化文件时间未变，完整性及外键检查通过。已给该测试模块增加自动隔离夹具，复测同时核对默认库文件哈希不变。没有降级或删除默认库；审计见 `.local/graph-canvas-m3/default-store-audit.json`。

## 复现入口

在项目根目录运行；先创建父证据目录，每批使用新的 `--basetemp`。Windows 的本地 asyncio／原生服务测试需允许回环套接字。

```powershell
New-Item -ItemType Directory -Path .local/graph-canvas-m3 -Force | Out-Null
$m3Temp = Join-Path (Get-Location) ('.local\graph-canvas-m3\pytest-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/test_workflow_execution.py tests/test_full_workflow.py tests/test_workflow_store.py tests/test_workflow_api.py tests/test_workflow_definition.py tests/test_submission_journal.py tests/test_run_configuration.py tests/test_workflow_factory.py -q --basetemp $m3Temp

$env:ATLAS_WORKFLOW_M3_API = '1'
$m3NativeTemp = Join-Path (Get-Location) ('.local\graph-canvas-m3\native-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/test_workflow_execution_api.py -q --basetemp $m3NativeTemp
.venv/Scripts/python.exe -m scripts.export_workflow_contract --check
```

在 `frontend/` 运行浏览器验证。使用未占用的端口，`CI=1` 禁止复用日常前端；原生测试的 Vite 代理与测试后端端口必须一致。

```powershell
$env:CI = '1'
$env:ATLAS_TEST_PORT = '5321'
node node_modules/@playwright/test/cli.js test tests/workflow-execution.spec.ts

$env:ATLAS_TEST_PORT = '5319'
$env:ATLAS_WORKFLOW_M3_API = '1'
$env:ATLAS_WORKFLOW_M3_PORT = '2858'
$env:ATLAS_BACKEND_URL = 'http://127.0.0.1:2858'
node node_modules/@playwright/test/cli.js test tests/workflow-execution-api.spec.ts --workers=1
npm run typecheck
npm run build
```

其余前端回归文件为 `workflow-editor/workflow-contract/workspace/live/live-submissions/live-events/live-recovery/live-report/report-card/demo/recordings.spec.ts`。新增 Python 模块及工作流／运行时模块使用项目完整 Ruff 规则；旧完整图与受理模块执行 E／F 检查并保留项目忽略的 E501，旧完整图测试保留“先配置环境再导入”的顺序并执行 F 检查。Prettier 检查本阶段修改的 TypeScript／CSS。

## 后续 M4

M3 证明编排、事务、恢复与观察契约，不证明真实模型产物质量。M4 仍需确定有界样本、尝试及费用范围，执行标准／扩展流程和澄清续问的真实验收，并测量发布、画布、较多动态任务的性能。没有自动开展这部分调用，也没有对旧研究执行重放。
