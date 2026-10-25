# 预览复现

工作目录：`D:\deep_research_public_preview`。基础提交：`5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`，分支 `codex/product-demo-video-20261025`，加上本目录的未提交媒体源码。

本目录依赖原仓库，不能作为独立源码包使用。具体依赖的前端文件与 SHA-256 在 `../brief.json`；原项目和 npm 依赖许可证继续适用。没有复制或重新分发系统字体。

## 已实际使用的环境

- Windows，Node.js 22.17.0，Python 3.13.5，Pillow 12.3.0。
- 原前端 `node_modules` 与 `frontend/package-lock.json`：Vite 8.3.4、React 19.3.0、Playwright 1.64.0。
- 本机 Google Chrome：通过独立无用户数据的浏览器上下文渲染。
- FFmpeg / ffprobe 7.1.1，`libx264` 编码。
- Segoe UI、Microsoft YaHei / 微软雅黑，原生组件使用前端既有字体栈；拼图使用本机 `msyh.ttc`、`msyhbd.ttc`。

脚本会探测常见 Windows Chrome / Edge 安装位置。其他位置设置 `CHROME_PATH`；拼图字体可用 `VIDEO_CJK_FONT`、`VIDEO_CJK_FONT_BOLD` 指定。所有文本文件显式使用 UTF-8。

## 已验证的命令

先在一个终端启动媒体开发服务，持续运行：

```powershell
Set-Location D:\deep_research_public_preview
node product-video/2026-10-25-v1/source/serve.mjs
```

在另一个终端生成、核对并编码预览：

```powershell
Set-Location D:\deep_research_public_preview
node product-video/2026-10-25-v1/source/render-preview.mjs
python product-video/2026-10-25-v1/source/package-preview.py
```

浏览器审阅地址：

```text
http://127.0.0.1:5187/product-video/2026-10-25-v1/preview/index.html
```

帧定位入口是 `await window.ready; await window.renderFrame(frame)`；自动化还等待 `window.sceneLoaded`，避免初始播放器和导出争用。整数范围为 0–359。生产取景使用 1440×1080 CSS 像素的独立 iframe，在 1920×1080、DPR 1 画布内按相机参数裁切；原应用首次布局核对使用 1440×962，字号、350 px 图谱宽和 330 px 检查器宽保持一致。

节点与阶段变化由 `timeline.json` 的 `native_demo_index` 选择原生合成状态；CSS 动画暂停后按状态起点定位到对应 `currentTime`，保留原生周期。节点选择保持至报告完成，避免系统更新抢走检查器焦点。

编码小样使用原时间轴第 60–239 帧，共 180 帧、6 秒。实际参数为 `-framerate 30 -start_number 60 -frames:v 180 -an -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r 30 -movflags +faststart`。完整命令保存在再生的 `cache/media-audit.json`。

`render-preview.mjs` 核对全程标识、原文、点击命中、连线方向、终态及新页面随机定位；`package-preview.py` 从当前小样解码抽帧，验证真实图像运动和稳定停顿，并生成五帧拼图。结果分别写入 `cache/capture-audit.json` 与 `cache/media-audit.json`。

这些命令只生成第一阶段预览，不会生成正式配乐、完整 MP4、发布或提交代码。
