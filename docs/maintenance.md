# 本地开发与维护

## Skill 优化入口

新增 `python -m scripts.research_agent.skill_evolution --help`，使用独立实验目录保存不可变 manifest、失败尝试、诊断、候选 diff 与报告，复用既有配置归档；详见 [操作说明](skill-evolution.md)。帮助／纯数据路径不导入研究图，真实诊断、生成与评估需显式 `--allow-external`。本轮仅做确定性检查，生产 Skill、模型和凭据配置不变；不要把未知费用或缺失评分补零。

本文按当前 `src/deep_research/` 实现整理。历史排障记录中的旧包名、旧目录、配额状态和待办不作为当前开发指令。架构约定见 [架构决策](architecture-decisions.md)，历史实验见 [评估记录](evaluation-history.md)。

## 仓库材料管理

正式前端在 `frontend/`；新设计草稿放入已忽略的 `open_design/` 或 `.local/`，定稿后将需要的源码整合进正式前端。构建输出与浏览器测试报告继续由前端 `.gitignore` 排除。

2026-10-29 从当前版本移除 `ui-drafts/`、一次性设计迁移脚本 `frontend/scripts/import-design.mjs`，以及演示视频 v1/v2。清理前的完整快照为 Git 提交 `dac1870ec56e08603f3e93e58bb5a2e916a45456`；旧文件留在历史中，无需在主目录继续保存副本。例如：

```powershell
git show dac1870ec56e08603f3e93e58bb5a2e916a45456:ui-drafts/atlas-workspace/APPLE_IMPLEMENTATION.md
git ls-tree -r --name-only dac1870ec56e08603f3e93e58bb5a2e916a45456 -- product-video/2026-10-25-v1 product-video/2026-10-25-v2
```

当前 [演示视频](../product-video/README.md) 为 v7：53 秒，沿用 v6 的“Agent 自动进化”章节卡与镜头结构，先解释研究方法与评估的关系，再介绍 Skill 优化机制；重写原创配乐并修订转场；保留源码、批准记录与校验清单。v6、v4 和 v3 原交付包归档保留，其历史文字和版本来源字段不改写；当前说明置于包外。视频材料通过 `.gitattributes` 的 `linguist-documentation` 排除出语言统计，正式应用源码仍正常计入。旧版本的本地缓存继续忽略，不重新入库。

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

当前代码保留安全核验诊断和显式启用的流式 JSON 策略；流式策略的完整业务验收尚未通过。2026-10-19 至 2026-10-21 的方案、结果和交接作为历史证据保留，统一见 [P1 实验归档](../frontend/docs/p1-experiments-2026-10.md)。下列日期记录中的“下一步”“最新入口”和未提交状态只描述当时情况，不构成当前开发任务。

2026-10-20 已执行下一批来源条件范围／分类单变量复验：十个离线 arm 没有取得有效选择或核验决定，两次新原生均在首轮澄清业务失败，交付 0/2。八十次模型 HTTP 尝试为 79 × 502、1 × 429，全部无 usage；搜索未触发，质量指标不可评价。实验选择提示已撤下，源码恢复进入本批时版本；本轮 227 项后端测试通过。失败、公开合成案例及新提示原文见[本轮结果](../frontend/docs/p1-selection-results-2026-10-20.md)，后续入口见[来源选择复验交接](../frontend/docs/handoff-after-p1-selection-2026-10-20.md)。本批所有 arm／原生身份已用；网关可用后只能另建有界批次，不能重跑旧入口。

2026-10-20 的历史交接见 [核验提示复验后交接](../frontend/docs/handoff-after-p1-review-2026-10-20.md)。本轮 12 个离线 arm 与两次新原生复验已全部结束，最终交付验收 1/2；新提示仍有误拒、误放行及无必要修订，已经撤下，工作区只保留安全诊断改进。最终代码 227 项后端测试通过，生产配置、P0 默认实录和历史原件不变。详见 [本轮结果](../frontend/docs/p1-review-results-2026-10-20.md)，不得复用本轮或旧批次身份。

