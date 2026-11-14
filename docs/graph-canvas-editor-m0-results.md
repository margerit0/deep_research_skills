# Graph 流程编辑器 M0 验证记录

验证日期：2026-11-14；记录更新：2026-11-15（Asia/Shanghai）。分支：`codex/graph-canvas-editor`。

代码起点：`d8caa38`；计划与初始交接提交：`f8e4af7`。本记录随 M0 原型提交。

**结论：M0 通过，可以进入 M1 契约与交互设计。** 原生图工厂能够按持久化 thread 绑定执行不同修订，且在没有显式 revision 参数的状态读取、澄清新提交和检查点恢复中找回原版本。React Flow 与当前前端兼容。

这是隔离技术原型。生产 `langgraph.json`、研究节点、受理库协议和主应用入口尚未接入流程编辑器；完整保存／发布／执行闭环仍属于 M1–M3。

## 1. 可复现实现

| 文件 | 职责 |
| --- | --- |
| [atlas_workflow_factory.py](../tests/atlas_workflow_factory.py) | 测试专用不可变修订、持久绑定、内容哈希、窄拓扑校验和 Command 路由适配 |
| [atlas_workflow_fixture.py](../tests/atlas_workflow_fixture.py) | 原生图工厂、真实业务节点、模型／工具替身、持久调用审计、两个扩展处理步骤 |
| [atlas_workflow_server.py](../tests/atlas_workflow_server.py) | 独立目录、空闲端口、导入前环境隔离、原生持久化服务 |
| [test_workflow_factory.py](../tests/test_workflow_factory.py) | 12 项确定性验证，包括真实调度顺序、reducer 覆盖及归档损坏 |
| [test_workflow_factory_api.py](../tests/test_workflow_factory_api.py) | 8 项显式启用的原生 HTTP／进程故障验证 |
| [workflow-canvas.tsx](../frontend/src/m0/workflow-canvas.tsx) | 独立画布、拖动、增删、连接、布局、缩放和主题 |
| [workflow-m0.spec.ts](../frontend/tests/workflow-m0.spec.ts) | 3 项浏览器验证及不同宽度截图 |

测试运行完整研究的既有业务函数；模型和搜索边界替换为确定性返回值。扩展步骤分别更新简报及协调器消息、覆盖整理后的笔记，保留原始笔记和来源。它们用于证明编排和状态传递，尚不是正式节点实现。

## 2. 实际结果

| 验证 | 结果与依据 |
| --- | --- |
| 修订隔离与新增／删除步骤 | `v1` 的 5 个父节点、`v2` 的 7 个父节点分别按发布顺序执行；v2 两个扩展步骤各调用 1 次，v1 为 0 次；搜索每个研究 1 次 |
| 澄清与新修订并发 | v1 等待补充期间发布 v2；回答与新 v2 研究并发执行。v1 仍使用原图、同一研究身份；协调器确实接收到 v2 优化后的简报 |
| 删除澄清 | 单独修订不调用澄清模型；保留原始用户要求，产出有效替身报告、笔记和来源 |
| 无 revision 的观察 | 原生 GET state、POST history、POST state/checkpoint 和旧 turn 回执均回读原修订；重复观察不增加 run 或模型调用 |
| 三个安全恢复边界 | 分别在澄清、简报、写作模型内停止专属服务，重启后核对同一 checkpoint，再以 `input: null` 创建恢复 run；原模型／Skills 配置及流程修订保持不变 |
| 重复恢复／提交 | 同一恢复身份重试返回同一个 run；重复原提交不另建 run；完成后换新恢复身份返回 409 |
| 不安全研究边界 | 搜索工具内部停止后，原生记录仍可能显示 running，但受理回执为 interrupted；恢复被拒绝，搜索计数保持 1、写作计数为 0 |
| 缺失／不兼容修订 | 删除修订、修改实现版本或破坏内容哈希后，已缓存图也不能继续用于状态读取；原生状态请求返回 409，受理回执 blocked，不选择其他版本 |
| 无绑定的直接原生执行 | 未知修订绑定返回 409；绕过受理层直接 POST 原生 run 会产生一个 error run，模型／工具调用为 0。这不是成功执行，也不保证原生入口零 run 记录 |
| 画布 | 添加、拖动、连接、删除关联边、键盘删除、核心节点锁定、Dagre 布局、缩放、浅／深色、减少动画设置通过 |
| 构建与页面隔离 | TypeScript 检查、普通生产构建和独立 M0 构建通过；主应用入口不导入 M0 页面 |

