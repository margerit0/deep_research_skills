# 星图工作台后端接口约定 · v1

本轮使用 `langgraph.json` 注册的 `research_agent_full`。只新增只读的 `/atlas/config`；会话、运行和检查点继续使用 LangGraph 原生 HTTP API。前端不拥有模型、Tavily 或 LangSmith 凭据。

## 标识及生命周期

| 标识                              | 所属层                    | 规则                                                   |
| --------------------------------- | ------------------------- | ------------------------------------------------------ |
| `Thread.id` / `live.threadId`     | 工作台 / LangGraph thread | 新真实会话使用同一个 UUID，首次发送才创建服务端 thread |
| `LiveResearch.id` / `research_id` | 一轮逻辑研究              | 首问与所有澄清回答保持不变；终态后新问题换一个 UUID    |
| `LiveTurn.id` / `turn_id`         | 一次用户提交              | 每次回答一个 UUID，同时用作 HumanMessage.id            |
| `LiveTurn.runId` / `run_id`       | 一次 LangGraph 执行       | 服务端生成；一轮逻辑研究可有多次 run                   |
| `report_research_id`              | 报告归属                  | 只有与当前研究标识相等，且业务状态正确，报告才可展示   |

所有标识和用户输入在发送网络请求前持久化。创建 thread 使用 `if_exists: do_nothing`；创建 run 使用 `multitask_strategy: reject`，禁止并发排队修改同一 thread。浏览器单次提交也有内存锁。

原生 run 创建接口不接受客户端指定 `run_id`。因此客户端把提交标识保存到 run metadata，响应丢失时以 `atlas_research_id` + `atlas_turn_id` 回查。刷新、定时轮询、“重新读取状态”均不会再次 POST 创建 run。尚无法确认的提交保持锁定，用户可新建另一个会话；本轮不承诺断网后的自动重发或跨标签页 exactly-once。

## HTTP 请求

本地默认访问前端 `/api`，由 Vite 转发到 `http://127.0.0.1:2024`。以下为转发后的 API 路径。

| 方法与路径                                                                                    | 用途                                                |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `GET /atlas/config`                                                                           | 契约版本、图 ID、六个实际模型角色、自动 Skills 能力 |
| `POST /threads`                                                                               | 指定 thread UUID 创建或取回 thread                  |
| `POST /threads/{thread_id}/runs`                                                              | 首问或同批次的澄清回答，创建后台执行                |
| `GET /threads/{thread_id}/runs/{run_id}`                                                      | 回读已知运行的执行状态                              |
| `GET /threads/{thread_id}/runs?limit=100&offset=...`                                          | 丢失响应后按 metadata 查找原提交，支持分页          |
| `GET /threads/{thread_id}/state`                                                              | 读取最新检查点，不依赖浏览器是否一直打开            |
| `GET /threads/{thread_id}/runs/{run_id}/stream?stream_mode=custom&cancel_on_disconnect=false` | 观察已创建运行的研究员事件，不启动或取消研究        |

创建 run 的示例（所有 ID 为示意值）：

```json
{
  "assistant_id": "research_agent_full",
  "input": {
    "research_id": "research-uuid",
    "turn_id": "turn-uuid",
    "messages": [{ "type": "human", "id": "turn-uuid", "content": "研究问题或澄清回答" }]
  },
  "metadata": {
    "atlas_research_id": "research-uuid",
    "atlas_turn_id": "turn-uuid"
  },
  "multitask_strategy": "reject",
  "if_not_exists": "reject",
  "durability": "sync",
  "stream_mode": ["custom"],
  "stream_resumable": true
}
```

澄清采用同一个 thread 的新 run、新 HumanMessage；不是 `Command(resume=...)`，因为现有 `clarify_with_user` 用 `goto=END` 等待回答。本轮请求不传模型 / Skills 覆盖参数。

`GET /atlas/config` 返回 `contract_version: 1`、`graph_id: research_agent_full`、`model_selection: server`、`skills_mode: auto`。支持研究员事件时另有 `research_events_version: 1`，客户端才在上述 POST 中增加 `stream_mode` 和 `stream_resumable`。旧服务没有此能力字段时继续使用检查点模式。

`models` 只包含 `role`、`model`、`provider`、`max_tokens`，来自已经构造的模型快照，不是重新猜测环境配置；模型未就绪返回 503。既不返回 API key，也不返回提供商 base URL。

