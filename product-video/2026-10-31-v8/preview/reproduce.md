# v8 预览复现

在仓库根目录运行，沿用 frontend/node_modules、Node、Python + Pillow、Chrome、FFmpeg/ffprobe 与 Microsoft YaHei，没有新增依赖。依赖原仓库组件、样式和合成数据。与 v7 比较需要本地的 `product-video/2026-10-30-v7/cache/final/frames`。

```powershell
python product-video/2026-10-31-v8/source/build.py
node product-video/2026-10-31-v8/source/serve.mjs
```

另开终端：

```powershell
node product-video/2026-10-31-v8/source/capture.mjs
node product-video/2026-10-31-v8/source/capture.mjs --clips
node product-video/2026-10-31-v8/source/capture.mjs --audit
node product-video/2026-10-31-v8/source/check-guards.mjs
python product-video/2026-10-31-v8/source/package-preview.py
node product-video/2026-10-31-v8/source/check-playback.mjs
python product-video/2026-10-31-v8/source/record-preview.py
```

服务仅监听 127.0.0.1:5192；捕获脚本禁止外部及后端 API 请求。`CHROME_PATH` 可指定 Chrome。

`--audit` 只把全片渲染到 `cache/audit/` 用于和 v7 比较，不生成视频，也不需要批准；`--final` 必须有绑定当前计划标识的 `approval.json`。`timeline.json` 改动后计划标识随之变化，需要重新确认。
