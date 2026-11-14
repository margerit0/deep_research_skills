# Graph 流程编辑器 M2 验证记录

日期：2026-11-15（Asia/Shanghai）。实现基线为 `codex/graph-canvas-editor` 的 M1 提交 `622ffb8`。用户已确认设计稿并明确要求执行 M2；本阶段接入正式编辑与版本管理，执行编译和新流程研究仍属于 M3。

## 1. 实际交付

- [WorkflowStore](../src/deep_research/workflow_store.py) 在现有受理 SQLite 中进行追加迁移，沿用同一连接的 `BEGIN IMMEDIATE`、WAL、FULL 同步及外键。工作流独立使用 `workflow_schema.version=1`，受理库 `user_version` 保持 2。
- [管理 API](../src/deep_research/workflow_api.py) 提供节点目录、创建、分页查询、草稿保存、精确版本校验、幂等发布、修订读取和归档。新增摘要及分页类型已由 [导出脚本](../scripts/export_workflow_contract.py) 同步到 JSON Schema 和前端类型。
- [正式编辑界面](../frontend/src/components/workflow/WorkflowWorkspace.tsx) 从工作台进入，包含三栏画布、节点库、参数、端口与键盘连线、整步撤销、保存／冲突处理、校验定位、发布只读视图、版本历史、导入导出及归档。
- [编辑状态](../frontend/src/state/useWorkflowEditor.ts) 串行合并保存，按完整文档回读未知结果；较旧响应不替换新输入。每个窗口有独立恢复副本，创建／发布请求在发出前保存标识，重试沿用原请求。
- 编辑器作为单独资源按需加载。1440／1024 桌面和 390／320 窄屏、浅深色及减少动画均有浏览器检查。使用方法见 [编辑器说明](../frontend/docs/workflow-editor.md)。

生产 `/atlas/config` 仅在管理存储可用时增加 `workflow_editor_version: 1`。**本阶段没有生产编译器，默认发布上下文不可用，生产校验／发布明确返回 503 `workflow_runtime_unavailable`。** 测试注入的上下文只用于验证事务和界面，不作为生产节点实现。未增加 `workflow_execution_version`、`workflow_events_version`、新 graph 注册或原生执行入口。

## 2. 存储与协议结论

初始草稿版本为 1，保存按预期版本递增，结构未完成但类型合法的内容仍可保存。发布请求在读取草稿版本和检查运行能力之前查幂等回执；成功发布同时固定不可变修订、回执映射及草稿新基线。事务中断不会留下半个发布结果。

修订及请求映射禁止 SQL 更新／删除；回读核对流程归属、修订编号、源草稿版本、执行摘要和完整记录校验值。后者包含名称与布局，不能用排除展示数据的执行摘要替代。归档不会删除草稿、修订或绑定引用。

分页采用 `after=0` 起始、默认 `limit=30`、上限 100。流程按创建序号倒序，保存不改变分页位置；修订按版本编号倒序。页尾 `next_cursor` 为排他的下一页游标，无更多记录时为 `null`。流程筛选为 `archived=active|archived|all`。

原始 HTTP 请求体上限为 278528 字节，解码前按流累计限制；文档规范化后仍受 256 KiB 上限约束。重复 JSON 键、非有限值、额外字段与无效身份均拒绝，错误响应不回显原输入或异常正文。归档请求也核对预期草稿版本。

M2 只预留 `workflow_thread_bindings` 表，没有写入生产绑定。M3 仍须将绑定、配置快照、受理意图与固定 run UUID 放进同一连接的事务；现有提交体、摘要、恢复边界和检查点字段均未更改。

## 3. 验证结果

| 检查 | 实际结果 |
| --- | --- |
| M2 后端存储／API | 45 项通过：存储 26 项、HTTP 19 项 |
| 后端契约及相关回归 | 129 项通过：v1 契约 78 项、M0 单元 12 项、受理日志 24 项、配置 15 项 |
| 正式编辑器浏览器 | 25 项通过，含复制标签页的草稿及创建回执隔离 |
| 前端契约及旧页面 | 契约 65 项、旧工作台／研究／受理／演示／实录 74 项通过 |
| TypeScript 与生产构建 | 通过；编辑器单独加载 |
| Python 静态检查、格式与生成物 | Ruff 检查／格式、变更前端源码的 Prettier 检查及生成物校验通过 |

