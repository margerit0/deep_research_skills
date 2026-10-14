# 星图工作台后端接口约定 · v1

工作台使用 `langgraph.json` 注册的 `research_agent_full`。自定义接口提供配置、事件回放、幂等受理和受限执行恢复；会话、运行、检查点与 SSE 仍由 LangGraph 管理。前端不拥有模型、Tavily 或 LangSmith 凭据。

## 报告正文事件扩展 · 2026-10-14

`GET /atlas/config` 新增 `report_events_version: 1` 和可选 `report_event_replay_version: 1`。独立类型 `atlas.report_event` 与研究员 v1 共用原生 `custom` SSE 观察连接，不改变研究员事件格式。旧服务 / 缓存仍支持检查点模式；历史受理配置不增加字段，恢复旧配置的写作 run 时使用当前后端能力。

事件公共字段为 `version: 1`、事件 `id`、`thread_id`、`research_id`、`turn_id`、`run_id`、`attempt_id`、`writing_attempt_id`、单调 `sequence`、UTC `at`、UTF-8 字节 `offset`。原生 metadata 中没有受理 attempt 的旧 run 使用 run ID 作为该身份。四种类型：

- `started`：真正开始一次写作，offset 为 0，独立写作 UUID；同 run 中重写也更换 UUID。
- `delta`：`text` 是有界正文块；offset 为该块之前的 UTF-8 字节数。
- `failed`：本次生成失败，保留已收到的连续草稿，不包含原始异常。
- `finished`：模型输出结束，`sha256` 为去除首尾空白后的完整正文摘要；仍需终态检查点确认。

只从最终模型的文本内容提取正文，过滤推理 / 工具块、供应商元数据和跨分片秘密值。按约 150 毫秒或 2048 个 Python 字符合并，上限 1,000,000 字符。显式最多三次重新生成，SDK 请求重试单独计算；不依赖不会重试流的 `RunnableRetry`。取消与退出信号不重试，当前流关闭后直接传播，已收到的草稿保留。非流式独立模型只发布实际完整输出。

持久回放为 `GET /atlas/threads/{thread_id}/runs/{run_id}/report-events`，参数、分页位置、`missing/expired/gap/reset/sealed/unconfirmed_before_sequence` 沿用下方研究日志协议，但事件类型独立。使用单独的 `atlas-report-events.sqlite3`，默认与研究日志同目录，可设 `ATLAS_REPORT_EVENT_DB`；保留期沿用 `ATLAS_EVENT_RETENTION_DAYS`。写入先提交后发布，读取不启动运行。恢复写作使用新 run 的正文日志，原 `event_run_id` 仍指向检索记录。

浏览器按后端 / thread / research / turn / run / attempt 保存事件和回放位置，去重且只应用连续、offset 匹配的正文。失败草稿独立保留；日志替换建立新的活动记录。存储失败不推进持久化位置，旧进程缺少终态时停止显示为仍在写作。最终结果增加 `report_run_id`、`report_turn_id`、`report_attempt_id`、`report_writing_attempt_id`，匹配后以终态检查点完整正文校准；原生 success、SSE 结束和日志 sealed 都不是业务成功。

原生 `submission-api.spec.ts` 的 `report native` 用例在实际流式替身的首块之后停止服务，验证即时落盘、重启回放、浏览器恢复、固定配置、原检索事件 run、搜索 / 压缩不重跑，以及重复恢复零新增调用。沿用下方 1B 启动命令，可用 `--grep 'report native'` 单独运行。实现细节与真实 Kimi 验收边界见 [实施说明](report-streaming-plan.md) 和 [验收记录](verification.md)。

## 标识及生命周期

| 标识                              | 所属层                    | 规则                                                   |
| --------------------------------- | ------------------------- | ------------------------------------------------------ |
| `Thread.id` / `live.threadId`     | 工作台 / LangGraph thread | 新真实会话使用同一个 UUID，首次发送才创建服务端 thread |
| `LiveResearch.id` / `research_id` | 一轮逻辑研究              | 首问与所有澄清回答保持不变；终态后新问题换一个 UUID    |
| `LiveTurn.id` / `turn_id`         | 一次用户提交              | 每次回答一个 UUID，同时用作 HumanMessage.id            |
| `LiveTurn.runId` / `run_id`       | 当前执行尝试              | 服务端先生成并持久化；恢复尝试使用新的 run             |
| `attempt_id`                      | 提交 / 恢复尝试           | 初次受理等于 turn ID；每次恢复独立 UUID，相同请求重用  |
| `LiveTurn.eventRunId`             | 研究事件来源              | 写作恢复继续回放原检索 run；不误用新 run 的空事件日志  |
| `report_research_id`              | 报告归属                  | 只有与当前研究标识相等，且业务状态正确，报告才可展示   |

