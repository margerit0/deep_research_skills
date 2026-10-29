# 2026 年 10 月 P1 实验归档

2026-10-29 整理。本文索引 2026-10-19 至 2026-10-21 遗留的方案、结果、交接和公开证据。材料留在原路径，便于保持链接有效；原始报告、JSON 证据和结果文档内容不变。旧方案与交接新增历史标记，正文中的分支、HEAD、未提交状态、待办及“下一批”均只描述记录当时的情况，不是当前任务或模型调用授权。

## 当前保留的实现

- **安全核验诊断**：`review_diagnostics.py` 限制可记录的提供商类型、代码、schema 字段路径和错误数量；`report_review.py` 区分没有有效决定的 SDK 读取失败；`research_agent_full.py` 将安全诊断随核验失败记录保存。相关测试为 `tests/test_review_diagnostics.py`。
- **可选流式 JSON**：`structured_output_fallback.py` 提供显式 `json_object` 策略，`utils.py` 允许网页摘要选择同一策略。新路径检查正常结束与 `[DONE]`、流内错误和 schema，保留 Qwen `/no_think` 与空 choices 诊断。默认仍为原生优先，没有自动切换生产配置。相关测试为 `tests/test_structured_output_stream.py`。
- 来源选择和核验提示实验未被采纳，不能将下列计划中的候选提示当作当前实现。摘要缓存仍只是历史后续建议。

## 批次索引与结论

| 批次 | 方案、结果与交接 | 结论边界 |
| --- | --- | --- |
| 2026-10-19 DeepSeek P1 | [方案](p1-deepseek-plan-2026-10-19.md) · [结果](p1-deepseek-results-2026-10-19.md) · [交接](handoff-after-p1-baseline-2026-10-19.md) | 三次原生业务完成 2/3，独立内容验收 0/3；不支持推广为可靠默认。 |
| 2026-10-20 核验提示 | [方案](p1-review-plan-2026-10-20.md) · [结果](p1-review-results-2026-10-20.md) · [交接](handoff-after-p1-review-2026-10-20.md) | 新提示仍有误拒和误放行，已撤下；保留诊断改进。 |
| 2026-10-20 来源条件选择 | [方案](p1-selection-plan-2026-10-20.md) · [结果](p1-selection-results-2026-10-20.md) · [交接](handoff-after-p1-selection-2026-10-20.md) | 未取得有效选择决定，原生交付 0/2；HTTP 失败不能评价语义改善。 |
| 2026-10-20 GLM 复测及流式尝试 | [方案](p1-glm-selection-plan-2026-10-20.md) · [选择结果](p1-glm-selection-results-2026-10-20.md) · [流式结果](p1-glm-stream-results-2026-10-20.md) · [交接](handoff-after-glm-retest-2026-10-20.md) | 新选择提示未采纳；流式原生观察结束时尚无报告，不能视为完整交付。 |
| 2026-10-20 GLM JSON 流读取 | [方案](p1-glm-jsonstream-plan-2026-10-20.md) · [结果](p1-glm-jsonstream-results-2026-10-20.md) · [交接](handoff-after-glm-jsonstream-2026-10-20.md) | 两份固定简报读取 2/2 有效；完整业务样本 0/1，因隔离遥测包装错误提前失败。可选实现的完整业务验收尚未通过。 |
| 2026-10-21 GLM 后续方案 | [完整交付与摘要优化计划](p1-glm-delivery-plan-2026-10-21.md) | 该文件为计划；本次归档未执行，也未据此补写完成结论。 |

## 公开原始证据

以下五份 JSON 与六份报告／草稿保持整理前的字节内容：

| 批次 | JSON 证据 | 报告与草稿 |
| --- | --- | --- |
| DeepSeek P1 | [机器证据](provider-2026-10-19-deepseek-p1-evidence.json) | [high01 草稿](provider-2026-10-19-deepseek-p1-high01-draft.md) · [high02 报告](provider-2026-10-19-deepseek-p1-high02-report.md) · [high03 报告](provider-2026-10-19-deepseek-p1-high03-report.md) |
| 核验提示 | [机器证据](provider-2026-10-20-deepseek-review-evidence.json) | [native01 草稿](provider-2026-10-20-deepseek-review-native01-draft01.md) · [native02 首稿](provider-2026-10-20-deepseek-review-native02-draft01.md) · [native02 修订稿](provider-2026-10-20-deepseek-review-native02-draft02.md) |
| 来源条件选择 | [机器证据](provider-2026-10-20-deepseek-selection-evidence.json) | 未交付报告。 |
| GLM 复测 | [机器证据](provider-2026-10-20-glm-retest-evidence.json) | 未交付报告。 |
| GLM JSON 流读取 | [机器证据](provider-2026-10-20-glm-jsonstream-evidence.json) | 完整业务样本未交付报告。 |

更完整的本地实验目录位于各交接引用的 `.local/`，不随公开检出提供。旧运行身份及冻结证据继续只读；归档不使旧启动器成为可重新执行的入口。

## 本次整理的验证

2026-10-29 在现有 Python 环境执行后端单元测试，结果为 **240 passed**。测试进程使用虚拟凭据和隔离配置库，禁用 HTTPX、Requests、urllib 的真实 HTTP 调用，记录到的真实 HTTP 尝试为 **0**。这属于程序回归检查，没有运行研究评估、模拟进化批次或真实模型测试。

Windows 沙箱中的空协程复现了本地 `socketpair` 阻塞；相同检查在沙箱外通过，因此本次单元测试在沙箱外运行，保留上述 HTTP 禁用措施。测试结果不替代模型质量或完整业务验收。

本地整理快照和测试 JUnit 结果保存在 `.local/pending-changes-20261029/`，其中保存原有 38 个待提交文件的整理前内容与哈希。公开文档保留本节的范围与结果，不要求读者拥有该本地目录。
