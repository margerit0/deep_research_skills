# Scoping Agent 评估方法

本文档说明 **范围界定 agent (scoping agent)** 是如何被评估的:为什么这么评、评什么、怎么跑、结果怎么解读、以及如何扩展。

---

## 1. 被评估的 agent

`scope_research` (见 `src/deep_research/research_agent_scope.py`) 是一个两节点的 LangGraph workflow:

```
       ┌────────────────────┐         ┌──────────────────────┐
START → │ clarify_with_user  │ ─yes──→ │ write_research_brief │ → END
       └────────┬───────────┘         └──────────────────────┘
                │ no (问澄清问题)
                └──→ END
```

- **`clarify_with_user`**: 看完用户的对话历史后决定是 "信息够了" 还是 "需要再问一句"。若需要澄清,直接 `END` 并把澄清问题写入 messages;若信息足够,流向下一节点。
- **`write_research_brief`**: 把完整对话压缩成一份 **research brief**,作为下游研究 agent 的根本指令。

这个 agent 的输出有两种形态:**澄清问题** 或 **研究简报**。本评估方案只针对后者——研究简报的质量。

---

## 2. 评估范围 (Scope of evaluation)

| 维度 | 是否覆盖 | 备注 |
|------|---------|------|
| 研究简报是否完整保留用户需求 | ✅ | 评估器 1:`evaluate_success_criteria` |
| 研究简报是否引入用户没说过的假设 | ✅ | 评估器 2:`evaluate_no_assumptions` |
| 澄清问题的 **时机** 判断是否合理(该问 / 不该问) | ❌ | 本数据集每条都是 "信息已经齐全",触发的全是 brief 路径 |
| 澄清问题的 **质量**(措辞、覆盖度) | ❌ | 同上 |
| brief 的语言一致性、长度、可读性 | ❌ | 当前未建模 |
| 下游研究 agent 在该 brief 下的最终报告质量 | ❌ | 属于端到端评估,不在本文档范围内 |

**核心结论**: 本评估回答的问题是 *"agent 能不能把对话忠实压缩成一份既不漏又不编的 brief"*,不回答 *"agent 该不该开口问澄清"*。

---

## 3. 数据集 (Dataset)

### 3.1 位置

- LangSmith 上的数据集名: `deep_research_scoping` (可通过 `LANGSMITH_DATASET` 环境变量覆盖)
- 本地源代码: `scripts/upload_scoping_dataset.py` 中的 `TEST_CASES` 列表

### 3.2 结构

10 个用例,每个用例包含两部分:

```python
{
    "conversation": [
        HumanMessage(...),   # 1) 用户的模糊请求
        AIMessage(...),      # 2) agent 提出的澄清问题
        HumanMessage(...),   # 3) 用户给出的具体条件
    ],
    "criteria": [
        "...",  # 第 3 步里用户**明确**说过的每一条事实
        "...",
    ],
}
```

`conversation` 是评估时喂给 agent 的 **input**;`criteria` 是 ground truth,代表 brief **必须保留** 的事实清单。

### 3.3 覆盖的主题

10 个用例尽量覆盖不同的领域和约束类型:

| # | 主题 | 典型 criteria |
|---|------|--------------|
| 1 | 退休投资 | 年龄、风险偏好、账户类型 |
| 2 | 纽约公寓 | 街区、户型、月租、入住时间 |
| 3 | 笔记本电脑 | 用途、预算、OS、重量 |
| 4 | 日本旅行 | 日期、预算、城市、兴趣 |
| 5 | 婚礼场地 | 日期、人数、户内外、停车 |
| 6 | 转行机器学习 | 背景、时间、目标岗位、预算 |
| 7 | 周年纪念晚餐 | 城市、菜系、人均预算、忌口 |
| 8 | AWS 认证 | 经验、目标岗位、预算分担 |
| 9 | 二手车 | 总价、车型、里程、配置 |
| 10 | 编程语言选型 | 项目类型、性能要求、团队栈 |

---

## 4. 评估方法论

### 4.1 LLM-as-judge

