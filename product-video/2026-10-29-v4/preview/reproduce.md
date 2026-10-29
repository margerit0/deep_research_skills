# v4 预览复现

在仓库根目录运行。基准提交 `9b6807e7b6d079bd9ac2e728ee6ce80325947937`；本轮改动位于本版目录与视频入口说明。原应用源码、后端、生产 Skills 和 v3 交付包不变。

依赖：项目 `frontend/node_modules` 的 React、Vite、Playwright；Node 22.17.0；Python 3.13.5、Pillow 12.3.0；FFmpeg/ffprobe；Microsoft YaHei。Chrome 默认路径为 `C:/Program Files/Google/Chrome/Application/chrome.exe`，可通过 `CHROME_PATH` 指定。没有新增依赖。源码复用原仓库的组件、样式与原创合成数据，必须保留仓库及原许可。

```powershell
python product-video/2026-10-29-v4/source/build.py
node product-video/2026-10-29-v4/source/serve.mjs
```

在另一个终端执行：

```powershell
node product-video/2026-10-29-v4/source/capture.mjs
node product-video/2026-10-29-v4/source/capture.mjs --clips
python product-video/2026-10-29-v4/source/package-preview.py
node product-video/2026-10-29-v4/source/check-playback.mjs
python product-video/2026-10-29-v4/source/record-brief.py
```

预览服务只监听 `127.0.0.1:5188`。Chromium 直连本地地址，捕获脚本拒绝外部与后端 API 请求。沙箱阻止本地套接字时，需要为本地服务与渲染进程提供相应执行权限。

`timeline.json` 是唯一可编辑时间轴。`plan.json` 和 `native-timeline.json` 由同一编译器派生；两段小样、音频规划、拍点和关键帧均使用该计划。未修改预览内容时，重新运行命令仅覆盖本版可再生预览文件；`cache/` 为忽略版本控制的中间帧。

完整视频及正式音轨仅在用户确认本版后制作。批准记录必须绑定当前 `planSha256`，不能继承 v3 的批准。