## 图状态

| 字段                                   | 说明                                                           |
| -------------------------------------- | -------------------------------------------------------------- |
| `active_research_id`, `active_turn_id` | 当前检查点已接受并开始处理的研究 / 提交标识                    |
| `research_status`                      | `running`、`awaiting_input`、`succeeded`、`failed`、`partial`  |
| `research_phase`                       | `clarify`、`brief`、`research`、`writing`、`complete`          |
| `effective_config`                     | 本次执行的实际模型及自动 Skills 配置快照                       |
| `messages`                             | 本轮对话；最终报告是命名为 `final_report` 的 AIMessage         |
| `research_brief`                       | 实际生成的研究简报                                             |
| `notes`, `raw_notes`                   | 有效研究笔记与原始材料；原始材料不进入前端本地存储             |
| `sources`                              | `{title, url}[]`，从 `tavily_search` 工具输出提取并按 URL 去重 |
| `supervisor_status`, `research_errors` | 研究子图完成情况与安全错误摘要 `{code, message, node}`         |
| `final_report`, `report_research_id`   | 报告正文及归属研究                                             |
| `research_events`                      | 本次提交的安全研究员事件；研究子流程返回时写入父图检查点       |

前端先核对 run 的 thread ID 和 metadata，再核对检查点的 active research / turn。LangGraph run 的 `pending/running` 表示执行中；`success` 仍要检查业务状态。原生 `error/timeout/interrupted` 优先于检查点中的旧状态，显示失败或带已有笔记的部分完成。

澄清问题返回后业务状态为 `awaiting_input`。只有业务状态为 `succeeded`、报告正文非空且归属正确，才能显示完整成功；`partial` 可以有带明确提示的报告，也可以只有已保留的研究笔记。缺少来源时标为部分完成，不能宣称报告完整。

新研究进入 `prepare_research` 时用 `Overwrite` 清空带 reducer 的 `notes`、`raw_notes`、`supervisor_messages`，重置研究轮次、简报、报告、来源和错误。澄清续问保留同批次消息；新批次的模型上下文仅保留新的用户问题，旧报告只留在工作台历史中。对已结束的同一个 turn 重复执行，图入口直接结束，不再次调用模型。

`supervisor_tools` 只将有效 `ConductResearch` 结果用于最终笔记，排除思考工具及 `## 研究未完成` 标记。并行研究使用独立异常结果收集，保留成功的兄弟任务；没有有效笔记时直接失败，有部分错误时报告必须标为部分完成。写作异常或空输出不会抹掉已有笔记。

共享 `structured_output_fallback.py` 及 Qwen `/no_think` 负载诊断保持原实现。原生 API 或提供商错误体不直接展示到前端；凭据、网关响应和原始工具跟踪不写入前端会话缓存。

## 研究员事件 · v1

完整图在 `supervisor_subgraph` 为本次研究建立独立记录器，通过 ContextVar 传入并行研究任务和同步工具线程。记录器同时调用 LangGraph 的 `get_stream_writer()` 和收集检查点记录；并行失败也保留已经发出的安全事件。该机制不向模型提示词或运行配置注入回调，不改变独立研究员图的评估输出。

原生 SSE 的事件名为 `custom`，`data` 是下列对象；SSE 自身的 `id` 是原生缓冲游标，与正文事件 UUID 分开：

```json
{
  "type": "atlas.research_event",
  "event": {
    "version": 1,
    "id": "0eeedc22-b9c8-41b4-80bd-967ad44e2c19",
    "research_id": "research-uuid",
    "turn_id": "turn-uuid",
    "sequence": 3,
    "at": "2026-10-10T15:00:00+00:00",
    "task_id": "35748ec4-cf1d-58d5-bcd7-184646efbdc9",
    "round": 1,
    "kind": "tool_started",
    "elapsed_ms": 1250,
    "tool": "tavily_search",
    "query": "Python 3.13 free threading documentation"
  }
}
```

