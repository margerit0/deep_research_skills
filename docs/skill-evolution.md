# 评估驱动的 Skill 持续优化

首版只处理 `product-comparison`，提供后端、CLI、SQLite 追溯记录和 Markdown 报告。流程是：开发集失败证据 → 可反驳的归因假设 → 最多两个候选 → 选择集配对比较 → 冻结一个候选 → 最终测试 → 显式晋升／回退。每个实验只允许一轮改进；没有自动循环或自动晋升。

**2026-10-29 本轮只实现代码和确定性检查。没有运行诊断模型、生成候选、judge、真实搜索、离线／回放评估或模拟进化实验。没有实验分数或端到端效果结论。** 单元测试中的小型数据仅验证程序逻辑。

## 文件与复用关系

| 文件 | 职责 |
| --- | --- |
| `src/deep_research/skill_evolution.py` | 严格数据契约、数据集隔离、候选校验、用户约束检查、确定性门槛 |
| `skill_evolution_models.py` | 诊断／候选提示词、独立来源支持度接口；全部调用共享 structured fallback |
| `skill_evolution_runner.py` | 版本固定、显式导入、阶段执行、配对比较、冻结、报告 |
| `skill_evolution_trace.py` | 仅在显式作用域内记录查询、工具结果、实际 Skill 加载与来源范围审计 |
| `skill_evolution_accounting.py` | 有来源和完整性声明的外部计费记录导入 |
| `skill_evolution_store.py` | 不可覆盖的 manifest、动作预留、尝试、候选、晋升及回退 |
| `scripts/research_agent/skill_evolution.py` | CLI |
| `tests/test_skill_evolution.py` | 禁止网络的确定性单元测试 |

沿用 `run_configuration.archive/revision/configuration_scope` 和按次模型配置，增加 `with_skill_revision`，只复制执行快照里的一个 Skill 修订。生产正文、模块级 `SKILLS_BODY`、其他研究和旧恢复快照不变。晋升后需重启服务使新请求看到新的默认正文，旧快照仍引用归档。

既有 `run_research_eval.py` 的 coverage 和 citation_grounding 直接复用，只增加显式 judge/invoke 注入参数并延迟 target 图导入；原调用的指标与 feedback 字段含义不变。新入口不对整个研究任务进行重试，已有模型、搜索工具和 shared fallback 内部的有界重试仍保留。

## 可离线运行的命令

在仓库根目录使用现有虚拟环境，无需同步依赖或联网：

```powershell
.venv/Scripts/python.exe -m scripts.research_agent.skill_evolution --help
.venv/Scripts/python.exe -m scripts.research_agent.skill_evolution schema --out manifest-schema.json
.venv/Scripts/python.exe -m scripts.research_agent.skill_evolution versions
.venv/Scripts/python.exe -m scripts.research_agent.skill_evolution schema --kind evidence
.venv/Scripts/python.exe -m scripts.research_agent.skill_evolution schema --kind accounting
```

`schema`、`versions`、参数解析、数据校验、collect、compare、report、account、freeze、晋升／回退本身均不调用模型或外部服务。`config` 会读取本地后端 `.env`、构造现有角色客户端并归档配置，**不发起模型请求**；它不是连通性检查。本轮没有执行 config。凭据值只从后端环境读取，不进入配置和报告。报告可能包含任务、来源正文和用户约束，属于本地研究材料；不要把环境文件或完整 HTTP 请求日志放入导入文件。

## 后续准备真实实验（本轮不执行）