所有标识和用户输入在发送网络请求前持久化。创建 thread 使用 `if_exists: do_nothing`；创建 run 使用 `multitask_strategy: reject`，禁止并发排队修改同一 thread。浏览器单次提交也有内存锁。

原生 HTTP run 创建接口不接受客户端指定 `run_id`。1B 使用可选的 `submission_recovery_version: 1` 契约，由服务端持久化固定 UUID 后调用锁定版本的内部 `create_valid_run(run_id=...)`。旧提交、旧后端仍按 metadata 查找运行，不自动转为可重试操作。所有观察回读均不自动 POST 执行；新契约在经过对账后提供显式重试 / 恢复入口。

## HTTP 请求

### 按次配置扩展 · 2026-10-11

`GET /atlas/config` 新增可选 `configuration_version: 1` 和 `catalog`。目录中的 `models` 是现有六个后端角色定义去重后的 `{id, model, provider, max_tokens}`；`defaults` 将六个角色映射到 ID；`skills` 只含名称与描述。ID 对应不可变修订，浏览器不能指定模型名、网关地址或凭据。只有同时支持 `submission_recovery_version: 1` 的后端才在前端开放按次选择。

原受理 JSON 新增可选 `selection`：

```json
{
  "version": 1,
  "models": {
    "SCOPING": "<目录 ID>",
    "SUPERVISOR": "<目录 ID>",
    "RESEARCHER": "<目录 ID>",
    "SUMMARIZATION": "<目录 ID>",
    "COMPRESSION": "<目录 ID>",
    "FINAL_REPORT": "<目录 ID>"
  },
  "skills": { "mode": "manual", "allowed": ["academic-research"] }
}
```

自动模式为 `{"mode":"auto","allowed":[]}`；手选空集合表示禁止所有 Skills。六个角色必须齐全，未知 ID、未知 skill、重复 skill、未知版本和额外字段明确拒绝。新研究只能选当前目录；同研究的澄清沿用原选择，可使用已归档但不再是默认值的 ID。省略选择的新受理固定当时默认配置；已有旧受理内容和摘要不迁移重写。

选择保存到浏览器 `LiveTurn.selection` 和服务端不可变 payload。受理事务同时写入 `submission_configurations` 的公开快照；回执 `configuration` 与检查点 `effective_config` 使用同一份快照，包含选择、实际六个模型及 Skills 修订。重试先比较原 payload，不因当前目录变化改写内容。浏览器也校验回执和检查点的选择与原提交一致。

服务端配置归档默认为受理库同目录的 `atlas-configs.sqlite3`，可设 `ATLAS_CONFIG_DB`。归档保存模型名、提供商、原网关、token 上限、凭据环境变量引用和 Skills 正文；不保存凭据值，不向前端返回网关或正文。旧修订不自动清除。备份时一并保留配置归档、受理库、原生检查点与事件库。缺失或不兼容的修订不猜测成当前默认值；凭据仍从后端本地环境读取。

实际调用通过每个父节点的 ContextVar 作用域传给协调器、研究员和工具，网页摘要线程显式复制上下文。模型按角色 / 修订缓存，绑定工具和重试包装均独立；执行时不修改全局环境或全局模型。原共享限流器继续用于研究员、网页摘要与压缩；scoping 和 Qwen 网页摘要使用共享 JSON fallback / `/no_think`，其他网页摘要保留 `function_calling`。独立图与评估默认调用保持兼容。

恢复摘要原本就覆盖 `effective_config`，现在节点进入时还校验它与受理快照相等。恢复同时验证原检查点和归档修订，受理后再次退出也重新核对；始终 `input: null`。三个安全节点的白名单及当前模型调用可能重复的边界不变。

手选只限制“允许自动加载的集合”：提示词索引与 `load_skill` 正文都受限制，拒绝项产生失败事件，不计作成功加载。历史配置详情分别展示允许集合与事件中的实际成功加载列表；自动模式同样固定当时可用 Skills 的正文修订。

