# Graph 流程编辑器 v1 契约

冻结日期：2026-11-15（Asia/Shanghai）。用户已对[独立设计稿](graph-canvas-editor-design-review.md)明确回复“确认设计稿”。本契约作为 M2 编辑与版本管理、M3 编译与执行接入的共同依据。

M1 已冻结数据类型、节点目录和校验语义，M2 已实现管理与正式编辑页。M3 已接入真实业务适配、发布上下文、原子受理绑定、父节点事件和正式运行视图，见 [M3 记录](graph-canvas-editor-m3-results.md)。能力根据实际存储、工厂注册、实现和运行时就绪状态分别声明。

## 1. 类型与版本

权威入口为 [Python 类型](../src/deep_research/workflow_definition.py)、[节点目录](../src/deep_research/workflow_registry.py)、[校验器](../src/deep_research/workflow_validation.py)和[前端类型](../frontend/src/data/workflowSchema.ts)。机器可读定义见 [JSON Schema](contracts/workflow-v1.schema.json)，各类型位于 `$defs`。

| 对象 | 固定语义 |
| --- | --- |
| `WorkflowDefinition` | `schema_version: 1`；节点、正常控制连线、流程默认配置；不包含坐标或运行状态 |
| `WorkflowDocument` | 流程名称、执行定义和展示信息；作为草稿的一次完整保存内容 |
| `NodeDefinition` | 稳定 `id`、类型 `type`、`type_version` 和参数；不接收函数路径、任意工具或节点级模型覆盖 |
| `EdgeDefinition` | `id/source/source_port/target/target_port`；首版只开放 `out → in` |
| `WorkflowPresentation` | 独立版本、节点标签／坐标和视口；未保存坐标的节点由前端自动排列 |
| `WorkflowDraft` | 流程 ID、当前 `edit_version`、基础修订、完整文档和更新时间 |
| `WorkflowRevision` | 服务端修订 ID、递增编号、源草稿版本、执行摘要、兼容版本、完整文档、说明和发布时间 |
| `WorkflowBinding` | 一个原生 thread 的流程引用、执行摘要、兼容版本及绑定时间 |
| `WorkflowValidation` | 校验范围、确切草稿版本、问题清单、是否截断；不能同时声明通过和存在错误 |

创建时由服务端生成 `workflow_id` 和 `revision_id`。展示版本由 `revision_number` 派生，首个版本为 v1，后续递增；设计稿中的 v2.3/v2.4 是示例标签，不要求用户管理语义版本号。

运行兼容版本分为 `compiler_version`、`node_registry_version`、`state_schema_version`，初值均为 1；执行入口固定为 `research_workflow`。版本相等仍须检查节点实现及实际 LangGraph 运行时可用性；M1 的类型常量不等于生产能力声明。

数值版本必须为正的安全整数，拒绝布尔、字符串、浮点版本及超出 JavaScript 安全整数的值。时间使用带偏移的 RFC 3339 字符串。文本长度按 Unicode 码点计算；整个文档另受 256 KiB UTF-8 大小限制。HTTP 层须在解码之前限制原始请求体大小。

## 2. 节点与状态

核心运行标识与 M0／现有业务函数保持一致。开始和结束是编辑定义中的系统节点，编译为 LangGraph START／END 边界，不引入新的业务函数。

| 类型 | 数量／身份 | 正常后继 | 模型角色 |
| --- | --- | --- | --- |
| `start` | 必需一个，ID 固定 | `prepare_research` | 无 |
| `prepare_research` | 必需一个，ID 固定 | 澄清或简报 | 无 |
| `clarify_with_user` | 零或一个，存在时 ID 固定 | 简报 | SCOPING |
| `write_research_brief` | 必需一个，ID 固定 | 计划优化或研究子流程 | SCOPING |
| `optimize_plan` | 可有多个，实例 ID 独立 | 计划优化或研究子流程 | SCOPING |
| `supervisor_subgraph` | 必需一个，ID 固定 | 材料整理或报告 | SUPERVISOR、RESEARCHER、SUMMARIZATION、COMPRESSION |
| `organize_notes` | 可有多个，实例 ID 独立 | 材料整理或报告 | COMPRESSION |
| `final_report_generation` | 必需一个，ID 固定 | `end` | FINAL_REPORT |
| `end` | 必需一个，ID 固定 | 无 | 无 |

