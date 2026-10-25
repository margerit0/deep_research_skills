# 完整视频复现

工作目录：`D:\deep_research_public_preview`。

基础提交 `5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`，分支 `codex/product-demo-video-20261025`，加上本次 `product-video/2026-10-25-v1/` 目录源码。用户原有未提交修改保留。本目录依赖原仓库，非独立源码包；所需原生文件哈希见 `../brief.json`，当前媒体源码与成片哈希见 `manifest.json`。

## 环境与字体

已实际使用 Windows、Node.js 22.17.0、Python 3.13.5、Pillow 12.3.0、FFmpeg / ffprobe 7.1.1。前端使用项目锁定的 Vite 8.3.4、React 19.3.0、Playwright 1.64.0。音频合成与解码对齐检查只使用 Node.js 标准库，没有新增 npm / Python 依赖。

渲染使用本机 Google Chrome、DPR 1、1920×1080 输出画布及 1440×1080 原生组件 iframe。字体沿用 Segoe UI、Microsoft YaHei / 微软雅黑；检查图使用 `msyh.ttc` 和 `msyhbd.ttc`，没有重新分发字体。其他浏览器位置通过 `CHROME_PATH` 指定；检查图可用 `VIDEO_CJK_FONT` 和 `VIDEO_CJK_FONT_BOLD` 指定中文字体文件。

原项目及依赖许可证继续适用。音乐为本次源码直接合成的原创振荡器、种子噪声和节拍编排，无外部音乐、采样、语音或模型生成服务。

## 已验证的制作命令

在一个终端启动本地媒体服务，并保持运行：

```powershell
Set-Location D:\deep_research_public_preview
node product-video/2026-10-25-v1/source/serve.mjs
```

另一个终端按顺序执行：

```powershell
Set-Location D:\deep_research_public_preview
node product-video/2026-10-25-v1/source/render-preview.mjs --final
node product-video/2026-10-25-v1/source/synthesize-audio.mjs
python product-video/2026-10-25-v1/source/package-final.py
node product-video/2026-10-25-v1/source/verify-audio.mjs
node product-video/2026-10-25-v1/source/playback-check.mjs
node product-video/2026-10-25-v1/source/playback-check.mjs --native
node product-video/2026-10-25-v1/source/playback-check.mjs --native --memory
python product-video/2026-10-25-v1/source/finalize-delivery.py
```

最后一步汇总现有核验记录。重新编码后需要复查新的检查图；人工核对记录必须绑定当前 MP4 哈希，脚本不会把旧记录当成新视频已经目视通过。

播放地址：

```text
http://127.0.0.1:5187/product-video/2026-10-25-v1/final/index.html
```

## 时间轴与编码

`timeline.json` 是分镜、360 个整数帧和动作事件的统一入口。完整渲染会检查当前批准状态、已确认时间轴及原生依赖哈希；图片和 WAV 写入可再生的 `cache/final/`，不覆盖已确认的五帧预览。

代码合成音轨为 48 kHz、双声道、576000 个采样点/声道，120 BPM、24 拍。离散事件起点由 `event.frame / fps` 直接计算，每帧 1600 个采样点；所有动作落在 15 帧的整拍上。持续动效仍使用前端原生周期。结尾淡出 0.52 秒。

编码参数：`libx264 -preset medium -crf 17 -profile:v high -level:v 4.1 -pix_fmt yuv420p -r 30`，音频 `aac -b:a 192k -ar 48000 -ac 2`，`-t 12 -movflags +faststart`。实际完整命令保存在 `cache/final/video-audit.json`。

检查图来自这一个最终 MP4 的第 45、105、195、255、345 帧。其他转场抽帧、连续动效对比、随机定位对比、时间戳及音频核验记录保存在 `cache/final/`，关键结果汇总至 `verification-data.json`。

AAC 原始解码包含 512 个尾部填充采样点，容器的可播放音轨时长为 12 秒。核验保留这一区别，没有用裁掉数据来掩盖编码填充。

浏览器播放脚本启用音轨、以 1 倍速播放完整文件。带 Web Audio 仪表的检查和普通原生播放器检查分开记录；`--memory` 可显式使用完整缓冲的对照。交付页由 `source/build-player.mjs` 构建，先载入完整文件再开放播放，避免本地渐进 HTTP 读取影响呈现。单独更新播放器可执行 `node product-video/2026-10-25-v1/source/build-player.mjs`，无需重编码视频。主观听音不由这些程序代替，具体边界见 `verification.md`。
