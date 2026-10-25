# 预览复现 · v3

工作目录：`D:\deep_research_public_preview`。分支：`codex/product-demo-video-20261025`。基准提交：`5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`。本版新增内容位于 `product-video/2026-10-25-v3/`，保留旧版本和原有工作区修改。

环境：Windows；Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe 7.1.1；项目 `frontend/node_modules` 中的 React、Vite、Playwright；Chrome；Microsoft YaHei 字体。无需新增 npm 依赖。源场景导入本仓库真实组件、样式、内置合成数据；依赖文件和哈希列在 `brief.json`，因此本目录不是独立于仓库的源码包。

本次复用已启动的 5187 本地媒体服务器。该服务根目录是仓库，可同时提供各版预览。端口空闲时可启动：

```powershell
node product-video/2026-10-25-v3/source/serve.mjs
```

在仓库根目录执行：

```powershell
node product-video/2026-10-25-v3/source/render-preview.mjs
python product-video/2026-10-25-v3/source/package-preview.py
node product-video/2026-10-25-v3/source/verify-playback.mjs
```

本次实际命令使用 `D:\nodejs\node.exe` 和 `D:\Python\Python313\python.exe`。设置 PATH 后可直接使用以上命令。Chrome 默认位置为 `C:/Program Files/Google/Chrome/Application/chrome.exe`，也可通过 `CHROME_PATH` 指定。

预览入口：

```text
http://127.0.0.1:5187/product-video/2026-10-25-v3/preview/index.html
http://127.0.0.1:5187/product-video/2026-10-25-v3/source/index.html
```

逐帧渲染器检查全部 540 帧，但只编码 0–419 帧的 14 秒无声小样。所有动画用帧号定位。点击前测量原生目标、校验顶部命中，并触发原组件回调；关闭菜单前检查选项，再按时间轴呈现选中后的配置。问题、Skills 选项和选中说明都与源数据比对。

打包程序验证实际小样的分辨率、帧率、帧数、时长和帧时间戳，并解码开场、菜单、点击、连续运动与停止状态。播放程序对同一个 MP4 以正常速度播放，检查播放字节哈希、呈现帧和回调缺口；本次实际使用播放器的原生文件播放回退路径。

完成目视检查后，将绑定本次 `motion-sample.mp4` 与 `storyboard-overview.png` 哈希的记录保存为 `cache/manual-review.json`，字段为 `sample_sha256`、`storyboard_sha256`、`method`、`result`。再执行：

```powershell
python product-video/2026-10-25-v3/source/finalize-preview.py
```

旧的播放或目视记录不能用于新小样。`cache/` 是可再生缓存，已忽略版本控制。正式配乐与完整 18 秒视频必须在本版预览确认后制作。
