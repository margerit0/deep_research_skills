# GLM 复测及流式尝试交接

> 历史材料（2026-10-29 整理）：本文保留记录当时的状态、约束和后续建议，不作为当前任务或启动授权。相关证据与现状见 [P1 实验归档](p1-experiments-2026-10.md)；不要据此重跑旧批次或自动启动模型实验。

2026-10-20，Asia/Shanghai。工作区 `D:\deep_research_public_preview`。本轮按用户要求读取聊天 `01a158a8-e73d-7e72-a798-80d9eec2c69b` 并使用 `z-ai/glm-5.3` 复测，随后按“换成流式请求尝试”调整测试方向。未提交或推送，生产源码与 `.env` 保持进入本轮时状态。

先读[离线及非流式结果](p1-glm-selection-results-2026-10-20.md)、[流式结果](p1-glm-stream-results-2026-10-20.md)及[统一机器证据](provider-2026-10-20-glm-retest-evidence.json)。

## 已结束的身份

- `.local/p1-glm-selection-20261020/`：五个已见案例，十个 arm，十四个稿件判断。十份有效选择；十三份有效决定均符合冻结标签，一份流内超时不可用。旧／新提示有效决定分别为 7/7、6/7。选择类别、范围和语义强度仍有错误，不采纳新提示。实际二十五次请求：24 × 200、1 × 504。
- `p1-glm-selection-20261020-native01`：十八次模型请求，2 × 200、16 × 504，业务 `failed/brief`，无搜索或报告。thread `e954969c-84d1-46ed-a6bc-baecc1cef2cd`。
- `p1-glm-selection-20261020-native02`：用户要求改用流式时中止，保留请求及 `user-steering-stop.json`，无业务终态声明，不补跑。thread `d2fce264-6ac1-443b-b16d-a0f798d7591b`。
- `p1-glm-stream-20261020-native01`：十次模型请求全部流式 HTTP 200；原生简报流约 603 秒超时，普通 JSON 提示流约 345 秒完成。真实 Skill 和两次搜索已执行，实际消费仅指定两篇 3.13 指南。30 分钟观察期结束时仍为 `running/research`，无报告；进程已停止、端口已释放。thread `87aafd15-6a5c-4657-a3b2-42f07633ee7a`，未完成 run `1bae232f-bd54-4d2d-88d2-7e8670877787`。

这些目录的执行身份均已用过，不可再次执行 `batch.py`、任何 arm 或 `run.mjs`，不可补跑失败或中止样本，不修改旧哈希使入口通过。结果是观察记录，不是待继续的后台任务；目前没有测试进程或自动化在运行。

## 本地材料

离线目录的 `criteria.json`、`case-*.json`、`plan.json`、`preflight.json`、`arms/*`、`independent-review.json`、`pre-native-audit.json`、`tests-isolated.xml` 保存输入、真实决定和独立审查。流式目录的 `plan.json`、`preflight.json`、`prepared-public-evidence.json` 和原生目录的 `model-http.jsonl`、`body-telemetry.jsonl`、`final.json`、`partial-verification.json`、`closeout.json`、`stages/` 保存流式证据。

流式隔离快照的 raw JSON helper 修改仅供审查；真实流程没有触发该分支，只有五个本地 mock 请求覆盖。所有真实请求 `stream=true` 由传输层断言和遥测证实。公开导出前 554 项保护文件及 123 项冻结文件均未变化；结果文档随后按终态补齐。提供方 completion=0 异常仍在，实际生成用量和费用未知。

后续若继续测试，应新建目录、端口、数据库及身份，先冻结计划。当前最明确的待验证项是如何减少原生结构化流的长等待以及在明确预算内完成压缩／写作／核验；来源选择的新提示尚未证明稳定改善。是否推广流式配置或调整 helper 属于新的实现工作，不能把本轮隔离测试当作已上线的修改。
