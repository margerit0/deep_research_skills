# 星图工作台 · Apple 银白

独立的 React + TypeScript + Vite 前端。真实模式连接现有 LangGraph API 的 `research_agent_full`，支持澄清续问、研究简报、研究、报告和检索来源。原有 Apple 银白 / 石墨界面和全流程动画演示继续保留。

## 启动

需要 Python 开发环境、Node.js 22.12+（本次使用 22.17.0）和 npm。先在一个终端启动后端：

```powershell
cd D:\deep_research_public_preview
$env:PYTHONUTF8 = '1'
$env:NO_PROXY = '*'
uv sync --locked --extra dev
uv run --locked --extra dev langgraph dev --no-browser --allow-blocking
```

模型、搜索和追踪凭据只保存在项目根目录的后端 `.env`。首次配置参照根目录 `.env.example`；LangGraph 在导入模型模块前加载它。修改模型或凭据后重启后端。本地请求需要直连时，在启动后端的终端设置 `$env:NO_PROXY = '*'`；可在后端 `.env` 保存 `NO_PROXY=*`。这也让模型、Tavily 和追踪请求直连。

然后在另一个终端启动前端：

```powershell
cd D:\deep_research_public_preview\frontend
npm ci
npm run dev
```

打开终端显示的地址，默认是 http://127.0.0.1:5173。依赖版本固定在 `package-lock.json`。Vite 将同站点 `/api` 请求转发至 `http://127.0.0.1:2024`，开发与生产预览都支持此代理。前端不读取根目录 `.env`。

后端端口不同可将 `frontend/.env.example` 复制为 `frontend/.env.local`，修改 `ATLAS_BACKEND_URL`。部署 `dist/` 时需要站点自己的 `/api` 反向代理，或者构建时设置 `VITE_LANGGRAPH_API_URL` 并在 API 端配置 CORS。前端环境文件只放地址，不放 API key；本轮面向本地开发，没有新增公网登录和多用户权限系统。

```powershell
npm run build       # 应用、配置、测试的 TypeScript 检查，然后生成 dist/
npm run preview     # 在本机预览生产构建，默认端口 4173
npm run typecheck
npm run test        # Playwright：使用本机已安装的 Google Chrome
npm run format:check
```

测试使用独立的临时浏览器上下文，不读取日常 Chrome 用户数据。测试自动启动 5173 端口的开发服务，也可复用已运行的服务。验收记录见 [docs/verification.md](docs/verification.md)。

## 完成一次真实研究

首次打开默认进入空白的真实会话。历史模拟会话仍可在侧栏查看，顶部的 **真实研究** 按钮可回到真实入口。会话的数据来源固定；在模拟会话里发送或新建仍是本地模拟，页面会标明“模拟数据”。

1. 在真实会话输入研究问题。模型按钮展示后端六个角色的实际配置，Skills 固定自动；本轮没有按次模型或手选 Skills 参数。
2. 若助手提出澄清问题，界面显示“等待补充”。在同一输入框回答，继续同一轮研究、同一个服务端 thread；一次 LangGraph run 的结束不代表报告已完成。
3. 查看实际研究简报、阶段状态和最终 Markdown 报告。来源列表来自搜索工具返回值，报告引用编号以正文为准。研究员节点由实际委派事件生成，展示协调轮次、检索、Skills 加载、笔记压缩及完成 / 失败；检查器中的任务、查询、笔记与耗时均来自后端。
4. 成功、失败和部分完成分别显示。部分研究员失败时保留有效成果；写作失败时展示已有笔记及来源。没有有效研究结果时不调用报告模型。
5. 刷新后回读当前运行与检查点，等待回读完成再发送。终态后再次提交会在同一会话创建新的研究批次，历史报告保留在本地记录中。

接口和状态映射详见 [后端接口约定](docs/backend-contract.md)。阶段状态每 2 秒回读；研究员进度通过原生 SSE 事件流更新。主阶段的“回读”记录使用浏览器观察时间，研究员记录使用后端时间，耗时截至最近一条后端事件。点击“定位当前”可定位正在执行的研究任务。

事件流中断时会提示“事件重连中”，仍继续回读阶段和结果；接收事件不会再次提交研究。安全事件在发送前写入本地 SQLite 日志，刷新或后端重启后按原有归属分页补回，事件与恢复位置一起保存。连接失败以最高 30 秒的退避重试，聚焦或网络恢复时及时对账。

读取暂时失败会提示重试；日志过期、丢失或缺少终态时显示记录不完整。后端重启后若旧任务没有终态证据，节点显示“完成状态未确认”；原生 run 仍可能显示运行中，这不证明执行已经继续。回放只恢复观察记录，保留已确认的笔记、来源和报告，不自动重新提交或恢复执行。