1. 准备相互独立的既有开发集、选择集、最终测试集导出；本功能不创建、扩充或上传测试数据。三个集合必须有不同 dataset_id，不允许重复 example ID 或完全相同的输入／参考内容哈希。语义近似题仍需数据维护者审查，哈希不能识别改写泄漏。
2. 在本地 `.env` 配置现有六角色和 `JUDGE_MODEL`、所需模型凭据及 Tavily。若使用历史 LangSmith 导出，另需 `LANGSMITH_API_KEY`。不要更改生产模型或网关来适配实验；执行复用归档版本。
3. 后续显式运行 `config --out configuration.json`，保存现有公开快照、judge 修订和代码／提示词／评估器哈希。保留对应 `atlas-configs.sqlite3`；纯数据文件不足以重建缺失的模型／Skill 归档。网关与凭据环境变量名只在既有后端归档中，不写入 manifest。
4. 按 `schema` 生成的契约编写 `manifest.json`。复制 configuration.json 中五个字段：`configuration`、`judge_revision`、`code_revision`、`prompt_revision`、`evaluator_revision`；填写独立 `experiment_id`、`parent_revision`、`datasets`、`budget`、`gates`。`parent_revision` 就是 `configuration.skill_revisions["product-comparison"]`。

数据文件采用以下结构（这里是格式说明，不是新增测试题）：

```text
{
  "dataset_id": "已有数据集的固定身份",
  "version": "不可变版本",
  "examples": [
    {"id": "已有 example ID", "inputs": {既有研究输入},
     "reference_outputs": {"criteria": [既有逐项标准]}}
  ]
}
```

`inputs` 只接受 `researcher_messages`、`research_topic`、`research_brief`、`user_requirements`、`research_constraints`。消息沿用 LangChain 可反序列化格式。显式 `research_constraints` 必须与用户原文经现有解析器获得的约束一致，不能替换成更宽范围。通用 `constraint_violations` 还支持登记的字符上限；未被确定性识别的自然语言要求不能据此宣称已验证。

manifest 的 `datasets` 包含 `development`、`selection`、`final` 三个键，每项是 `dataset_id`、`version`、`examples`；其中 examples 是 `example_id → revision({"inputs": inputs, "reference_outputs": reference_outputs})`。`revision` 来自 `deep_research.run_configuration`，不是文件字节哈希。登记时只写身份与摘要，不写选择／最终集的题目、答案或轨迹。每次执行必须与登记内容完全一致，不支持隐式 limit 或最新数据集。

可用 `register --input development.json --out development-registry.json` 对**已有**数据导出生成上述身份登记；选择集和最终集同理。这个命令只计算摘要，不生成题目、不调用模型，生成器也不接收这些源文件路径。将三个 registry 对象分别填入 manifest 的对应 split。

所有门槛必须显式填写。例如可由实验负责人预先选择以下**配置值**（不是测量值或推荐成绩）：

```json
{
  "budget": {
    "rounds": 1, "candidates": 2, "analysis_calls": 1, "generation_calls": 1,
    "max_skill_chars": 12000, "max_output_chars": 16000,
    "max_tokens": 100000, "max_searches": 8,
    "max_seconds": 900.0, "max_failures": 0, "recursion_limit": 30
  },
  "gates": {"coverage_gain": 0.05, "support_floor": 0.9, "max_regression": 0.02}
}
```

初始化后 manifest 不可覆盖。若配置错误，创建新实验目录与新身份，不改旧记录或自动降低门槛。代码哈希覆盖本地 Python 实现、既有研究员评估器和锁文件；执行前检查，代码改动后必须建立新 manifest。

```powershell
python -m scripts.research_agent.skill_evolution init --dir .local/evolution/EXPERIMENT --spec manifest.json --parent src/deep_research/skills/product-comparison.md
python -m scripts.research_agent.skill_evolution validate --dir .local/evolution/EXPERIMENT
```

## 显式启动与查看（后续授权后运行）

以下命令会调用模型和搜索；`--allow-external` 是必需的显式开关，帮助和解析不会自动加载图：

```powershell
python -m scripts.research_agent.skill_evolution run --dir .local/evolution/EXPERIMENT --split development --dataset development.json --allow-external
python -m scripts.research_agent.skill_evolution diagnose --dir .local/evolution/EXPERIMENT --allow-external
python -m scripts.research_agent.skill_evolution generate --dir .local/evolution/EXPERIMENT --allow-external
python -m scripts.research_agent.skill_evolution run --dir .local/evolution/EXPERIMENT --split selection --dataset selection.json --allow-external
python -m scripts.research_agent.skill_evolution compare --dir .local/evolution/EXPERIMENT --candidate 1
python -m scripts.research_agent.skill_evolution report --dir .local/evolution/EXPERIMENT --out report.md
```

