# 新窗口交接：P0 事实限定与 DeepSeek 思考实验

记录日期：2026-10-16。用户要求先保存进度，后续新窗口继续。本窗口已停止模型验收与专用服务，不要把磁盘上的旧 `running` 状态当作仍在执行。

## 接手时先知道这些

- 工作区：`D:\deep_research_public_preview`，PowerShell。分支 `chore/public-edits`，HEAD `67ed6f619d80e395be6b5d74e65887c05a0c1f7b`。全部修改未提交、未推送。
- 原任务来自聊天 `codex://threads/01a13f94-bc82-7a60-8172-92c245f7df5c`，本窗口继续实现并验收 P0；无需重新做已经完成的来源传递实现。
- **用户已选择继续现有 `deepseek-v4.1-flash` 配置，并建议尝试开启思考。** 不要再次询问模型选择，不切回 Kimi。此前原网关 Kimi 返回上游 410。
- **P0 仍未完成。** 最近完成的 `m` 轮为 `succeeded/complete`、500 汉字、全部机械检查与原生模型核验通过，但独立内容检查仍有两项问题。修正后的 `n` 轮按用户要求中断，最终代码尚无完整原生内容通过证据。
- 本地生产 `.env`、凭据、代理、TLS、共享结构化 / Qwen fallback 和旧报告／实录／数据库保留。保护清单 436 个旧文件哈希未变。
- 先读本文件，再读 [结果记录](p0-fact-fidelity-results-2026-10-16.md)、[维护说明](../../docs/maintenance.md) 和 [架构约定](../../docs/architecture-decisions.md)。遵守根目录 `AGENTS.md`。旧 `.local` 材料是证据，不是另一个待实现计划。

## 不可放宽的验收条件

使用原始两轮输入、新隔离身份，从界面发起真实完整流程。不得把独立改稿、写作节点单独重放、人工纠错内容或测试替身当成原生通过；不能注入 Python 场景答案清单。任何生产代码修改后，需要新的最终代码原生验收。

原始输入已固定在各轮 `inputs.json`，准备脚本从旧已审查 harness 提取并校验 SHA-256：

1. `请帮我做一项对比研究。`
2. `比较 Python 3.13 实验性的 free-threaded CPython 与默认 GIL 构建，帮助开发者判断是否试用。仅比较 GIL 状态、C 扩展兼容性、适用限制三个维度，给出约 500 字中文报告和编号引用。研究员必须先调用 load_skill 工具，skill_name 使用 product-comparison，再进行真实检索。资料范围固定为两篇官方指南：https://docs.python.org/3.13/howto/free-threading-python.html 和 https://docs.python.org/3.13/howto/free-threading-extensions.html；请用简单的关键词或 site: 查询检索这两页，不扩展到长篇版本更新汇总或历史提案。只依照这两页给出可核验的试用建议，说明 GIL 运行时开关及不兼容扩展的处理；证据不足时明确说明，不编造。范围已明确，不需要再次澄清。`

正文按来源章节之前的 `[\u4e00-\u9fff]` 计数，**400–650 汉字**。同时要求：

- 只采用两条精确版本 URL；研究员在模型／检索前实际加载 `product-comparison`。
- 保留会改变结论的条件、例外、历史时间属性；约 40% 开销须带 pyperformance／默认构建基线和 C 扩展、I/O 例外。历史展望不是今天的承诺。
- 扩展声明或编译成功不能代替实质线程安全／内部状态审查；风险充分条件不能写成唯一风险条件；回退 GIL 不保证其他问题都消失。
- 两页没有提供的开关取值或任意运行中切换行为必须明确为证据缺口，不编造操作命令。次要 API 可删；保留则所有条件、检测对象和语义必须准确。
- 最终稿对应独立 writing attempt；检查点、正文 UTF-8 偏移、事件顺序与 SHA-256 完全一致。
- 完整首段在对应写作尝试结束前可见且有截图；刷新不新增执行；没有未解释的恢复提示／浏览器错误。
- 原生模型核验的 `passed=true` 不能代替独立逐句来源检查。机械通过也不等于内容通过。

## 已完成的实现

主要源码：

