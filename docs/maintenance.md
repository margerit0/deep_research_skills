# 本地开发与维护

本文按当前 `src/deep_research/` 实现整理。历史排障记录中的旧包名、旧目录、配额状态和待办不作为当前开发指令。架构约定见 [架构决策](architecture-decisions.md)，历史实验见 [评估记录](evaluation-history.md)。

## 环境与入口

在项目根目录执行：

```powershell
$env:PYTHONUTF8 = "1"
uv sync --locked --extra dev
uv run --locked --extra dev pytest
uv run --locked --extra dev langgraph dev --no-browser --allow-blocking
```

`--extra dev` 安装 `pyproject.toml` 中的 LangGraph CLI/API 等可选开发依赖；默认的 dev dependency group 主要提供 pytest，两者不是同一项配置。`--locked` 使用已提交的锁文件并检查其与项目配置一致。

单元测试自带导入阶段所需的默认模型配置，对模型和搜索调用使用测试替身，不依赖真实密钥。Qwen fallback 测试拦截当前 SDK 的原始响应调用，并验证空 `choices` 的重试与最终诊断。

开发依赖也包含 HTTPX 与 Requests 的 SOCKS 支持，用于当前进程通过 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY` 使用 SOCKS 代理的情况。HTTPX 需要 `socksio`，Tavily 使用的 Requests 需要 `PySocks`；这些依赖不改变代理地址或路由。

首次配置使用根目录 [.env.example](../.env.example) 创建本地 `.env`，填写模型角色和凭据。已有本地配置可以沿用。不要搬运旧虚拟环境；用当前项目的锁文件同步依赖。

`langgraph.json` 从项目根目录读取 `.env`。自行编写 Python 入口时，必须在导入任何研究图模块之前调用 `load_dotenv()`，因为模型会在模块导入阶段实例化：

```python
from dotenv import load_dotenv

