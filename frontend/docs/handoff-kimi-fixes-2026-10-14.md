# Kimi 验收问题修正：新窗口交接

准备日期：2026-10-14，Asia/Shanghai。项目目录：`D:\deep_research_public_preview`。

用户下一步准备在新窗口修正本轮遗留问题。本次只准备交接材料，尚未开始业务修复或新一轮模型调用。

## 先确认工作区

- 分支：`chore/public-edits`。
- 本次收尾提交：`2d9704aff2e005fa0df429eac93caf7b92737ddf`，`feat: preserve completed Kimi research in Atlas replay`；本地较远端领先 3 个提交，尚未推送。
- 前置实现：`1a2e368` 完成报告正文流式与持久写作恢复；`87705a4` 增加历史实录回放；`b5b53f4` 增加按次模型 / Skills 配置。
- 制作本交接前工作区干净。本交接文件及 `next-steps.md` 的入口是随后新增的未提交文档；接手先检查实际 `git status` / HEAD，保留它们及任何后续改动。
- 先读 [AGENTS.md](../../AGENTS.md)、[维护说明](../../docs/maintenance.md)、[架构约定](../../docs/architecture-decisions.md)，再读[最新验收](verification.md)首节与[引用审查](provider-2026-10-14-kimi-full-citation-review.md)。`.local/` 是实测材料和辅助脚本，不能把历史实验脚本当作当前生产实现。

本次收尾聊天：`codex://threads/01a13ab5-c50a-7160-98bb-827f084ee28b`。实际发起两轮 Kimi 实测的聊天：`codex://threads/01a13a51-5671-7b91-95fb-0b0b651effe2`。需要补充历史时按需读取，当前交接已包含主要事实。

## 已完成且无需重做的工作

第二轮真实 Kimi 研究完整执行了澄清 → 同 thread 补充 → 简报 → 研究 → 压缩 → 报告 → 刷新回读。业务状态 `succeeded/complete`，研究错误为空，两个原生 run 均 `success`，两个固定回执均 `completed`。

| 项目                | 已核验结果                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------ |
| thread              | `c468ce34-1b78-4bf9-a5ce-ec817c369292`                                                           |
| research            | `f9c25b2d-1da7-4cc9-b49f-fe4e842afcb9`                                                           |
| 澄清 run            | `d1474ea3-621c-4716-aa23-814d4033dd04`                                                           |
| 补充后研究 run      | `5c263020-b39f-4315-ae37-dec598406583`                                                           |
| 最终固定 checkpoint | `1f1c7d52-afaf-62ee-8009-c0163eca7861`                                                           |
| 成果                | 一个研究员完成、1 份笔记、3 条来源、22 条研究事件、1610 字符报告（正文 568 个汉字）              |
| 正文流              | 1 次写作尝试、103 条正文事件；UUID、序号、UTF-8 offset、归属和最终哈希一致                       |
| 实时首段            | 完整首段截图比模型写作结束早 29.436 秒，已通过严格首段观测                                       |
| 回读                | 报告、来源、配置与固定检查点和刷新前后浏览器一致；始终两个 run，刷新没有新增执行                 |
| 模型 / 搜索         | 模型 15 次 HTTP 尝试：14 次 200、1 次连接失败后恢复；搜索 4 次尝试：3 次 200、1 次连接失败后恢复 |

保留[报告原文](provider-2026-10-14-kimi-full-report.md)与[机器证据](provider-2026-10-14-kimi-full-evidence.json)。原报告 SHA-256：`fc2d4f6985bd1e595ba5466693b4a89205646b93cbbc6740913d402b0b9ab0b3`。

播放器已新增 **Kimi K3 · 完整流程实录** 和“实际报告与来源”章节，并显示验收限定。GLM 失败、旧 Kimi 中断、旧部分完成报告及完整模拟都保留。离线跳章在 Markdown 懒加载完成前滚动的问题已修复；最终 14 项前端回放 / 模拟测试、生产构建、格式检查通过。这个收尾提交没有改研究后端；历史 132 项后端通过记录不等于新修复后的测试结果。

## 待修正问题与代码入口

### 1. 显式 Skills 要求在委派时丢失

**已确认**：用户补充要求和生成的研究简报都包含“先调用 `load_skill`，`skill_name=product-comparison`”；唯一 `delegated` 事件的 `topic` 没有这一要求，后续没有任何 `load_skill` 调用。配置允许该 Skill 不等于实际加载。

入口：