计划 2 的四项原生验收已加入原 `submission-api.spec.ts`，使用同一组启动命令，额外覆盖并发六角色 / Skills、澄清与默认值变化、创建前退出与写作恢复。每项均核对实际 run、持久调用计数和配置。旧客户端省略 `selection` 的测试继续保留；新客户端的重复请求需包含原 `LiveTurn.selection`。

本地默认访问前端 `/api`，由 Vite 转发到 `http://127.0.0.1:2024`。以下为转发后的 API 路径。

| 方法与路径                                                                                    | 用途                                                |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `GET /atlas/config`                                                                           | 契约版本、图 ID、六个实际模型角色、自动 Skills 能力 |
| `POST /threads`                                                                               | 指定 thread UUID 创建或取回 thread                  |
| `POST /threads/{thread_id}/runs`                                                              | 首问或同批次的澄清回答，创建后台执行                |
| `GET /threads/{thread_id}/runs/{run_id}`                                                      | 回读已知运行的执行状态                              |
| `GET /threads/{thread_id}/runs?limit=100&offset=...`                                          | 丢失响应后按 metadata 查找原提交，支持分页          |
| `GET /threads/{thread_id}/state`                                                              | 读取最新检查点，不依赖浏览器是否一直打开            |
| `GET /threads/{thread_id}/state/{checkpoint_id}`                                              | 回读已确认 turn 的固定终态检查点                    |
| `GET /threads/{thread_id}/runs/{run_id}/stream?stream_mode=custom&cancel_on_disconnect=false` | 观察已创建运行的研究员事件，不启动或取消研究        |
| `GET /atlas/threads/{thread_id}/runs/{run_id}/events`                                         | 分页回放持久化研究员事件，不创建或继续运行          |
| `POST /atlas/threads/{thread_id}/submissions/{turn_id}`                                       | 新提交或以原标识重试受理                            |
| `GET /atlas/threads/{thread_id}/submissions/{turn_id}`                                        | 对账受理、当前尝试、终态与恢复条件                  |
| `POST /atlas/threads/{thread_id}/submissions/{turn_id}/recoveries/{attempt_id}`               | 显式恢复已验证的父检查点，或重试同一恢复受理        |

旧契约直接创建 run 的示例（所有 ID 为示意值；新契约见下方 1B 章节）：

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

启用本地事件日志时另有 `research_event_replay_version: 1`。这是回放协议能力，不表示存储始终可写；读取失败会单独提示和重试。旧后端、旧配置快照未声明此能力时，仍可使用原生事件缓冲和检查点。

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
- `id` 用于去重，`sequence` 是所属 run 的业务事件顺序；日志可用时，同 run 再次进入研究子流程沿用序号。它与原生 SSE 游标分开保存。`at` 为后端 UTC 时间，`elapsed_ms` 从该任务委派开始用单调时钟计量。
- `task_id` 由研究、提交、本次子流程调用、协调轮次与工具调用标识生成。每次实际委派展示独立节点，再次进入子流程不会覆盖先前任务。`round` 是协调器的决策轮次，包含未委派任务的决策，因此可跳号。
- 事件类型为 `delegated`、`model_started/finished/failed`、`tool_started/finished/failed`、`compression_started/finished/failed`、`completed`、`failed`。单个工具返回不代表研究员完成，SSE 结束也不代表研究成功。
- `delegated.topic` 保存实际任务；工具只允许公开搜索 `query` 或 Skills 名称。检索完成可带 `sources` / `source_count`，任务完成可带压缩笔记 `output`。不发送模型推理文本、Skills 正文、原始搜索正文、异常响应或凭据。任务 / 查询 / 笔记分别限 2000 / 1000 / 8000 字符，截断有明确标记；单事件最多附 50 个来源。

客户端首次用 `Last-Event-ID: -1` 读取当前 run 可用的缓冲，此后将已应用事件与 SSE 游标一起保存。刷新后使用同一作用域的已保存游标；缓冲游标被服务端拒绝时回退到 `-1`，业务日志回放独立继续。浏览器缓存扩展 `LiveResearch.events` 和可选 `eventRecovery`；旧会话缺少事件时默认为空，损坏的恢复位置单独丢弃，不丢弃对话。未知事件版本或无效自定义载荷不会阻止报告回读。

