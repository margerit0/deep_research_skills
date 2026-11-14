# Graph 流程编辑器实施交接

更新日期：2026-11-15（Asia/Shanghai）。

本文件为新实施聊天提供入口、当前状态和下一步。完整范围、设计与排期见 [项目计划书](graph-canvas-editor-plan.md)。后续实施时，更新本文件的当前状态，并链接实际代码、提交和验证记录；不要将预期结果写成已验证事实。

## 1. 当前起点

| 项目 | 当前状态 |
| --- | --- |
| 工作目录 | `D:\deep_research_public_preview` |
| 当前分支与代码基线 | `codex/graph-canvas-editor`；从 `d8caa38` 开始 |
| 计划提交 | `f8e4af7`：计划书与初始交接 |
| 实施分支 | 已创建，继续使用当前分支 |
| 实施进度 | M0 完成，可以进入 M1；M1–M4 尚未实施 |
| 已有证据 | M0 后端 20 项、画布浏览器 3 项通过；相关后端回归、类型检查、两种构建和静态检查通过，详见 [M0 验证记录](graph-canvas-editor-m0-results.md) |
| 尚缺证据 | 正式事务与协议、保存／发布／执行闭环、不同模型／Skills 与流程的组合矩阵、性能、真实模型业务验收 |
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

### 下一轮：M1 契约与交互设计

1. 冻结定义、展示数据、草稿、不可变修订及 thread 绑定的 schema；核心运行节点保留稳定名称。
2. 明确节点输入输出、可写字段、模型角色、reducer 处理与合法拓扑，设计结构化校验问题协议。
3. 设计保存版本冲突、发布幂等，以及修订／配置／受理意图同事务持久化；新字段仅在存在时影响旧摘要。
4. 固定图工厂的执行／观察行为与缺失实现的处置，沿用三个安全恢复边界；M0 无绑定原生请求会形成 error run，正式入口须明确受理前校验。
5. 设计完整编辑页和验收用例。原型入口 `/m0/workflow.html` 只验证基础交互，不包含保存、发布或真实执行选择。

M3 生产执行接入通过验收前，不声明生产 `workflow_execution_version`；原型 `/m0` 测试路由不加入生产服务。下一阶段优先读取 M0 记录的“进入 M1 的决定与边界”。

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