- `source_evidence.py`：捕获实际消费正文／片段，绑定精确 URL、来源方式、完整正文哈希、长度、起止位置和截断标记。每来源最多 24000 字符、写作合计最多 48000；并发上下文隔离，同 URL 的不同正文版本保留。
- `utils.py`、`research_agent_skills.py`、`multi_agent_supervisor.py`、三个 state 模块：证据独立于派生笔记传至写作；压缩只读取实际检索结果、子任务及要求，排除模型自述／方法论；原追溯笔记格式保留。
- `research_agent_full.py`：全部采用来源完整落入预算时直接依据正文写作；短报告使用简洁模板；原生核验和一次修订后才提交最终报告。
- `report_review.py`：使用同一 FINAL_REPORT 角色，严格 `passed: bool` 与 `issues: list[str]`；复用共享 helper 的 JSON/schema 提示构造，兼容客户端显式请求 `json_object`；不追加格式修复调用、不自动修补含糊 JSON。程序单独计数，非法或不可用核验不能通过。
- `ReportReviewFormatError` 保存可见响应 SHA-256、字符数、结束原因和错误类型；不保存响应正文、校验输入或思考内容。SDK 的 `LengthFinishReasonError` 也转为这个安全诊断。
- `report_streaming.py`：最多两次语义核验／一次修订，传输与修订共用三次生成上限，各草稿独立身份并保留。`finished` 只是输出完成，终态报告另行绑定通过稿。
- `model_transport.py`：主管和缓冲核验遇到三类读流异常最多额外重试一次；不重试 403 等 HTTP 拒绝，不派发半截工具参数。
- `submission_journal.py`：证据与核验记录纳入恢复摘要，旧检查点缺字段时仍兼容，新研究清空；重复提交不重写。

本实验 SDK 最多五次 HTTP 尝试；写作节点最多三次生成加四次核验读取，即 **35 次 HTTP 尝试上界**。其他角色／搜索的既有上限另计。没有增加无界模型纠错循环。

最新仅改通用提示的两点已存在源码中：分别说明接口／指标检测的是能力、配置还是当前运行状态；试用建议明确实质安全适配与内部状态审查，不能用声明、构建成功、性能或并发测试替代。不要再重复添加。

## 思考实验结论与最新身份

以下目录都在 `.local/`，前缀 `p0-fidelity-20261015-`；每轮保留原始输入、源码快照、请求统计、实际来源／摘要／写作输入与独立数据库。

| 后缀                          | 思考配置                      | 结果                                                                            |
| ----------------------------- | ----------------------------- | ------------------------------------------------------------------------------- |
| `thinking-deepseek-20261016j` | 写作 high，核验 high          | 草稿 470 汉字；研究员失败；核验零可见输出、`length` 截断                        |
| `thinking-deepseek-20261016k` | 写作 low，核验 low            | 草稿 464／517 汉字；首轮核验有效 JSON 并触发修订；复核零可见输出、`length` 截断 |
| `thinking-deepseek-20261016l` | 原计划 high／low              | 仅准备，没有执行，不计入验收                                                    |
| `thinking-deepseek-20261016m` | 写作 high，核验 disabled/none | 500 汉字；业务、全部机械检查和原生核验通过；独立内容检查不通过                  |
| `thinking-deepseek-20261016n` | 同 m，加载最新通用提示        | 研究阶段按用户要求交接而中断，无报告；不是自然失败，也不是通过                  |

思考参数只由隔离 harness 绑定到 FINAL_REPORT 的写作／核验调用，**没有写入生产 `.env`，也没有进入原有配置归档字段**。下次直接启动普通后端不会自动得到该实验配置。沿用现有模型、网关／凭据、SOCKS5 `127.0.0.1:55430`、TLS、`NO_PROXY=*`、`AGENT_RPM=30`。其他五个角色未显式开启思考：官方工具模式要求回传 `reasoning_content`，现有 ChatOpenAI 不保留该字段，不要直接全局开启。

`thinking-streams.jsonl` 只记录推理字段是否出现、可见 chunk 数和结束原因，关联 `model-http.jsonl` 的请求 ID。`m` 中写作确实返回推理字段，核验请求为 `thinking.type=disabled`、`reasoning_effort=none`，响应未带推理。短探测也证明原网关接受该开关；不能推断思考对所有任务都更好。

`m` 是最接近通过的完整原生轮次：

- thread：`fbb29c17-b8d6-404a-b4cd-ed9cc897437a`
- research run：`b483d836-0863-43a3-bd43-0b047f72ba96`
- writing attempt：`769ad48f-55da-4f7d-bee4-22031aadfa23`
- 报告 SHA-256：`4d0f67b58dd93fe6eb8217ff4b5c923549c1cab7efee24f406bc6b6a9eddba17`
- `report.md`、`mechanical-verification.json`、`content-review.json` 可直接读；后者明确为 false。
- 剩余问题：把 `python -VV`、`sys.version` 与 `sys._is_gil_enabled()` 合并描述为判断“实际状态”，未区分构建能力和当前 GIL 状态；建议的明确前提只有扩展声明／单独构建，未清楚要求实质安全和内部状态审查。不要因 500 字／模型核验通过就忽略。
- 当时所有机械检查通过；后续生产提示已改，不能将这份机械结果冒充当前源码验收。

