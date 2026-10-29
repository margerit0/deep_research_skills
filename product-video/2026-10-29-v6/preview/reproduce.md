# v6 预览复现

在仓库根目录运行，沿用 frontend/node_modules、Node、Python + Pillow、Chrome、FFmpeg/ffprobe 与 Microsoft YaHei。没有新增依赖。需要原仓库组件、样式、合成数据和原许可。

```powershell
python product-video/2026-10-29-v6/source/build.py
node product-video/2026-10-29-v6/source/serve.mjs
```

另开终端：

```powershell
node product-video/2026-10-29-v6/source/capture.mjs
node product-video/2026-10-29-v6/source/capture.mjs --clips
python product-video/2026-10-29-v6/source/package-preview.py
node product-video/2026-10-29-v6/source/check-playback.mjs
python product-video/2026-10-29-v6/source/record-delivery.py
```

服务仅监听 127.0.0.1:5190；捕获脚本禁止外部及后端 API 请求，沙箱需要本地套接字权限。`CHROME_PATH` 可指定 Chrome。

`timeline.json` 为唯一时间轴来源，章节文案、动作和停顿均从计划派生。章节期间固定报告完成态，再接回已存在的报告缩入动画。`cache/` 为可再生的中间帧与检查缓存。

新章节画面和 53 秒版本尚待确认，不能沿用 v4 的确认记录制作成片。