研究员事件更新节点和检查器，不修改业务成功状态。阶段、简报和报告继续以 run + checkpoint 回读为准；事件连接失败不会取消运行或 POST 重发。运行已结束却缺少任务终态时，节点显示“完成状态未确认”。

## 持久事件回放 · v1

请求必须带 `research_id`、`turn_id`，可选 `after`（已保存业务序号，默认 0）、`limit`（默认 50，范围 1–100）和 `journal_id`（上次回放的日志 UUID）。路径中的 thread / run 必须是 UUID；所有响应不缓存。该接口只读取安全事件，不调用图或模型，不修改原生 run。

| 返回字段                                                   | 含义                                                             |
| ---------------------------------------------------------- | ---------------------------------------------------------------- |
| `version`, `thread_id`, `run_id`, `research_id`, `turn_id` | 协议版本及完整归属；客户端全部校验                               |
| `status`                                                   | `ready` 可读取、`expired` 已过保留期、`missing` 无可读日志       |
| `journal_id`                                               | 此 run 日志的 UUID；没有日志时为 null                            |
| `events`                                                   | 按业务序号升序排列的安全事件                                     |
| `next_sequence`, `last_sequence`, `has_more`               | 本页恢复位置、服务端已知最高位置、是否还有后续页                 |
| `sealed`                                                   | 本次事件捕获已关闭；不等于任务或研究成功                         |
| `gap`, `reset`                                             | 已知记录缺口、客户端位置需要重置；不会用合成事件补齐             |
| `unconfirmed_before_sequence`                              | 此序号及以前属于旧捕获过程的任务，缺少终态时不能继续显示为执行中 |

`after` 超过服务端位置，或 `journal_id` 不同，返回 `reset: true` 并从头回放可用记录。写入失败可能使序号不连续或缺少末尾事件；服务端用 `gap` 和最高位置明确表示，最后一页不会无限回读。请求参数错误返回 400，归属或日志版本不兼容返回 409，暂时无法访问存储返回 503；日志关闭时为 404，不公开底层路径或异常正文。

`EventRecorder` 先过滤公开字段，再同步提交 SQLite 事务，最后发布 SSE。写入或观察者失败均不终止研究；写入失败只记录异常类型，并在后续写入、关闭记录或回读时显式反映缺口。完整子流程返回后仍把事件写入父检查点。只在原生 API 提供 thread / run 身份时启用日志，独立研究图和评估不需要配置存储。

本地默认文件为 `.langgraph_api/atlas-events.sqlite3`，可用后端 `ATLAS_EVENT_DB` 指定路径。使用 WAL 和 `synchronous=FULL`，同进程首次初始化串行化，避免并发研究竞争建库；后续事件由 SQLite 事务排序。保留期 `ATLAS_EVENT_RETENTION_DAYS` 默认 30，合法范围 1–3650，按最后写入时间计算。在开始捕获或回读时清理过期正文，再保留一个保留期的过期标记；此后返回 `missing`。`LANGGRAPH_DISABLE_FILE_PERSISTENCE=true` 且未显式配置 `ATLAS_EVENT_DB` 时不启用日志。

前端按后端地址、thread、research、turn、run 隔离恢复位置；只有事件与位置一起写入 `localStorage` 成功，才推进可持久化位置。保存失败时保留内存事件和未确认提示，稍后重新读取。每次最多读取四页，剩余内容后续补回；先核对原生 run / checkpoint，回放不会覆盖业务结果。日志接口暂时不可达或研究期间长期缺少日志时提示重试；过期、替换、已知缺口、终态缺失时显示记录不完整。

## 提交确认与执行恢复 · v1

`submission_recovery_version: 1` 只在锁定的 LangGraph 1.1.3、API 0.8.7、inmem runtime 0.28.1 且原生文件持久化启用时声明。`ATLAS_SUBMISSIONS_ENABLED=false` 可关闭能力。版本更新后默认关闭，先跑原生故障验收再调整 `atlas_runtime.py`；不要仅修改版本断言。普通非持久化替身和 1A 专项仍使用旧契约。

初次提交先以原生 `POST /threads` 创建 UUID 会话，再调用受理接口。请求必须包含不可变内容与前一 turn，服务端不接受客户端模型参数、任意 checkpoint 或运行策略：

```json
{
  "research_id": "research-uuid",
  "text": "研究问题或澄清回答",
  "expected_turn_id": null
}
```

