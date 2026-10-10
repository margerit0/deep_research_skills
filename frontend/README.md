# 星图工作台 · Apple 银白

独立的 React + TypeScript + Vite 前端。第一阶段只使用本地模拟数据，不需要启动 Python 服务、配置 API 密钥或加载设计预览宿主。

## 启动

需要 Node.js 22.12+（本次使用 22.17.0）和 npm。

```powershell
cd D:\deep_research_public_preview\frontend
npm ci
npm run dev
```

打开终端显示的地址，默认是 http://127.0.0.1:5173。依赖版本固定在 `package-lock.json`。

```powershell
npm run build       # 应用、配置、测试的 TypeScript 检查，然后生成 dist/
npm run preview     # 在本机预览生产构建，默认端口 4173
npm run typecheck
npm run test        # Playwright：使用本机已安装的 Google Chrome
npm run format:check
```

测试使用独立的临时浏览器上下文，不读取日常 Chrome 用户数据。测试自动启动 5173 端口的开发服务，也可复用已运行的服务。验收记录见 [docs/verification.md](docs/verification.md)。

## 已实现的本地操作

- 新建和切换多个对话，分别保存草稿、消息与运行历史；刷新恢复。
- Enter 发送、Shift+Enter 换行、输入法组词保护。每条发送消息保存独立的模型与 Skills 配置；查看旧消息的“当前步骤”可回到对应运行。
- 模型 / Skills 紧凑实色菜单：向上展开、选中标记、方向键及 Home/End、Esc 关闭并返回焦点、点击外部关闭。触屏目标至少 44 px。
- 可收起的运行图谱、当前步骤定位、节点检查器的概览 / 输入输出 / 执行记录。页签支持左右方向键及 Home/End；Esc 收起检查器并返回对应节点。
- “演示下一步”推进确认范围 → 并行研究 → 报告写作 → 完成。“重新演示”重置所选运行的阶段，保留它原来的配置。待执行节点没有结果或执行记录。
- 右上角外观按钮依次切换跟随系统、浅色、深色。保留 Apple 银白 / 石墨色板、28 px 模糊和边缘反光；遵循减少动态效果、减少透明度偏好。
- 桌面为侧栏、对话、350 px 图谱；收起图谱后对话居中且限宽 720 px。窄屏图谱排在对话下方，左上角星号打开最近对话抽屉。

会话保存在当前浏览器、当前站点的 `localStorage`（键 `atlas-workspace:v1`）。开发端口与生产预览端口的会话互不共享。损坏数据回退为初始演示；存储不可用或容量耗尽时会显示提示，内存中的操作仍可使用。当前不提供跨设备或多标签页同步。

## 模拟数据边界

模型菜单只是示例配置，不代表后端支持这些模型。Skills 是本地选择，没有调用后端 `load_skill`。回复、阶段、耗时、来源数量、节点输入输出、事件与最终报告均为模拟；没有模型请求、真实检索、流式响应或真实研究结论。

初始示例沿用已确认的三个研究员。新问题采用两个研究员的本地场景，图谱从数据渲染数量；真实研究员数量和多轮委派将来由后端事件决定。每条新消息在第一阶段建立独立的模拟运行，真实对话澄清与续跑协议尚未接入。

完整图仍按 `clarify_with_user → write_research_brief → supervisor_subgraph → final_report_generation` 展示。研究员内部的模型 / 工具循环和 `compress_research` 保留在检查器里。

## 代码结构

| 位置                          | 职责                                           |
| ----------------------------- | ---------------------------------------------- |
| `src/components/`             | 导航、消息、输入框、菜单、图谱、节点检查器     |
| `src/state/useWorkspace.ts`   | 不可变状态转换、会话选择、版本化本地存储与恢复 |
| `src/data/schema.ts`          | 运行、节点、会话类型和存储校验                 |
| `src/data/mock.ts`            | 模拟运行、阶段与节点视图适配                   |
| `src/data/example-nodes.json` | 已确认示例中的静态数据                         |
| `src/apple.css`               | 从已确认主 HTML 提取的 Apple 色板与原始样式    |
| `src/app.css`                 | 独立应用的滚动、窄屏导航与布局适配             |
| `tests/workspace.spec.ts`     | 行为与响应式浏览器验证                         |

`scripts/import-design.mjs` 记录一次性迁移方式。日常开发与构建不运行它；手动运行会重新生成 `apple.css` 和示例 JSON。应用不引用 `ui-drafts/`，也不依赖 `window.openai`、`Tweak`、`viz-carousel`、iframe 或宿主图标库。Lucide 图标随应用打包。

下一阶段可用 LangGraph 事件替换 `mock.ts` 的数据来源，并单独定义每次运行的模型与手选 Skills 契约。服务端凭据继续留在后端 `.env`。
