# Graph 流程编辑器实施交接

更新日期：2026-11-21。

本文件为新实施聊天提供入口、当前状态和下一步。完整范围、设计与排期见 [项目计划书](graph-canvas-editor-plan.md)。后续实施时，更新本文件的当前状态，并链接实际代码、提交和验证记录；不要将预期结果写成已验证事实。

**设计确认（2026-11-15）：用户在展示设计稿后明确回复“确认设计稿”，随后要求执行 M2 和继续 M3。** M0–M3 已完成，无需重复请求设计批准。M4 接续稳定性与性能，当前结果及待复验项见 [M4 记录](graph-canvas-editor-m4-results.md)。按用户要求先跳过需要真实模型的测试。

## 1. 当前起点

| 项目 | 当前状态 |
| --- | --- |
| 工作目录 | `D:\deep_research_public_preview` |
| 当前分支与代码基线 | `codex/graph-canvas-editor`；从 `d8caa38` 开始 |
| 计划提交 | `f8e4af7`：计划书与初始交接 |
| M0 提交 | `62ba7da`：流程修订、恢复验证与独立画布原型 |
| M1 提交 | `622ffb8`：v1 契约、目录与校验 |
| 实施分支 | 已创建，继续使用当前分支 |
| 实施进度 | M0–M3 完成；M4 的原生持久化／终态回读修复、动态任务分组和离线基准已实现 |
| M2／M3 提交 | `574e655`：正式流程编辑器与版本管理；`ae3c524`：发布工作流的生产执行 |
| 已有证据 | M0 后端 20 项、画布浏览器 3 项通过；相关后端回归、类型检查、两种构建和静态检查通过，详见 [M0 验证记录](graph-canvas-editor-m0-results.md) |
| 设计评审 | 独立原型 14 个交互场景通过，5 个尺寸／主题组合检查完成；入口、截图和限制见[设计评审记录](graph-canvas-editor-design-review.md) |
| M1 验证 | 后端及回归 124 项、前端契约 60 项通过；类型、构建、静态检查及生成物检查通过，见 [M1 记录](graph-canvas-editor-m1-results.md) |
| M2 验证 | 后端及回归 174 项、前端 164 项通过；含正式编辑器 25 项、契约 65 项及旧页 74 项，见 [M2 记录](graph-canvas-editor-m2-results.md) |
| M3 验证 | 后端 226 项、原生 API 14 项、前端 230 项、原生浏览器 1 项通过；见 [M3 记录](graph-canvas-editor-m3-results.md) |
| 生产能力 | 编辑存储就绪后声明 `workflow_editor_version: 1`；实际生产工厂注册、运行时和实现就绪后声明 `workflow_execution_version: 1`、`workflow_events_version: 1` |
| M4 验证 | 229 项确定性后端、14 项隔离原生 HTTP 通过；离线基准已有证据，体感与数值边界见 [M4 记录](graph-canvas-editor-m4-results.md) |
| 尚缺证据 | 两个旧工作区浏览器用例与一个原生浏览器用例的超时复验；真实模型报告质量及费用暂缓，替身测试不能代替 |
| 其他工作区内容 | `frontend/design-mockups/` 在本任务前已存在且未跟踪，不自动纳入本功能提交 |

进入实施时，以实际 `git status`、当前分支及 `git log` 更新上述状态。分支已存在就接续使用，不因本表的初始记录重复创建。

## 2. 目标与设计建议的边界

用户已明确确认：画布应支持添加、删除、连接节点，编辑结果发布后影响真实研究执行。

计划书建议首版编辑主流程，提供“研究计划优化”“材料整理”扩展节点；核心产物节点保留，条件分支、任意循环和研究员内部编辑后续开放。建议使用 React Flow、不可变流程修订、LangGraph 图工厂及独立节点事件。

M0 已验证 React Flow／Dagre 和“一个原生 thread 绑定一个流程修订”的路径。正式协议与生产接入仍须 M1–M3 实现；测试专用绑定表和执行重定向不能直接成为生产事务方案。已验证项、调整和边界见 [M0 验证记录](graph-canvas-editor-m0-results.md)。