同 thread 的下一次提交将 `expected_turn_id` 设为上一 turn ID。服务端检查已有受理、执行状态和检查点；并发或过时的提交返回 409。相同 turn 和完全相同的内容返回原受理，相同 turn 搭配不同内容、研究归属或前一 turn 返回 409。澄清回答仍是新 turn；已完成研究不能再用原 research ID 发起新 turn。

SQLite 受理意图包含固定 run UUID，在创建原生 run 之前提交。原生线程信息先持久化，原生 run 受理完成后再持久化；分配 UUID 不代表模型已执行。图节点在外部调用前必须成功提交进程归属和节点输入摘要，并持久化原生检查点。重启后的旧执行不能直接重放原问题。对尚未开始的意图重试会完成原受理，使用同一个 run UUID，而不是再产生一个执行身份。

受理库默认 `.langgraph_api/atlas-submissions.sqlite3`，`ATLAS_SUBMISSION_DB` 可覆盖，空值沿用默认。使用 WAL、FULL 同步及事务。它保存提交原文、标识、不可变内容摘要、尝试历史和终态检查点位置，不保存凭据；不按事件日志的 30 天保留期清除。请一并备份受理库、原生 `.langgraph_api` 与事件库。文件删除、损坏或版本不一致时关闭恢复，不据此猜测请求未执行。

回执的 `version/thread_id/research_id/turn_id/attempt_id/run_id` 必须全部校验，`attempts` 按顺序列出 `{attempt_id, run_id, kind}`。`event_run_id` 指向实际检索事件所属运行；报告恢复不把旧事件归到新的写作 run。`run` 只包含安全的原生身份 / 状态 / 归属，客户端仍读取检查点判断业务结果。

| 回执状态      | 含义与入口                                                                       |
| ------------- | -------------------------------------------------------------------------------- |
| `accepted`    | 已记录原执行或恢复尝试，继续观察                                                 |
| `retryable`   | 有受理记录但没有节点执行证据，`retry_allowed` 允许使用原内容继续受理             |
| `completed`   | 此 turn 有归属正确的终态检查点；`checkpoint_id` 固定结果位置，不等于研究业务成功 |
| `interrupted` | 执行已结束或所属进程已退出；只在 `recovery.allowed` 为 true 时允许恢复           |
| `blocked`     | 会话、运行或可验证检查点缺失，保留成果，不自动重建                               |
| `rejected`    | 受理发生明确冲突，保留原输入                                                     |

查询一个尚无记录的提交返回 404 `submission_unknown`；若会话不存在则为 `thread_missing`。只有按新契约持久化的提交能利用前者安全重试，旧 metadata 查询没有这一保证。无效请求返回 400，冲突返回 409，存储或运行时暂不可用返回 503；异常正文不会进入前端。

确认 `completed` 前会持久化原生检查点并记录其位置。后续回读使用该 checkpoint，避免新 turn 的状态覆盖旧成果。重复提交已完成 turn 不新增 run；即使终态原生状态仍短暂是 `running`，归属正确的持久终态可以确认完成。业务 `awaiting_input`、`failed`、`partial` 也可能对应已完成的一次 turn，仍按原业务契约展示。

恢复只支持后端重启后、拥有原始受理记录的三个父图节点：

| 下一节点                  | 验证和重复调用范围                                                             |
| ------------------------- | ------------------------------------------------------------------------------ |
| `clarify_with_user`       | active IDs、阶段、原 run、节点输入摘要与实际模型标识一致；澄清模型可能再次调用 |
| `write_research_brief`    | 同上，保留已确认的澄清消息；简报模型可能再次调用                               |
| `final_report_generation` | 同上且存在有效笔记；写作模型可能再次调用，已完成检索和压缩不重跑               |

`supervisor_subgraph` 是尚未拆分的父研究节点，不能从其中一个工具任意续跑。缺少输入摘要、多个下一节点、旧 / 不完整检查点、归属不匹配、模型标识改变或同进程尚不能证明停止时均拒绝恢复。原生异常正文不作为允许恢复的依据。

点击恢复后，浏览器先保存独立 attempt UUID 与下列请求，再提交。后端重新核对当前状态、原 run 与精确 checkpoint，退役旧进程的孤立 run，并以 `input: null` 创建新 run；不重新发送 HumanMessage。

