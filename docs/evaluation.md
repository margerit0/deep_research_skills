# 评估 Runbook

本文是评估系统的操作手册。设计理念与维度矩阵见 [README 的「🧪 评估」段](../README.md#-评估)；这里只讲怎么跑、怎么调参、怎么读结果。

`scripts/` 下有**三套**基于 [LangSmith](https://smith.langchain.com/) 的评估流程，各针对流水线的一个环节，互相独立。每套都遵循同一个「**上传数据集 → 跑评估 → 回读结果**」三件套结构。

## 三套评估一览

| 评估套件 | 评估对象（target） | 数据集（10 条中文用例） | 评分指标 | 脚本目录 |
|---|---|---|---|---|
| **Scoping** | `scope_research`：多轮对话 → 研究简报 | `deep_research_scoping` | `success_criteria_score`、`no_assumptions_score` | `scripts/scoping/` |
| **Research Agent** | `researcher_agent_skills`：端到端走完整「加载 skill → 检索 → 反思 → 压缩」循环 | `deep_research_agent_quality` | `criteria_coverage_score`、`citation_grounding_score` | `scripts/research_agent/` |
| **Supervisor** | `supervisor` 节点**单步**：只评并行委托决策（不真跑子研究员，很轻） | `deep_research_supervisor_parallelism` | `correct_next_step`、`delegation_quality_score` | `scripts/supervisor/` |

## 各指标定义

- **Scoping**
  - `success_criteria_score`（LLM judge）— 逐条判断简报是否覆盖了 ground-truth criteria，得分 = 覆盖条数 / 总条数。
  - `no_assumptions_score`（LLM judge）— 简报是否**只**使用了用户明说过的信息，没有自行脑补假设（布尔，0/1）。
- **Research Agent**
  - `criteria_coverage_score`（LLM judge）— 逐条判断 `compressed_research` 是否覆盖了该用例的 6–8 条研究维度，得分 = 覆盖条数 / 总条数。
  - `citation_grounding_score`（LLM judge）— 从报告抽 5–10 条可验证事实声明，看每条所在句是否带 `[N]` 内联标记且能在 Sources 段找到对应 URL；得分 = 接地条数 / 总条数。**缺 Sources 段直接归零**。
- **Supervisor**
  - `correct_next_step`（**确定性**，不调 LLM）— supervisor 发出的 `ConductResearch` 调用数是否恰好等于期望并行线程数 `num_expected_threads`（对/错 = 1/0）。
  - `delegation_quality_score`（LLM judge）— 委托指令（`research_topic`）的三项检查：完整覆盖问题 / 互不重叠 / 自包含，得分 = 通过项数 / 3。

## 前置条件

`.env` 需配置：

- `LANGSMITH_API_KEY`
- 对应 target 角色的 `{ROLE}_MODEL`（`SCOPING_MODEL` / `RESEARCHER_MODEL`+`SUMMARIZATION_MODEL`+`COMPRESSION_MODEL` / `SUPERVISOR_MODEL`）
- judge 用的 `JUDGE_MODEL`

## 1) 上传数据集（仅首次或数据集变更时）

```bash
cd deep_research_skills

python -m scripts.scoping.upload_scoping_dataset            # 数据集已存在则跳过
python -m scripts.research_agent.upload_research_dataset    # 加 --recreate 先删后建
python -m scripts.supervisor.upload_supervisor_dataset
```

## 2) 跑评估

```bash
# ── 范围界定 ──
python -m scripts.scoping.run_scoping_eval --limit 3        # 先跑前 3 条冒烟
python -m scripts.scoping.run_scoping_eval                  # 全量 10 条

# ── 单体研究员（端到端，最重）──
python -m scripts.research_agent.run_research_eval --limit 1   # 冒烟
python -m scripts.research_agent.run_research_eval             # 全量

# ── supervisor 并行决策（每条仅 1 次 LLM 调用，很轻）──
python -m scripts.supervisor.run_supervisor_eval
```

三个 `run_*` 脚本共享一组 CLI 参数：

| 参数 | 作用 |
|---|---|
| `--limit N` | 只评估前 N 条（冒烟用；默认全量） |
| `--max-concurrency N` | example/agent 并发数。research_agent 走真实 Tavily + 多次摘要，较重，默认 2；scoping / supervisor 默认 1。**上游限流（429/504/空补全）时务必降到 1** |
| `--judge-role ROLE` | LLM-judge 用哪个模型角色。默认 `JUDGE`（即 `JUDGE_MODEL`）；想让 judge 复用 agent 模型可传如 `--judge-role RESEARCHER` |
| `--experiment-prefix` | 自定义 LangSmith 实验名前缀 |

> ⚠️ research_agent 还有独立的 `--judge-concurrency`（judge LLM 全局并发上限，默认 2），与 `--max-concurrency` 解耦——agent 可高并发跑搜索，但 judge 调用另设更低上限，避免多 example 同时判分把网关打到 429。

> ⚠️ judge 角色为何默认走 `JUDGE_MODEL`：若 agent 模型指向 Qwen 等**不支持 `enable_thinking` 参数**的端点，judge 复用它会无法产出 feedback。除非确认端点兼容，否则保持默认。

## 3) 回读结果做诊断

每套都有一个 `fetch_last_*` 脚本，从 LangSmith 拉取**最近一次实验**的逐条结果（含输入、ground-truth、agent 完整输出、每项 judge 的分数与 reasoning、`run_id`），输出 JSON 便于排查或喂给诊断 agent：

```bash
# 只看非满分条目并写文件
uv run python -m scripts.scoping.fetch_last_eval --only-failures --out diag_scoping.json
uv run python -m scripts.research_agent.fetch_last_research_eval --only-failures --out diag_research.json
uv run python -m scripts.supervisor.fetch_last_supervisor_eval --only-failures --out diag_supervisor.json
```

可选参数：`--only-failures`（只输出非满分条目）、`--out FILE`（写文件，默认 stdout）、`--project-name`（指定具体实验，默认取最近一次）。

## 容错说明

- 单条 example 失败（如 Tavily 偶发空响应、网关 5xx 重试耗尽）只 **log 不中断**，批量评估能跑完，失败条目在 LangSmith UI 标红供逐条排查。
- 所有 judge / target 调用都过 `structured_output_fallback` + 退避重试；瞬时故障一般会自愈，持续失败再查端点与限流配置。
