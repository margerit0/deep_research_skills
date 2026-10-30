# v7 成片复现

工作目录为仓库根目录。基准提交 `eb9f9faab45447b9d28f03464d20a28b86b3a93e`；制作源码标识见 `manifest.json`。依赖原仓库组件、样式和原创合成数据，不是脱离仓库的独立源码包，保留原许可。

环境：Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe 7.1.1；项目 frontend/node_modules；Chrome；Microsoft YaHei。Chrome 可用 `CHROME_PATH` 覆盖，字体路径见打包脚本。未新增 npm 或 Python 依赖。

用户在请求中预先授权本次无需确认分镜，记录见 `../approval.json`。时间轴与计划必须保持批准标识；改动时间轴后需要重新取得确认。

```powershell
python product-video/2026-10-30-v7/source/build.py
node product-video/2026-10-30-v7/source/serve.mjs
```

另一个终端依次运行，前一步成功后再进行下一步：

```powershell
node product-video/2026-10-30-v7/source/capture.mjs --final
node product-video/2026-10-30-v7/source/synthesize-audio.mjs
python product-video/2026-10-30-v7/source/package-final.py
node product-video/2026-10-30-v7/source/verify-audio.mjs
node product-video/2026-10-30-v7/source/playback-final.mjs
```

53 秒、1590 帧、106 拍和 2,544,000 音频样本均由同一计划派生；配乐的段落、和声与音效位置都从 `plan.json` 计算。配乐先归一到 -16 LUFS，再经前视限幅，最后一秒自然收束。编码为 CRF 17、H.264、yuv420p，AAC 192 kbps、48 kHz、双声道。完整参数见 `verification-data.json`。

本地服务仅监听 127.0.0.1:5191；沙箱若阻止本地套接字，需要允许本地服务和浏览器渲染进程。渲染器拒绝外部及后端 API 请求，并使用灰阶字形渲染（`--disable-lcd-text`）。播放器通过播放按钮启用 Web Audio，再检查每个呈现帧与音频信号。

打包脚本会与 `product-video/2026-10-29-v6/cache/final/frames` 逐帧比较，确认画面改动只出现在修订的转场窗口内。该目录是不入库的缓存；缺失时跳过比较并如实记录。响度对比直接读取 v6 的 MP4。

查看最终 MP4 的 `check-sheet.png` 和 `cache/final/transitions.png`，在 `cache/final/visual-review.json` 记录当前成片哈希、检查方法与真实目视结论。主观听音只能由试听者确认，写入 `../approval.json` 的 `acceptance` 并绑定成片哈希；未做时不得标为完成。完成后运行：

```powershell
python product-video/2026-10-30-v7/source/finalize.py
```

重新编码必须重新抽帧、播放、检查音频和画面，不能沿用旧 MP4 的验收记录。当前入口为 `product-video/index.html`。根 README 的内嵌播放器只接受在 GitHub 网页上传的附件地址；切换版本时先上传 MP4，再同步更新根 README 与 `product-video/status.json` 的 `readmeVersion`、`publishedVersion` 和 `hostedPlayer`。