也可以 `collect --dir ... --input evidence.json` 导入明确身份的开发证据列表，格式见 `Evidence`。每条必须关联 experiment/run/example、数据集身份／内容哈希、版本、任务／用户要求／约束、实际 Skill 修订与正文、加载证据、工具／查询／来源、压缩结果、错误、feedback 和统计。缺失轨迹和统计保持 null，不从压缩稿推导完整轨迹。

旧 `fetch_last_research_eval` 导出可作为 collect 输入，但必须显式 `--project-name EXPERIMENT`，不能 `--only-failures`；collector 校验导出的完整计数和 manifest 的身份。新增导出字段为 input_payload、reference_outputs、source_evidence。历史缺失的 Skill 加载、轨迹和版本保持未知，只能支持有限诊断，不能强行生成内容修订。若原导出不含精确输入／参考身份，需要后续单独显式回读；本轮没有执行任何 fetch。

诊断区分内容、选择／加载、执行不遵循、检索访问、压缩／写作损失、基础设施、评估器、证据不足／混合八类。只有内容类且有实际加载正文、失败逐项 feedback 和可见轨迹时才允许生成候选。模型归因仍是待验证假设，包含证据引用、反证和验证建议。候选生成入口只接收开发证据和父正文，不能读取选择／最终数据文件；最终反馈没有回流入口。

候选包含父／子修订、完整正文、diff、理由、预期改善、影响范围和诊断哈希。确定性检查锁住 frontmatter/name/元数据与已有用户范围句，要求固定用户优先政策，限制长度，拦截新增具体 URL、日期、价格和开发答案／标准原句。**这些检查不能识别所有语义改写或所有易变事实**；实际使用时仍应审阅 diff，确认只有方法变化。生产 Skill 本轮没有修改。

## 比较、计费与完成性

每个登记 example 都要有基线与候选各一次尝试；交替先后顺序，固定相同输入、模型、提示、评估器和预算。每个阶段在调用前持久预留，只能执行一次。中断或失败保留，重复命令不会悄悄重跑；需要新实验身份重新安排，不自动修复样本数量。启动前失败也会留下 batch 预留，缺失尝试阻止通过。

保留原 `criteria_coverage_score`、`citation_grounding_score` 的 `score/comment/value` 和逐项内容。新增 `source_support_score` 使用真实 `source_evidence` 正文；对全部可见文本单元给出 supported／contradicted／insufficient，非事实单元单独标识。支持和矛盾必须携带正文哈希、来源索引、字符区间及程序提取的片段。遗漏、重复、越界、错误哈希均拒绝；位置正确只是可核对出处，不证明语义支持。截断正文／snippet 的局限保留。judge 失败保留缺失 feedback，不伪装成零分。

门槛要求平均配对 coverage 改善达到预设增量、每题来源支持度达到底线、没有新增硬约束违规、每题每项回归在容忍内、成本与长度预算合规、运行／证据／评分完整。输出 `pass`、`reject` 或 `insufficient_evidence`；缺失运行、基础设施失败、评分缺失、统计未知优先归为证据不足，并保留已知质量问题。退出码 0 只表示命令完成，必须查看结果与门槛。

搜索工具调用数在调用前计数（失败也计），并有调用前上限；耗时覆盖研究与评分。tokens 和包含 SDK／raw HTTP 内部重试的失败总数默认未知，因为现有返回值不能证明完整。工具级失败仍在 trace 中保存。不能用成功请求 usage 代替全部成本。