```json
{
  "research_id": "research-uuid",
  "parent_run_id": "interrupted-run-uuid",
  "checkpoint_id": "verified-checkpoint-uuid"
}
```

恢复响应丢失、恢复受理中再次退出时沿用原 attempt；不同恢复操作不能重复消费同一过时的父 run。当前模型节点的内部重试策略保持原样，不承诺任意崩溃下外部请求只发生一次。恢复观察不会增加 run；恢复执行会新增一个明确归属的 run，验收需分别统计。

## 恢复保证与边界

正常状态每 2 秒回读，连接失败使用带少量抖动、最高 30 秒的退避；SSE、状态回读、事件回放分别管理。刷新、切换会话、窗口重新聚焦或网络恢复时也会对账，同一 run 在当前页面只有一个 SSE 观察连接。后台真实研究可在用户查看另一会话或演示时继续完成并接收事件。界面保留四个主阶段，研究员节点由实际委派动态加入。

旧版 `atlas-workspace:v1` 数据保持兼容；没有 `source` 的旧会话按模拟数据解释。新真实会话单独存储 `live` 映射和报告缓存。服务端会话不存在、接口不可达或提交结果不明时保留本地内容并停止新提交，不自动创建替代 thread。清除浏览器存储后，本轮没有按账号重新发现远端会话的功能。

本次依据锁定的 LangGraph 1.1.3、API 0.8.7、inmem runtime 0.28.1、CLI 0.4.26 验证。开发运行时的 SSE `message_stores` 位于进程内存，重启会丢失；原生持久化还存在约 10 秒的后台刷盘边界。新增日志保证已提交事件可以在父研究节点返回前、进程停止后从同一数据库补回，不依赖这两个边界。

1A 保证观察与记录恢复；事件日志不会自行恢复执行。1B 受理回执识别旧进程，提供上述三个经过验证的恢复边界，不能仅信任原生 `running` 状态。日志中的未确认任务仍显示“完成状态未确认”；无法续跑时保留本地、检查点和后续回放中已确认的笔记、来源与报告。日志文件丢失、保留期已过、从未成功提交的事件不保证补回。

本实现面向单进程本地开发服务；SQLite 文件和进程身份不是多实例部署的共享执行协调协议。未纳入恢复白名单的节点、跨设备会话发现和多用户权限仍属后续范围。

## 原生 API 的可复现替身验证

普通 `npm test` 使用 HTTP 替身和演示数据，不调用真实模型。要同时验证原生 LangGraph API、真实图节点及浏览器，在根目录启动专用测试服务：

```powershell
$env:PYTHONUTF8 = '1'
uv run --locked --extra dev python tests/atlas_fixture_server.py --port 2025
```

启动器读取 `tests/atlas-langgraph.json`，不加载生产 `.env`，模型和搜索是 `tests/atlas_fixture_graph.py` 的确定性替身。它先设置环境，再调用同版本原生服务入口 `run_server(disable_persistence=True)`，自动创建 `.local/atlas-api-fixture/case-*` 工作目录，拒绝占用中的端口。测试在提交前核对服务标识、原生持久化关闭和事件日志关闭。在另一终端启动专用前端（Windows 下显式保留此服务，避免测试器结束时 npm 子进程影响清理）：

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

### 强制停止与重启验收

在前端目录运行独立验收（以下端口需空闲）：

```powershell
$env:ATLAS_TEST_PORT = '5176'
$env:ATLAS_BACKEND_URL = 'http://127.0.0.1:2026'
$env:ATLAS_RECOVERY_API = '1'
$env:ATLAS_RECOVERY_PORT = '2026'
npm test -- tests/recovery-api.spec.ts --workers=1 --output test-results/recovery-native
```

`recovery-api.spec.ts` 为每次测试在 `.local/atlas-recovery-api/case-*` 建立独立配置、数据库和原生持久化目录；使用模型 / 搜索替身，拒绝复用已占用的后端端口，并在提交前核对专属服务标识和前端代理。它在检索工具内部阻塞，确认父检查点尚无事件、浏览器也未收到事件，再停止专用后端、重启同一目录，只开放日志回放。测试核对事件 UUID 全部恢复、旧任务完成状态未确认、无虚构报告，服务端仍只有两次 run，最后停止该测试进程。

