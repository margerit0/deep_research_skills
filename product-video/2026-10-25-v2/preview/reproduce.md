# 预览复现 · v2

工作目录：`D:\deep_research_public_preview`。分支：`codex/product-demo-video-20261025`，基准提交：`5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`。保留已有未提交修改；本版只新增 `product-video/2026-10-25-v2/`。

环境：Windows；Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe 7.1.1；项目 frontend/node_modules 中的 Vite、React 和 Playwright；已安装的 Chrome 或 Edge。中文字体使用 Microsoft YaHei，默认从 Windows Fonts 加载。源码导入项目真实前端组件、样式及内置合成数据，因此不能单独复制本目录作为独立源码包。依赖文件及哈希见 `../brief.json`。

本次复用了已启动的 5187 本地媒体服务器。其根目录是仓库，能够同时提供 v1 和 v2。若端口没有服务，先运行：

```powershell
node product-video/2026-10-25-v2/source/serve.mjs
```

随后在同一仓库的另一个终端执行本次实际运行的命令：

```powershell
node product-video/2026-10-25-v2/source/render-preview.mjs
python product-video/2026-10-25-v2/source/package-preview.py
```

本次使用的可执行文件为 `D:\nodejs\node.exe` 和 `D:\Python\Python313\python.exe`；若已在 PATH，可直接使用上面的名称。Chrome 默认检测 `C:/Program Files/Google/Chrome/Application/chrome.exe`，可用 `CHROME_PATH` 指定其他安装位置。

本地入口：

```text
http://127.0.0.1:5187/product-video/2026-10-25-v2/preview/index.html
http://127.0.0.1:5187/product-video/2026-10-25-v2/source/index.html
```

渲染器检查 0–359 帧的语义、披露标识、点击命中、图谱端点及新页面随机定位；只编码 0–239 帧的预览片段，不生成完整带声音视频。`package-preview.py` 从实际小样解码并检查运动及报告停止状态。

完整缓冲播放器验证：打开预览入口，等“已就绪”后点击播放。验收以实际 8 秒 MP4 为准。本次还使用 Playwright 在页面内记录 `requestVideoFrameCallback` 与 `getVideoPlaybackQuality()`；正常 1 倍速播放，240 帧、呈现掉帧 0、回调缺口 0，详见 `verification-data.json`。

`cache/` 为可再生成数据，不纳入版本控制。预览清单及哈希由下面命令绑定到源码与当前小样；重新渲染后须重新播放、目视检查，再执行：

```powershell
python product-video/2026-10-25-v2/source/finalize-preview.py
```
