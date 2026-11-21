# Graph 流程编辑器 M4 验收记录

更新日期：2026-11-21。分支：`codex/graph-canvas-editor`，M3 基线 `ae3c524`。

**结论：稳定性修复和离线基准已落地；后端离线验收通过。浏览器有 3 项超时待独立复验，真实模型／检索质量按用户要求暂缓。** 本轮没有重新调用真实模型、检索或评估服务，不以原生 run 成功或替身报告证明业务质量。

## 实施与兼容性

- 固定版 LangGraph 的状态／历史 JSON 读取曾把检查点待应用的 `Overwrite` 指令变为普通字典，触发列表 reducer 类型错误。版本适配只恢复这一已知指令；临时观察 saver 不再替换主 saver 的刷盘注册，也不会读写同名文件。
- 受理回执不再用包含待提交写入的最新视图确认终态。只有按相同 checkpoint ID 独立读到同一尝试的终态，才刷盘并固定该 ID。读历史不补造工作流绑定、重放模型或改变执行拓扑。Windows 故障注入直接核对被注入的进程退出码，不与预期退出竞态强杀。
- 拖动帧复用画布连线定义；动态研究员超过 20 个时按组展示，只挂载当前展开组。定位活动任务会自动展开对应组并滚动、聚焦；折叠该组后关闭检查器，焦点回到对应组按钮。

## 离线验证

| 项目 | 已观察结果 |
| --- | --- |
| 后端确定性回归 | **229 通过**。含旧受理／工作流协议，以及新增的 `Overwrite` 解码、主 saver 隔离、待提交终态不入回执三项回归。证据：`backend-offline.xml`。 |
| 隔离原生 HTTP | **14/14 通过**。含事务内／受理后退出、响应丢失与重试、原修订恢复、拒绝不安全续跑、旧图引用省略／null 兼容、缺失实现时旧历史仍可读、已归档版本原会话续问。证据：`native-regression.xml` 及 M3 独立用例目录。 |
| 浏览器回归 | **233 通过、2 超时、17 未启用**。通过项包括旧缓存回读、真实纪录的只读演示、编辑／查看尺寸与主题、键盘、120 任务分页回放／展开／折叠／定位。前一次全量回归的 `workspace.spec.ts` 中「全部节点和检查器标签」「1440px 浅色布局」超时，尚未独立重测。 |
| 原生浏览器 | **未通过整项**。两个修订都已发布并分别得到替身报告，已回读各 1 个 run、正确归属和业务终态；重载后点击「刷新状态」超时，后续检查未执行。不能把两份报告视作本项通过。 |
| 前端构建 | TypeScript 类型检查、生产构建及改动的前端文件 Prettier 检查通过。 |
| 默认数据保护 | 对比阶段开始前的 12 个文件：`.env` 和默认 `.langgraph_api/` 文件集合及 SHA-256 均未变化。没有迁移或重写日常研究数据。 |

本阶段本地证据根为 `.local/graph-canvas-m4/`。上表两轮浏览器日志分别在 `browser-offline-0977f401ccc54cefa0b9e94e0e6e8935/`、`browser-native-5742c360d7124f5c854e6c96a425dab6/`，超时的 trace 和诊断仍保留。

## 性能证据

Windows 桌面，Intel Core i9-14900HX；画布样本使用 1440×960 的无头 Chrome 157.0.8103.80。下面区分先前通过的离线基准与本轮回归；本轮独立性能复测已取消，不把之前结果写成本轮实测。