- `research_id` / `turn_id` 必须与正在观察的 run 对应；客户端还限制所属 thread / run，不接受旧研究或旧澄清提交的事件。
- `id` 用于去重，`sequence` 是本次研究子流程内的统一顺序；`at` 为后端 UTC 时间。`elapsed_ms` 从该任务委派开始用单调时钟计量，界面不编造运行秒表。
- `task_id` 由研究、提交、协调轮次与工具调用标识生成。每次实际委派展示独立节点，后续轮次不会覆盖先前任务。`round` 是协调器的决策轮次，包含未委派任务的决策，因此可跳号。
- 事件类型为 `delegated`、`model_started/finished/failed`、`tool_started/finished/failed`、`compression_started/finished/failed`、`completed`、`failed`。单个工具返回不代表研究员完成，SSE 结束也不代表研究成功。
- `delegated.topic` 保存实际任务；工具只允许公开搜索 `query` 或 Skills 名称。检索完成可带 `sources` / `source_count`，任务完成可带压缩笔记 `output`。不发送模型推理文本、Skills 正文、原始搜索正文、异常响应或凭据。任务 / 查询 / 笔记分别限 2000 / 1000 / 8000 字符，截断有明确标记；单事件最多附 50 个来源。

客户端先用 `Last-Event-ID: -1` 读取当前 run 可用的缓冲，短暂断线后使用内存中的最新游标重连；刷新后重新读取可用缓冲，并按事件 UUID 去重。浏览器缓存扩展 `LiveResearch.events`，旧会话缺少字段时默认为空。未知事件版本或无效自定义载荷不会阻止报告回读。

研究员事件更新节点和检查器，不修改业务成功状态。阶段、简报和报告继续以 run + checkpoint 回读为准；事件连接失败不会取消运行或 POST 重发。运行已结束却缺少任务终态时，节点显示“完成状态未确认”。

## 本轮恢复边界

状态每 2 秒回读；刷新、切换会话、窗口重新聚焦或网络恢复时也会读取。后台真实研究可在用户查看另一会话或演示时继续完成并接收事件。界面保留四个主阶段，研究员节点由实际委派动态加入；主阶段“回读”记录与后端研究员时间线分别保留。

旧版 `atlas-workspace:v1` 数据保持兼容；没有 `source` 的旧会话按模拟数据解释。新真实会话单独存储 `live` 映射和报告缓存。服务端会话不存在、接口不可达或提交结果不明时保留本地内容并停止新提交，不自动创建替代 thread。清除浏览器存储后，本轮没有按账号重新发现远端会话的功能。

LangGraph dev 使用本机持久化目录 `.langgraph_api/`。研究子流程返回时才将完整事件列表写入父图检查点；原生事件缓冲依赖服务端保留策略，进程重启可能丢失。进程在子流程中途退出且浏览器未收到的事件，仍可能无法恢复。不要把已有缓冲回读理解为服务器重装、目录丢失、跨设备或任意中断后的完整恢复。本轮不提供 token 流重放、自动重试不明提交或多用户权限管理。

## 原生 API 的可复现替身验证

普通 `npm test` 使用 HTTP 替身和演示数据，不调用真实模型。要同时验证原生 LangGraph API、真实图节点及浏览器，在根目录启动专用测试服务：

```powershell
$env:PYTHONUTF8 = '1'
uv run --locked --extra dev langgraph dev --config tests/atlas-langgraph.json --no-browser --no-reload --allow-blocking --port 2025
```

该配置不加载生产 `.env`，模型和搜索是 `tests/atlas_fixture_graph.py` 的确定性替身，并禁用文件持久化。在另一终端启动专用前端（Windows 下显式保留此服务，避免测试器结束时 npm 子进程影响清理）：

```powershell
cd frontend
$env:ATLAS_BACKEND_URL = 'http://127.0.0.1:2025'
npm run dev -- --port 5175 --strictPort
```

再在前端目录运行：

```powershell
$env:ATLAS_TEST_PORT = '5175'
$env:ATLAS_API_FIXTURE = '1'
npm test -- tests/live-api.spec.ts --workers=1 --output test-results/native-fixture
```

该验收同时检查事件记录和原生 SSE 缓冲一致、研究员完成状态、检查点的研究 / 提交 / 报告归属，以及服务端实际只有两个 run；不会只统计浏览器 POST 数。

真实模型联调使用正常后端与前端，清除 `ATLAS_API_FIXTURE`，显式设置 `$env:ATLAS_LIVE = '1'` 和 `$env:NO_PROXY = '*'` 再运行同一测试。此模式调用模型和 Tavily，产生真实费用；测试要求完成澄清、补充回答、报告与来源，并在刷新后仍只有两次运行提交。供应商问题按用户要求暂缓，当前未执行完整真实联调；不能将替身结果记为真实联调成功。