`n` 的停止现场：

- thread：`880899c1-855c-4b37-b8ac-d8727aad3806`
- run：`679eaf39-3c75-4eb1-9304-6e1513dca7b4`
- `handoff-snapshot.json` 保存 `running/research`，无最终报告；`handoff-events.json`、`handoff-report-events.json` 和 `interruption.json` 一并保留。
- 已核实命令行并停止本轮后端 PID 36528、观察器 PID 6756 及其专属浏览器子进程；原运行器保存日志并清理前端，2071/5229 均释放。
- `run-result.json` 的非零退出来自人为停止，必须与 `interruption.json` 一起理解。不修改旧状态来伪造失败或完成。
- `supervisor_subgraph` 中途退出不能安全从任意工具续跑。下次使用新身份，不重用 n 目录／原 run。

## 已通过的检查

- 全量后端：196 passed，28.94 秒，`.local/p0-fact-fidelity-20261015/pytest-thinking-length-final-20261016/`。随后仅调整通用提示。
- 最后提示后的针对性核验／完整图回归：40 passed，16.76 秒，`.local/p0-fact-fidelity-20261015/pytest-thinking-final-constraints-20261016/`。
- Ruff `--select F --no-cache` 和 `git diff --check` 通过。
- 先前修订机制加入后的 15 项原生替身回归通过：13 提交／配置／写作恢复、1 live-api、1 recovery；见 `.local/p0-fidelity-20261016/native-reviewed/result.json`。这 15 项早于本次思考／格式诊断改动，没有假称已重跑。
- 保护清单 `.local/p0-fact-fidelity-20261015/preservation-baseline.json` 的 436 个文件未变。原有 `handoff-next-planning-2026-10-15.md`、`next-steps.md` 和 `handoff-p0-fact-fidelity-2026-10-15.md` 的用户改动保留。

## 新窗口下一步

先检查当前工作区和端口，不改动 `.env` 或旧目录；确认没有新用户改动。当前没有后台执行需要接管。首要动作是在最新代码下完成一轮原始输入验收，建议沿用 **high 写作／非思考 JSON 核验**，不要先重写已有实现。

示例使用尚未用过的 o 标签和新端口；若已存在，换全新标签／端口，不删除或复用：

```powershell
Set-Location D:\deep_research_public_preview
git status --short
Test-Path .local/p0-fidelity-20261015-thinking-deepseek-20261016o
.venv/Scripts/python.exe -X utf8 .local/p0-fact-fidelity-20261015/prepare.py thinking-deepseek-20261016o 2072 5230 deepseek-v4.1-flash thinking-final high none
node.exe .local/p0-fact-fidelity-20261015/run.mjs thinking-deepseek-20261016o
```

启动真实 harness 在此 Windows 沙箱通常需要 `require_escalated`（Vite 的临时配置文件权限）；这是执行权限问题，不是重新征求模型／任务授权。原运行器启动专属隐藏后端、Vite 和无头真实 Chrome，最多观察 30 分钟，后端保护期限 1950 秒。不要创建新的用户聊天／自动化替代当前任务。

完成后检查 `run-result.json`、`final.json`、`report_reviews`、`research_errors`，以及实际报告。若有终态报告，运行：

```powershell
.venv/Scripts/python.exe -X utf8 .local/p0-fidelity-20261016/verify_native_result.py p0-fidelity-20261015-thinking-deepseek-20261016o
```

再根据本轮 `stages/consumed-source-*.json` 中的实际消费正文独立逐句核对所有保留断言。检查两项最新修复及其他既定条件，不能只核对关键词。没有报告时直接检查草稿／核验错误，不把机械脚本的 false 当作新根因。

继续保留失败身份与草稿，运行 `archive_drafts.py` 导出逐字节草稿。`evidence_inventory.py` 的轮次列表和测试 XML 路径目前显式列举，新增轮次后需要更新；`content-review-final.json` 目前为 false。只有最终代码原生业务、机械及独立内容核对都通过，才能改为 true 并关闭 P0。随后更新结果记录和验证文档；一次通过不宣称稳定性已证明，P1 对照与 P3 新实录仍后置。

手工改文件优先 `apply_patch`。若遇 Windows sandbox refresh 错误，先验证文件可写，再做窄范围 PowerShell 修改并看 diff；不要盲目重复 patch。始终遵守现有 Qwen `/no_think` 与 `choices=null` 共享回退，不改凭据，不输出私有推理，不创建未授权子代理。