该用例等待原生运行元数据独立刷盘后再停止，以便核对两次 run；事件日志已在等待前提交。它不证明提交应答丢失时的幂等受理或执行自动续跑。`test_event_journal.py` 另以直接退出子进程验证不依赖最后检查点或 finalizer 的事件落盘。

### 1B 受理与执行故障验收

先显式启动专用前端，保留到测试结束（端口占用时换一组空闲端口）：

```powershell
cd frontend
$env:ATLAS_BACKEND_URL = 'http://127.0.0.1:2027'
$env:NO_PROXY = '*'
npm run dev -- --port 5177 --strictPort
```

另一个终端运行：

```powershell
cd frontend
$env:ATLAS_TEST_PORT = '5177'
$env:ATLAS_SUBMISSION_API = '1'
$env:ATLAS_SUBMISSION_PORT = '2027'
$env:NO_PROXY = '*'
npm test -- tests/submission-api.spec.ts --workers=1 --output test-results/submission-native
```

测试器通过 `tests/atlas_submission_server.py` 启动实际原生服务，每个用例使用 `.local/atlas-submission-api/case-*` 独立目录，明确启用持久化，不读取生产 `.env`。替身的模型 / 工具调用计数先同步提交 SQLite。测试拒绝占用的后端端口，核对每次进程身份，在指定受理 / 模型 / 工具内部立即强制退出，不等待十秒后台刷盘。

8 项覆盖：响应丢失及完成 turn 重复请求 / 并发冲突；原生创建前与创建后但确认前退出；澄清、简报、写作中退出并从检查点继续；研究工具中退出与服务端会话丢失；恢复受理中再次退出。写作用例同时通过 Chrome 点击恢复、丢失恢复响应、刷新和窄屏截图。每项结束停止自己的进程，`native-evidence.json` 保存进程身份与调用数，原生 run 列表另在断言中核对。用例中的直接完整首问加一次恢复为 **2 个 run**，不要与“先澄清一次再回答”的普通两次提交混为一谈。

当前 CLI 0.4.26 / API 0.8.7 会覆盖 `LANGGRAPH_DISABLE_FILE_PERSISTENCE`，其配置校验又会过滤顶层 `disable_persistence`。因此旧命令仅在 `env` 中设为 true，不能证明已关闭持久化。普通替身使用上述专用启动器，提前设置环境并直接传入原生服务参数；恢复用例明确启用持久化、提前注入环境且使用独立目录。不要用正常开发数据目录进行强制停止验收。

真实模型联调使用正常后端与前端，清除 `ATLAS_API_FIXTURE`，显式设置 `$env:ATLAS_LIVE = '1'` 和 `$env:NO_PROXY = '*'` 再运行 `tests/live-api.spec.ts`。此模式调用模型和 Tavily，产生真实费用；测试要求完成澄清、补充回答、报告与来源，并在刷新后仍只有两次运行提交。2026-10-13 后续 GLM 复测确认简报失败；同网关 / 同密钥的 Kimi 隔离测试取得笔记和 8 条来源，但在报告写作时被预设保护期限中断。2026-10-14 通过代理恢复该写作检查点后获得部分完成报告，共 3 个 run；原研究失败与严格首段观测缺口仍保留。完整成功研究仍未验收，详见 [最新记录](verification.md)；不能将单步成功、原生 run 成功或离线回放画面记为真实闭环通过。

真实模式当前使用 **600 秒**澄清观察窗口，单测试整体最多 **1800 秒（30 分钟）**。第二次提交后的终态等待取整体剩余时间并预留 **30 秒**回读，替代此前固定的 1140 秒阶段窗口；Kimi 旧用例仍按当时的 1140 秒超时如实记录，不回写成新预算已通过。这些是浏览器观察期限，不会增加 SDK / helper / 节点的有限重试次数，也不会在观察失败时重新提交问题。替身模式仍使用原 180 / 660 / 900 秒预算。真实复测应显式设置测试级 `retries: 0`，为专属后端设置清理期限，结束前先回读受理回执及所属终态检查点；超时只能记为未完成，不能用原生 run 的 `success` 推断报告交付。

离线实录通过 `recordings.json` 保存公开配置、安全对话、笔记、来源、研究事件和客户端请求计数。界面以独立内存会话分章节展示，不调用提交、恢复或事件回放 API，也不宣称补齐服务器历史。最后的 `running` 是中断前快照，显示为记录中断而不改写业务状态。详见 [实录约定](recorded-runs.md)。