## 3. 最小阅读入口

首先遵循根目录 [AGENTS.md](../AGENTS.md)。再阅读本交接与 [计划书](graph-canvas-editor-plan.md)，重点为现状、首版范围、第 6 节执行机制、第 8 节阶段和第 9 节验收。

按当前阶段读取以下参考文档的相关部分即可：

- [维护说明](maintenance.md)：环境加载、启动、测试替身、持久化和运行时版本约束。
- [架构约定](architecture-decisions.md)：研究／执行边界、配置快照、事件日志、受理与恢复。
- [后端接口约定](../frontend/docs/backend-contract.md)：身份与生命周期、按次配置、提交／恢复、原生测试启动方式。

历史 `.local/` 材料是证据，不是新的待办；需要故障背景时再读取对应记录。无需为接续工作复制完整聊天记录或遍历所有历史实验。

## 4. 会影响实现的现有约束

- `Graph.tsx` 当前是展示组件；`NodeDetail` 是展示模型，不能直接承担工作流执行定义。
- `getLiveNodes` 按固定阶段推导主节点；动态研究员来自实际事件，不是可直接删改的固定编排节点。
- 部分父节点返回硬编码 `Command(goto=...)`。新连接必须与业务路由一致，避免旧跳转与新增边同时执行。
- `prepare_research` 维护研究身份、状态重置和 reducer 清理；澄清通过 `goto=END` 等待，回答是同 thread 的新 run。
- 模型与 Skills 使用按研究固定的快照；流程修订须加入同样的受理、归属和恢复校验。
- 当前安全恢复边界只有澄清、简报、最终报告三个父节点；研究子图内部的任意断点恢复未受支持。
- 原生 run 成功、事件流结束与业务研究成功含义不同；验收需核对产物及其归属。
- 环境配置必须先于图模块导入。保留共享结构化输出 fallback、Qwen `/no_think` 及现有限流／诊断行为。

这些约束的完整依据以第 3 节引用的项目文档和当前代码为准。

## 5. 已完成阶段：M0 技术验证

目标是在隔离原型中证明后续执行接入可行。生产工作流管理、完整编辑页面和完整编译器分别属于后续阶段。

| 验证项 | 应取得的证据 |
| --- | --- |
| 两个流程修订 | 同一个图工厂在两个独立 thread 中构造不同路径；新增／删除测试节点改变实际调用顺序与计数 |
| 修订定位 | 首次执行、历史检查点读取及没有显式 revision 参数的状态请求，都能找到正确的绑定 |
| 澄清续问 | v1 等待回答时提供 v2，原研究的新提交仍使用 v1；新会话可以选择 v2 |
| 重启恢复 | 使用测试专属持久化目录停止并重启服务，按精确检查点和 `input: null` 恢复原修订 |
| 非法或缺失修订 | 拒绝未知、缺失或不兼容版本，不静默执行当前默认图 |
| 调度唯一性 | 路由适配原型不会同时执行旧后继与新后继；回读和刷新不新增 run |
| 前端依赖兼容 | 最小画布验证候选库与当前 React／TypeScript／Vite 兼容，记录确切依赖版本和构建结果 |

后端使用模型和搜索替身，不读取生产凭据、不调用真实模型或 Tavily。测试使用独立目录和空闲端口；停止与重启操作仅作用于本测试启动的进程，不操作日常研究服务或根目录的既有持久化数据。

建议将需要长期保留的原型及测试放入正常源码或测试目录；临时数据库和大日志放入新的 `.local/` 专属目录。M0 完成时创建简短的验证记录，列出实际命令、结果、限制、方案调整和可复现入口，再更新本文件。

上述验证项已通过，实际命令、调用计数、故障结果和本地 case 索引见 [M0 验证记录](graph-canvas-editor-m0-results.md)。原生测试使用真实业务函数及原有受理／恢复协议；运行状态、产物归属、run 数与调用次数均有断言。

### 已完成：前端设计评审与用户确认