基础节点参数为空对象。v1 草稿的参数键只允许 `instructions`，并在保存／导入的结构解析时拒绝模型覆盖、密钥或任意代码等额外字段。两个扩展类型发布时必须包含非空白 `instructions`，最多 4000 码点；基础节点发布时仍须为空参数。处理要求是插入固定消息段的纯文本，不是模板变量语言。多个同角色节点沿用本轮研究相同的模型快照。

节点目录公开允许的输入输出、正常后继、角色、参数描述及状态读写模式，不公开处理函数或凭据。后端的读写清单见 `state_reads/state_writes`；生产适配器须限制业务更新字段，并按 `replace/overwrite/merge_messages` 处理 reducer。

关键状态决定：

1. **计划优化**同时替换 `research_brief` 和 `supervisor_messages`。后者使用 `Overwrite`，使协调器读取优化后的简报。
2. **材料整理**写入独立的 `organized_notes`，不改写 `notes/raw_notes/sources/source_evidence`，不注册新检索来源。初始化将该字段置为 `None`；首个整理节点使用原笔记，后续整理节点可消费前一份整理结果。写作在该字段非 `None` 时使用整理结果，否则使用原笔记；空整理结果须按失败处理，不能悄悄回退伪装成功。
3. **绑定**由编译器／受理层安装为 `workflow_binding`，不允许扩展节点改写。
4. **系统结果**采用 `WorkflowBusinessResult.outcome`；正常 `continue` 只取定义中的唯一后继，等待／失败／部分完成进入系统终态。业务节点不能提供任意 `goto`。编译器使用单一路由机制，不同时保留旧 `Command.goto` 与普通后继边。
5. **澄清**的等待回答出口不由用户编辑；回答依旧是同 thread 的新提交，不迁移到 `interrupt/resume`。

首版最多 30 个主流程节点，包含开始、初始化和结束。发布路径必须为一条完整、无环的正常链。草稿可以暂时为空、断连或未填参数；未知节点类型保留为待修复问题，不能发布。字段类型错误、非有限坐标、非法字段以及超过大小限制的文档不能保存。首版不开放任意分支、循环或研究员内部编辑。

## 3. 执行摘要与发布快照

`semantic_hash()` 和前端 `workflowSemanticHash()` 使用相同的 SHA-256 输入规则：

- 覆盖定义版本、节点实例 ID／类型／实现版本／参数、正常连接和流程默认配置。
- 节点和连线按确定顺序排列；Skills 手选列表排序。
- 不覆盖流程名称、节点标签、坐标、视口、连线 ID 或数组存储顺序。
- 编译器、节点目录及状态版本由兼容对象另外固定，缓存键须同时包含摘要和兼容版本。

只有经过校验的 v1 参数进入发布摘要。首版参数为文本或空对象；前端摘要函数不承诺为未知未来节点的任意数字参数提供跨语言规范化。

发布记录仍包含完整名称和展示快照。执行摘要只能验证执行定义的完整性，不能替代数据库对发布记录的不可变约束；即使仅修改坐标，也必须形成新的草稿或修订，不能更新旧修订。存储回读检查摘要、流程归属和兼容字段，不重新计算后覆盖损坏的原摘要。

## 4. M2 保存、校验和发布协议

以下管理接口已在 M2 实现；客户端只在 `workflow_editor_version: 1` 明确存在时显示正式编辑入口。M3 的生产发布上下文检查实际处理器和配置；执行上下文不可用时，校验／发布返回 503 `workflow_runtime_unavailable`，不使用占位实现放行。