2026-10-19 的 [P1 首批交接](../frontend/docs/handoff-after-p1-baseline-2026-10-19.md) 保留当时的未提交文件、已结束实验及后续建议；不作为当前窗口的续接任务。

2026-10-19 已按 [P1 方案](../frontend/docs/p1-deepseek-plan-2026-10-19.md)完成三次有界原生重复及两组固定候选稿 high／low 配对。原生业务完成 2/3、独立内容通过 0/3；高思考仍有误放行，低思考也出现不可靠拒绝理由，不能据此自动推广生产默认。P2 同步保留连接失败、429、HTTP 200 后 SDK 错误、实际 token 和完整消费耗时；生产代码、`.env`、旧证据和默认 P0 成功实录未变。最新结果与后续实验边界见 [P1 结果](../frontend/docs/p1-deepseek-results-2026-10-19.md)，本地入口 `.local/p1-deepseek-20261019/README.md`；原三次运行身份与配对 arm 已用，后续必须另建有界清单，不重跑旧身份。

2026-10-19 用户随后要求将已通过 P0 的 DeepSeek 实录设为默认演示，该前端接入及会话隔离检查已完成，旧模拟和历史实录保留。P0 后端已提交为 `fae0c67`；前端接入与新交接在后续提交中。当时的后续任务见 [P1 与后续任务交接](../frontend/docs/handoff-p1-after-deepseek-replay-2026-10-19.md)，不要再按旧交接重做 P0 或新实录接入。下文源码／保护哈希相同的结论对应当时验收快照，此后授权的前端改动另有测试及保护记录。

2026-10-19 收尾复核确认：2026-10-17 的 DeepSeek `af` 原生流程已通过本次固定场景 P0，541 汉字报告的 16 条断言独立核对通过，当前源码与验收快照一致。完整证据清单已补齐至 33 次实验，436 个受保护文件未变。最终实验为模型直连、high 写作／32000、high 核验／128000；这些仍是隔离入口覆盖，普通后端不会自动继承。一次通过不证明重复运行稳定性，后续安排以 [验收记录](../frontend/docs/verification.md) 首节为准，旧交接中的未完成状态保留作历史。

2026-10-17 的 P0 续验增加逐条来源位置校验，以及不读取候选稿的来源条件选择；实质适用／安全／适配前提与其他条件分开，避免被支持声明或数值挤掉。来源选择和两稿核验共用四次读取预算，条件选择在同一写作节点内复用。短报告在来源正文之后再次明确篇幅和取舍要求。真实实验按用户要求将模型客户端改为直连，保留原 DeepSeek、网关、凭据与 TLS；搜索配置独立。实验中的思考和核验 token 覆盖只由隔离入口绑定，不写入生产 `.env` 或原有配置归档。实际结果与复现入口见 [P0 续验记录](../frontend/docs/p0-fact-fidelity-results-2026-10-17.md)，不能将原文定位或模型 `passed=true` 单独视为内容验收通过。

2026-10-15 的 [Kimi 约束修复](../frontend/docs/kimi-fixes-2026-10-15.md) 为委派保留原始要求、真实预加载指定 Skills，并在摘要前执行精确 URL 范围。直接读取指定页面带独立来源标记；摘要支持结构化流式，失败时保留有界原文与安全诊断。写作日志不再因研究 SSE 的空游标记录而提前回读。新要求字段已纳入恢复校验，旧检查点摘要仍兼容；生产 `.env` 与共享结构化 / Qwen fallback 文件保持原样。真实各轮结果以新验收记录为准，不覆盖旧记录。

2026-10-14 的计划 3 已接入最终报告正文流式。独立 `report_streaming.py` 仅发送正文，按约 150 毫秒或 2048 字符合并；明确区分至多三次生成尝试，SDK 重试另计，模型完成不等于业务成功。取消执行时关闭模型流、保留已提交草稿并传播取消信号，不重新生成。正文日志默认与研究事件库同目录，名为 `atlas-report-events.sqlite3`，可设 `ATLAS_REPORT_EVENT_DB`；应与其余恢复数据库一并保留。API 与前端分别使用 `report_events_version`、`report_event_replay_version`、`atlas.report_event` 和 `/report-events`，见 [实施说明](../frontend/docs/report-streaming-plan.md)。