更新后需重启后端，`/atlas/config` 的 `research_events_version: 1` 表示支持事件协议，`research_event_replay_version: 1` 表示启用持久回放。旧后端仍可显示主阶段和报告，不会生成虚构研究员。供应商问题按用户要求暂缓处理，当前真实模型完整闭环仍待验收；事件与界面验证使用明确标注的替身，结果见验收记录。

默认日志路径为后端工作目录的 `.langgraph_api/atlas-events.sqlite3`，目录需可写并在重启时保留。后端 `.env` 可选配置 `ATLAS_EVENT_DB` 和 `ATLAS_EVENT_RETENTION_DAYS`（默认 30，范围 1–3650）；保留期从最后写入开始计算。独立评估不写此日志，关闭文件持久化的普通替身默认也不写。当前保证适用于单进程本地服务。

发送前会先保存提交标识；网络响应丢失时按标识查找已有运行，不会自动重发。无法确认是否接受、或服务端会话已不存在时，可以“重新读取状态”或新建研究，旧内容继续保留。浏览器存储不可写时允许保存内存草稿，但禁用真实提交，以免刷新丢失提交标识。多标签页协同编辑和跨设备会话发现尚未实现。

## 全流程动画演示

点击页面顶部的 **全流程演示**，即可播放约 65 秒、18 幕的独立示例：模型与 Skills 菜单 → 问题输入 → 助手逐字回复 → 确认范围与生成简报 → 三个研究员并行检索 → 输入输出与执行记录 → 汇总 → 报告逐字生成 → 图谱收放与另一种外观。

播放器支持暂停 / 继续、上一幕 / 下一幕、点击进度条跳转、1× / 1.5× / 2×、从头重播与退出。节点脉冲、完成标记、连线流动、消息和报告入场、检查器页签切换及玻璃反光都包含在流程中。鼠标经过玻璃面板仍可体验原有的边缘跟随反光。

点击节点、菜单或修改外观会暂停，方便自由检查；继续播放后按脚本进入下一幕。切换浏览器标签页会自动暂停，回来后手动继续。窄屏会将当前演示内容滚动到可见区域，播放器保持可用。开启系统“减少动态效果”时关闭动画、直接显示完整文本，仍能体验全部步骤。

演示使用独立的内存会话，不写入本地会话存储。退出或刷新恢复原有会话、草稿、模型 / Skills 配置与外观；切换到原对话或新建研究会结束演示。演示输入框只读，退出后可正常输入。演示的检索、证据和报告都是模拟，不会创建后端运行。进入演示前已启动的真实研究继续在后端执行，工作台仍会回读它的状态，退出后可看到结果。

若已有开发服务占用端口，可以为验收指定独立端口：

```powershell
$env:ATLAS_TEST_PORT = '5174'
npm test
```

遇到开发服务热更新后仍显示旧模块或空模块时，重启该开发服务再刷新页面。Vite 已忽略 `test-results/` 与 `playwright-report/` 的文件监听，生成测试报告不会触发工作台重新加载。

## 保留的模拟会话与交互

- 新建和切换多个对话，分别保存草稿、消息与运行历史；刷新恢复。
- Enter 发送、Shift+Enter 换行、输入法组词保护。每条发送消息保存独立的模型与 Skills 配置；查看旧消息的“当前步骤”可回到对应运行。
- 模型 / Skills 紧凑实色菜单：向上展开、选中标记、方向键及 Home/End、Esc 关闭并返回焦点、点击外部关闭。触屏目标至少 44 px。
- 可收起的运行图谱、当前步骤定位、节点检查器的概览 / 输入输出 / 执行记录。页签支持左右方向键及 Home/End；Esc 收起检查器并返回对应节点。
- “演示下一步”推进确认范围 → 并行研究 → 报告写作 → 完成。“重新演示”重置所选运行的阶段，保留它原来的配置。待执行节点没有结果或执行记录。
- 右上角外观按钮依次切换跟随系统、浅色、深色。保留 Apple 银白 / 石墨色板、28 px 模糊和边缘反光；遵循减少动态效果、减少透明度偏好。
- 桌面为侧栏、对话、350 px 图谱；收起图谱后对话居中且限宽 720 px。窄屏图谱排在对话下方，左上角星号打开最近对话抽屉。

会话保存在当前浏览器、当前站点的 `localStorage`（键 `atlas-workspace:v1`）。存储结构采用兼容扩展，旧模拟会话、草稿和配置可继续恢复。开发端口与生产预览端口的会话互不共享。损坏数据回退为新的真实会话和内置示例；存储不可用或容量耗尽时会显示提示。