| 接口 | 请求／返回内容 |
| --- | --- |
| `GET /atlas/workflow-node-types` | 返回 `WorkflowNodeCatalog` |
| `GET /atlas/workflows` | 返回 `WorkflowPage`，含 `WorkflowSummary` 列表及下一页游标 |
| `POST /atlas/workflows` | `CreateWorkflowRequest`；从标准模板、发布引用或导入文档新建流程，返回 `WorkflowDraft` |
| `GET /atlas/workflows/{id}` | 返回当前 `WorkflowDraft`；只读查询不创建或发布新内容 |
| `GET /atlas/workflows/{id}/summary` | 返回 `WorkflowSummary`，供直接打开页面时核对归档状态和最新发布引用 |
| `PUT /atlas/workflows/{id}/draft` | `SaveDraftRequest`；返回保存后的 `WorkflowDraft` |
| `POST /atlas/workflows/{id}/validate` | `ValidateWorkflowRequest`；返回 `scope: publication` 的 `WorkflowValidation` |
| `POST /atlas/workflows/{id}/publish` | `PublishWorkflowRequest`；返回已固定的 `WorkflowRevision` |
| `GET /atlas/workflows/{id}/revisions` | 返回 `WorkflowRevisionPage`；条目为从修订投影的 `WorkflowRevisionSummary` |
| `GET /atlas/workflows/{id}/revisions/{revision_id}` | 返回完整不可变 `WorkflowRevision` |
| `POST /atlas/workflows/{id}/archive` | `ArchiveWorkflowRequest` 含预期草稿版本；返回归档后的 `WorkflowSummary`，不删除记录或运行绑定 |

分页参数为 `after=0` 起始、`limit=30` 默认且最多 100；流程筛选为 `archived=active|archived|all`，默认 `active`。流程按创建序号倒序，保存不改变分页位置；修订按 `revision_number` 倒序。`next_cursor` 是下一页的排他游标，无更多记录时为 `null`。归档只在首次操作时核对草稿版本，已经归档的流程重复请求返回其摘要。

存储迁移在受理连接的事务内进行。M2 使用 `workflow_schema.version=1`，M3 追加逐提交绑定和父事件表后升级为 **2**，受理库的 `user_version=2` 不变。修订、创建／发布回执、绑定及父事件有禁止更新／删除的约束；修订回读另外校验包含展示快照的完整记录摘要。请求体在解码前限制为 278528 字节，文档规范化后仍限 256 KiB。重复 JSON 键和非有限值也拒绝。

### 草稿保存

初始草稿版本为 1。每次成功写入在同一事务检查 `expected_edit_version`、保存完整文档、更新时间并递增版本。过时写入返回 409：

```json
{"reason":"workflow_edit_conflict","current_edit_version":13}
```

前端继续保留本地文档，提供另存新流程或备份后载入较新草稿。自动保存建议在最后一次编辑约 800ms 后发出，一次拖动只记一个撤销项。连续保存串行合并；较旧响应不能覆盖较新的本地改动。

保存响应丢失时先 GET 回读。若文档与本次提交的完整内容相同，可确认保存完成；否则保留本地并进入冲突处理，不用新的版本号盲目重放旧文档。结构未完成的合法草稿可保存，但不能发布。

### 校验

前端 `validateWorkflowStructure()` 的结果属于 `scope: structure`。服务端加载确切保存版本，以实际节点实现、模型修订、Skills 目录和运行兼容性构建 `PublicationContext`，完成 `scope: publication` 校验；该范围必须提供非空 `checked_edit_version`。没有服务器上下文和确切版本的本地通过结果不构成发布凭证。

问题使用稳定 `code/severity/node_id/edge_id/field/message`；`field` 为 JSON Pointer。最多返回 100 项，超过时置 `truncated: true` 并保持未通过。提示不回显参数原文、密钥或提供商异常。

### 发布与重试

请求仅含 `request_id/expected_edit_version/note`；客户端不能指定发布 ID、执行摘要或执行图。UI 在发出请求前持久保存请求 ID，重复点击和未知结果重试复用同一 ID。

服务端先按目标草稿版本取得快照，在写事务外完整校验。在写事务内按以下顺序操作：

1. 查发布请求记录。同 ID 与相同规范化请求返回原修订，即使草稿版本已经变化；同 ID 但内容不同返回 `workflow_request_conflict`。
2. 确认流程未归档、草稿版本和被校验的完整文档仍一致；不一致返回 `workflow_edit_conflict`。
3. 分配递增修订编号，插入完整修订与请求结果映射，不更新任何旧修订。
4. 将同流程草稿的基础修订指向新版本，并递增草稿编辑版本。UI 进入发布版只读视图；再次编辑时 GET 新的草稿版本。

