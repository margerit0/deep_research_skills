# 成片复现 · v3

工作目录：`D:\deep_research_public_preview`。分支：`codex/product-demo-video-20261025`。基准提交：`5cf597d4cd7d1ba07949a61ef5561abdd9fc733d`。原工作区未提交修改保留，媒体文件位于 `product-video/2026-10-25-v3/`。

本版已获用户明确确认。`approval.json` 绑定原预览清单、时间轴和小样哈希，`preview/approved-timeline.json` 保存批准前的完整时间轴。不得用其他版本的确认记录替换。

## 环境

- Windows；Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe 7.1.1。
- 使用项目 `frontend/node_modules` 中现有的 React、Vite、Playwright，没有新增 npm 依赖。
- Chrome 默认路径：`C:/Program Files/Google/Chrome/Application/chrome.exe`，可用 `CHROME_PATH` 指定。
- 中文字体为 Microsoft YaHei，默认读取 `C:/Windows/Fonts/msyh.ttc` 和 `msyhbd.ttc`；可用 `VIDEO_CJK_FONT`、`VIDEO_CJK_FONT_BOLD` 指定字体。更换字体须重新目视检查排版。
- 源码直接导入本仓库原生组件、CSS 和内置合成数据。依赖与哈希见 `../brief.json`，不是脱离仓库的独立源码包；保留原项目及依赖许可。

## 实际制作命令

本次复用运行在 5187 的本地媒体服务器，该服务根目录为仓库，可同时提供各版内容。若该端口尚未运行服务：

```powershell
node product-video/2026-10-25-v3/source/serve.mjs
```

从仓库根目录运行：

```powershell
node product-video/2026-10-25-v3/source/render-preview.mjs --final
node product-video/2026-10-25-v3/source/synthesize-audio.mjs
python product-video/2026-10-25-v3/source/package-final.py
node product-video/2026-10-25-v3/source/verify-audio.mjs
node product-video/2026-10-25-v3/source/playback-final.mjs
```

本次实际使用 `D:\nodejs\node.exe` 和 `D:\Python\Python313\python.exe`；配置 PATH 后可直接使用上述名称。`ffmpeg`、`ffprobe` 位于 PATH。全程 UTF-8 文件读写。

渲染器先验证批准的时间轴和原生源码哈希，再输出 0–539 共 540 帧。配乐为 18 秒 / 120 BPM / 36 拍，所有动作音效取自同一时间轴。完整编码参数保存在 `verification-data.json`：H.264 High、CRF 17、yuv420p、30 fps，AAC 192 kbps、48 kHz、双声道。

打包程序从同一个最终 MP4 解码八张检查图及转场帧，验证帧时间戳、原生运动、报告与品牌停顿，以及和已批准画面的相符程度。音频验证区分 AAC 尾部填充和有效播放时长，核对峰值、削波及事件对齐。

播放脚本以真实点击启动视频和 Web Audio，保持 1 倍速、音量 1、未静音，验证实际加载字节哈希、逐帧呈现覆盖和音频信号。浏览器累计解码计数可能包含预加载重复帧，验收不把该计数当作文件总帧数。

## 目视记录与绑定

检查本次 `final/check-sheet.png`、`cache/final/opening-skills-check.png`、`cache/final/execution-closing-check.png` 及所需完整解码帧。将目视结果写入 `cache/final/manual-review.json`，字段包含 `movie_sha256`、`check_sheet_sha256`、`visual_result`、`method`、`subjective_listening`。必须绑定当前 MP4，不能复用旧哈希记录。

```powershell
python product-video/2026-10-25-v3/source/finalize-delivery.py
```

本次未进行主观听音，记录为 false。任何重新编码都需要重新抽帧、音频验证、播放和目视检查，再生成清单。`cache/` 是可再生缓存，已忽略版本控制；最终文件、源码和批准记录分别保留。

本地播放入口：

```text
http://127.0.0.1:5187/product-video/2026-10-25-v3/final/index.html
```