## 数据来源边界

模拟会话和全流程演示里的模型 / Skills 菜单只是示例，不代表真实后端支持按次切换。其回复、阶段、耗时、来源数量、节点输入输出、事件与报告都来自 `mock.ts` / `demo.ts`。真实会话单独使用 `live` 状态和 LangGraph 接口，绝不以模拟结果补齐缺失数据。

模拟示例沿用三个研究员，模拟新问题使用两个研究员。真实图谱保留四个主阶段，只根据实际事件增加研究任务节点；后续协调轮次的委派有独立任务标识，不从示例推断研究员数量。缺少完成事件的任务不会因为运行结束就显示完成。

完整图仍按 `clarify_with_user → write_research_brief → supervisor_subgraph → final_report_generation` 展示。研究员内部的模型 / 工具循环和 `compress_research` 保留在检查器里。

## 代码结构

| 位置                                                   | 职责                                                  |
| ------------------------------------------------------ | ----------------------------------------------------- |
| `src/components/`                                      | 导航、消息、输入框、菜单、图谱、节点检查器            |
| `src/state/useWorkspace.ts`                            | 不可变状态转换、会话选择、版本化本地存储与恢复        |
| `src/state/useLiveResearch.ts`                         | 提交记录、后台运行回读、澄清续问与网络状态            |
| `src/api/langgraph.ts`                                 | 配置和原生 LangGraph thread / run / state API         |
| `src/api/researchStream.ts`                            | 原生 custom SSE、UTF-8 分片与事件校验                 |
| `src/api/eventReplay.ts` / `src/data/eventRecovery.ts` | 持久事件分页校验、恢复作用域、恢复位置与退避          |
| `src/data/liveSchema.ts` / `live.ts`                   | 真实接口校验、状态映射及阶段节点适配                  |
| `src/data/researchEvents.ts`                           | 研究 / 提交归属、事件去重、实际研究员节点和时间线     |
| `src/components/LiveConversation.tsx`                  | 真实消息、报告、失败信息与检索来源                    |
| `src/components/BackendControls.tsx`                   | 后端实际模型与自动 Skills 展示                        |
| `src/state/useDemo.ts`                                 | 独立演示会话、可暂停时钟、播放控制及后台暂停          |
| `src/data/demo.ts`                                     | 18 幕脚本、逐字文本和演示节点视图                     |
| `src/components/DemoPlayer.tsx`                        | 演示播放器、章节导航与场景跟随                        |
| `src/data/schema.ts`                                   | 运行、节点、会话类型和存储校验                        |
| `src/data/mock.ts`                                     | 模拟运行、阶段与节点视图适配                          |
| `src/data/example-nodes.json`                          | 已确认示例中的静态数据                                |
| `src/apple.css`                                        | 从已确认主 HTML 提取的 Apple 色板与原始样式           |
| `src/app.css`                                          | 独立应用的滚动、窄屏导航与布局适配                    |
| `src/demo.css`                                         | 演示播放器、图谱 / 消息动效与减少动态效果适配         |
| `tests/workspace.spec.ts`                              | 行为与响应式浏览器验证                                |
| `tests/demo.spec.ts`                                   | 完整播放、时钟控制、会话隔离与窄屏演示验证            |
| `tests/live.spec.ts`                                   | 使用 HTTP 替身的真实模式浏览器回归                    |
| `tests/live-events.spec.ts`                            | 事件流、并行 / 多轮任务、刷新隔离与窄屏回归           |
| `tests/live-recovery.spec.ts`                          | 日志回放、断线刷新、存储失败、缺口和窄屏提示          |
| `tests/recovery-api.spec.ts`                           | 专用持久化后端在研究中停止、重启与事件回放验收        |
| `tests/live-api.spec.ts`                               | 显式启用的原生 LangGraph API / 真实模型联调           |
| `../tests/atlas_fixture_server.py`                     | 使用独立目录、明确关闭持久化的普通原生 API 替身启动器 |

`scripts/import-design.mjs` 记录一次性迁移方式。日常开发与构建不运行它；手动运行会重新生成 `apple.css` 和示例 JSON。应用不引用 `ui-drafts/`，也不依赖 `window.openai`、`Tweak`、`viz-carousel`、iframe 或宿主图标库。Lucide 图标随应用打包。

观察与记录恢复的原生 API 验收命令见 [接口约定](docs/backend-contract.md)，它使用独立的临时持久化目录。下一阶段按 [后续计划](docs/next-steps.md) 完成提交确认与执行中断恢复，再贯通按次模型 / Skills 和真实报告流式显示。供应商恢复后重跑真实研究闭环验收；服务端凭据继续留在后端 `.env`。
