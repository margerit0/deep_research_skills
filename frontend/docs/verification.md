# 第一阶段验收记录

## 全流程演示增量验收 · 2026-10-10

基准提交 `77a3542`，分支 `chore/public-edits`。在现有 React 应用中增加约 65 秒、18 幕的全流程演示；原 Apple 银白 / 石墨配色、玻璃面板、紧凑实色菜单及三栏布局继续保留。

- 播放内容：模型 / Skills 展开、模拟输入、消息入场与逐字回复、确认范围、生成简报、并行研究员脉冲与进度、连线流动、输入输出、事件逐条到达、笔记汇总、报告逐字生成、完成标记、图谱收放和外观切换。
- 控制：暂停 / 继续、前后章节、进度条跳转、1× / 1.5× / 2×、重播和退出。手动检查暂停；标签页隐藏暂停；自动切场不抢键盘焦点。
- 隔离：演示状态仅存在内存中。验证退出、刷新和切回原会话后保留草稿、运行配置快照及外观；演示期间修改模型不改写已开始运行的配置。
- 可访问性：减少动态效果时关闭动画并直接显示完整文本；保留减少透明度支持。手机播放器与章节按钮触屏目标至少 44 px，章节条单行横向滑动，当前场景自动滚动到播放器下方。
- Chrome 共 26 项检查通过，包括原有 19 项和新增 7 项。新增用受控浏览器时钟验证完整自动播放、暂停期间文本和时间冻结、倍速、跳转、重播及隐藏标签页暂停；覆盖 1440、1024、390、320 px 演示布局。原有深浅色 320–1440 px、输入法、存储恢复等回归保持通过。
- `npm run build`、`npm run typecheck`、`npm run format:check` 与 `git diff --check` 全部通过。手机章节条调整后，7 项演示检查再次通过，并验证播放器高度与图谱可见范围。本轮浏览器验收使用 `ATLAS_TEST_PORT=5174`，避开旧开发服务缓存的空模块。

截图由实际 React 应用生成。静态验收截图关闭动态效果以便检查布局，动画行为另由正常动态效果下的播放测试验证。

- [演示 · 浅色桌面](screenshots/demo-light-1440.png)
- [演示 · 深色桌面](screenshots/demo-dark-1024.png)
- [演示 · 390 px 手机视口](screenshots/demo-light-390.png)
- [演示 · 完整报告](screenshots/demo-report-1440.png)

所有内容仍为本地模拟；没有真实模型、检索、流式网络响应或研究结论。浏览器检查范围仍为 Chrome，未执行 Safari / Firefox。

## 原第一阶段基线

日期：2026-10-10。实现基准为 `ui-drafts/atlas-workspace/APPLE_IMPLEMENTATION.md`、主 HTML 与 Apple 浅色 / 深色 / 窄屏 / 菜单参考截图。

## 执行环境与检查

- Windows，Node.js 22.17.0；React、TypeScript、Vite、Lucide、Playwright 版本固定于锁文件。
- `npm run build`：应用及工具配置的 TypeScript 检查、Vite 生产构建通过。
- `npm test`：19 项 Playwright / Chrome 检查全部通过。
- `npm run format:check`：手写代码格式检查通过。

行为检查覆盖模型和 Skills 的图标、实色背景、鼠标 / 键盘选择、单菜单互斥、Esc 焦点恢复、点击外部关闭；Enter 发送、Shift+Enter 换行、composition 事件期间禁止发送；模型 / Skills 运行快照、旧运行查看、草稿隔离、会话恢复；全部七个示例节点与三个页签、待执行无输出或事件、检查器收起及焦点返回、演示完成和重置；动态研究员数量和新问题内容隔离；文本安全渲染、损坏存储回退及存储不可用提示；手机导航抽屉、44 px 触屏目标及长选择器标签；减少动态效果与减少透明度。

输入法采用浏览器 composition / KeyboardEvent 模拟验证，不替代对不同操作系统真实输入法的人工体验测试。当前浏览器验证范围为 Chrome，未执行 Safari / Firefox。

响应式检查覆盖浅色与深色的 1440、1024、900、736、390、320 px。检查页面横向溢出、菜单边界、图谱收起后的布局、浏览器运行和控制台错误，以及意外外部请求。减少透明度通过 Chromium 媒体偏好模拟验证。

## 与参考图的目视对照

沿用原稿的 Apple 银白 / 石墨色值、350 px 图谱、14 px 节点圆角、28 px 玻璃模糊和 232 px / 11 px 实色菜单。桌面主要区域与参考截图位置对应，390 px 保留对话在上、图谱在下的结构。

独立应用增加了外观切换、本地演示说明和手机最近对话入口。桌面对话内容和图谱各自滚动，输入框保持可见；窄屏使用页面滚动。900 px 左右隐藏侧栏，避免对话栏被压窄；仍可从星号入口访问会话。未更换配色或重新设计界面。

- [浅色桌面](screenshots/apple-light-1024.png)
- [深色桌面](screenshots/apple-dark-1024.png)
- [390 px 窄屏](screenshots/apple-light-390.png)
- [320 px 窄屏](screenshots/apple-light-320.png)
- [模型菜单](screenshots/apple-light-model.png)
- [Skills 菜单](screenshots/apple-light-skills.png)

这些截图来自实际 React 应用。运行测试可重新生成全部截图和 HTML 报告于 `test-results/` / `playwright-report/`，这两个目录不入库。
