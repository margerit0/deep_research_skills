# Graph 流程编辑器 M1 验证记录

日期：2026-11-15（Asia/Shanghai）。分支：`codex/graph-canvas-editor`。实施前 HEAD：`3dea298`；本记录随 M1 提交保存。

用户在当前聊天查看独立原型后明确回复“确认设计稿”。设计门槛已通过；本阶段完成 v1 核心契约、节点目录、校验和后续事务／执行约束，下一阶段为 M2 正式编辑器及版本管理。

## 1. 实际交付

| 内容 | 入口 |
| --- | --- |
| 定稿及确认来源 | [设计评审记录](graph-canvas-editor-design-review.md) |
| v1 协议、事务及验收条件 | [契约文档](graph-canvas-editor-contract.md) |
| 执行／展示／草稿／修订／绑定类型 | [workflow_definition.py](../src/deep_research/workflow_definition.py) |
| 九类节点、参数、模型角色、状态读写与恢复边界 | [workflow_registry.py](../src/deep_research/workflow_registry.py) |
| 结构、发布上下文、归属与正常路由核对 | [workflow_validation.py](../src/deep_research/workflow_validation.py) |
| 前端 Zod 类型、结构预检及相同摘要算法 | [workflowSchema.ts](../frontend/src/data/workflowSchema.ts) |
| 可检查的 Schema 与共享数据 | [JSON Schema](contracts/workflow-v1.schema.json)、[语义场景](../tests/fixtures/workflows/v1-cases.json)、[跨端报文及摘要](../tests/fixtures/workflows/v1-wire-examples.json) |
| 生成／漂移检查入口 | [export_workflow_contract.py](../scripts/export_workflow_contract.py) |

v1 草稿参数只接受已开放的文本处理要求，禁止密钥、模型覆盖或运行状态等额外字段进入保存／导入协议。空草稿、断连及未填要求仍能表示为待修复的草稿；发布校验拒绝这些未完成结构。

发布可执行性需要实际节点实现及模型／Skills 可用性上下文。结构预检与发布校验以 `scope` 区分，不因客户端预检通过而宣称可发布。M2 的发布事务可使用替身验收，真实节点实现和生产执行能力仍由 M3 完成。

## 2. 验证结果

相关后端批次：**124 passed，0 failed，0 skipped**。

| 文件 | 通过数 |
| --- | ---: |
| `tests/test_workflow_definition.py` | 73 |
| `tests/test_workflow_factory.py` | 12 |
| `tests/test_submission_journal.py` | 24 |
| `tests/test_run_configuration.py` | 15 |

前端 `workflow-contract.spec.ts`：**60 passed，0 failed，0 skipped**。该文件通过 Playwright runner 验证契约，不是正式编辑页面的端到端验收。

已执行且通过：

- 27 个共享结构场景，两端对允许／拒绝及稳定问题代码判断一致。
- 14 类跨端报文样例，以及标准、配置和含 Unicode 处理要求的跨语言摘要。
- 必需节点、澄清移除、多扩展节点、断连、循环、重复身份、非法阶段和参数、30 节点边界、UTF-8 大小限制及 Unicode 码点边界。
- 发布版本摘要完整性、thread 绑定冲突、原修订继承、不可用编译器的只读查看与拒绝执行。
- 系统终态不跟随正常后继；导入协议不接受密钥或节点模型覆盖字段。
- 新契约模块在独立 Python 进程导入时没有导入研究图、模型工厂、OpenAI 客户端或 Skills 加载器。
- TypeScript 类型检查、正式前端生产构建、Ruff 检查／格式检查、所改前端文件的 Prettier 检查，以及生成物漂移检查。

本地机器结果保存在 `.local/graph-canvas-m1/backend-results.xml` 和 `.local/graph-canvas-m1/frontend-results.xml`；测试临时目录使用每批新建的项目内路径。未修改或停止日常研究服务。

## 3. 复现

在项目根目录：

```powershell
uv run --locked --extra dev python -m scripts.export_workflow_contract --check
$m1Temp = Join-Path (Get-Location) ('.local\graph-canvas-m1\pytest-' + [guid]::NewGuid().ToString('N'))
uv run --locked --extra dev pytest tests/test_workflow_definition.py tests/test_workflow_factory.py tests/test_submission_journal.py tests/test_run_configuration.py -q --basetemp $m1Temp
uv run --locked --extra dev ruff check src/deep_research/workflow_definition.py src/deep_research/workflow_registry.py src/deep_research/workflow_validation.py scripts/export_workflow_contract.py tests/test_workflow_definition.py
```

在 `frontend` 目录：

```powershell
npm.cmd run build
$env:CI = '1'
$m1Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$m1Listener.Start()
$env:ATLAS_TEST_PORT = [string]$m1Listener.LocalEndpoint.Port
$m1Listener.Stop()
.\node_modules\.bin\playwright.cmd test tests/workflow-contract.spec.ts --workers=2 --reporter=dot
```

变更正式类型或节点目录时，先运行不带 `--check` 的导出命令更新生成物，再执行两端测试。不要单独修改生成的 Schema 或报文文件。

## 4. 阶段边界

本阶段没有实现 WorkflowStore、HTTP 管理接口、正式 React 编辑页或生产图工厂，没有新增数据库迁移、真实模型调用或工作流执行能力声明。保存并发、发布幂等、绑定与受理原子事务、事件持久化及重启恢复的生产实现与故障注入，仍按 M2／M3 的冻结验收条件推进。

原 `workflow_contract.py` 继续描述研究状态与来源，不承担新的工作流执行定义。现有生产请求摘要与恢复函数尚未接入新字段；M3 必须按契约中的“仅在字段存在时加入”规则实现并验证兼容性。

未改动原 M0 原型、锁文件、生产环境配置或既有 `frontend/design-mockups/`。本轮证据不证明真实报告质量、端点可用性、性能指标或研究子图任意位置可恢复。