2026-10-14 的新建 Kimi 研究已完成两次提交 / 两个 run，业务为 `succeeded/complete`，报告 1610 字符、3 条来源、103 条正文事件；检查点与刷新回读一致，完整首段截图早于写作结束 29.436 秒。六角色使用同一 Kimi、原网关 / 凭据和显式 SOCKS5 `127.0.0.1:55430`。实际 Skills 加载、严格两页检索及部分报告表述未通过全部场景要求；首段截图上的瞬时日志回读提示原因未确认。结果与独立失败轮的证据见 [最新验收](../frontend/docs/verification.md)。

此前 Kimi 曾从原写作检查点恢复：原两次提交 / 两个 run 加一个写作恢复，共三个 run，业务为部分完成。原研究笔记、8 条来源、失败、配置和部分报告均保留。这次历史恢复与新建成功研究有各自身份，不合并运行次数或改写原状态。生产 `.env`、TLS、共享 limiter 和结构化 fallback 保持不变。

2026-10-11 的计划 2 已支持按次模型 / Skills。前端从现有六角色配置的去重目录选择各角色模型，发送后锁定一轮研究；澄清、提交重试、恢复和历史都沿用受理快照。`run_configuration.py` 通过执行作用域和模型缓存隔离请求，网页摘要线程复制上下文，共享限流器及 Qwen `/no_think` 路径保留。旧独立图、评估和不支持选择的后端继续使用默认调用。

新配置归档默认是受理库同目录的 `atlas-configs.sqlite3`，可用 `ATLAS_CONFIG_DB` 改路径，必须与受理、事件和原生检查点一起备份。归档包含原网关、模型参数、凭据环境变量名和 Skills 正文修订，不含密钥值；前端只看到公开快照与修订 ID。重启后默认模型 / Skills 内容变化不覆盖历史。旧修订的网关仍需可访问，密钥仍从本地 `.env` 加载；不要删除归档后期待恢复旧研究。

Skills 自动模式固定当时全部可用正文；手选是允许自动加载的集合，空集合禁止全部。系统提示词目录和 `load_skill` 均按快照过滤，界面单独显示实际成功加载记录。完整定义见接口文档的“按次配置扩展”。

2026-10-13 的后续真实复测已将澄清观察放宽到 600 秒，并试验每种模型请求最多 5 次、3 / 6 / 12 / 24 秒退避。GLM 两轮均确认 `failed/brief`。按用户要求，同网关 / 同密钥的隔离进程将六角色换为 `moonshotai/kimi-k3`，取得 231 字简报、30 条研究事件、1 份笔记及 8 条来源；1950 秒后端保护期限到达时仍为 `running/writing`、报告为空，不能记作完整交付或业务失败。连接提前关闭及 TLS EOF 与证书校验失败分别记录。上述模型切换和退避仅用于隔离实验，生产 `.env`、TLS、`NO_PROXY=*`、共享 limiter 与结构化 fallback 保持原配置。详见 [最新验收记录](../frontend/docs/verification.md)。

2026-10-14 完成 GLM / Kimi 离线实录回放与证据包整理。回放不创建执行、不修改本地会话，不等同于在线报告流式；下载包包含安全对话、检查点、笔记、来源、研究事件、HTTP 尝试、退避及逐文件校验清单。临时浏览器材料的缺失和 API / 浏览器快照差异单独记录，不能仅凭回放画面推断真实完整验收通过。使用方法与数据边界见 [真实记录回放](../frontend/docs/recorded-runs.md)。

