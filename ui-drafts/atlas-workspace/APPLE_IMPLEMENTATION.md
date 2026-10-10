# Apple 银白：前端实施交接

更新：2026-10-10。项目：`D:/deep_research_public_preview`。

## 已确认的决定与当前状态

- 用户已选择「星图工作台」的 **Apple 银白** 配色，计划在新会话实施。继续沿用已确认的对话布局、可收起流程图和 Codex 风格紧凑模型/Skills 菜单。
- 配色设计与校对材料已提交为 `e99140f`（`design: add Apple Claude and forest colorway studies`）。上一版银灰玻璃基线为 `712bb45`。
- 当前只有 HTML 设计稿和本地演示交互，尚无正式 React 前端，也未接入真实研究运行。这次交接没有启动前端开发。
- 下面的实施分期是建议；新会话的用户指令决定本次开发范围。建议第一轮完成 React 界面和本地交互，再单独接入后端。

## 首轮必读材料

按用途读取，先看源码与图片，不必读取三套生成副本：

| 材料 | 用途 |
| --- | --- |
| [根目录 AGENTS.md](../../AGENTS.md) | 编辑、环境与后端维护约定 |
| [完整设计交接](HANDOFF.md) | 已确定的交互、图结构和演示边界；历史上的“只改设计稿”约束针对当时任务 |
| [主源码](atlas-conversation-workspace.html) | 颜色、尺寸、布局与本地行为；根节点 `data-palette="apple"` |
| [Apple 独立预览](preview/atlas-apple-preview.html) | 离线操作和观察；包含宿主包装，不是正式应用代码 |
| [Apple 浅色桌面](references/atlas-colorway-apple-light-1024.png) | 主视觉基准 |
| [Apple 深色桌面](references/atlas-colorway-apple-dark-1024.png) | 深色基准 |
| [Apple 窄屏](references/atlas-colorway-apple-light-390.png) | 响应式基准 |
| [模型菜单](references/atlas-colorway-apple-model.png) / [Skills 菜单](references/atlas-colorway-apple-skill.png) | 紧凑实色菜单基准 |
| [维护说明](../../docs/maintenance.md) / [架构约定](../../docs/architecture-decisions.md) | 现有后端边界与真实研究图结构 |

检查器的输入输出和执行记录还可参考 `references/atlas-glass-inspector-io.png` 与 `references/atlas-glass-inspector-events.png`。旧的 `atlas-pickers-*` 仅用于菜单历史参考；Claude 与青绿稿保留为备选记录，不是本次实现目标。

## 需要保留的设计与行为

- 左侧最近对话，中间对话与底部输入框，右侧运行图谱。收起图谱后，聊天内容居中并限制阅读宽度。
- Apple 银白色板来自源码中的 `--cw-*`，浅色银白/石墨/清蓝，深色石墨灰。保留悬浮面板、克制的玻璃反光；正文不模糊。不要为迁移组件库而改版。
- 默认图谱宽 350 px、节点圆角 14 px、玻璃模糊 28 px。模型/Skills 按钮桌面高 28 px，菜单宽约 232 px、圆角 11 px、实色底，向上展开；触屏目标至少 44 px。保留箭头、Skills 图标、选中标记、键盘选择、Esc 返回焦点及点击外部关闭。
- 输入支持 Enter 发送、Shift+Enter 换行，中文输入法组词期间不触发发送。每条发送消息记录当时的模型与 Skill；修改输入框选择不能改写已开始运行的配置。
- 节点检查器支持概览、输入/输出、执行记录，保持节点切换、独立收起与焦点操作。等待中节点不展示已完成输出。
- 深浅色、320–1440 px 响应式布局，以及减少动态效果/减少透明度偏好。

图结构按实际代码理解：完整图是 `clarify_with_user → write_research_brief → supervisor_subgraph → final_report_generation`。界面中的三个研究员是演示子图视图，真实研究员数量与多轮委派不能硬编码为始终三个。研究员内部 `llm_call → tool_node → llm_call` 循环后进入 `compress_research`，不要把方法论加载、检索、反思画成新的全局节点。