从旧版本复制或从运行历史的旧版本创建副本时，首版使用 `CreateWorkflowRequest.source.kind: revision` 创建新流程 ID。编辑当前发布版本使用同流程的基线草稿。已有更新的本地或服务器草稿须保留，不能因打开一个旧版本而隐式覆盖。

导入只接收 `WorkflowDocument`，先执行结构／类型及大小检查，生成新的流程身份；不导入修订身份、thread 绑定、运行事件或秘密配置。导入的合法但未完成拓扑仍以草稿展示其问题。

错误约定：无效结构或请求为 400；未知流程／修订为 404；并发、重试内容或归档冲突为 409；发布校验不通过为 422 并附 `WorkflowValidation`；存储或执行能力不可用为 503。异常正文不进入响应。

## 5. M3 受理事务与版本绑定

受理请求只新增可选引用：

```json
{"workflow_ref":{"workflow_id":"workflow-example","revision_id":"revision-example"}}
```

它是现有提交体的补充，不替代研究 ID、原文、前一 turn 及配置选择。未提供或为 `null` 时，解析后移除该字段，保留旧 `digest(payload)` 语义。服务端记录的有效绑定另外持久化，不能擅自把推导出的字段补入原请求摘要。

绑定规则：

- 全新、空的原生 thread 可选择已发布且未归档流程的版本；省略引用沿用旧默认图语义。
- 已有绑定的 thread 在后续研究、澄清、重试和恢复中沿用该修订。省略引用从受理归档解析；显式提供不同引用返回 `workflow_binding_conflict`，切换版本使用新 thread。
- 已有旧图运行／检查点的 thread 不能升级为新结构，返回 `legacy_workflow_locked`。
- 发布新版本、归档流程或当前默认模型改变，不改写已有研究的流程和配置快照。归档只阻止新 thread 选择该流程，既有绑定的受支持执行可继续。

流程表、草稿表、修订表、发布请求表及 `workflow_thread_bindings` 放在现有受理 SQLite。修订记录使用追加约束；编号和幂等键用唯一索引；绑定对 thread 唯一并引用原修订。

**同一连接、同一 `BEGIN IMMEDIATE` 事务**同时写入或核对：原修订引用及内容／版本、thread 绑定、逐提交绑定副本、`submission_configurations` 的有效配置快照、submission payload／摘要和固定 run UUID 的 attempt。实现使用 `SubmissionJournal.reserve_in_connection()`，不先在独立连接提交绑定。受理回执在存在绑定时增加 `workflow_binding`，不改写原 payload。

模型和 Skills 的完整内容归档仍使用现有配置归档，在受理事务之前完成解析、归档和完整性检查。同事务固定的是有效配置快照及引用；不能把多个 SQLite 文件宣称为一个原子提交。保留既有归档与备份规则，事务失败可留下未被引用的不可变配置，但不能留下缺少绑定或快照的已受理研究。

原生 thread 持久化先于受理意图；原生 run 创建在意图提交之后，沿用已分配的 UUID。LangGraph 原生数据和受理 SQLite 不是同一个事务，继续使用现有持久化屏障、回执回读、执行声明及恢复机制。

## 6. 工厂、观察与恢复

工厂须按访问上下文区分用途：assistants 的结构查看可返回不执行的模板；thread 状态／历史读取必须定位该 thread 的原绑定。绑定缺失、修订缺失、摘要错误或实现不可用时明确失败，不退回最新发布版或默认图。

`verify_binding()` 核对 thread、流程／修订引用、执行摘要及兼容版本。完整的旧 v1 归档在编译器不可用时仍可只读查看；执行必须拒绝。更新版本不能代替旧实现。正式受理入口须在创建 run 前完成可执行性校验，避免将 M0 的“创建后 error run”作为产品行为。