独立设计稿已完成，用户已明确确认。直接查看[设计评审记录](graph-canvas-editor-design-review.md)中的预览与截图作为实施依据。原型位于 `.local/graph-canvas-design/2026-11-15-review/` 目录；设计阶段仅创建设计产物并更新设计说明，未修改项目源码、测试、依赖或 M0 原型。下面保留原设计阶段的范围与确认要求。

先读取当前星图工作台的页面、组件和样式，围绕“可编辑研究流程”制作一套完整的前端设计稿。沿用现有银白／石墨主题、布局和组件风格；M0 画布仅是技术原型，不代表用户已认可的视觉方案。

设计稿应能直观看到以下关键页面或状态：

- 从工作台进入流程管理，以及选择流程／草稿的入口。
- 主编辑画布：节点库、可拖动节点与连线、工具栏、保存状态。
- 添加／删除可选节点、选中节点后的参数面板，以及必需节点的锁定提示。
- 校验问题定位、保存冲突／失败提示、发布版本及“使用此版本发起研究”的操作顺序。
- 已发布版本与运行观察的关系；动态研究员属于运行实例，不能通过删除卡片取消任务。

优先交付桌面主设计和关键操作状态，并说明窄屏查看方式。提供可直接查看的设计稿、截图或独立可点击原型，以及简短的交互说明；避免只有文字计划。可在新的 `.local/graph-canvas-design/` 专属子目录生成设计产物，不覆盖已有 `frontend/design-mockups/`。

设计阶段允许只读检查现有项目、更新设计说明及创建独立设计产物；用户确认前不修改项目的前后端源码、测试、依赖、构建配置或 M0 原型，也不接入真实后端。若使用 HTML 制作可点击稿，仅在独立设计目录创建文件。

展示设计后等待用户明确确认或提出修改。确认来源必须是用户对设计稿的回复；M0 验证通过、已有计划或普通进度说明均不替代设计确认。根据反馈迭代，确认后再按定稿推进以下实施事项。

### 已完成：M1 契约与交互设计

下列契约已形成代码、机器 Schema 和验收条件，入口为 [v1 契约](graph-canvas-editor-contract.md)与 [M1 验证记录](graph-canvas-editor-m1-results.md)。生产 API、存储与编译器尚未接入；不能把 M1 的纯数据校验器或发布上下文替身当成真实执行能力。

1. 冻结定义、展示数据、草稿、不可变修订及 thread 绑定的 schema；核心运行节点保留稳定名称。
2. 明确节点输入输出、可写字段、模型角色、reducer 处理与合法拓扑，设计结构化校验问题协议。
3. 设计保存版本冲突、发布幂等，以及修订／配置／受理意图同事务持久化；新字段仅在存在时影响旧摘要。
4. 固定图工厂的执行／观察行为与缺失实现的处置，沿用三个安全恢复边界；M0 无绑定原生请求会形成 error run，正式入口须明确受理前校验。
5. 设计完整编辑页和验收用例。原型入口 `/m0/workflow.html` 只验证基础交互，不包含保存、发布或真实执行选择。

M3 已通过原生替身验收并按实际运行能力声明执行版本；原型 `/m0` 测试路由仍不加入生产服务。当前优先读取 v1 契约与 M3 记录，M0 的工厂与恢复证据作为补充依据。

### 已完成：M2 编辑与版本管理

1. 按 v1 契约实现正式 WorkflowStore 与管理 API，沿用受理数据库、迁移和持久化约束；验证草稿版本冲突、发布请求幂等、归档及副本身份。
2. 将已确认的三栏界面落到正式 React／React Flow 页面，接入节点目录、参数、撤销、保存状态、校验及发布只读视图。使用 `workflowSchema.ts`，不复制独立 HTML 中的模拟保存逻辑。
3. 加入工作台／流程管理入口及窄屏查看布局。原 `Graph.tsx` 的运行观察职责保留，动态研究员不成为可删除的设计时节点。
4. 以 API／存储替身和浏览器检查完成 M2 验收。真实发布校验必须核对可用实现；未实现的扩展节点等待 M3，不用占位处理器冒充可执行。
5. M2 仅在对应管理能力就绪时声明 `workflow_editor_version`；真实执行入口及事件能力由 M3 原生验收后开放。