## 建议实施分期

### 第一阶段：React 界面与本地交互

先检查新会话中的仓库状态与已有前端目录。如果仍无前端工程，可在 `frontend/` 建立 React + TypeScript 工程；具体构建工具和依赖按实际环境选择，并提交锁文件。

将对话导航、消息区、输入框及两个菜单、图谱、节点检查器拆成可维护组件。使用独立的本地演示数据与状态层，让后续真实运行数据可以替换演示来源。保留设计稿作为视觉参照，不直接将完整预览包装嵌入 iframe 作为正式实现。

`window.openai.widgetState`、`setWidgetState`、`Tweak`、`viz-carousel` 都属于设计预览宿主。正式前端用自己的状态管理与持久化；不依赖宿主注入 Lucide，图标应随应用正常加载。保留图标的外观与可用性，不要求照搬 PNG 遮罩实现。

这一阶段用明确标识的演示数据完成行为验证，模型选择和 Skills 选择仍是本地状态，不调用真实模型、检索服务或修改 Python 研究逻辑。

### 第二阶段：真实后端接入

在新会话明确包含该阶段时实施。先读取 `langgraph.json` 以及 `src/deep_research/` 下的 `research_agent_full.py`、`research_agent_scope.py`、`multi_agent_supervisor.py`、`research_agent_skills.py`、相关 `state_*.py`、`model_config.py` 和 `skills_loader.py`，确定实际输入、状态与事件映射。

连接目标是现有 LangGraph API，完整图 ID 为 `research_agent_full`。真实的会话历史、流式输出、澄清与继续研究、错误/中断/完成状态以及研究员进度，必须按实际协议接入。不能把本地“演示下一步”当作运行事件。

按次模型切换与手选 Skills 尚未接入后端，需要单独设计其配置契约。后端模型由环境变量按角色构建，部分在导入时实例化；Skills 当前由模型按需加载。示例菜单不证明服务端已支持相应模型。凭据保持在后端 `.env`，不要复制到前端或交接材料。

## 首阶段交付与验收

- 能独立启动的 React 界面、启动命令、依赖锁文件及简短运行说明。
- 与 Apple 截图对照检查桌面、390 px/320 px 窄屏和深浅色；没有横向溢出，菜单不越界，收起图谱后布局正常。
- 验证消息发送、输入法、模型/Skills 菜单、运行配置快照、图谱与检查器、本地会话恢复等关键行为；运行实际采用的构建、类型检查与必要交互检查。
- 原设计验证记录可参考 `references/atlas-glass-verification.json`、`references/atlas-colorways-verification.json`、`references/atlas-picker-icons-verification.json`；它们不能替代对新 React 代码的验证。
- 清楚报告已经完成的功能和仍然使用模拟数据的部分。

## 可粘贴到新会话的请求（建议首阶段）

```text
项目目录：D:\deep_research_public_preview

我已选定「星图工作台」的 Apple 银白方案。请先读取：
D:\deep_research_public_preview\ui-drafts\atlas-workspace\APPLE_IMPLEMENTATION.md
以及其中列出的主 HTML、Apple 参考图、AGENTS.md 和必要交接材料。

现在开始正式 React + TypeScript 前端实现。第一阶段完成界面与本地交互，使用模拟数据，暂不接入真实后端。保留已有对话布局、可收起流程图、节点检查器、Codex 风格的紧凑实色模型/Skills 菜单，以及 Apple 银白的深浅色与玻璃效果。

先检查仓库状态与已有工程，给出简短实施安排后直接开发。在没有现成前端工程时放在 frontend/。不要重新设计配色，也不要依赖设计预览宿主。完成后运行构建和必要交互校对，对照参考图检查桌面与窄屏，提供启动方式和仍使用模拟数据的说明。
```

上下文组织参考：[OpenAI 官方 Prompting 文档](https://learn.chatgpt.com/docs/prompting)。这里将目标、相关文件、参考图、边界和验收方式集中说明；新会话仍以用户当次要求为准。