两个评估器都用 LLM 充当 judge。判定原则参考 [Hamel 的 LLM-as-judge 实践](https://hamel.dev/blog/posts/llm-judge/index.html):

- **角色定义**: prompt 中明确 judge 的身份 (例 "资深研究简报评估专家")
- **二元判定**: PASS/FAIL 或 CAPTURED/NOT CAPTURED,**不做多维主观打分**,因为后者跨次一致性差
- **结构化 XML 提示词**: 用 `<role>`/`<task>`/`<criterion_to_evaluate>` 等标签分块,降低歧义
- **示例驱动**: prompt 内嵌正反例,锁定 judge 的判定边界
- **保守倾向**: prompt 中规定 "存疑时倾向于 NOT CAPTURED / FAIL",避免乐观偏差

### 4.2 为什么要有 ground truth criteria,不能让 judge 自由打分?

> 给 judge 一份明确的 `criteria` 列表后,任务从 "判断 brief 好不好"(开放性) 降级为 "判断 brief 是否包含 X"(闭合二元)。
> 二元判断的跨次一致性远高于主观打分,这也是同一份 brief 多次评估能得到稳定结果的前提。

详细对比可参考评估器 prompt 中的 `<evaluation_examples>` 节。

### 4.3 一致性 vs. 强度的权衡

`evaluate_success_criteria` 把每条 criterion **单独** 评(`batch_invoke_with_structured_output_fallback`),不让 judge 一次性给整体打分。原因:

- 单条评估的任务复杂度低 → 即使用便宜模型也能稳定
- 整体打分需要 judge 同时记忆所有 criteria,容易漏 / 错配
- 单条结果可解释(每条都有 reasoning),失败时能精确定位 brief 漏了什么

---

## 5. 评估器详解

### 5.1 评估器 1:`evaluate_success_criteria` (覆盖度)

**位置**: `scripts/run_scoping_eval.py:110-155`

**Prompt**: `BRIEF_CRITERIA_PROMPT` (见 `src/deep_research/prompts.py:454`)

**输入**:
- `outputs["research_brief"]` — agent 生成的简报
- `reference_outputs["criteria"]` — 标准答案列表

**做什么**:

1. 对 `criteria` 列表中的每一条,单独构造一个 prompt,让 judge 判断 brief 是否覆盖
2. judge 返回 `Criteria { criteria_text, reasoning, is_captured: bool }`
3. 汇总: `score = captured_count / total_count`,范围 `[0.0, 1.0]`

**LangSmith 字段名**: `success_criteria_score` (1.0 = brief 完整覆盖,0.0 = 全部漏掉)

**附带数据**: `individual_evaluations` 列表,每条 criterion 都有独立的 reasoning,LangSmith UI 上可下钻查看 judge 为什么这么判。

### 5.2 评估器 2:`evaluate_no_assumptions` (反幻觉)

**位置**: `scripts/run_scoping_eval.py:157-176`

**Prompt**: `BRIEF_HALLUCINATION_PROMPT` (见 `src/deep_research/prompts.py:519`)

**输入**: 同上

**做什么**:

1. 把整份 brief 和 criteria 列表一起喂给 judge
2. judge 判定 brief 是否引入了用户**未明确提及**的偏好/约束/受众
3. 返回 `NoAssumptions { no_assumptions: bool, reasoning: str }`

**LangSmith 字段名**: `no_assumptions_score` (True = brief 没幻觉,False = 引入了用户没说过的东西)

**典型失败案例**(摘自 prompt 中的 examples):

- 用户只说 "在旧金山找咖啡馆" → brief 写成 "为旧金山的**年轻职场人士**找**时尚**的咖啡馆" → FAIL (受众和风格都是 agent 自己加的)

---

## 6. 评分解读

### 6.1 单次实验的分数含义

| 指标 | 满分 | 含义 |
|------|------|------|
| `success_criteria_score` | 1.0 | brief 完整保留了所有用户需求 |
| `no_assumptions_score` | True (1) | brief 没有引入用户未提及的假设 |

10 条 example 跑完后,LangSmith 会显示平均分。**两个指标需要联读**:

- **高覆盖 + 高反幻觉**: 理想态——brief 既全又准
- **高覆盖 + 低反幻觉**: agent 写得太"卖弄",加了不该加的东西
- **低覆盖 + 高反幻觉**: agent 过于保守,漏掉了用户给的细节
- **低覆盖 + 低反幻觉**: agent 偏离了对话内容,既漏又乱

### 6.2 跨实验对比

每次 `client.evaluate(...)` 会创建一个新的 **实验** (实验名前缀通过 `--experiment-prefix` 控制)。LangSmith UI 支持把多个实验并排对比,适合的场景:

- 改了 prompt 后看是否真的提升了分数
- 换了底层模型(便宜的 vs. 强的)看是否还能维持质量
- 用 `--judge-role` 切换 judge,验证 judge 自身的稳定性

---

## 7. 操作流程

### 7.1 前置条件

`.env` 文件需包含:

```bash
LANGSMITH_API_KEY=ls__...
LLM_PROVIDER=openai             # 或 anthropic、modelscope 等
LLM_BASE_URL=https://...        # 可选,OpenAI 兼容网关时填
LLM_API_KEY=sk-...              # 可选,不填则用 provider 默认 env
SCOPING_MODEL=gpt-4.1           # 必填:scope agent 用哪个模型
# 可选:让 judge 用不同模型 (配合 --judge-role JUDGE 使用)
JUDGE_MODEL=claude-opus-4-7
```

### 7.2 完整流程

```bash
cd deep_research_skills
source .venv/Scripts/activate

# 1) 上传数据集 (只需第一次, 之后改用 --recreate 覆盖)
python -m scripts.upload_scoping_dataset

# 2) 小规模冒烟 (验证流程通不通, 省 token)
python -m scripts.run_scoping_eval --limit 2

# 3) 全量评估
python -m scripts.run_scoping_eval

# 4) 迭代 prompt 后再次评估, 用不同 prefix 便于对比
python -m scripts.run_scoping_eval --experiment-prefix "v2-tighter-prompt"
```

### 7.3 查看结果

LangSmith UI: <https://smith.langchain.com/>

进入 `deep_research_scoping` 数据集 → Experiments 标签 → 选中一次实验 → 可看到:

- 每条 example 的输入(对话)、agent 输出(brief)、两个评分
- 点击某条评分 → 看到 judge 的完整 reasoning
- 多个实验勾选后 → 并排对比分数和 trace

---

## 8. 文件清单

| 路径 | 角色 |
|------|------|
| `src/deep_research/research_agent_scope.py` | scope agent 实现,导出 `scope_research` |
| `src/deep_research/prompts.py:454` | `BRIEF_CRITERIA_PROMPT` (评估器 1 的 judge prompt) |
| `src/deep_research/prompts.py:519` | `BRIEF_HALLUCINATION_PROMPT` (评估器 2 的 judge prompt) |
| `src/deep_research/model_config.py` | 统一模型工厂 `get_chat_model(role)` |
| `src/deep_research/structured_output_fallback.py` | 结构化输出的 fallback 实现(兼容多 provider) |
| `scripts/upload_scoping_dataset.py` | **创建并上传数据集**(含 10 个中文用例) |
| `scripts/run_scoping_eval.py` | **触发评估实验**(含两个评估器) |
| `docs/scoping_evaluation.md` | 本文档 |

---

## 9. 扩展指南

### 9.1 加新的测试用例

编辑 `scripts/upload_scoping_dataset.py` 的 `TEST_CASES` 列表,追加新的字典即可。**注意保持结构**:

```python
{
    "conversation": [
        HumanMessage(content="模糊请求"),
        AIMessage(content="澄清问题"),
        HumanMessage(content="具体条件——这里出现的每个事实都要进 criteria"),
    ],
    "criteria": [
        "事实 1",
        "事实 2",
        # ...
    ],
}
```

然后跑:

```bash
python -m scripts.upload_scoping_dataset --recreate
```

`--recreate` 会先删后建,避免和老数据集冲突。

### 9.2 调整评估标准 (改 judge 行为)

**不要**改 `scripts/run_scoping_eval.py`,改 `src/deep_research/prompts.py`:

- 想让 judge 更严:在 `BRIEF_CRITERIA_PROMPT` 的 `<evaluation_guidelines>` 中收紧 CAPTURED 的条件
- 想让 judge 更宽容:增加 "等效概念也算覆盖" 这类条款
- 想让 judge 检查新维度(比如语言一致性):**不要硬塞进现有 prompt**,新建一个 prompt + 评估器更干净

### 9.3 加新的评估维度

例如想加 "brief 的简洁度评估":

1. 在 `prompts.py` 加新 prompt 例如 `BRIEF_CONCISENESS_PROMPT`
2. 在 `scripts/run_scoping_eval.py` 加一个 schema (例 `Conciseness(BaseModel)`) 和一个评估函数 `evaluate_conciseness`
3. 把它追加到 `client.evaluate(evaluators=[...])` 的列表里

LangSmith UI 会自动新增一列指标,无需额外配置。

### 9.4 换 judge 模型

不需要改代码,改 `.env` + CLI:

```bash
# .env
JUDGE_MODEL=gpt-5            # 或 claude-opus-4-7 之类更强的

# 命令行
python -m scripts.run_scoping_eval --judge-role JUDGE
```

`get_chat_model("JUDGE")` 会自动读取 `JUDGE_MODEL` 环境变量。这种 "agent 用便宜模型 + judge 用强模型" 的组合在 prompt 迭代期特别有用。

---

## 10. 已知局限

1. **不评估澄清逻辑本身**: 当前 10 条 example 全是 "信息已经齐全 → 走 brief 路径" 的场景。要测 "是否该问澄清",需要新增 "模糊一次性请求" 类型的 example 和一个新评估器(标注 `should_clarify: True/False`,然后比对 agent 行为)。

2. **judge 自身的可靠性未做交叉验证**: 当前实验里 judge 的判断被视为可信。如要进一步验证,可以:
   - 人工抽检 10-20 条 judge 评判,看一致率
   - 或者用多个不同 judge (`--judge-role` 切换) 跑同样的实验,看分数稳定性

3. **数据集规模偏小**: 10 条 example 跑出的分数方差较大,适合开发期快速对比 prompt 改动,但不足以作为发布门槛。如要做 release gate,建议扩到 50-100 条并人工 review 一遍 criteria 标注质量。

4. **`criteria` 标注是人工写的**: 这就是 ground truth 的本质,但也意味着标注者的偏见会传到 judge 评分里。建议关键场景下 2 人独立标注 + 互查。

5. **不评估 brief 转化为最终报告后的实际效果**: brief 写得好 ≠ 下游研究 agent 能用它产出好报告。端到端评估需要单独设计。
