# 示例报告（Examples）

本目录收录由本仓库深度研究智能体 **`research_agent_full`**（Scope → Research → Write 全流程）**自动生成**的完整示例。每份报告都附带一段「**决策与执行轨迹**」，逐一记录流水线里每个 agent 的每一步：

- **Scope**：澄清判断 + 把多轮需求转写成的研究简报；
- **Supervisor**：每一轮的反思（`think_tool`）、把任务拆成了哪几个子课题、是否并行派发、何时判定完成；
- **每个研究员**：负责哪个子课题、按需加载了哪个 skill（`load_skill`）、搜了哪些 query、做了哪些反思。

> ⚠️ 这些报告由模型自动生成、**未经人工校订**，仅用于展示系统能力；事实细节可能有误或过时，请勿作为权威信息引用。运行结果具有随机性（同一简报每次的子课题拆分、检索路径、报告长度都会不同）。

## 目录

| 示例 | 主题类型 | 这一跑展示了 |
|---|---|---|
| [**DeepSeek 360° 全景调研**](deepseek-360.md) | 跨领域综合调研 | Supervisor 把「一家公司的多面调研」拆成 **3 个独立子课题并行**，3 名研究员分别路由到 **3 个不同 skill**（`academic-research` 查论文 / `people-research` 查创始人 / `product-comparison` 做模型对比）——多智能体并行 + skills 按需路由的典型形态 |
| [**冰岛自驾环岛 8 天行程规划**](iceland-self-drive.md) | 生活决策类 | Supervisor 拆成「行程+景点」与「自驾+住宿实务」**2 路并行**，研究员加载 `product-comparison` 方法论检索官方旅游/路况信息，输出带 `[N]` 引用的可执行规划 |

## 这些示例在展示什么

- **Skills 渐进式披露**：研究员先只看到 skills 索引（name + description），需要时才用 `load_skill` 加载完整方法论再开搜——轨迹里的 `📚 加载 skill` 就是这一步。不同子课题会路由到不同 skill。
- **多智能体并行调度**：Supervisor 读完研究简报后决定怎么拆。**是否并行取决于问题形状**——能拆成互相独立的子问题（多对象对比、多个相对独立的侧面）就**并行**派发多名研究员；整体性很强、不宜拆分的题目则交给**单个**研究员深委派（见 `lead_researcher_prompt` 的 Scaling Rules）。两份示例这一跑都触发了并行拆分。
- **引用接地**：报告中的事实尽量带 `[N]` 内联标记，文末附 Sources 段。
- **全过程可观测**：从用户提问到最终成文，每个 agent 的每一步决策都落在「🧭 决策与执行轨迹」里。

## 复现 / 跑自己的主题

```bash
cd deep_research_skills          # 需先配好 .env：各角色模型 + TAVILY_API_KEY

# 跑内置示例
uv run python examples/run_example.py --slug deepseek-360
uv run python examples/run_example.py --slug iceland-self-drive

# 跑自定义主题
uv run python examples/run_example.py --slug my-topic --title "我的标题" --brief "一段研究简报……"
```

产出写到 `examples/<slug>.md`。脚本通过 `astream_events` 还原全流程决策轨迹，并对最终报告调用做了重试。

> ⚠️ 上游网关在突发负载下会限流（429/5xx/超时），**多个示例请串行跑，不要并发**；`.env` 里设 `AGENT_RPM` 可进一步限速。