后端实际合计 **174 项通过**，前端合计 **164 项通过**，均无失败或跳过。后端证据为 `.local/graph-canvas-m2/backend-results.xml`，前端证据为 `.local/graph-canvas-m2/frontend-results.xml`。前端契约 65 项使用 Playwright 运行器，但不是浏览器界面场景。管理路由整理导入后另行复测 19 项，通过记录为 `api-final.xml`。统一前端回归后修复画布端口刷新与首次测量时机，再复测全部编辑器 **25 项通过**，记录为 `frontend-editor-final.xml`，并核对更新后的截图。

主要测试入口：

- [存储测试](../tests/test_workflow_store.py)：创建与发布并发、过时保存、校验后竞争、完整事务回滚、迁移、完整归档读取、不可变约束、旧版本副本、归档及分页。
- [HTTP 测试](../tests/test_workflow_api.py)：完整管理闭环、请求大小／类型／秘密字段、状态码和能力声明。
- [编辑器测试](../frontend/tests/workflow-editor.spec.ts)：增删／复制／连接／拖动／键盘／IME、自动保存、两个窗口、未知保存／发布结果、导入导出、发布竞争、归档、存储失败及五种尺寸／主题组合。
- [契约测试](../frontend/tests/workflow-contract.spec.ts)：两端字段、问题协议、Unicode 和执行摘要一致性。

截图位于 `.local/graph-canvas-m2/screenshots/`：`editor-1440-light.png`、`editor-1024-light.png`、`editor-1024-dark.png`、`editor-390-light.png`、`editor-320-light.png`。已查看桌面浅深色与 320 像素属性面板。关键控件无横向溢出，窄屏只读，不承诺触屏拖拽编排。

测试期间发现并修复了选中状态反复同步、连线删除后表单收起、暂时空名称的恢复及保存中继续编辑后的未知结果恢复。React Flow 测量信息在更新时保留，初次适应画布等待原生测量批次，端口换边时才主动刷新内部坐标。验收核对默认视图中的结束节点及连线路径的屏幕端点与实际端口位置；最终专项检查不再出现此前的 ResizeObserver 循环提示。

## 4. 复现命令

使用已安装且与锁文件一致的项目虚拟环境。根目录：

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.local\uv-cache'
New-Item -ItemType Directory -Path .local/graph-canvas-m2 -Force | Out-Null
$m2Temp = Join-Path (Get-Location) ('.local\graph-canvas-m2\pytest-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/test_workflow_store.py tests/test_workflow_api.py tests/test_workflow_definition.py tests/test_workflow_factory.py tests/test_submission_journal.py tests/test_run_configuration.py -q --basetemp $m2Temp --junitxml .local/graph-canvas-m2/backend-results.xml
uv run --locked --extra dev python -m scripts.export_workflow_contract --check
uv run --locked --extra dev ruff check src/deep_research/workflow_definition.py src/deep_research/workflow_store.py src/deep_research/workflow_api.py src/deep_research/atlas_api.py scripts/export_workflow_contract.py tests/test_workflow_store.py tests/test_workflow_api.py
```

`frontend` 目录：

```powershell
npm.cmd run build
$env:CI = '1'
$m2Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$m2Listener.Start()
$env:ATLAS_TEST_PORT = [string]$m2Listener.LocalEndpoint.Port
$m2Listener.Stop()
$env:PLAYWRIGHT_JUNIT_OUTPUT_FILE = '..\.local\graph-canvas-m2\frontend-results.xml'
.\node_modules\.bin\playwright.cmd test tests/workflow-editor.spec.ts tests/workflow-contract.spec.ts tests/workspace.spec.ts tests/live.spec.ts tests/live-submissions.spec.ts tests/demo.spec.ts tests/recordings.spec.ts --workers=2 --reporter=dot,junit
```

本机为 Node 22.17.0、Python 3.13.3、Playwright 1.64.0 和已安装的 Chrome。Windows 沙箱内的 Python asyncio 回环连接被阻塞，HTTP／浏览器检查在允许本地回环连接的环境中运行；UV 使用项目内缓存。测试数据库、浏览器上下文及 Vite 端口独立，没有启动或停止日常研究服务。旧演示离线场景的本机配置连接拒绝日志不代表研究执行失败。

## 5. 下一阶段

M3 仍须实现真实业务适配器、编译器、实际可用发布上下文、版本与受理同事务绑定、节点事件和原生故障验收。只有完成对应验收后，才能开放生产发布和“使用此版本发起新研究”，并声明执行／事件能力。

本轮没有调用真实模型、搜索或评估服务，未改动后端 `.env`、锁文件、M0 原型或既有 `frontend/design-mockups/`。未运行 M3 原生执行闭环、真实模型质量或 M4 性能矩阵；本记录不将界面与替身结果作为真实研究执行证据。