- [multi_agent_supervisor.py](../../src/deep_research/multi_agent_supervisor.py)：`supervisor_tools()` / `investigate()`，目前只把模型生成的 `research_topic` 作为研究员的 HumanMessage 和主题。
- [state_multi_agent_supervisor.py](../../src/deep_research/state_multi_agent_supervisor.py)：`SupervisorState.research_brief`、`ConductResearch`。
- [prompts.py](../../src/deep_research/prompts.py)：`lead_researcher_prompt`、`research_agent_prompt_with_skills`；监督者评估提示词还明确假定研究员只见自己的 `research_topic`，改变上下文契约时一并检查。
- [research_agent_skills.py](../../src/deep_research/research_agent_skills.py)、[skills_loader.py](../../src/deep_research/skills_loader.py)、[product-comparison.md](../../src/deep_research/skills/product-comparison.md)、[run_configuration.py](../../src/deep_research/run_configuration.py)。

**建议方向，尚未实施**：可靠传递用户的全局过程要求与来源限制，同时保留各子任务范围和上下文隔离；不要只针对这道 Python 题硬编码 Skill。检查 Skill 的首次查询模板与用户指定的简单关键词 / `site:` 查询之间的优先级。继续尊重按次配置、手选允许集合及空集合禁用语义；不可通过伪造工具事件或修改旧记录补齐加载成功。

验收：在要求且允许加载的研究中，真实 `load_skill` 成功事件先于首次 `tavily_search`，原简报约束到达研究员；禁用、未知或不允许的 Skill 有明确行为，不静默忽略。

### 2. 两篇指定页面的来源限制没有落实

允许的两页：

1. `https://docs.python.org/3.13/howto/free-threading-python.html`
2. `https://docs.python.org/3.13/howto/free-threading-extensions.html`

**已确认**：第三次检索额外返回并纳入研究来源的是 `https://docs.python.org/3/howto/free-threading-extensions.html`。这是当前版本路径，不等同于固定 3.13 页面；最终报告虽只列两条引用，研究过程中采用的来源已经越界。

入口：[utils.py](../../src/deep_research/utils.py) 的 `tavily_search()` → `deduplicate_search_results()` → `process_search_results()` / `summarize_webpage_content()`；再检查研究约束如何由完整图、主管传入工具，以及 [workflow_contract.py](../../src/deep_research/workflow_contract.py) 的来源提取与归并。

**建议方向，尚未实施**：把明确的来源约束传到实际证据消费环节，使用通用的范围处理，不硬编码这两个 URL。原始搜索命中和最终采用的来源要分别记录：搜索服务可能返回额外链接，范围外命中应保留审计信息，但不能继续进入摘要、研究证据、最终来源与引用。不能靠删改原始 HTTP 日志制造通过。

验收：允许页面用于研究；范围外、错误版本或不合规重定向有可解释处理；无合规来源时诚实说明证据不足，不能让模型自行补链接。

### 3. 最终报告的事实限定与建议需要改进

完整逐项审查见[引用审查](provider-2026-10-14-kimi-full-citation-review.md)。重点包括：

- “其他平台需源码构建”缺乏唯一性依据；源码构建只是其中一种途径。
- GIL 重新启用不能推导出所有工作负载“并行收益归零”。
- 扩展的声明与重新编译不等于完成线程安全适配，仍须审查内部状态和并发访问。
- 借用引用等风险应保留“包含对象可能被并发修改”等条件。
- 约 40% / ≤10% 必须区分 pyperformance 测试范围、工作负载差异与未来目标，不能写成普遍或已兑现的保证。
- 环境变量 / 启动选项不能概括为运行中可“随时”切换；限定页面没有展开的参数语义应明示未知。
- 固定 3.13 文档的历史预期不能直接支持当前“等待 3.14”的建议。
- 扩展兼容性部分宜涵盖来源明确指出的 Limited C API / stable ABI 限制。

入口：[prompts.py](../../src/deep_research/prompts.py) 的 `summarize_webpage_prompt`、压缩提示词及 `final_report_generation_prompt`；[research_agent_full.py](../../src/deep_research/research_agent_full.py) 的 `final_report_generation()`。先核对限定在哪一层丢失，再选最小的通用修复。

验收：新的模型输出保留关键限定，区分来源事实、目标和推断，满足约定篇幅及引用要求；原报告原文和哈希继续保留，修订稿或新一轮报告用新文件 / 新身份保存。

### 4. 在线写作日志短暂回读提示：原因尚未确认

[真实首段截图](screenshots/report-kimi-full-first-paragraph-1440.png)出现“写作记录暂时无法回读，正在重试；已收到的草稿会保留。”最终 103 条日志完整回读，正文与检查点一致，但当时没有保存足够的请求诊断，不能直接归因为网关、HTTP 错误或数据丢失。

