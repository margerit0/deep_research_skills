"""Bind approved sources, final video, audio and observed verification results."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
CACHE, FINAL = ROOT/'cache/final', ROOT/'final'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

t = read(ROOT/'timeline.json')
approval = read(ROOT/'approval.json')
brief = read(ROOT/'brief.json')
capture = read(CACHE/'capture-audit.json')
video = read(CACHE/'video-audit.json')
score = read(CACHE/'audio-source.json')
audio = read(CACHE/'audio-decoded-audit.json')
playback = read(CACHE/'playback-audit.json')
manual = read(CACHE/'manual-review.json')
digest = sha(FINAL/'product-demo.mp4')
assert t['approval'] == approval and approval['status']=='approved' and approval['approved_version']==t['version']
assert sha(ROOT/'preview/manifest.json')==approval['preview_manifest_sha256']
assert sha(ROOT/'preview/approved-timeline.json')==approval['approved_timeline_sha256']
assert sha(ROOT/'preview/motion-sample.mp4')==approval['approved_sample_sha256']
assert digest==video['movie_sha256']==playback['movieSha256']==playback['servedSha256']==manual['movie_sha256']
assert sha(FINAL/'check-sheet.png')==manual['check_sheet_sha256']
assert score['timelineSha256']==sha(ROOT/'timeline.json') and score['sourceSha256']==sha(CACHE/'music.wav')
assert capture['allFramesChecked']==video['video_frames']==t['frame_count']
assert not capture['errors'] and not capture['blocked'] and all(item['equal'] for item in capture['randomAccess'])
assert len(capture['clicks'])==4 and all(item['hit'] and item['visible'] and item['insideViewport'] and item['callbackMatches'] for item in capture['clicks'])
assert audio['clippedSamples']==0 and audio['playableSeconds']==t['duration_seconds']
assert len(audio['eventAlignment'])==len(score['cues']) and all(abs(item['lagMilliseconds'])<=2 for item in audio['eventAlignment'])
assert playback['ended'] and not playback['muted'] and playback['volume']==1 and playback['duration']==t['duration_seconds']
assert playback['presentationCoverage']['complete'] and playback['presentationCoverage']['uniqueFrames']==t['frame_count']
assert playback['droppedDuringPlayback']==0 and playback['frameCallbackGaps']==0 and not playback['pageErrors']
assert playback['audioMeter']['activeFrames']>t['frame_count']*.8

preview_manifest = read(ROOT/'preview/manifest.json')
approved_sources = []
for name in ['source/app.tsx','source/scene.js','source/scene.css','source/index.html']:
    expected = next(item['sha256'] for item in preview_manifest['files'] if item['path']==name)
    assert sha(ROOT/name)==expected,name
    approved_sources.append({'path':name,'sha256':expected,'unchanged':True})
for dependency in brief['sources']:
    assert sha(ROOT.parent.parent/dependency['path'])==dependency['sha256'],dependency['path']

verification = {'version':t['version'],'approval':approval,'movie_sha256':digest,'video':video,'audio_source':score,'audio_decoded':audio,'browser_playback':playback,'visual_review':manual,'approved_visual_sources':approved_sources,'semantic_capture':{key:capture[key] for key in ['allFramesChecked','clicks','graph','randomAccess','errors','blocked']},'formatting_changes_from_preview':['页脚“产品演示 / 预览 v3”改为“产品演示 / v3”，画面、交互及时间轴保持已确认版本。'],'subjective_listening':'not_performed'}
write(FINAL/'verification-data.json',verification)
max_lag = max(abs(item['lagMilliseconds']) for item in audio['eventAlignment'])
graph_error = max(item['maxError'] for item in capture['graph'])
report = f'''# 成片检查记录 · {t['version']}

按用户于 {approval['approved_date']} 回复“{approval['user_message']}”确认的 v3 预览制作。原预览时间轴与批准记录分别保存为 `../preview/approved-timeline.json`、`../approval.json`。

对应视频：`product-demo.mp4`，SHA-256：`{digest}`。

## 文件与内容

| 项目 | 实际结果 |
| --- | --- |
| 视频 | H.264 High / yuv420p / 1920×1080 |
| 帧率、帧数、时长 | 恒定 30 fps / 解码 {video['video_frames']} 帧 / {t['duration_seconds']}.000 秒 |
| 帧时间戳 | 首帧 {video['video_pts_first']:.6f} 秒，末帧 {video['video_pts_last']:.6f} 秒，间隔连续为 1/30 秒 |
| 音轨 | AAC / 48 kHz / 立体声 / 有效播放 {audio['playableSeconds']} 秒 |
| 配乐 | 原创代码合成，无歌词，{score['bpm']} BPM / {score['beats']} 拍 |
| 完整 UI 停留 | 第 0–59 帧，2 秒 |
| Skills 选择 | 4 秒展开菜单，6 秒选中产品对比，结果停留 2 秒 |
| 报告、品牌稳定停留 | 2.5 秒 / 1 秒 |

AAC 解码为每声道 {audio['decodedSamplesPerChannel']} 个样本，其中 {audio['aacTrailingPaddingSamples']} 个属于尾部编码填充；容器有效播放为 {audio['playableSamplesPerChannel']} 个样本，即 18 秒。填充峰值约 {audio['paddingPeak']:.9f}，不把填充误称为额外视频时长。

## 画面与原生交互

- 全部 {capture['allFramesChecked']} 帧检查披露标识、源问题、菜单、配置结果、报告和完成状态。全程保留“合成演示 · 流程已压缩”。
- 开场显示完整原生工作台；输入框取景覆盖 Skills 菜单。五个选项、产品对比的标签与说明均匹配仓库原文。
- 四次点击在原生目标可见时测量顶部命中并触发真实组件回调；菜单选择在关闭前核验命中。随后按统一帧时间轴呈现配置结果。
- 原生 7 个研究节点、10 条有向连线和返回回路逐条核对，端点最大误差 {graph_error:.5f} CSS px。
- {len(capture['randomAccess'])} 个新页面非顺序定位与顺序渲染的状态、相机、文本和动效一致，像素抗锯齿差异处于既有容差内。
- 四个画面源码文件与已批准预览哈希完全一致。八张成片关键帧与预览相符，比较时仅排除页脚版本标记区域。
- 从当前 MP4 解码核查同一运行状态的第 275/295 帧，图谱局部有 {video['decoded_running_motion']['pixels_over_8']} 个像素变化超过 8/255。报告、品牌稳定帧的平均通道差分别为 {video['decoded_report_hold']['mean_absolute_channel_error']:.5f}/255、{video['decoded_brand_hold']['mean_absolute_channel_error']:.5f}/255。
- 页面错误、外部请求、后端请求均为 0。没有真实模型调用、真实用户资料或真实录屏；合成报告没有真实编号引用，因此没有添加引用核对操作。

`check-sheet.png` 的八帧均从上述哈希对应的最终 MP4 解码，时间为 1.5、3.5、5、7、9.5、12.5、14.5、17.5 秒。检查图没有使用旧片或编码前 PNG 代替。

目视检查：{manual['visual_result']}

## 声音、同步和完整播放

解码音频峰值 {audio['peakDbfs']:.2f} dBFS、削波样本数 {audio['clippedSamples']}；真峰值 {video['loudness']['truePeakDbfs']:.1f} dBFS，综合响度 {video['loudness']['integratedLUFS']:.1f} LUFS。音乐由振荡器、固定种子噪声和时间轴事件生成，没有外部音频素材或人声；末尾有 {score['fadeOutSeconds']} 秒淡出。

{len(audio['eventAlignment'])} 个动作音效从同一时间轴生成。源 PCM 与 AAC 解码音频的事件窗口相关对齐，最大偏移 {max_lag:.3f} ms；Skills 点击为 4、6 秒，节点和页签点击为 11、11.5 秒。

成片已通过本地播放器完整播放到 18 秒结束：1 倍速，音轨未静音，音量 1。呈现时间戳覆盖全部 {playback['presentationCoverage']['uniqueFrames']} 个视频帧，呈现掉帧 {playback['droppedDuringPlayback']}，回调缺口 {playback['frameCallbackGaps']}。播放加载的字节哈希与交付 MP4 完全相同。音频仪表在 {playback['audioMeter']['activeFrames']} 个呈现回调中检测到有效信号，浏览器解码音频 {playback['audioDecodedBytes']} 字节。

浏览器的累计视频计数包含预加载或重复解码，不能代替文件帧数。本记录以 MP4 实际解码帧数和逐帧呈现时间戳覆盖作为证据，原始浏览器计数保存在详细数据中。

**未完成项：主观听音验收。** 当前环境完成了音频数值检查、动作同步、音频信号检测、正常速度的程序播放，以及成片抽帧目视检查；不把这些结果等同于人工连续观看或主观音色验收。

## 交付与复现

可编辑源码位于 `../source/`，环境与实际命令见 `reproduce.md`，详细检查结果见 `verification-data.json`，文件及依赖哈希见 `manifest.json`。

`preview/` 保留批准前的历史预览，旧页面中的“等待确认”和旧清单中的 pending 表示生成当时的状态；当前批准以 `approval.json` 为准。旧版本、原工作区修改均保留，没有提交、推送或发布代码。
'''
(FINAL/'verification.md').write_text(report,encoding='utf-8')
brief['stage']='final_delivered'
brief['output'].update({'finalFile':'final/product-demo.mp4','finalSha256':digest,'checkSheet':'final/check-sheet.png','finalFrames':t['frame_count'],'finalDurationSeconds':t['duration_seconds'],'music':f"原创代码配乐，{score['bpm']} BPM / {score['beats']} 拍，AAC 48 kHz 立体声",'validation':'编码、抽帧、同步、启用音轨的程序播放均完成；主观听音未执行'})
brief['output'].pop('plannedFinal',None)
write(ROOT/'brief.json',brief)
assets = [p for p in ROOT.rglob('*') if p.is_file() and 'cache' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p != FINAL/'manifest.json']
write(FINAL/'manifest.json',{'version':t['version'],'approved':True,'movie_sha256':digest,'external_repository_dependencies':brief['sources'],'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(assets)]})
print(json.dumps({'movie_sha256':digest,'files':len(assets),'videoFrames':t['frame_count'],'droppedFrames':playback['droppedDuringPlayback'],'subjectiveListening':'not performed'},ensure_ascii=False))
