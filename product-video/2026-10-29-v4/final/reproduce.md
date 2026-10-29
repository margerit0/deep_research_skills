# v4 成片复现

工作目录为仓库根目录。基准提交 `9b6807e7b6d079bd9ac2e728ee6ce80325947937`；本轮未提交改动及文件标识见 `manifest.json`。依赖原仓库组件、样式和原创合成数据，不是脱离仓库的独立源码包，保留原许可。

环境：Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe；项目 frontend/node_modules；Chrome；Microsoft YaHei。Chrome 可用 `CHROME_PATH` 覆盖，字体路径见打包脚本。未新增 npm 或 Python 依赖。

用户已明确批准本版 42 秒方案，记录在 `../approval.json`。`../preview/approved-timeline.json` 与 `approved-brief.json` 保留批准时记录。当前 `plan.json` 必须与批准标识相符。

```powershell
python product-video/2026-10-29-v4/source/build.py
node product-video/2026-10-29-v4/source/serve.mjs
```

另一个终端中运行：

```powershell
node product-video/2026-10-29-v4/source/capture.mjs --final
node product-video/2026-10-29-v4/source/synthesize-audio.mjs
python product-video/2026-10-29-v4/source/package-final.py
node product-video/2026-10-29-v4/source/verify-audio.mjs
node product-video/2026-10-29-v4/source/playback-final.mjs
```

时间轴是唯一的时长来源：42 秒、1260 帧、84 拍和 2,016,000 音频样本由同一计划派生。视频为 CRF 17、H.264、yuv420p；音频为 AAC 192 kbps、48 kHz、双声道。完整编码参数保存在 `verification-data.json`。

本地预览服务仅监听 127.0.0.1:5188；沙箱若阻止本地套接字，需要允许本地服务与浏览器渲染进程。渲染器禁止外部／后端 API 请求。完整播放器通过用户手势启用 Web Audio，再检查每个呈现帧和音频信号。

从最终 MP4 查看 `check-sheet.png` 与 `cache/final/transitions.png`，在 `cache/final/visual-review.json` 记录当前成片哈希、检查方法和真实目视结论。主观听音未做时不得标为完成。然后运行：

```powershell
python product-video/2026-10-29-v4/source/finalize.py
```

任何重新编码均需重新抽帧、播放、音频与目视检查。不要复用旧成片哈希的验收记录。根目录 `product-video/index.html` 指向当前成片，预览页保留为已确认归档。
