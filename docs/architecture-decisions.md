# 研究系统的架构约定

本文保留历史 Skills 交接中仍适用的设计理由，并按当前代码校正。独立 React 前端见 [星图工作台](../frontend/README.md)，真实模式已接入 `research_agent_full`，原有模拟数据和动画演示独立保留。

## 图入口与评估边界

[langgraph.json](../langgraph.json) 注册四个入口：

| 图 ID | 用途 | 导出对象 |
|---|---|---|
| `scope_research` | 澄清需求、生成研究简报 | `research_agent_scope.py:scope_research` |
| `research_agent_skills` | 单个研究员：加载方法论、搜索、反思、压缩 | `research_agent_skills.py:researcher_agent_skills` |
| `research_agent_supervisor` | 多研究员调度 | `multi_agent_supervisor.py:supervisor_agent` |
| `research_agent_full` | Scope → Supervisor → 最终报告 | `research_agent_full.py:agent` |

当前单体研究实现为 Skills 版。各层的评估边界不同：research-agent 评估读取单个研究员的 `compressed_research`；supervisor 评估检查单步委托；完整图输出 `final_report`。单体评估分数不能直接解释为完整报告质量。

研究员节点主要使用同步模型与工具调用；supervisor 通过异步调用组织多个研究员。直接调用完整图时使用 `ainvoke`，不要把早期文档的“全程同步”理解为整个项目的执行模型。

## 工作台的研究与执行边界

一条真实工作台会话对应一个 LangGraph thread。一轮研究可以包含首问和多次澄清回答，因此可以对应多个 LangGraph run。澄清仍使用 `goto=END` 返回问题，后续回答以同 thread 的新输入启动；没有迁移为 `interrupt/resume` 协议。

完整图新增 `prepare_research` 和明确的业务状态。进入新批次时用 `Overwrite` 重置带 reducer 的 `notes`、`raw_notes`、`supervisor_messages`，并清除旧简报、报告、来源、错误和轮次；新的 scoping 上下文仅保留本次问题。只有同批次的澄清续问保留消息历史。旧研究保存在工作台历史中，不参与下一轮研究提示词。

`research_status` 区分运行、等待补充、成功、失败、部分完成。报告必须有 `report_research_id` 归属，前端还核对当前 turn，以排除尚未重置的旧检查点。执行异常可以由节点转换为安全的业务失败，所以 API run 的成功不能直接映射为 UI 研究成功。来源从真实 `tavily_search` 工具消息中提取，LLM 自己生成的链接不会冒充检索来源。

前端使用版本 1 的显式接口契约，先落盘提交标识，再创建后台 run。未知提交结果只按 metadata 回读，不自动重发；同 thread 使用 `multitask_strategy=reject`。这是本轮的重复提交防护，不是完整断线恢复或跨标签页协同协议。标准 API 没有客户端指定 run ID 的契约，因此没有假定原生 POST 幂等。

主图阶段、实际简报和报告继续从检查点读取；研究员数量与任务细节由原生 `custom` 事件流驱动。每次实际委派有独立任务标识和协调轮次，覆盖并行与后续追加任务。真实模式模型来自后端模型工厂的实际构造快照，Skills 由研究员自动加载；模拟菜单的值不传给后端。接口细节见 [后端接口约定](../frontend/docs/backend-contract.md)。

## 研究员进度与最终结果分开处理

父图的研究节点要等整个协调子流程返回后才写检查点，因此单靠主图轮询无法展示中途检索。`research_events.py` 在一次父节点调用内建立记录器，用 ContextVar 将记录器与任务身份传给并行协程及同步工具线程，同时发布原生 SSE 并保留安全事件。独立研究员图及评估输出保持原约定，提示词和模型配置没有加入遥测对象。

研究员完成、工具返回、SSE 结束和完整研究成功是不同层次的状态。客户端只用事件更新任务节点与检查器，最终业务结果仍依据 run、`research_status` 和报告归属。失败事件保留成功兄弟任务；没有确认终态的节点不显示成功。

事件正文只含任务、查询 / Skills 名称、阶段、时间、来源和压缩笔记；排除模型推理、原始工具正文与异常响应。记录器给并发事件分配统一顺序，每个事件有独立 UUID；客户端校验研究 / 提交 / run 归属并去重，演示状态与真实事件继续隔离。

