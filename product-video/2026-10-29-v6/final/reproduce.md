# v6 成片复现

工作目录为仓库根目录。基准提交 `9b6807e7b6d079bd9ac2e728ee6ce80325947937`；制作源码标识见 `manifest.json`。依赖原仓库组件、样式和原创合成数据，不是脱离仓库的独立源码包，保留原许可。

环境：Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe；项目 frontend/node_modules；Chrome；Microsoft YaHei。Chrome 可用 `CHROME_PATH` 覆盖，字体路径见打包脚本。未新增 npm 或 Python 依赖。

用户在 v6 章节卡预览后明确回复“制作完整视频”，记录见 `../approval.json`。`../preview/approved-timeline.json`、`approved-brief.json` 与 `approved-index.html` 保存批准时输入。时间轴与计划必须保持批准标识。

```powershell
python product-video/2026-10-29-v6/source/build.py
node product-video/2026-10-29-v6/source/serve.mjs
```

另一个终端依次运行，前一步成功后再进行下一步：

```powershell
node product-video/2026-10-29-v6/source/capture.mjs --final
node product-video/2026-10-29-v6/source/synthesize-audio.mjs
python product-video/2026-10-29-v6/source/package-final.py
node product-video/2026-10-29-v6/source/verify-audio.mjs
node product-video/2026-10-29-v6/source/playback-final.mjs
```

53 秒、1590 帧、106 拍和 2,544,000 音频样本均由同一计划派生；最后一小节保留两拍并淡出。编码为 CRF 17、H.264、yuv420p，AAC 192 kbps、48 kHz、双声道。完整参数见 `verification-data.json`。

本地服务仅监听 127.0.0.1:5190；沙箱若阻止本地套接字，需要允许本地服务和浏览器渲染进程。渲染器拒绝外部及后端 API 请求。播放器通过播放按钮启用 Web Audio，再检查每个呈现帧与音频信号。

查看最终 MP4 的 `check-sheet.png` 和 `cache/final/transitions.png`，在 `cache/final/visual-review.json` 记录当前成片哈希、检查方法与真实目视结论；未做主观听音时不得标为完成。完成后运行：

```powershell
python product-video/2026-10-29-v6/source/finalize.py
```

重新编码必须重新抽帧、播放、检查音频和画面，不能沿用旧 MP4 的验收记录。当前入口为 `product-video/index.html`；预览保留为已确认归档。README 使用仓库内封面与 MP4 链接，未上传 GitHub 附件或提交推送。
