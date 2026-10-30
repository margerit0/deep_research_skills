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
listening = approval.get('acceptance')
movie_sha = sha(FINAL / 'product-demo.mp4')
assert movie_sha == numeric['movieSha256'] == playback['movieSha256'] == visual['movieSha256']
assert P['planSha256'] == numeric['planSha256'] == score['planSha256'] == approval['planSha256']
assert approval['status'] == 'approved'
assert listening is None or (listening['movieSha256'], listening['subjectiveListening']) == (movie_sha, 'accepted'), 'The listening acceptance must name this exact encoding.'
assert playback['ended'] and not playback['muted'] and playback['presentationCoverage']['complete']
assert not playback['droppedDuringPlayback'] and not playback['frameCallbackGaps'] and not playback['pageErrors']
assert not audio['clippedSamples'] and not score['clippingSamples'] and visual['visualResult'] == 'passed'
write_json(FINAL / 'verification-data.json', {**numeric, 'score': score, 'decodedAudio': audio, 'programPlayback': playback, 'visualReview': visual, 'subjectiveListening': listening or 'not_run'})
duration, frames = P['video']['durationSeconds'], P['video']['totalFrames']
key_count = len(P['keyframes'])
beat_count = len(P['beats'])
samples = P['audio']['sampleCount']
version = ROOT.name
now, before = numeric['loudness']['current'], numeric['loudness']['parent']
names = {'intro': '开场', 'skills': '选择方法', 'groove': '并行研究', 'chapter': '章节卡', 'explain': '方法讲解', 'analyse': '诊断与候选', 'validate': '独立验证', 'release': '人工采纳', 'brand': '品牌收尾'}
arc = '、'.join(f"{names[s['section']]} {s['lufs']:.1f}" for s in score['loudness']['sections'])
harmony = score['harmonicCheck']
parent = numeric['parentComparison']
spans = lambda runs: '、'.join(f'{a}–{b - 1}' for a, b in runs)
scope = f"与 {parent['version']} 的渲染帧逐帧比较（任一通道差值超过 8/255 记为变化，排除版本页脚）：有变化的帧 {spans(parent['changedRanges'])}，共 {parent['changedFrames']} 帧，全部落在报告窗口 {spans(parent['intendedWindows'])} 内，窗口外 {parent['changedOutsideWindows']} 帧；其余 {parent['unchangedFrames']} 帧最大通道差值 {parent['peakDifferenceInUnchangedFrames']}/255。" if parent['status'] == 'compared' else f"未比较：{parent['reason']}"
music = numeric['parentMusic']
score_scope = f"音轨与 {music['version']} 的 `music.wav` 逐位相同（SHA-256 `{music['sha256']}`）。" if music['status'] == 'compared' else f"未比较：{music['reason']}"
psnr = min(x['encodedAgainstRendered']['lumaPSNR'] for x in numeric['encodedSimilarity'])
heard = f"用户于 {listening['date']} 试听当前成片后确认满意，原话与成片哈希记录在 `../approval.json` 的 `acceptance`。工具环境本身不做主观听音（`visualReview.subjectiveListening` 记为 `not_run`）。" if listening else '当前工具环境未进行主观听音；上述数值和启用音轨的程序播放通过，不等于听感验收。'
text = dict(encoding='utf-8', newline='\n')
(FINAL / 'verification.md').write_text(f'''# v8 成片验证

2026-10-31。成片 SHA-256：`{movie_sha}`。计划：`{P['planSha256']}`。

| 检查 | 结果 |
|---|---|
| 规格与解码 | H.264 / yuv420p，1920×1080，30 fps，{duration:g} 秒；完整解码 {frames} 帧，逐帧时间戳连续。 |
| 配乐 | 沿用 v7 的原创代码合成配乐，无歌词或外部采样；120 BPM、{beat_count} 拍；AAC、48 kHz、双声道。{score_scope}{harmony['notes']} 个音符全部在 D 大调内（脚本强制），持续半音摩擦 {harmony['sustainedSemitoneRubs']} 处。 |
| 响度与频谱 | 综合 {now['integratedLufs']:.1f} LUFS（v7 {before['integratedLufs']:.1f}），响度范围 {now['loudnessRangeLu']:.1f} LU（v7 {before['loudnessRangeLu']:.1f}），真峰值 {now['truePeakDbtp']:.1f} dBTP（v7 {before['truePeakDbtp']:.1f}）。2–6 kHz {now['bandRmsDb']['2-6kHz']:.1f} dB（v7 {before['bandRmsDb']['2-6kHz']:.1f}），6 kHz 以上 {now['bandRmsDb']['over6kHz']:.1f} dB（v7 {before['bandRmsDb']['over6kHz']:.1f}）。 |
| 段落响度 | 源音轨各段 K 加权均值（LUFS）：{arc}。 |
| 帧与交互 | 全部 {frames} 帧检查文字、字体、溢出、披露及转场遮挡；4 次原生点击验证命中目标和真实回调。 |
| 报告卡片 | 375 帧起逐帧确认是报告卡片：有 `.cw-report-head`，无回退态、原始 # 和引用／来源／折叠控件；390 帧起标题、状态、三个编号章节、下一步正文和免责声明与源数据一致；405–479 帧完整卡片在镜头内，底部说明在卡片内，输入框在卡片下方，遮罩已退；报告缩入时不压看板顶栏。 |
| 改动范围 | {scope} |
| 编码质量 | {key_count} 张关键帧与渲染帧比较，亮度 PSNR 最低 {psnr:.1f} dB。 |
| 运动与停止 | 从当前 MP4 检查原生图谱运动、报告完成后停止、报告连续缩入、章节标题及品牌稳定停留。 |
| 音频削波 | 编码后峰值 {audio['peakDbfs']:.2f} dBFS，削波样本 0；有效 {samples:,} 样本／声道，AAC 尾部填充 {audio['aacTrailingPaddingSamples']} 样本。 |
| 动作同步 | {len(audio['eventAlignment'])} 个动作音效与源音轨相关对齐，最大偏移 {max(abs(x['lagMilliseconds']) for x in audio['eventAlignment']):g} 毫秒，最低相关 {min(x['correlation'] for x in audio['eventAlignment']):.3f}。 |
| 程序播放 | 1 倍速完整播放，音轨启用、音量 1；唯一呈现帧 {playback['presentationCoverage']['uniqueFrames']}，播放期间掉帧 {playback['droppedDuringPlayback']}；音频信号计量有效。浏览器计数与文件解码数分别保存。 |
| 目视检查 | 查看当前 MP4 的 {key_count} 张关键帧、各转场帧及页脚原尺寸裁切；检查中文、连线、边界、品牌及全程披露，详见 `verification-data.json` 的 `visualReview`。未做连续目视播放。 |
| 主观听音 | {heard} |
| 内容边界 | 使用项目原创合成数据；优化部分为机制示意，无虚构实验、分数或提升结论；未调用模型或搜索服务。 |

`check-sheet.png` 来自这个最终 MP4。详细记录见 `verification-data.json`；逐帧图片、音轨与转场检查图是 `cache/final/` 中的可再生缓存。
''', **text)
(FINAL / 'reproduce.md').write_text(f'''# v8 成片复现

工作目录为仓库根目录。基准提交 `87e66a700fab2d906b5edcbbc6467efc6a6dd982`（新版报告卡片）；制作源码标识见 `manifest.json`。依赖原仓库组件、样式和原创合成数据，不是脱离仓库的独立源码包，保留原许可。

环境：Node 22.17.0；Python 3.13.5 + Pillow 12.3.0；FFmpeg/ffprobe 7.1.1；项目 frontend/node_modules；Chrome；Microsoft YaHei。Chrome 可用 `CHROME_PATH` 覆盖，字体路径见打包脚本。未新增 npm 或 Python 依赖。

用户在 v8 预览后明确确认了本次方案，记录见 `../approval.json`。时间轴与计划必须保持批准标识；改动时间轴后需要重新取得确认。

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

{duration:g} 秒、{frames} 帧、{beat_count} 拍和 {samples:,} 音频样本均由同一计划派生；配乐的段落、和声与音效位置都从 `plan.json` 计算。配乐先归一到 -16 LUFS，再经前视限幅，最后一秒自然收束。编码为 CRF 17、H.264、yuv420p，AAC 192 kbps、48 kHz、双声道。完整参数见 `verification-data.json`。

本地服务仅监听 127.0.0.1:5192；沙箱若阻止本地套接字，需要允许本地服务和浏览器渲染进程。渲染器拒绝外部及后端 API 请求，并使用灰阶字形渲染（`--disable-lcd-text`）。播放器通过播放按钮启用 Web Audio，再检查每个呈现帧与音频信号。

打包脚本会与 `product-video/2026-10-30-v7/cache/final/frames` 逐帧比较，确认画面改动只出现在报告窗口内，并核对 `music.wav` 与 v7 逐位相同。这些是不入库的缓存；缺失时跳过比较并如实记录。响度对比直接读取 v7 的 MP4。预览阶段的步骤见 `../preview/reproduce.md`。

查看最终 MP4 的 `check-sheet.png` 和 `cache/final/transitions.png`，在 `cache/final/visual-review.json` 记录当前成片哈希、检查方法与真实目视结论。主观听音只能由试听者确认，写入 `../approval.json` 的 `acceptance` 并绑定成片哈希；未做时不得标为完成。完成后运行：

```powershell
python product-video/{version}/source/finalize.py
```

重新编码必须重新抽帧、播放、检查音频和画面，不能沿用旧 MP4 的验收记录。当前入口为 `product-video/index.html`。根 README 的内嵌播放器只接受在 GitHub 网页上传的附件地址；切换版本时先上传 MP4，再同步更新根 README 与 `product-video/status.json` 的 `readmeVersion`、`publishedVersion` 和 `hostedPlayer`。
''', **text)
def write_manifest():
    sources = [{'path': str(p.relative_to(ROOT)).replace('\\', '/'), 'sha256': sha(p)} for p in sorted((ROOT / 'source').iterdir()) if p.is_file()]
    write_json(FINAL / 'manifest.json', {'movieSha256': movie_sha, 'planSha256': P['planSha256'], 'approval': '../approval.json', 'files': [{'path': p.name, 'sha256': sha(p)} for p in sorted(FINAL.iterdir()) if p.is_file() and p.name != 'manifest.json'], 'sources': sources})