独立前端已接入 `research_agent_full`，启动方式见 [frontend/README.md](../frontend/README.md)，接口定义见 [backend-contract.md](../frontend/docs/backend-contract.md)。自定义 HTTP app 提供配置、事件回放，以及 1B 的 `/atlas/threads/{thread_id}/submissions/{turn_id}` 受理 / 对账和 `/recoveries/{attempt_id}` 恢复入口。配置只返回实际构造的六个模型角色及能力，事件与回执不包含密钥、提供商 URL 或原始异常。运行、检查点及 SSE 仍由 LangGraph 管理。

前端默认用 Vite 的 `/api` 转发访问 2024 端口。它不读取根目录后端 `.env`，也不把本地模拟模型菜单的选择传给后端。调整后端模型、凭据或 Skills 文件后要重启服务，让导入时快照生效。`--allow-blocking` 与现有同步研究工具保持兼容；不要借此认为整个图是同步运行的。

若要求模型、搜索和追踪请求直连，在后端启动终端设置 `$env:NO_PROXY = '*'`，并按需要在本地 `.env` 保存 `NO_PROXY=*`。请求超时或证书错误时，应分别验证代理路径、直连路径与证书信任；不要把一个最小请求的成功当成完整研究成功。

一次 LangGraph run 的 `success` 只表示图执行正常返回；澄清等待、研究失败、部分完成都可能正常返回。前端必须依据 `research_status` 及 `active_research_id` / `active_turn_id` / `report_research_id` 判断结果。后端已在新研究入口重置累积字段；不要从客户端仅用 `notes=[]` 假定能够清空带加法 reducer 的状态。

回归分三层：`pytest` 的图和模型替身、前端的 HTTP / SSE 替身、原生 API 服务配合模型 / 搜索替身。普通 API 替身由 `tests/atlas_fixture_server.py` 读取 `tests/atlas-langgraph.json` 启动，不加载生产 `.env`；它在导入前设置环境，并向同版本的原生 `run_server` 明确传入 `disable_persistence=True`，工作目录固定在 `.local/atlas-api-fixture/case-*`。恢复验收另用 `frontend/tests/recovery-api.spec.ts`，在 `.local/atlas-recovery-api/case-*` 建立专属配置和持久化目录，在工具内部停止并重启自己的后端。真实模型联调必须显式启用 `ATLAS_LIVE=1`，同时检查业务状态、正文、来源及 run 数量。步骤和结果见 [前端验收记录](../frontend/docs/verification.md)。

研究员进度通过原生 `custom` SSE 发送。`research_events_version: 1` 和可选 `research_event_replay_version: 1` 分别表示实时事件与持久日志回放，更新代码后要重启服务。`research_events.py` 在父研究节点建立独立记录器，捕获委派、研究模型、工具、压缩和任务终态；安全事件在发送前同步提交 SQLite，子流程返回后仍写入父图检查点。不收集原始模型推理或工具正文，观察者或存储故障不会让研究失败。

默认日志为 `.langgraph_api/atlas-events.sqlite3`；后端 `ATLAS_EVENT_DB` 可改路径，`ATLAS_EVENT_RETENTION_DAYS` 默认 30，合法范围 1–3650。不要清除日志目录后期待补回旧事件。保留期按最后写入计算，过期正文在开始捕获或回读时清理，过期标记再保留一个保留期。普通非持久化测试未显式配置路径时不启用日志；独立图和评估没有原生 thread / run 身份时也不写事件库。

排查时分别核对事件流、事件日志和业务状态。SSE 关闭或日志 `sealed` 都不表示研究成功；已提交的日志在进程停止后仍可分页读取，最终结果仍核对 run 和 checkpoint。后端可能保留旧 `running` 状态但没有续跑，旧捕获过程的非终态任务会标为“完成状态未确认”。浏览器将事件和恢复位置一起保存，存储失败不推进位置；重连、聚焦与网络恢复只读，不增加 run。

1A 的事件回放不启动执行。1B 在持久化单进程本地服务中增加幂等受理与三个经过验证的父检查点恢复：澄清、简报、报告写作。`supervisor_subgraph` 中途退出尚不能安全续跑；保留确认过的成果并新建研究。恢复可能再次调用当前模型节点，写作恢复不重跑已完成的检索和压缩。