三个恢复场景最终均为 `research_status=succeeded`、`research_phase=complete`，报告研究／turn 归属正确，保留 1 份笔记和 1 条来源。仅以原生 run success 或进程退出码判断成功的做法未用于本次验收。

| 中断位置 | 澄清调用 | 简报调用 | 优化步骤 | 搜索 | 压缩 | 整理步骤 | 写作调用 | 原生 run 数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 澄清 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 2 |
| 简报 | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 2 |
| 写作 | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 2 |

写作恢复沿用原检索事件 run。上述计数包含被中断的调用；重复当前模型调用是既有恢复协议允许的行为。

最终执行：M0 pytest **20 passed，0 failed，0 skipped**（91.40 秒）；画布 Playwright **3 passed**（5.6 秒）。另执行过三个原有后端回归文件及当时 11 项 M0 单元验证，共 **76 passed**；最终 M0 单元增加了 1 项归档身份校验。Ruff 与新前端文件的 Prettier 检查通过。

## 3. 环境与本地证据

环境为 Windows 11、Intel Core i9-14900HX、约 32 GB 内存；Python 3.13.3、Node 22.17.0、Chrome 157.0.8103.52。运行时版本保持 LangGraph 1.1.3、API 0.8.7、inmem 0.28.1、CLI 0.4.26。

前端锁定 `@xyflow/react` **12.12.1**、`@dagrejs/dagre` **3.1.3**；React／React DOM 19.3.0、TypeScript 7.0.2、Vite 8.3.4。独立 M0 构建 JS 为 454.00 kB（gzip 145.20 kB），CSS 为 17.51 kB（gzip 3.22 kB）；这是整个原型入口体积，不是主应用的增量体积。

最后一批本地证据保留在 `.local/atlas-workflow-m0/`，不提交数据库、大日志或模型配置归档：

| 场景 | case 目录 |
| --- | --- |
| 并发修订、澄清、历史回读 | `case-f1aa88rt` |
| 删除澄清 | `case-gxfing7v` |
| 澄清恢复 | `case-udm4r994` |
| 简报恢复 | `case-uscx7l3p` |
| 写作恢复 | `case-j0rg_z18` |
| 不安全工具中断 | `case-u8xgmr3r` |
| 归档故障 | `case-emm672kq` |
| 无绑定拒绝执行 | `case-11yqrqx6` |

每个 case 有 `server.log`、`evidence.json`、调用审计 SQLite 和原生持久化目录；`evidence.json` 包含测试名称、进程实例、调用记录及已观察的状态／run。最后一批 pytest 汇总为 `m0-results.xml`。不同复现批次会生成新的 case 名称。

浏览器截图在 `frontend/test-results/workflow-m0/`，验证宽度为 1440、1024、390、320，高度为 900。已目视检查 1440 浅色和 320 深色截图。首次截图发现原型通用按钮 padding 挤掉缩放图标，已限定样式作用范围；窄屏整页截图的尺寸告警通过明确页面及画布高度修正，最终三项测试断言控制台无 warning/error。

首次 pytest 使用系统旧临时目录时发生 Windows 拒绝访问；后续统一使用本项目内全新 `--basetemp`，没有修改系统临时目录权限。Windows 虚拟环境 Python 可能有启动器和服务两个 PID，测试通过随机 fixture 身份识别服务，只停止本 case 的进程。

## 4. 复现命令