| 场景 | 方法与结果 |
| --- | --- |
| 30 个主流程节点／29 条边，本地校验及发布 | 生产 HTTP 路径、隔离持久化，3 次预热后各 30 个样本，取最近秩 P95；此前通过的 `case-lsix4byd/publication-timing.json`：校验 **80.3 ms**，发布 **96.2 ms**，测试夹具无模型／工具或执行审计。目标 ≤1 秒。 |
| 50 个展示节点／100 条边拖动 | 使用正式画布组件的仅展示样本，不放宽 v1 发布上限。此前通过的 `browser-measured/`：140 个移动均观测到，**36.6 次可见位置更新/秒**，输入至位置可观测 **P95 26.9 ms**。用浏览器帧回调观察节点位置变化，不是显示器实际呈现帧率。目标 ≥30、≤100 ms。 |
| 拖动、撤销与防抖 | 本轮浏览器回归实测松手后 **832 ms** 发起一次保存。拖动持续超过防抖窗口仍不保存；一次撤销恢复原文档，过程中不创建 run。 |
| 动态研究员 | 本轮浏览器回归以 **120** 个回放任务验证默认折叠、一次只渲染 20 个、Enter／Space 展开折叠、定位并聚焦第 120 个运行中实例。 |

## 如何复验（无需外部服务）

后端从项目根目录运行。为每批 pytest 和浏览器输出分配新的工作区内目录，浏览器用未占用的回环端口。模型／检索替身由隔离启动器安装，关闭真实模式。

```powershell
$m4 = (Resolve-Path -LiteralPath .local/graph-canvas-m4).Path
$env:ATLAS_WORKFLOW_M3_API = '1'
.venv/Scripts/python.exe -m pytest tests/test_workflow_execution_api.py -q --basetemp (Join-Path $m4 ('native-' + [guid]::NewGuid().ToString('N')))
Remove-Item Env:ATLAS_WORKFLOW_M3_API
$env:ATLAS_WORKFLOW_M4_PERF = '1'
.venv/Scripts/python.exe -m pytest tests/test_workflow_m4_performance.py -q --basetemp (Join-Path $m4 ('perf-' + [guid]::NewGuid().ToString('N')))
```

浏览器从 `frontend/` 运行，基准单 worker，不与其它测试并跑。

```powershell
$m4 = (Resolve-Path -LiteralPath ../.local/graph-canvas-m4).Path
$env:CI = '1'
$env:ATLAS_TEST_PORT = '5486'
$env:ATLAS_BACKEND_URL = 'http://127.0.0.1:1'
Remove-Item Env:ATLAS_LIVE -ErrorAction SilentlyContinue
$env:ATLAS_WORKFLOW_M4_PERF = '1'
node node_modules/@playwright/test/cli.js test tests/workflow-performance.spec.ts --workers=1 --reporter=list --output (Join-Path $m4 ('browser-perf-' + [guid]::NewGuid().ToString('N')))
node node_modules/@playwright/test/cli.js test tests/workspace.spec.ts --grep 'all nodes and tabs|layout light 1440' --workers=1 --reporter=list --output (Join-Path $m4 ('browser-recheck-' + [guid]::NewGuid().ToString('N')))

$env:ATLAS_WORKFLOW_M3_API = '1'
$env:ATLAS_WORKFLOW_M3_PORT = '2875'
$env:ATLAS_BACKEND_URL = 'http://127.0.0.1:2875'
node node_modules/@playwright/test/cli.js test tests/workflow-execution-api.spec.ts --workers=1 --reporter=list --output (Join-Path $m4 ('browser-native-' + [guid]::NewGuid().ToString('N')))
```

确定性后端集合沿用 [M3 复现入口](graph-canvas-editor-m3-results.md#复现入口)，另加 `tests/test_atlas_native_checkpoints.py`。复验超时项前先保留失败 trace，不降低断言或将超时计为通过。

## 暂缓的真实质量验证

历史隔离批次 `live-oio1tf18/` 的标准流程、扩展流程、澄清三个样本均在澄清节点失败：9 次模型 HTTP 尝试返回 401，没产生可验报告、来源或澄清续轮，**0/3 通过**。原生 run 的 `success` 只表示执行结束，业务状态实际为 `failed`。没有可确认的费用记录。此前的失败不能由替身结果覆盖。

仅在用户重新确认后，先核对供应商认证与预期费用上限，再按固定的三个样本、尝试数和总时限验收。须分别回读业务终态、原修订与报告归属、正文对原始要求的满足、实际来源及澄清续轮；记录全部失败和缺失值。不重跑旧研究、不改默认库，不因网络问题放宽来源或凭据约束。
