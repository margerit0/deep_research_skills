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

独立前端已接入 `research_agent_full`，启动方式见 [frontend/README.md](../frontend/README.md)，接口定义见 [backend-contract.md](../frontend/docs/backend-contract.md)。`langgraph.json` 的自定义 HTTP app 仅提供 `/atlas/config`，返回进程实际构造的六个模型角色和自动 Skills 能力；不包含密钥或提供商 URL。会话和运行仍使用 LangGraph 原生 API。

前端默认用 Vite 的 `/api` 转发访问 2024 端口。它不读取根目录后端 `.env`，也不把本地模拟模型菜单的选择传给后端。调整后端模型、凭据或 Skills 文件后要重启服务，让导入时快照生效。`--allow-blocking` 与现有同步研究工具保持兼容；不要借此认为整个图是同步运行的。

若要求模型、搜索和追踪请求直连，在后端启动终端设置 `$env:NO_PROXY = '*'`，并按需要在本地 `.env` 保存 `NO_PROXY=*`。请求超时或证书错误时，应分别验证代理路径、直连路径与证书信任；不要把一个最小请求的成功当成完整研究成功。

一次 LangGraph run 的 `success` 只表示图执行正常返回；澄清等待、研究失败、部分完成都可能正常返回。前端必须依据 `research_status` 及 `active_research_id` / `active_turn_id` / `report_research_id` 判断结果。后端已在新研究入口重置累积字段；不要从客户端仅用 `notes=[]` 假定能够清空带加法 reducer 的状态。

回归分三层：`pytest` 的图和模型替身、`frontend/tests/live.spec.ts` 的 HTTP 替身、`tests/atlas-langgraph.json` 的原生 API 服务配合模型 / 搜索替身。最后一层的测试服务不加载生产 `.env`，并禁用文件持久化。真实模型联调必须显式启用 `ATLAS_LIVE=1`，同时检查业务状态、正文、来源及 run 数量。完整步骤与本次结果见 [前端验收记录](../frontend/docs/verification.md)。

研究员进度通过原生 `custom` SSE 发送。`research_events_version: 1` 是后端能力标识，更新代码后要重启服务。`research_events.py` 在父研究节点建立独立的事件记录器，分别捕获委派、研究模型、工具、压缩和任务终态；研究子流程返回后，安全事件列表写入父图检查点。它不收集原始模型推理或工具正文，也不会因事件观察者断线使研究失败。

排查进度时分别检查事件流和业务状态：事件流关闭不表示研究完成，仍需读取 run 和 checkpoint。浏览器会恢复可用缓冲并按 UUID 去重；服务进程中途退出导致的未落盘事件丢失，尚不属于完整恢复保证。`frontend/tests/live-events.spec.ts` 覆盖并行任务、追加委派、旧事件隔离、SSE 分片和窄屏布局；原生 API 测试还核对缓冲事件与检查点一致、刷新后服务端仍只有两次 run。

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