1B 默认受理库为 `.langgraph_api/atlas-submissions.sqlite3`，`ATLAS_SUBMISSION_DB` 非空时可改路径。受理记录不随事件保留期删除；原文、内容摘要、run / attempt 身份与终态位置均属于本地后端数据。备份或移动服务时保留受理库、原生 `.langgraph_api` 和事件库；缺少任一执行依据时不猜测请求未发生。

`atlas_runtime.py` 将私有运行时依赖集中到版本适配层，仅启用已经验收的 LangGraph 1.1.3 / API 0.8.7 / inmem 0.28.1。它为原生持久化对象安装串行同步写入，在受理、节点调用和确认终态前设置刷盘边界，不修改安装目录中的包文件。升级依赖后先重跑故障测试，再更新版本支持；不要仅删除版本限制。`ATLAS_SUBMISSIONS_ENABLED=false` 可关闭新能力；旧提交仍按旧协议回读。

`test_submission_journal.py` 验证并发固定身份、旧进程阻止执行、检查点归属 / 输入摘要、终态位置及迁移。`live-submissions.spec.ts` 验证响应丢失、重试、冲突、恢复记录落盘、结果隔离和成果保留。`submission-api.spec.ts` 在 `.local/atlas-submission-api/case-*` 启动专属原生后端，立即在受理、模型或工具内部停止进程，检查实际 run 列表与持久工具计数；不等待十秒后台刷盘，不读取生产 `.env`。普通 API、1A、1B 的默认专用端口和复现命令均见接口文档。

2026-10-10 用户确认当前网关问题由供应商后续修复，要求跳过连接排障并继续事件图谱开发。保持指定模型、地址、本地密钥与 `NO_PROXY=*`，未关闭 TLS 校验。供应商恢复前，替身验收不能代表完整真实研究已通过。

## 结构化输出与网关兼容

2026-10-20 增加显式的流式 JSON 对象策略：共享 helper 可传 `strategy="json_object"`，或在模型构造 metadata 中设置 `structured_output_strategy: json_object`。默认仍为原生优先；普通配置和 `.env` 没有自动切换。新路径复用已有客户端的连接、超时、SDK 重试和共享限流，确认 `stop` / `[DONE]` 后做原 schema 校验，不修复无效流为成功。网页摘要仅显式选择时接入此路径，Qwen `/no_think`、空 choices 两次上限及诊断保留。两份固定简报真实读取 2/2 通过，完整原生样本因隔离遥测重复导入错误为 0/1，不能视为完整接入已验收；240 项后端测试和两个包装修复离线测试通过。新入口见 [JSON 流读取交接](../frontend/docs/handoff-after-glm-jsonstream-2026-10-20.md)，旧身份不可重跑。

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

| 数据           | Feedback 字段                  |
| -------------- | ------------------------------ |
| 数值评分       | `score`                        |
| 文本摘要或理由 | `comment`                      |
| 逐项结构化明细 | `value.individual_evaluations` |

历史文档曾推荐把明细写入 `metadata`，该建议后来被纠正；当时 `extra` 路径也没有保存所需数据。维护这里时以 [写入实现](../scripts/scoping/run_scoping_eval.py) 和 [回读实现](../scripts/scoping/fetch_last_eval.py) 为准，并验证写入后能读回。

`error_handling="log"` 允许批量评估在部分调用失败后继续，因此退出码为 0 或打印“评估已完成”不能证明每条用例都有有效评分。应核对用例数量、agent 错误、缺失 feedback，以及各项明细；缺失评分与真实零分应分开统计。

运行方法见 [评估操作手册](evaluation.md)。真实评估会调用模型、搜索服务和 LangSmith，先用 `--limit 1 --max-concurrency 1` 检查改动路径，再按需要扩大。对照实验使用明确的 `--project-name` 回读，记录模型、judge、数据集版本及失败数量。