上述交付已接入正式源码，并完成 [M2 验证](graph-canvas-editor-m2-results.md)。编辑入口为 `/#workflows`，使用方法见 [前端说明](../frontend/docs/workflow-editor.md)。创建／发布请求提前保存标识，完整文档回读不覆盖新输入；复制浏览器标签页后，各窗口保留独立的恢复副本。

M2 阶段存储放在现有受理 SQLite，工作流迁移为 1，受理库版本为 2；修订、幂等回执和草稿新基线同事务提交。当时仅预留绑定表，生产发布上下文未接入。以下 M3 已完成实际绑定与发布接入，不能把历史 M2 限制误读为当前能力。

### 已完成：M3 编译与运行接入

1. 真实节点适配器提取业务结果，编译器只按定义选择唯一后继。多个扩展、删除扩展和删除澄清的实际调用已验证。计划优化使用 `Overwrite`；材料整理写独立 `organized_notes`，完整证据／短报告分支也消费整理结果。
2. WorkflowStore 已使用生产 `PublicationContext` 核对实际实现、运行时、模型修订和 Skills；不是测试占位处理器。原生注册入口为 `deep_research.workflow_runtime:graph`。
3. 同一受理事务固定修订、thread 绑定、逐提交绑定副本、有效配置和固定 run UUID。工作流迁移升级为 2，受理库版本仍为 2；独立配置内容归档仍在事务前处理。
4. 省略／null 引用维持旧摘要；旧图 thread 不能升级。原 thread 后续研究、澄清及恢复沿用原绑定，归档不使既有受支持绑定失效。恢复仍只开放三个核心父节点。
5. 父节点事件持久化在受理库，校验归属与连续序号后回放。已发布页面可创建新会话，问题由用户输入后发送。正式运行图按发布链纵向展示，动态研究员单独观察。原生浏览器已验证删除节点实际改变新版本执行且旧会话不变。

一次旧配置回归测试触发了默认受理库的空工作流表迁移，未新增受理或运行；已修正该测试模块的存储隔离，并通过默认库哈希不变的复测。详情及只读完整性核对见 M3 记录，不要为此降级或删除原数据库。

### M4 剩余验收

1. 从 [M4 记录](graph-canvas-editor-m4-results.md)取三项浏览器超时的 trace 和复验命令；单 worker 独立执行，不与性能基准并跑。
2. 需要重测基准时使用隔离 HTTP 和仅展示画布；30 个可发布节点的限制不变。保留配置归档、研究成果、版本约束和默认库。
3. 暂不启动真实模型／检索。恢复此项前由用户确认供应商认证、样本、尝试和费用范围；然后核对业务终态、报告归属、正文、要求满足情况和实际来源。

## 6. 实现与验证入口