入口：[reportReplay.ts](../src/api/reportReplay.ts) 的 `readReportPage()`，[useLiveResearch.ts](../src/state/useLiveResearch.ts) 的报告回放分支及 `reportReplayStates`，[LiveConversation.tsx](../src/components/LiveConversation.tsx)、[LiveReportDraft.tsx](../src/components/LiveReportDraft.tsx)，以及后端 [report_streaming.py](../../src/deep_research/report_streaming.py)、[atlas_api.py](../../src/deep_research/atlas_api.py)。

**待验证假设**：写作刚开始时日志仍为 `missing`、请求超时 / 失败、schema / 归属 / 游标校验失败、客户端保存失败等都会走到相关状态，不能只因捕获了提示就选定某一个原因。下轮保存安全的请求状态、时间与错误类别，结合当时写作身份定位；不要记录凭据、完整私有 payload 或模型推理，也不要通过隐藏提示冒充修复。

验收：合理区分尚未就绪、暂时失败和真实缺口；恢复后状态可清除，已接收草稿保留，刷新 / 重连不新增 run。离线回放跳章滚动已经在 `2d9704a` 修复，不要重复当作这个在线问题处理。

## 复测与保留边界

1. 先检查实际 HEAD / 工作区和上述代码，补充能复现约束丢失、来源过滤、内容限定或回放状态问题的针对性测试。后端可从 [test_full_workflow.py](../../tests/test_full_workflow.py)、配置相关测试和 [test_report_streaming.py](../../tests/test_report_streaming.py) 扩展；前端从 [live-report.spec.ts](../tests/live-report.spec.ts)、[recordings.spec.ts](../tests/recordings.spec.ts) 开始。按改动范围跑检查，报告明确区分替身与真实调用。
2. 修复后用 Kimi 新建隔离研究验收，保留两次提交 / 两个 run 的澄清流程，以及首段提前可见、报告 / 来源 / 配置与检查点一致、刷新零新增执行。不要对这个已完成的 turn 重新走写作恢复。
3. 沿用六个角色 `moonshotai/kimi-k3`、本地 `.env` 的原网关 / 凭据和显式 SOCKS5 `127.0.0.1:55430`。保留 TLS、`NO_PROXY=*`、共享 `AGENT_RPM=30`；在进程中配置代理，不修改生产 `.env`。载入环境后再导入图模块。
4. 不改动共享结构化 fallback、Qwen `/no_think` 及其 payload 诊断。涉及 LangSmith 评估时遵守 `score` / `comment` / `value.individual_evaluations` 契约，检查失败运行和缺失反馈，不能只看退出码。
5. 新建目录和身份记录复测。失败、超时、重试、部分完成和缺失反馈如实保存；不要把成功响应、业务 `succeeded` 或配置允许集合单独当作全部验收通过。
6. 交付修复说明、针对性测试、真实新报告与引用审查、证据包和更新后的验收 / 交接。只有新证据支持时才新增或调整新实录的验收结论，旧实录与旧报告不改写。

## 本机材料与运行注意

以下均位于项目根目录的 `.local/`，不会随 Git checkout 自动携带：

- `kimi-full-20261014/`：首轮 30 分钟未完成，52 次模型 HTTP 尝试，其中 31 次 504；保留研究任务失败与未完成状态。
- `kimi-full-20261014-focused/`：已完成第二轮的 `final.json`、`clarification.json`、`browser-evidence.json`、研究 / 正文事件、HTTP 日志、截图、两篇引用页面及原生 `state/`。
- `kimi-full-closeout-20261014/`：`baseline.json`（92 份原件的哈希及旧实录）、准备 / 导出脚本、最后 14 项前端测试结果、构建与格式结果。
- `exports/atlas-kimi-full-2026-10-14.zip`：43 个文件、4,878,767 字节；SHA-256 `fd93ef79cf097a4095e8ca0dd5e8953b59561a402eb955f31355cb717d7032c9`。旁有 `.zip.sha256`，包内有逐文件 manifest；原生数据库不在包内。

可借鉴 `kimi-full-20261014-focused/driver.mjs` 的完整首段 MutationObserver、回执 / 检查点、日志分页及刷新核验方式。配套 `server.py` / `application.py` / `run.mjs` 有硬编码路径、端口和拒绝复用旧目录的保护；先读再适配到新隔离目录，直接运行旧脚本不是新一轮复测。旧观察器退出码没有强制检查 Skills，下一轮需要明确验证实际事件顺序与全部场景要求。

最后核验时 2039 / 5195、2041 / 5197、5199 端口均空闲。前端首次 Playwright 自启 Vite 在清理阶段未退出，已核对并只停止本轮服务；最终由 `kimi-full-closeout-20261014/run-ui.mjs` 管理独立 Vite 与 Playwright，14 项测试在 21.3 秒内通过，正常清理。复用辅助脚本也要更换输出目录，保留既有证据。