如后续获得完整 provider／代理账本，可用 `account --dir ... --input accounting.json` 附加一次成本记录。契约见 `Accounting`：run_id、原 result 的 revision 摘要、来源账本文件 SHA256、来源说明、确认人、`includes_all_retries_and_judges=true`、全部请求列表（request_id、model/search/source_access、failed、tokens）。成功与失败请求都必须保留；任一 model tokens 缺失则总量仍未知。重复请求身份、少于可见搜索次数、错误运行摘要均拒绝。原始未知统计保留不覆盖。

完整性声明是操作者对外部证据的责任，程序不能证明 provider 导出没有漏项。不可用真实零 token 的证明补齐失败调用时，应保持未知并阻止晋升。冻结后不能补改选择集成本记录，最终集成本可追加。

token／耗时／失败总数是采纳预算，不是对已经发出的网络请求强制取消；搜索上限作用于工具调用，工具内部重试可能增加物理请求，账本据实核对。模型内部 fallback 仍使用共享有界重试；analysis_calls/generation_calls 约束的是逻辑调用数，不能等同于 HTTP 请求数。严格消费上限需同时由后续运行环境配置 provider 配额／超时，不能声称本功能提供硬实时费用熔断。

## 冻结、最终验证、晋升和回退

选择集通过所有门槛（包括完整成本）后才允许冻结；最终集只在冻结成功之后读取。最终集也按同一预设门槛比较父版本与冻结候选，不回流生成器。

```powershell
python -m scripts.research_agent.skill_evolution freeze --dir .local/evolution/EXPERIMENT --candidate 1
python -m scripts.research_agent.skill_evolution run --dir .local/evolution/EXPERIMENT --split final --dataset final.json --allow-external
python -m scripts.research_agent.skill_evolution compare --dir .local/evolution/EXPERIMENT --candidate 1 --split final
python -m scripts.research_agent.skill_evolution report --dir .local/evolution/EXPERIMENT --out final-report.md
```

默认到报告和结论为止。经审阅后才显式执行以下本地文件动作；本轮没有执行生产晋升或回退：

```powershell
python -m scripts.research_agent.skill_evolution promote --dir .local/evolution/EXPERIMENT --production-file src/deep_research/skills/product-comparison.md
python -m scripts.research_agent.skill_evolution rollback --dir .local/evolution/EXPERIMENT --production-file src/deep_research/skills/product-comparison.md
```

晋升重新计算最终门槛、核对冻结候选和当前父版本，归档前后正文，再原子替换指定文件；回退只恢复记录中的原文，并拒绝覆盖晋升之后的其他改动。SQLite 和文件替换不是跨文件事务：记录区分动作预留与完成；若崩溃，检查文件修订和 ledger，不能靠“没有 completed”认定没有发生替换。重复生产操作被拒绝。保留实验目录、配置归档和生产文件的版本控制记录。

报告按失败证据 → 诊断 → 候选 diff → 基线／候选逐项结果 → 门槛理由呈现，同时保留所有失败、未完成尝试和晋升／回退来源。它明确标注研究员评估针对 `compressed_research`，不能直接当作 `final_report` 质量。

## 本轮验证边界

只运行本功能纯数据测试、已检查为纯本地的既有加载器／来源证据测试、CLI 帮助、相关 Ruff 和编译检查。新测试通过 socket 拦截阻止网络；未运行任何模型替身研究流程或模拟改善批次。后续真实模型兼容性、语义归因可靠性、候选有效性、网关重试成本及真实配对表现仍待单独验证。

本轮结果：45 项新增单元检查，加上既有加载器与来源证据的 15 项检查，共 **60 passed**。既有 `test_concurrent_and_nested_captures_do_not_leak` 需要 Windows asyncio 内部回环 socket，在本沙箱中未完成，已停止该进程并在最终检查中明确 deselect（1 项）；未改动该测试。新增模块／CLI／测试完整 Ruff、既有改动文件的错误级 Ruff、Python 编译与 `git diff --check` 通过。CLI 顶层／run 帮助与 accounting schema 输出可用。没有运行模型相关测试、评估批次、生产晋升或回退。