| 关注点 | 当前文件 |
| --- | --- |
| 固定图和业务跳转 | [research_agent_full.py](../src/deep_research/research_agent_full.py)、[state_scope.py](../src/deep_research/state_scope.py) |
| 受理及恢复 | [submission_api.py](../src/deep_research/submission_api.py)、[submission_journal.py](../src/deep_research/submission_journal.py) |
| 原生运行时兼容 | [atlas_runtime.py](../src/deep_research/atlas_runtime.py)、[langgraph.json](../langgraph.json) |
| 模型／Skills 修订 | [run_configuration.py](../src/deep_research/run_configuration.py) |
| 现有画布和运行状态 | [Graph.tsx](../frontend/src/components/Graph.tsx)、[live.ts](../frontend/src/data/live.ts) |
| 前端构建 | [package.json](../frontend/package.json)、[Playwright 配置](../frontend/playwright.config.ts) |
| 原生受理故障测试 | [submission-api.spec.ts](../frontend/tests/submission-api.spec.ts)、[atlas_submission_server.py](../tests/atlas_submission_server.py) |
| 原生事件恢复测试 | [recovery-api.spec.ts](../frontend/tests/recovery-api.spec.ts)、[atlas_recovery_fixture.py](../tests/atlas_recovery_fixture.py) |
| 工作流管理与迁移 | [workflow_store.py](../src/deep_research/workflow_store.py)、[workflow_api.py](../src/deep_research/workflow_api.py) |
| 正式流程编辑器 | [WorkflowWorkspace.tsx](../frontend/src/components/workflow/WorkflowWorkspace.tsx)、[useWorkflowEditor.ts](../frontend/src/state/useWorkflowEditor.ts)、[workflows.ts](../frontend/src/api/workflows.ts) |
| M2 验收 | [test_workflow_store.py](../tests/test_workflow_store.py)、[test_workflow_api.py](../tests/test_workflow_api.py)、[workflow-editor.spec.ts](../frontend/tests/workflow-editor.spec.ts) |
| M3 生产编译与节点 | [workflow_runtime.py](../src/deep_research/workflow_runtime.py)、[workflow_compiler.py](../src/deep_research/workflow_compiler.py)、[workflow_nodes.py](../src/deep_research/workflow_nodes.py) |
| M3 运行观察 | [workflow_events.py](../src/deep_research/workflow_events.py)、[workflowRuntime.ts](../frontend/src/data/workflowRuntime.ts)、[WorkflowRunGraph.tsx](../frontend/src/components/workflow/WorkflowRunGraph.tsx) |
| M3 验收 | [test_workflow_execution.py](../tests/test_workflow_execution.py)、[test_workflow_execution_api.py](../tests/test_workflow_execution_api.py)、[workflow-execution.spec.ts](../frontend/tests/workflow-execution.spec.ts)、[workflow-execution-api.spec.ts](../frontend/tests/workflow-execution-api.spec.ts) |
| M4 验收 | [test_atlas_native_checkpoints.py](../tests/test_atlas_native_checkpoints.py)、[test_workflow_m4_performance.py](../tests/test_workflow_m4_performance.py)、[workflow-performance.spec.ts](../frontend/tests/workflow-performance.spec.ts) |

以下相关回归、类型检查和构建已在 M0 执行；详细命令和结果以验证记录为准。Windows pytest 使用记录中的全新项目内 `--basetemp`，避免旧系统临时目录的权限问题：

```powershell
# 在项目根目录运行已有相关后端回归
uv run --locked --extra dev pytest tests/test_full_workflow.py tests/test_submission_journal.py tests/test_run_configuration.py

# 在项目根目录运行前端类型检查与构建
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

原生测试需要按 [接口文档](../frontend/docs/backend-contract.md) 配置专属前端代理、端口及启用变量。`submission-api.spec.ts` 需要 `ATLAS_SUBMISSION_API=1`，`recovery-api.spec.ts` 需要 `ATLAS_RECOVERY_API=1`；没有启用时会跳过，跳过不能计为验收通过。

M0 的新原生测试入口为 `tests/test_workflow_factory_api.py`，必须显式设置 `ATLAS_WORKFLOW_M0_API=1`；新画布测试为 `frontend/tests/workflow-m0.spec.ts`。完整复现见 [验证记录](graph-canvas-editor-m0-results.md)。保留当前锁文件及运行时版本约束。

## 7. 后续如何更新上下文

每个阶段完成或出现实质性方案调整时：

1. 更新“当前起点”：实际分支、当前阶段、完成项和下一步。
2. 记录影响下一阶段的决定及原因，关联到具体代码或验证记录。
3. 记录实际执行的命令、通过／失败／跳过情况，以及仍未验证的边界。
4. 将计划变化更新到计划书；实施证据链接到单独记录，避免反复复制长日志。
5. 将交接更新与对应实现一起提交，使从该提交启动的新聊天能重建当时状态。

可在后续提交中记录上一阶段的提交哈希；不要在一个提交中尝试填写它尚未生成的自身哈希。长期仓库规则继续放在 `AGENTS.md`，本功能的临时进度保留在本文件。