在项目根目录运行。每次使用全新的临时目录；原生测试自动选择端口、检查专属 fixture 身份、关闭自己的进程，不加载生产 `.env`。

```powershell
$m0Temp = Join-Path (Get-Location) ('.local\atlas-workflow-m0\verify-' + [guid]::NewGuid().ToString('N'))
$env:ATLAS_WORKFLOW_M0_API = '1'
uv run --locked --extra dev pytest tests/test_workflow_factory.py tests/test_workflow_factory_api.py -q --basetemp $m0Temp --junitxml .local/atlas-workflow-m0/m0-results.xml
```

未设置 `ATLAS_WORKFLOW_M0_API=1` 时原生测试会跳过，跳过不能计为通过。以下是已执行的相关回归命令（使用另一个全新临时目录）：

```powershell
$m0Temp = Join-Path (Get-Location) ('.local\atlas-workflow-m0\regression-' + [guid]::NewGuid().ToString('N'))
uv run --locked --extra dev pytest tests/test_workflow_factory.py tests/test_full_workflow.py tests/test_submission_journal.py tests/test_run_configuration.py -q --basetemp $m0Temp
```

前端在 `frontend` 目录运行，下面的命令自动取得空闲端口。Windows 使用 `.cmd` 入口保留参数：

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd run build:workflow-m0
$env:CI = '1'
$m0Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$m0Listener.Start()
$env:ATLAS_TEST_PORT = [string]$m0Listener.LocalEndpoint.Port
$m0Listener.Stop()
.\node_modules\.bin\playwright.cmd test tests/workflow-m0.spec.ts --workers=1 --reporter=list --output=test-results/workflow-m0
```

手动查看原型：启动 `npm.cmd run dev` 后打开 `/m0/workflow.html`；标准主应用路径不增加原型入口。独立构建位于 `frontend/dist/workflow-m0/`，其站点入口为 `/m0/workflow.html`。

## 5. 进入 M1 的决定与边界

1. 保留一个原生 thread 固定一个流程修订。切换版本创建新 thread，澄清和恢复沿用原绑定。
2. 工厂从服务端持久归档解析绑定，并区分 `ServerRuntime.access_context`。只有 assistants 的结构查看可使用不执行的 schema 模板；thread 读取和执行缺绑定时拒绝。
3. 核心节点稳定命名。路由适配替换正常 `Command.goto`，保留等待／失败的 END；除 START 外不再叠加普通调度边。正式实现还需抽出显式业务结果契约。
4. 正式受理必须将修订、绑定、语义哈希和配置快照与受理意图原子提交。M0 的绑定表和重定向 `create_native` 是测试接缝，不可直接作为生产事务设计；原生直接入口的失败时机也需在 M1/M3 明确。
5. 恢复继续只开放既有三个安全父节点。正式协议须将流程版本和扩展状态加入输入摘要，兼容旧摘要，并处理不可用实现的历史查看；本轮不放宽任何生产恢复检查。
6. React Flow／Dagre 版本可用于 M1/M2。原型只证明基础交互；撤销、持久保存、发布、节点属性、完整合法拓扑和真正执行选择尚未实现。

本轮未调用真实模型、Tavily 或 LangSmith，不证明报告内容质量、模型网关可用性、扩展节点语义质量、多用户／多实例行为或研究子图任意断点恢复。模型／Skills 的既有固定配置用于恢复核对；不同模型／Skills 与不同流程修订的完整组合矩阵留到 M3。

性能尚未测量。后续采用上述基准环境，固定 50 节点／100 连线，记录 Chromium Performance 与交互耗时分位数；M2 验证画布 FPS／响应，M1 契约落地后测校验／发布 P95，M3 验证 100 个动态任务实例。4–7 节点原型与构建成功不能替代这些指标。

M1 下一步：冻结流程定义／展示数据／不可变修订／绑定 schema、节点目录及状态读写契约、合法拓扑、保存冲突与发布幂等协议；设计生产受理事务和兼容策略，再落实编辑页交互与验收用例。