load_dotenv()
from deep_research.research_agent_full import agent
```

自建 React 界面可以连接 LangGraph API。模型、Tavily 和 LangSmith 凭据保留在后端环境中；前端配置只需提供后端地址。

## 星图工作台真实模式

独立前端已接入 `research_agent_full`，启动方式见 [frontend/README.md](../frontend/README.md)，接口定义见 [backend-contract.md](../frontend/docs/backend-contract.md)。`langgraph.json` 的自定义 HTTP app 提供只读 `/atlas/config` 和 `/atlas/threads/{thread_id}/runs/{run_id}/events`。配置只返回实际构造的六个模型角色及能力，回放只返回安全研究员事件；不包含密钥或提供商 URL。会话和运行仍使用 LangGraph 原生 API。

前端默认用 Vite 的 `/api` 转发访问 2024 端口。它不读取根目录后端 `.env`，也不把本地模拟模型菜单的选择传给后端。调整后端模型、凭据或 Skills 文件后要重启服务，让导入时快照生效。`--allow-blocking` 与现有同步研究工具保持兼容；不要借此认为整个图是同步运行的。

若要求模型、搜索和追踪请求直连，在后端启动终端设置 `$env:NO_PROXY = '*'`，并按需要在本地 `.env` 保存 `NO_PROXY=*`。请求超时或证书错误时，应分别验证代理路径、直连路径与证书信任；不要把一个最小请求的成功当成完整研究成功。

一次 LangGraph run 的 `success` 只表示图执行正常返回；澄清等待、研究失败、部分完成都可能正常返回。前端必须依据 `research_status` 及 `active_research_id` / `active_turn_id` / `report_research_id` 判断结果。后端已在新研究入口重置累积字段；不要从客户端仅用 `notes=[]` 假定能够清空带加法 reducer 的状态。

回归分三层：`pytest` 的图和模型替身、前端的 HTTP / SSE 替身、原生 API 服务配合模型 / 搜索替身。普通 API 替身由 `tests/atlas_fixture_server.py` 读取 `tests/atlas-langgraph.json` 启动，不加载生产 `.env`；它在导入前设置环境，并向同版本的原生 `run_server` 明确传入 `disable_persistence=True`，工作目录固定在 `.local/atlas-api-fixture/case-*`。恢复验收另用 `frontend/tests/recovery-api.spec.ts`，在 `.local/atlas-recovery-api/case-*` 建立专属配置和持久化目录，在工具内部停止并重启自己的后端。真实模型联调必须显式启用 `ATLAS_LIVE=1`，同时检查业务状态、正文、来源及 run 数量。步骤和结果见 [前端验收记录](../frontend/docs/verification.md)。

研究员进度通过原生 `custom` SSE 发送。`research_events_version: 1` 和可选 `research_event_replay_version: 1` 分别表示实时事件与持久日志回放，更新代码后要重启服务。`research_events.py` 在父研究节点建立独立记录器，捕获委派、研究模型、工具、压缩和任务终态；安全事件在发送前同步提交 SQLite，子流程返回后仍写入父图检查点。不收集原始模型推理或工具正文，观察者或存储故障不会让研究失败。

默认日志为 `.langgraph_api/atlas-events.sqlite3`；后端 `ATLAS_EVENT_DB` 可改路径，`ATLAS_EVENT_RETENTION_DAYS` 默认 30，合法范围 1–3650。不要清除日志目录后期待补回旧事件。保留期按最后写入计算，过期正文在开始捕获或回读时清理，过期标记再保留一个保留期。普通非持久化测试未显式配置路径时不启用日志；独立图和评估没有原生 thread / run 身份时也不写事件库。

排查时分别核对事件流、事件日志和业务状态。SSE 关闭或日志 `sealed` 都不表示研究成功；已提交的日志在进程停止后仍可分页读取，最终结果仍核对 run 和 checkpoint。后端可能保留旧 `running` 状态但没有续跑，旧捕获过程的非终态任务会标为“完成状态未确认”。浏览器将事件和恢复位置一起保存，存储失败不推进位置；重连、聚焦与网络恢复只读，不增加 run。

本轮完成单进程本地服务的观察与记录恢复，未承诺幂等受理或任意节点的执行恢复。`test_event_journal.py` 覆盖写入、退出、并发初始化、迁移和过期；`live-recovery.spec.ts` 覆盖分页、位置重置、存储失败、终态缺失和窄屏提示；原生恢复验收核对停机前事件全部补回且 run 数仍为两次。

2026-10-10 用户确认当前网关问题由供应商后续修复，要求跳过连接排障并继续事件图谱开发。保持指定模型、地址、本地密钥与 `NO_PROXY=*`，未关闭 TLS 校验。供应商恢复前，替身验收不能代表完整真实研究已通过。

## 结构化输出与网关兼容

Scoping 节点和 LangSmith 结构化评估器复用 [structured_output_fallback.py](../src/deep_research/structured_output_fallback.py)。新增评估器应调用共享 helper，避免独立实现一套 `with_structured_output()` 路径。

当前 helper 对符合其判定条件的 Qwen 模型使用 `/no_think` JSON 路径，经 OpenAI SDK 的 `with_raw_response.create()` 读取原始响应，再由项目代码检查 `choices`、提取 JSON、执行 schema 校验和有限重试。保留这一层的诊断信息；不要把空 `choices` 当成有效结果。不同网关对 `enable_thinking` 的支持不同，替换模型或端点时需要验证相应路径。

2026 年 5 月的一次 403 故障由特定网关对旧 urllib 客户端签名的拦截造成，后来更换了 transport。该记录说明排障应对比请求头、响应状态和客户端行为，不能把所有 403 都归因于同一个原因。后续的 `KeyError('research_brief')` 也可能只是上游失败后缺少输出的连带结果。

网页摘要是另一个调用点：[utils.py](../src/deep_research/utils.py) 显式采用 `method="function_calling"`。2026 年 6 月曾因默认结构化输出方式与网关不兼容而大量降级为截断原文；研究覆盖率下降时应检查摘要阶段日志。

## 重试、并发与失败输出

- Tavily 的自定义 `tavily.errors.TimeoutError` 与 Python 内建 `TimeoutError`、`requests.exceptions.Timeout` 不同，修改重试逻辑时要核对实际异常类型。
- Tavily 调用点的重试、评估整案重试、压缩与最终报告模型的重试处在不同层。调参时核算整体尝试次数与成本，避免叠加出过大的重试量。
- `AGENT_RPM` 在单个进程中由 researcher、网页摘要和 compression 共享。评估的 example 并发与 judge 并发另行控制；降低一个参数不代表另一个也降低。
- 无有效搜索结果或压缩输出为空时，研究员返回以 `## 研究未完成` 开头的标记。界面应展示失败状态，而不是把该文本当成成功报告。
- 完整图只把有效 `ConductResearch` 结果用于报告，排除思考工具输出和失败标记。并行研究的部分失败保留成功任务；无有效笔记时不调用最终报告模型，写作失败则返回 `partial` 并保留已有笔记及来源。
- 本地进程异常结束后，远端追踪的状态可能滞后。排障同时检查本地进程、日志和远端记录。

## 评估明细必须可回读

当前 Scoping 评估器与回读脚本使用以下约定：

| 数据 | Feedback 字段 |
|---|---|
| 数值评分 | `score` |
| 文本摘要或理由 | `comment` |
| 逐项结构化明细 | `value.individual_evaluations` |

历史文档曾推荐把明细写入 `metadata`，该建议后来被纠正；当时 `extra` 路径也没有保存所需数据。维护这里时以 [写入实现](../scripts/scoping/run_scoping_eval.py) 和 [回读实现](../scripts/scoping/fetch_last_eval.py) 为准，并验证写入后能读回。

`error_handling="log"` 允许批量评估在部分调用失败后继续，因此退出码为 0 或打印“评估已完成”不能证明每条用例都有有效评分。应核对用例数量、agent 错误、缺失 feedback，以及各项明细；缺失评分与真实零分应分开统计。

运行方法见 [评估操作手册](evaluation.md)。真实评估会调用模型、搜索服务和 LangSmith，先用 `--limit 1 --max-concurrency 1` 检查改动路径，再按需要扩大。对照实验使用明确的 `--project-name` 回读，记录模型、judge、数据集版本及失败数量。
