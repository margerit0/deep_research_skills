"""Bind delivery records to the verified movie and advance the current entry."""
from pathlib import Path
import hashlib
import json
from timeline import load_plan,write_json
ROOT=Path(__file__).resolve().parent.parent
P=load_plan(ROOT/'plan.json')
FINAL=ROOT/'final';CACHE=ROOT/'cache/final'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
numeric=read(FINAL/'verification-data.json')
audio=read(CACHE/'audio-decoded-audit.json')
playback=read(CACHE/'playback-audit.json')
visual=read(CACHE/'visual-review.json')
movie_sha=sha(FINAL/'product-demo.mp4')
assert movie_sha==numeric['movieSha256']==playback['movieSha256']==visual['movieSha256']
assert playback['ended'] and not playback['muted'] and playback['presentationCoverage']['complete']
assert not audio['clippedSamples'] and visual['visualResult']=='passed'
write_json(FINAL/'verification-data.json',{**numeric,'decodedAudio':audio,'programPlayback':playback,'visualReview':visual})
(FINAL/'verification.md').write_text(f'''# v4 成片验证

2026-10-29。成片 SHA-256：`{movie_sha}`。计划：`{P['planSha256']}`。

| 检查 | 结果 |
|---|---|
| 规格与解码 | H.264 / yuv420p，1920×1080，30 fps，42 秒，完整解码 1260 帧，时间戳连续。 |
| 配乐 | 原创代码合成，无歌词或外部采样；120 BPM、84 拍；AAC、48 kHz、双声道。 |
| 帧与交互 | 全部 1260 帧检查文案、字体、溢出及披露；4 次原生点击在命中前检查目标并验证真实回调。 |
| 已确认方案 | 时间轴未变；14 张关键帧与批准预览比较。原生画面保持一致，新增卡片存在 Windows 动画合成后的字体抗锯齿差异，布局、文案与图形保持一致。编码细节按亮度 PSNR 检查，均高于 45 dB。 |
| 运动与停止 | 最终 MP4 解码检查原生图谱运动、新增候选动画、报告完成后的停止及品牌稳定区间。 |
| 音频削波 | 编码后峰值 {audio['peakDbfs']:.2f} dBFS，削波样本 0；有效 2,016,000 样本／声道，AAC 尾部填充 {audio['aacTrailingPaddingSamples']} 样本。 |
| 动作同步 | {len(audio['eventAlignment'])} 个动作音效与源音轨相关对齐，最大偏移 {max(abs(x['lagMilliseconds']) for x in audio['eventAlignment']):g} 毫秒。 |
| 程序播放 | 1 倍速完整播放，音轨启用、音量 1；唯一呈现帧 {playback['presentationCoverage']['uniqueFrames']}，播放期间掉帧 {playback['droppedDuringPlayback']}；声音信号计量有效。浏览器计数与文件解码数分别保留。 |
| 目视检查 | 从当前 MP4 提取 14 张关键帧、转场与运动检查帧，检查中文、连线、边界、品牌与披露。开场 90–103 帧维持上方披露，直到下方披露完全出现。 |
| 主观听音 | 当前工具环境未进行主观听音；数值及音轨启用的程序播放通过，不等于听感验收。 |
| 内容边界 | 原创合成研究数据；新增功能明确为机制示意，无虚构实验、分数或提升结论；未调用模型或搜索服务。 |

检查图 `check-sheet.png` 来自这个最终 MP4，而非预览 PNG。源帧、音轨和详细转场图是 `cache/final/` 中的可再生缓存。完整数值与播放记录在 `verification-data.json`。
''',encoding='utf-8')
(FINAL/'reproduce.md').write_text('''# v4 成片复现

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
''',encoding='utf-8')
brief=read(ROOT/'brief.json');brief['state']='complete';brief['spec']['preview']='已于 2026-10-29 确认；预览归档，当前成片为 final/product-demo.mp4'
brief['finalDelivery']={'movieSha256':movie_sha,'planSha256':P['planSha256'],'approval':'approval.json','subjectiveListening':'not_run','withinPlanRepairs':['90–103 帧保持开场披露直到页脚披露完全可见','成片移除预览版本标识，时间轴和布局不变']}
write_json(ROOT/'brief.json',brief)
status_path=ROOT.parent/'status.json';status=read(status_path)
status['readmeVersion']='2026-10-29-v4'
status['hostedPlayer']={'status':'awaiting_upload_authorization','reason':'自动审批拒绝访问已登录 GitHub 附件上传页面；本地 README 使用封面与相对 MP4 链接。','remoteRepositoryUpdate':'not_performed'}
current=status['versions'][0];current['state']='complete';current['final']={'video':'2026-10-29-v4/final/product-demo.mp4','page':'2026-10-29-v4/final/index.html','sheet':'2026-10-29-v4/final/check-sheet.png','verification':'2026-10-29-v4/final/verification.md','reproduce':'2026-10-29-v4/final/reproduce.md','sha256':movie_sha}
write_json(status_path,status)
(ROOT.parent/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=2026-10-29-v4/final/index.html"><title>星图工作台 · 当前成片</title><p><a href="2026-10-29-v4/final/index.html">打开 v4 配乐成片</a></p></html>',encoding='utf-8')
preview=ROOT/'preview/index.html';page=preview.read_text(encoding='utf-8')
page=page.replace('v4 · 等待本版预览确认','v4 · 已确认预览归档').replace('原发布版 v3 仍保留在 README。','当前成片已更新至 v4。').replace('本阶段仅制作预览；配乐与完整 MP4 将在本版内容、时长及镜头确认后制作。','本页为确认时的预览归档；42 秒配乐成片已完成。')
page=page.replace('<main>','<main><p><a href="../final/index.html">打开当前 v4 配乐成片</a> · 以下为已确认预览归档</p>',1)
preview.write_text(page,encoding='utf-8')
sources=[]
for path in sorted((ROOT/'source').glob('*')):
    if path.is_file():sources.append({'path':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':sha(path)})
write_json(FINAL/'manifest.json',{'movieSha256':movie_sha,'planSha256':P['planSha256'],'approval':'../approval.json','files':[{'path':p.name,'sha256':sha(p)} for p in sorted(FINAL.iterdir()) if p.is_file() and p.name!='manifest.json'],'sources':sources})
print('Verified delivery complete: '+movie_sha)
