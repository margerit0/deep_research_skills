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

| 方法与路径                                           | 用途                                                |
| ---------------------------------------------------- | --------------------------------------------------- |
| `GET /atlas/config`                                  | 契约版本、图 ID、六个实际模型角色、自动 Skills 能力 |
| `POST /threads`                                      | 指定 thread UUID 创建或取回 thread                  |
| `POST /threads/{thread_id}/runs`                     | 首问或同批次的澄清回答，创建后台执行                |
| `GET /threads/{thread_id}/runs/{run_id}`             | 回读已知运行的执行状态                              |
| `GET /threads/{thread_id}/runs?limit=100&offset=...` | 丢失响应后按 metadata 查找原提交，支持分页          |
| `GET /threads/{thread_id}/state`                     | 读取最新检查点，不依赖浏览器是否一直打开            |

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
  "durability": "sync"
}
```

澄清采用同一个 thread 的新 run、新 HumanMessage；不是 `Command(resume=...)`，因为现有 `clarify_with_user` 用 `goto=END` 等待回答。本轮请求不传模型 / Skills 覆盖参数。

`GET /atlas/config` 返回 `contract_version: 1`、`graph_id: research_agent_full`、`model_selection: server`、`skills_mode: auto`。`models` 只包含 `role`、`model`、`provider`、`max_tokens`，来自已经构造的模型快照，不是重新猜测环境配置；模型未就绪返回 503。既不返回 API key，也不返回提供商 base URL。

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

前端先核对 run 的 thread ID 和 metadata，再核对检查点的 active research / turn。LangGraph run 的 `pending/running` 表示执行中；`success` 仍要检查业务状态。原生 `error/timeout/interrupted` 优先于检查点中的旧状态，显示失败或带已有笔记的部分完成。

澄清问题返回后业务状态为 `awaiting_input`。只有业务状态为 `succeeded`、报告正文非空且归属正确，才能显示完整成功；`partial` 可以有带明确提示的报告，也可以只有已保留的研究笔记。缺少来源时标为部分完成，不能宣称报告完整。

新研究进入 `prepare_research` 时用 `Overwrite` 清空带 reducer 的 `notes`、`raw_notes`、`supervisor_messages`，重置研究轮次、简报、报告、来源和错误。澄清续问保留同批次消息；新批次的模型上下文仅保留新的用户问题，旧报告只留在工作台历史中。对已结束的同一个 turn 重复执行，图入口直接结束，不再次调用模型。

`supervisor_tools` 只将有效 `ConductResearch` 结果用于最终笔记，排除思考工具及 `## 研究未完成` 标记。并行研究使用独立异常结果收集，保留成功的兄弟任务；没有有效笔记时直接失败，有部分错误时报告必须标为部分完成。写作异常或空输出不会抹掉已有笔记。

共享 `structured_output_fallback.py` 及 Qwen `/no_think` 负载诊断保持原实现。原生 API 或提供商错误体不直接展示到前端；凭据、网关响应和原始工具跟踪不写入前端会话缓存。

## 本轮恢复边界

状态每 2 秒回读；刷新、切换会话、窗口重新聚焦或网络恢复时也会读取。后台真实研究可在用户查看另一会话或演示时继续完成。界面展示四个主阶段；检查器执行记录是带本地观察时间的状态回读，不是研究员事件流。

旧版 `atlas-workspace:v1` 数据保持兼容；没有 `source` 的旧会话按模拟数据解释。新真实会话单独存储 `live` 映射和报告缓存。服务端会话不存在、接口不可达或提交结果不明时保留本地内容并停止新提交，不自动创建替代 thread。清除浏览器存储后，本轮没有按账号重新发现远端会话的功能。

LangGraph dev 使用本机持久化目录 `.langgraph_api/`。不要把浏览器刷新恢复理解为服务器重装、目录丢失、跨设备或任意中断后的完整恢复。本轮不提供 token 流重放、自动重试不明提交或多用户权限管理。

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

真实模型联调使用正常后端与前端，清除 `ATLAS_API_FIXTURE`，显式设置 `$env:ATLAS_LIVE = '1'` 再运行同一测试。此模式调用模型和 Tavily，产生真实费用；测试要求完成澄清、补充回答、报告与来源，并在刷新后仍只有两次运行提交。不能将替身结果记为真实联调成功。
