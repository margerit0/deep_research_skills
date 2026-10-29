"""Bind the delivery to its verified movie and advance the current entry."""
from pathlib import Path
import hashlib
import json
from timeline import load_plan, write_json

ROOT = Path(__file__).resolve().parent.parent
P = load_plan(ROOT / 'plan.json')
FINAL, CACHE = ROOT / 'final', ROOT / 'cache/final'
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
numeric = read(FINAL / 'verification-data.json')
audio = read(CACHE / 'audio-decoded-audit.json')
score = read(CACHE / 'audio-source.json')
playback = read(CACHE / 'playback-audit.json')
visual = read(CACHE / 'visual-review.json')
approval = read(ROOT / 'approval.json')
movie_sha = sha(FINAL / 'product-demo.mp4')
assert movie_sha == numeric['movieSha256'] == playback['movieSha256'] == visual['movieSha256']
assert P['planSha256'] == numeric['planSha256'] == score['planSha256'] == approval['planSha256']
assert approval['status'] == 'approved'
assert playback['ended'] and not playback['muted'] and playback['presentationCoverage']['complete']
assert not playback['droppedDuringPlayback'] and not playback['frameCallbackGaps'] and not playback['pageErrors']
assert not audio['clippedSamples'] and visual['visualResult'] == 'passed'
write_json(FINAL / 'verification-data.json', {**numeric, 'score': score, 'decodedAudio': audio, 'programPlayback': playback, 'visualReview': visual})
duration, frames = P['video']['durationSeconds'], P['video']['totalFrames']
key_count = len(P['keyframes'])
beat_count = len(P['beats'])
samples = P['audio']['sampleCount']
version = ROOT.name
(FINAL / 'verification.md').write_text(f'''# v6 成片验证

2026-10-29。成片 SHA-256：`{movie_sha}`。计划：`{P['planSha256']}`。

| 检查 | 结果 |
|---|---|
| 规格与解码 | H.264 / yuv420p，1920×1080，30 fps，{duration:g} 秒；完整解码 {frames} 帧，逐帧时间戳连续。 |
| 配乐 | 原创代码合成，无歌词或外部采样；120 BPM、{beat_count} 拍；AAC、48 kHz、双声道。进入章节卡时降低旋律强度。 |
| 帧与交互 | 全部 {frames} 帧检查文字、字体、溢出及披露；4 次原生点击验证命中目标和真实回调。 |
| 已确认方案 | 时间轴保持批准版本；{key_count} 张关键帧与批准预览比较，排除版本页脚变化；布局与文字保持一致。编码后的亮度 PSNR 均高于 45 dB。 |
| 运动与停止 | 从当前 MP4 检查原生图谱运动、报告完成后停止、报告连续缩入、章节标题及品牌稳定停留。 |
| 音频削波 | 编码后峰值 {audio['peakDbfs']:.2f} dBFS，削波样本 0；有效 {samples:,} 样本／声道，AAC 尾部填充 {audio['aacTrailingPaddingSamples']} 样本。 |
| 动作同步 | {len(audio['eventAlignment'])} 个动作音效与源音轨相关对齐，最大偏移 {max(abs(x['lagMilliseconds']) for x in audio['eventAlignment']):g} 毫秒。 |
| 程序播放 | 1 倍速完整播放，音轨启用、音量 1；唯一呈现帧 {playback['presentationCoverage']['uniqueFrames']}，播放期间掉帧 {playback['droppedDuringPlayback']}；音频信号计量有效。浏览器计数与文件解码数分别保存。 |
| 目视检查 | 查看当前 MP4 的 {key_count} 张关键帧、章节卡和方法衔接的转场帧；检查中文、连线、边界、品牌及全程披露。 |
| 主观听音 | 当前工具环境未进行主观听音；数值与启用音轨的程序播放通过，不等于听感验收。 |
| 内容边界 | 使用项目原创合成数据；优化部分为机制示意，无虚构实验、分数或提升结论；未调用模型或搜索服务。 |

`check-sheet.png` 来自这个最终 MP4。详细记录见 `verification-data.json`；逐帧图片、音轨与转场检查图是 `cache/final/` 中的可再生缓存。
''', encoding='utf-8')
(FINAL / 'reproduce.md').write_text(f'''# v6 成片复现

工作目录为仓库根目录。基准提交 `9b6807e7b6d079bd9ac2e728ee6ce80325947937`；制作源码标识见 `manifest.json`。依赖原仓库组件、样式和原创合成数据，不是脱离仓库的独立源码包，保留原许可。

环境：Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe；项目 frontend/node_modules；Chrome；Microsoft YaHei。Chrome 可用 `CHROME_PATH` 覆盖，字体路径见打包脚本。未新增 npm 或 Python 依赖。

用户在 v6 章节卡预览后明确回复“制作完整视频”，记录见 `../approval.json`。`../preview/approved-timeline.json`、`approved-brief.json` 与 `approved-index.html` 保存批准时输入。时间轴与计划必须保持批准标识。

```powershell
python product-video/{version}/source/build.py
node product-video/{version}/source/serve.mjs
```

另一个终端依次运行，前一步成功后再进行下一步：

```powershell
node product-video/{version}/source/capture.mjs --final
node product-video/{version}/source/synthesize-audio.mjs
python product-video/{version}/source/package-final.py
node product-video/{version}/source/verify-audio.mjs
node product-video/{version}/source/playback-final.mjs
```

{duration:g} 秒、{frames} 帧、{beat_count} 拍和 {samples:,} 音频样本均由同一计划派生；最后一小节保留两拍并淡出。编码为 CRF 17、H.264、yuv420p，AAC 192 kbps、48 kHz、双声道。完整参数见 `verification-data.json`。

本地服务仅监听 127.0.0.1:5190；沙箱若阻止本地套接字，需要允许本地服务和浏览器渲染进程。渲染器拒绝外部及后端 API 请求。播放器通过播放按钮启用 Web Audio，再检查每个呈现帧与音频信号。

查看最终 MP4 的 `check-sheet.png` 和 `cache/final/transitions.png`，在 `cache/final/visual-review.json` 记录当前成片哈希、检查方法与真实目视结论；未做主观听音时不得标为完成。完成后运行：

```powershell
python product-video/{version}/source/finalize.py
```

重新编码必须重新抽帧、播放、检查音频和画面，不能沿用旧 MP4 的验收记录。当前入口为 `product-video/index.html`；预览保留为已确认归档。README 使用仓库内封面与 MP4 链接，未上传 GitHub 附件或提交推送。
''', encoding='utf-8')
brief = read(ROOT / 'brief.json')
brief['state'] = 'complete'
brief['revision']['approval'] = approval['evidence'] + '；完整配乐视频已完成，记录见 approval.json。'
brief['spec']['preview'] = '2026-10-29 已确认；预览归档，当前成片为 final/product-demo.mp4'
brief['finalDelivery'] = {'movieSha256': movie_sha, 'planSha256': P['planSha256'], 'approval': 'approval.json', 'subjectiveListening': 'not_run', 'changes': ['按批准方案生成完整配乐视频；仅将页脚预览标记改为产品演示']}
write_json(ROOT / 'brief.json', brief)
status_path = ROOT.parent / 'status.json'
status = read(status_path)
status.update(currentVersion=version, currentFinalVersion=version, readmeVersion=version)
current = next(v for v in status['versions'] if v['id'] == version)
current['state'] = 'complete'
current['final'] = {'video': f'{version}/final/product-demo.mp4', 'page': f'{version}/final/index.html', 'sheet': f'{version}/final/check-sheet.png', 'verification': f'{version}/final/verification.md', 'reproduce': f'{version}/final/reproduce.md', 'sha256': movie_sha}
write_json(status_path, status)
(ROOT.parent / 'index.html').write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={version}/final/index.html"><title>星图工作台 · 当前成片</title><p><a href="{version}/final/index.html">打开 v6 配乐成片</a></p></html>', encoding='utf-8')
preview = ROOT / 'preview/index.html'
page = (ROOT / 'preview/approved-index.html').read_text(encoding='utf-8')
page = page.replace('v6 · 修订预览待确认', 'v6 · 已确认预览归档')
page = page.replace('保留上一版因果衔接，建议全片从 50 秒调整为 53 秒。', '已确认并完成 53 秒配乐成片，保留上一版因果衔接。')
page = page.replace('当前 README 仍指向 v4 成片；v6 时长与叙事变更等待确认后再制作完整配乐视频。', '当前 README 已更新为 v6 配乐成片；本页仅保留确认时的小样与分镜。')
page = page.replace('<main>', '<main><p><a href="../final/index.html">打开当前 v6 配乐成片</a> · 以下为已确认预览归档</p>', 1)
preview.write_text(page, encoding='utf-8')
preview_manifest = read(ROOT / 'preview/manifest.json')
preview_manifest['files'] = [{'path': p.name, 'sha256': sha(p)} for p in sorted((ROOT / 'preview').iterdir()) if p.is_file() and p.name != 'manifest.json']
write_json(ROOT / 'preview/manifest.json', preview_manifest)
sources = [{'path': str(p.relative_to(ROOT)).replace('\\', '/'), 'sha256': sha(p)} for p in sorted((ROOT / 'source').iterdir()) if p.is_file()]
write_json(FINAL / 'manifest.json', {'movieSha256': movie_sha, 'planSha256': P['planSha256'], 'approval': '../approval.json', 'files': [{'path': p.name, 'sha256': sha(p)} for p in sorted(FINAL.iterdir()) if p.is_file() and p.name != 'manifest.json'], 'sources': sources})
print('Verified delivery complete: ' + movie_sha)