恢复白名单仍为 `clarify_with_user/write_research_brief/final_report_generation`。两类扩展节点和研究子图内部均不声明可恢复。M3 扩展 `state_digest()` 时仅在键实际存在时加入 `workflow_binding/organized_notes`，不能用 `.get()` 给旧检查点补 `null`；旧摘要必须保持字节级一致。恢复以精确 checkpoint 和 `input: null` 使用原修订、原输入及原配置。

父节点事件使用 `atlas.workflow_event`，载荷为 `WorkflowNodeEvent`。事件 UUID、归属标识、原生 run、attempt、修订、节点和连续序号必须核对；先持久化再投递。开始／结束编译为系统边界，不创建业务调用或父事件。动态研究员继续使用原事件，不成为设计时节点。前端实际完成状态来自节点事件与检查点，业务成功仍要求研究终态、正确报告归属及有效产物。

回放入口为 `GET /atlas/threads/{thread_id}/runs/{run_id}/workflow-events`，必需 query 为 `research_id/turn_id/attempt_id`，可选 `after=0/limit=50/journal_id`，`limit` 上限 100。返回原事件分页公共字段及 `attempt_id/workflow_ref/semantic_hash`；按 run 连续计数，先校验完整归属再返回。事件在受理库保留，`sealed` 不是业务成功标记。旧进程的未完成尝试返回 `gap` 与 `unconfirmed_before_sequence`，前端不会继续显示其未确认节点为运行中。

生产能力分开声明：`workflow_editor_version`、`workflow_execution_version` 和 `workflow_events_version`。M3 已通过原生替身验收；当前服务还须实际注册生产工厂并具备兼容实现，才声明执行和事件版本。只有编辑能力时不能出现可真实执行的版本入口；旧后端不支持所选流程时拒绝，不静默运行内置图。真实发布校验依赖实际节点实现，不能使用占位处理器冒充可执行。

## 7. 已冻结的后续验收

| 阶段／场景 | 必须核对的结果 |
| --- | --- |
| M2 · 编辑与撤销 | 添加、删除、拖动和连接只生成预期操作；输入框／IME 不触发画布 Delete 或撤销 |
| M2 · 持久化 | 重开草稿恢复内容与布局；失败保留本地；双窗口过时写入不覆盖新内容 |
| M2 · 幂等发布 | 丢失发布响应后同 ID 只得到一个修订；改用不同内容但相同 ID 被拒绝 |
| M2 · 发布竞态 | 校验后草稿变化导致拒绝；发布记录的定义、布局和源编辑版本一致 |
| M2 · 副本／归档 | 旧版本副本有新流程身份；归档不删运行引用；导入无法携带执行或秘密字段 |
| M2 · 定稿界面 | 1440／1024 三栏、390／320 查看布局、银白／石墨、键盘与减少动画均可用 |
| M3 · 实际路径 | 添加／删除扩展节点改变真实调用计数；无旧 goto 与新后继重复执行 |
| M3 · 业务语义 | 计划优化后的简报被协调器使用；材料整理保留来源与原始笔记；无有效材料不生成成功报告 |
| M3 · 事务故障 | 受理前后退出不产生孤立绑定或重复 run；原请求回读／重试沿用同一身份 |
| M3 · 澄清并发 | v1 等待时发布 v2，原 thread 继续 v1；显式切换被拒绝，新 thread 可选 v2 |
| M3 · 配置组合 | 不同流程／六角色模型／Skills 的快照互不混用；恢复仍取原归档 |
| M3 · 重启恢复 | 三个安全边界恢复原版本；不安全位置保留成果，不自动续跑 |
| M3 · 兼容与事件 | 缺失实现可查看完整旧归档但不能执行；刷新、重连和历史回放不新增 run |
| M4 · 实际质量／性能 | 按计划书运行有界真实验收、画布和发布性能测量；不以替身结果替代报告质量 |

上述表格是分阶段验收条件。M1、M2 和 M3 已完成，M2 的发布测试上下文限制已由 M3 的生产实现接续。[M4 实际证据](graph-canvas-editor-m4-results.md)区分后端通过、本地基准、浏览器超时和暂缓的真实质量；模型／检索替身不代表真实研究质量。
