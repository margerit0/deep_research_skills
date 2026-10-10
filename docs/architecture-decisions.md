# 研究系统的架构约定

本文保留历史 Skills 交接中仍适用的设计理由，并按当前代码校正。它描述现有后端，不代表已实现新的 React 界面。

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
