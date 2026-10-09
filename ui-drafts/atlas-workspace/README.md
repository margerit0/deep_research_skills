# 星图工作台 UI 草稿

这里保存截至 2026-10-10 的玻璃对话版，作为继续修改前的版本基线。当前包含设计稿和本地演示交互；正式 React 前端及后端接入尚未开始。

## 打开与继续修改

- 直接用浏览器打开 [完整预览](preview/atlas-glass-preview.html)。资源已内嵌，可离线查看。
- 修改 [可编辑源码](atlas-conversation-workspace.html)。它是用于对话预览的 HTML 片段。
- 继续设计前读取 [交接说明](HANDOFF.md)，保留对话布局、可收起图谱、紧凑模型/Skills 菜单及节点检查器。

## 文件结构

| 路径 | 内容 |
| --- | --- |
| `atlas-conversation-workspace.html` | 后续编辑的主源码 |
| `preview/atlas-glass-workspace.html` | 对话中展示的片段副本，归档时与主源码完全一致 |
| `preview/atlas-glass-preview.html` | 带预览包装和内嵌资源的完整 HTML |
| `references/atlas-glass-*.png` | 本版整体、菜单、检查器、深浅色与窄屏参考图 |
| `references/atlas-glass-verification.json` | 本版交互、尺寸和布局验证记录 |
| `references/atlas-pickers-*` | 加入玻璃效果前的参考图和验证记录 |
| `scripts/inspect-atlas-glass.cjs` | 生成预览、截图与交互校对的脚本 |
| `vendor/` | 独立预览所用的固定版本 Floating UI 资源 |

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
```

脚本会更新 `preview/` 的预览及片段副本，以及 `references/` 的截图和验证记录。省略 `--verify` 仅进行预览冒烟检查，验证记录也会被该次结果覆盖，因此完整校对请保留此参数。

本次归档沿用已经通过的 7 个节点、3 个检查器页签、菜单、状态恢复、深浅色和 320–1024 px 布局检查。整理目录时逐文件核对了移动或复制内容的 SHA-256，主源码未作设计修改。
