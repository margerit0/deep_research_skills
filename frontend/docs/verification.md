# 第一阶段验收记录

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
