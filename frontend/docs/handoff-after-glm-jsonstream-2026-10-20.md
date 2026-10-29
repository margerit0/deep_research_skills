# GLM JSON 流读取优化后交接

> 历史材料（2026-10-29 整理）：本文保留记录当时的状态、约束和后续建议，不作为当前任务或启动授权。相关证据与现状见 [P1 实验归档](p1-experiments-2026-10.md)；不要据此重跑旧批次或自动启动模型实验。

2026-10-20，Asia/Shanghai。分支 `chore/public-edits`，HEAD 仍为 `5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`；没有提交或推送。先读 [方案](p1-glm-jsonstream-plan-2026-10-20.md)、[结果](p1-glm-jsonstream-results-2026-10-20.md)、[机器证据](provider-2026-10-20-glm-jsonstream-evidence.json)，再看 `docs/maintenance.md`、`docs/architecture-decisions.md`。

## 当前实现和证据

- 共享 `src/deep_research/structured_output_fallback.py` 新增显式 `json_object` 策略；也可由模型 metadata 选择，默认原生优先。新策略强制流式、检查 `stop` 和 `[DONE]`、拒绝流内错误及无效 JSON，再做原 schema 校验。复用既有客户端/限流和 Qwen `/no_think`、choices=null 诊断。没有修改 `.env` 或自动启用生产 GLM 配置。
- `src/deep_research/utils.py` 仅在显式新策略时让摘要复用共享 helper。`tests/test_structured_output_stream.py` 增加 13 项回归，隔离配置库全量 240 项通过。进入本批的 report_review、research_agent_full、安全诊断及文档改动都保留。
- 保存同一简报输入的两份真实读取 2/2 完整有效，54.51 / 116.26 秒，各一次流式 JSON 对象 HTTP 200，均有 stop / `[DONE]`，原 schema 和明确要求通过。仅证明此输入两次可用，不证明稳定加速或完整交付。上游仍报告异常的 completion=0。
- 原生完整业务验收 0/1：本地隔离遥测重复导入导致 NameError，业务 failed/clarify，模型请求零；原生 run success 不算业务成功。报告、压缩、核验、刷新验收都未执行。
- 来源摘要精确重复已定位：相同任务、URL 和正文哈希的 Python 指南被再次摘要，第二次约 153 秒。扩展指南正文哈希不同不能合并。没有实现缓存。

## 已用身份与隔离包装错误

`.local/p1-glm-jsonstream-20261020/` 保存初始 diff、658 项保护文件、旧耗时审查、输入/设计计划、147 项调用前冻结哈希、两个 pilot 及测试。两个 pilot 身份已用，不可重跑。

`p1-glm-jsonstream-20261020-native01` 是零请求、零提交、零 run 的 Vite 写权限启动失败；原样保留。`native02` 使用 2152/5312、独立数据库及 42 项追加冻结文件，已创建 thread `577bcaa0-2917-4b69-946c-b313bc25ca5e` / run `3fad5f5d-2e24-4690-9612-a8f9ce13e9b1`，终态业务 failed/clarify。两个启动目录都不可重启，不改旧哈希。

根因在 application.py 的新遥测包装：模型工厂安装标记跨模块共享，但 read_scope 是第一次导入模块的局部全局变量，第二次导入重新包装后没有此变量。`.local/p1-glm-jsonstream-20261020/audit_install.py` 提供共享 helper 上的幂等安装修复，`test_audit_install.py` 两项离线通过；**旧冻结启动器未修改，修复尚未通过真实原生验收。** 不要直接运行修复文件期待续跑旧任务。

本批没有失败补跑；完整业务样本分母仍为 1、交付 0，另报告启动 2 次、1 次就绪。所有端口已释放，没有测试进程或自动化；历史 running 记录不表示后台执行。

## 下一批顺序

1. 先在新目录构造安装幂等的隔离入口，并在无真实网络的 graph/http 双重导入检查中验证包装只安装一次、作用域与工厂关联正确；可复用 audit_install 的安装器。旧启动器和所有证据只读。
2. 新建端口、数据库、身份和预算，冻结当前来源选择/写作/核验提示，保持每次 SDK 最多五次 HTTP、三次生成、四次读取、一次语义修订。新完整观察期可沿用两小时，以允许低 TPS；不要增加失败补跑次数来凑成功率。
3. 在新的有界清单中做真实原生验收。保留本批 0/1，不把新结果改写成这一批已通过。业务 succeeded、400–650 汉字、指定两页、Skill 顺序、逐句支持/重要前提、核验归属/哈希和刷新无新增执行都须独立检查。
4. 读取策略与完整路径可用后，另批设计研究作用域内的摘要精确缓存；键包括正文版本与有效模型/提示配置，记录命中及失败。先解决精确重复，不把不同正文按 URL 混为一个来源。

原始计数器将 stop / `[DONE]` 后主动关闭记作 GeneratorExit，本批保留原值并加解释字段；后续若改计数器应另做协议测试，不能改旧证据。真实调用前仍先加载环境，再导入图；凭据留在后端本地 `.env`。
