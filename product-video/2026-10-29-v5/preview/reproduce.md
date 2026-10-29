# v5 修订预览复现

在仓库根目录运行。使用原有 Node、Python + Pillow、FFmpeg/ffprobe、Chrome、Microsoft YaHei，以及 frontend/node_modules 的 React、Vite 和 Playwright。Chrome 可由 `CHROME_PATH` 指定；没有新增依赖。源码直接复用原仓库组件、样式和合成数据，需要原仓库及许可。

```powershell
python product-video/2026-10-29-v5/source/build.py
node product-video/2026-10-29-v5/source/serve.mjs
```

另开终端：

```powershell
node product-video/2026-10-29-v5/source/capture.mjs
node product-video/2026-10-29-v5/source/capture.mjs --clips
python product-video/2026-10-29-v5/source/package-preview.py
node product-video/2026-10-29-v5/source/check-playback.mjs
python product-video/2026-10-29-v5/source/record-delivery.py
```

本地服务监听 127.0.0.1:5189。渲染器仅允许本地场景请求，禁止后端 API 与外部网络；沙箱需要相应本地套接字权限。

唯一时间轴是 `timeline.json`；生成 `plan.json` 与原生适配的 `native-timeline.json`。原生报告连续缩放取自实测窗口边界；方法卡为同一 DOM 元素，跨两镜保持位置。`cache/` 是可再生缓存，不提交。

v5 尚无批准记录，不继承 v4 确认；修改了时长与镜头安排，需确认本版预览后才制作完整配乐成片。
