# 星图工作台 UI 草稿

这里保存截至 2026-10-10 的三套配色稿：Apple 银白、Claude 暖陶、青绿 · 林间。用户已选定 **Apple 银白**，准备在新会话实施；入口见 [Apple 前端实施交接](APPLE_IMPLEMENTATION.md)。共用已确定的对话布局、悬浮侧栏与图谱、带边缘光感的输入框，以及节点检查器。模型和 Skills 菜单仍是 Codex 风格的紧凑实色浮层。当前仅包含设计稿和本地演示交互，正式 React 前端尚未开始。配色稿提交为 `e99140f`，改色前的银灰基线为 `712bb45`。

## 打开与继续修改

- 直接用浏览器打开 [三套配色对照](preview/atlas-colorways-preview.html)，用下方轮播控件切换。资源已内嵌，可离线查看。
- 独立预览：[Apple 银白](preview/atlas-apple-preview.html)、[Claude 暖陶](preview/atlas-claude-preview.html)、[青绿 · 林间](preview/atlas-forest-preview.html)。深浅色跟随外观，也可通过设计控件调整。
- 修改 [可编辑源码](atlas-conversation-workspace.html)。它是用于对话预览的 HTML 片段。
- 继续设计前读取 [交接说明](HANDOFF.md)，保留对话布局、可收起图谱、紧凑模型/Skills 菜单及节点检查器。

## 文件结构

| 路径 | 内容 |
| --- | --- |
| `atlas-conversation-workspace.html` | 后续编辑的主源码 |
| `APPLE_IMPLEMENTATION.md` | 已选 Apple 银白的正式前端实施交接与新会话起始请求 |
| `atlas-colorways.html` | 从主源码生成的三套配色轮播片段，用于对话展示 |
| `preview/atlas-{apple,claude,forest}-*` | 三套独立片段及带内嵌资源的完整预览 |
| `preview/atlas-colorways-preview.html` | 完整轮播对照预览 |
| `preview/atlas-glass-workspace.html` | 对话中展示的片段副本，与主源码保持一致 |
| `preview/atlas-glass-preview.html` | 带预览包装和内嵌资源的完整 HTML |
| `references/atlas-glass-*.png` | 本版整体、菜单、检查器、深浅色与窄屏参考图 |
| `references/atlas-glass-verification.json` | 本版交互、尺寸和布局验证记录 |
| `references/atlas-liquid-verification.json` | 本轮指针高光与减少动态效果/透明度的专项校对记录 |
| `references/atlas-pickers-*` | 加入玻璃效果前的参考图和验证记录 |
| `scripts/inspect-atlas-glass.cjs` | 生成预览、截图与交互校对的脚本 |
| `scripts/verify-picker-icons.cjs` | 图标库缺失/延迟加载情况下的按钮与菜单回归校对 |
| `scripts/build-colorways.cjs` | 从共享源码生成三套配色与对照稿；只替换色板和隔离标识 |
| `scripts/inspect-colorways.cjs` | 三套配色的截图、对比度、深浅色布局、菜单与轮播校对 |
| `references/atlas-colorway-*` | 三套配色的深浅色、窄屏和菜单参考图 |
| `references/atlas-colorways-verification.json` | 本轮配色专项校对记录 |
| `vendor/` | 固定版本 Floating UI、Lucide 按钮图标遮罩与许可 |

原来的 `docs/frontend-ui/HANDOFF.md` 保留为迁移入口。此前聊天使用的可视化目录副本仍保留，以维持已展示内容的可用性；项目内本目录是后续工作的依据。

## 本地校对

查看现有预览无需安装依赖。重新生成需要已有的 Node.js、Playwright、Chromium、Python，以及当前环境的 `visualize` 技能。脚本通过环境变量接受本机工具路径，不依赖旧聊天的工作目录。

| 环境变量 | 用途 |
| --- | --- |
| `ATLAS_VISUALIZE_RENDERER` | 必填，指向当前 `visualize` 技能的 `scripts/render.py` |
| `ATLAS_NODE_MODULES` | 可选，已有 Node.js 依赖目录；省略时使用正常模块解析 |
| `ATLAS_PYTHON` | 可选，Python 可执行文件；默认 `python` |
| `ATLAS_LUCIDE_UMD` | 可选，Lucide UMD 文件；默认从现有依赖中定位 |
| `ATLAS_CHROMIUM_EXECUTABLE` | 可选，已安装 Chromium 路径；默认使用 Playwright 管理的浏览器 |

在项目根目录执行：

```powershell
node ui-drafts/atlas-workspace/scripts/inspect-atlas-glass.cjs --verify
node ui-drafts/atlas-workspace/scripts/build-colorways.cjs
node ui-drafts/atlas-workspace/scripts/inspect-colorways.cjs
node ui-drafts/atlas-workspace/scripts/verify-picker-icons.cjs
```

脚本会更新 `preview/` 的预览及片段副本，以及 `references/` 的截图和验证记录。省略 `--verify` 仅进行预览冒烟检查，验证记录也会被该次结果覆盖，因此完整校对请保留此参数。

本轮重新通过了 7 个节点、3 个检查器页签、菜单、状态恢复、深浅色和 320–1440 px 布局检查；三套色板另通过 30 组布局及主要文字颜色对比度检查。重载前会等待独立预览的异步保存完成；完整验证同时断言没有运行错误、控制台错误和资源请求失败。液体玻璃的指针高光与系统辅助显示偏好专项记录保留自前一轮基线。

图标专项校对还需已有 Sharp。它模拟宿主未提供 Lucide，验证模型与 Skills 按钮的三个图标仍可显示、菜单仍可通过鼠标和键盘操作、窄屏位置正常，并验证后续加载 Lucide 不产生重复图标。结果与局部截图保存在 `references/atlas-picker-icons-*`。