子流程返回时把事件列表写入父检查点，新研究清空该列表。父节点完成前的持久化由下面的事件日志承担；原生缓冲与浏览器缓存继续用于实时显示和去重。

## 事件日志与执行恢复分开

锁文件对应 LangGraph 1.1.3、API 0.8.7、inmem runtime 0.28.1、CLI 0.4.26。已核对运行时实现：SSE `message_stores` 是内存列表，原生 `PersistentDict` 另有约 10 秒的刷盘周期。父研究节点返回前的事件无法仅靠 `durability=sync` 或保存 `Last-Event-ID` 保证跨进程回放，因此保留原生 SSE，并增加最小的 SQLite 安全事件日志及只读分页接口。

`event_journal.py` 按 thread / run 保存归属、事件 UUID、递增序号、日志 UUID 和关闭 / 缺口标记。先提交日志，再发布事件；WAL 与 FULL 同步保护已提交事务，同进程建库串行化，事件追加使用 SQLite 事务。失败不会中止研究，界面据缺口标记保留已知成果并说明不完整。保留期和存储路径属于后端配置，不暴露给浏览器。

本地进程身份用于识别旧捕获过程，新的子流程调用也隔离任务 ID。旧任务没有完成或失败证据时不会继续显示为执行中；原生 run 和检查点仍是业务状态来源。`sealed` 仅说明事件捕获结束。强制停止测试已验证：研究工具执行中、父检查点尚无事件时，重启能够回放已提交事件，而原生 run 可能仍标为 `running`、并未实际续跑。

浏览器按后端地址、thread、research、turn、run 保存 SSE 游标和独立的业务恢复序号。事件与恢复位置原子写入同一份本地会话，写入失败保留内存内容但不推进位置；检查点回读与事件合并互不覆盖。退避重连和分页回放只观察已有运行，演示继续隔离。旧后端和旧缓存通过可选能力、默认值及单独丢弃无效位置保持兼容。

这项选择仅面向单进程本地开发，不将 SQLite / 进程身份当作多实例协调或共享部署协议。下一批另行建立幂等受理和经过验证的检查点执行恢复；逐 token 报告与按次模型 / Skills 也仍在后续范围。

## Skills 按需加载

[skills_loader.py](../src/deep_research/skills_loader.py) 在模块导入时扫描包内 `skills/*.md`，形成元数据和正文快照。系统提示词只包含名称与描述索引，模型通过 `load_skill` 获取所需正文，减少无关方法论占用上下文。

每份 skill 的 frontmatter 至少包含 `name`、`description`，且 `name` 必须等于文件名主干。格式有误的文件会记录 warning 并跳过；整个目录缺失则报错。未知 skill 名会返回错误说明及可选名称，便于模型重新选择。

Skills 位于 Python 包内，并通过 `pyproject.toml` 的 package-data 随包安装。增加新文件时检查打包结果和索引；修改磁盘文件后需要重启进程才能刷新导入时的快照。

## 研究证据与方法论分开处理

[research_agent_skills.py](../src/deep_research/research_agent_skills.py) 构造 `raw_notes` 时保留 AI 消息和 `RESEARCH_TOOL_WHITELIST` 中工具的消息。目前工具白名单只有 `tavily_search`，`load_skill` 与 `think_tool` 的工具正文不进入这些原始笔记。

新增检索工具时，需要同时检查白名单及 `_has_real_search_results()` 的判断；仅把工具挂到模型上还不够。压缩模型仍读取研究对话，不能把 `raw_notes` 的过滤描述为所有模型输入都已经过滤。

无搜索结果或压缩结果为空时，会返回明确的研究未完成标记。这是对下游界面和调度的失败信号。压缩模型与最终报告模型已有有限重试，早期交接中的“待增加压缩重试”已不适用。

## 提示词的约束

- 研究 brief 保留用户明确表达的需求；当前日期只提供背景，不应自动变成用户未提出的筛选条件。
- 枚举与多实体比较先覆盖所有类别或实体，再深入局部，避免反复研究少数对象。
- 官方页面无法提供可提取的具体数据时，可以寻找可信第三方来源。该策略仍需给出证据与引用，不能把未核实数据包装成事实。
- 报告中的具体事实使用编号引用，并在 Sources 段映射到来源。质量评估同时检查覆盖与引用，不能只看报告长度。

提示词调整的历史证据与局限见 [评估记录](evaluation-history.md)，运行与兼容性约定见 [维护说明](maintenance.md)。