# The current entry only moves once the user has listened to this exact encoding.
if not listening:
    write_manifest()
    print('Verified, waiting for listening acceptance; current entry unchanged: ' + movie_sha)
    raise SystemExit
brief = read(ROOT / 'brief.json')
brief['state'] = 'complete'
brief['spec']['preview'] = 'preview/index.html；用户确认预览后制作成片，见 approval.json'
brief['sources'] = [{'path': f'product-video/{version}/source/{p.name}', 'sha256': sha(p)} for p in sorted((ROOT / 'source').iterdir()) if p.is_file()]
brief['finalDelivery'] = {'movieSha256': movie_sha, 'planSha256': P['planSha256'], 'approval': 'approval.json', 'subjectiveListening': 'accepted_by_user' if listening else 'not_run', 'changes': brief['revision']['changes']}
write_json(ROOT / 'brief.json', brief)
status_path = ROOT.parent / 'status.json'
status = read(status_path)
status.update(currentVersion=version, currentFinalVersion=version)
status.pop('pendingVersion', None)
status['hostedPlayer'].setdefault('version', status['readmeVersion'])
preview = next(v for v in status['versions'] if v['id'] == version)['preview']
current = {
    'id': version,
    'state': 'complete',
    'planSha256': P['planSha256'],
    'approval': {'planSha256': approval['planSha256'], 'evidence': approval['evidence']},
    'acceptance': listening,
    'changes': brief['revision']['changes'],
    'coverage': f'{version}/brief.json',
    'preview': preview,
    'final': {'video': f'{version}/final/product-demo.mp4', 'page': f'{version}/final/index.html', 'sheet': f'{version}/final/check-sheet.png', 'verification': f'{version}/final/verification.md', 'reproduce': f'{version}/final/reproduce.md', 'sha256': movie_sha},
}
status['versions'] = [current, *[v for v in status['versions'] if v['id'] != version]]
write_json(status_path, status)
(ROOT.parent / 'index.html').write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={version}/final/index.html"><title>星图工作台 · 当前成片</title><p><a href="{version}/final/index.html">打开 v8 成片</a></p></html>', **text)
write_manifest()
print('Verified delivery complete: ' + movie_sha)
