"""Bind the delivery, editable sources, approval and actual validation evidence."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parent.parent
CACHE=ROOT/'cache/final'
FINAL=ROOT/'final'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

timeline=read(ROOT/'timeline.json')
approval=read(ROOT/'approval.json')
capture=read(CACHE/'capture-audit.json')
video=read(CACHE/'video-audit.json')
audio=read(CACHE/'audio-decoded-audit.json')
score=read(CACHE/'audio-source.json')
playback=read(CACHE/'playback-native-audit.json')
instrumented=read(CACHE/'playback-audit.json')
manual=read(CACHE/'manual-review.json') if (CACHE/'manual-review.json').exists() else {}
digest=sha(FINAL/'product-demo.mp4')
assert approval['status']=='approved' and timeline['approval']['status']=='approved'
assert sha(ROOT/'preview/approved-timeline.json')==approval['approved_timeline_sha256']
assert digest==video['movie_sha256']==playback['movieSha256']==instrumented['movieSha256']
assert capture['allFramesChecked']==360 and not capture['errors'] and not capture['blocked']
assert all(x['equal'] for x in capture['randomAccess'])
assert playback['ended'] and not playback['muted'] and playback['duration']==12
assert audio['clippedSamples']==0 and all(abs(x['lagMilliseconds'])<=2 for x in audio['eventAlignment'])
visual_current=manual.get('movie_sha256')==digest
if not visual_current:
    manual={'movie_sha256':digest,'visual_result':'待目视复核：未找到绑定当前成片哈希的检查记录。','subjective_listening':False}

verification={
    'version':timeline['version'],'approval':approval,'movie_sha256':digest,
    'video':video,'audio_source':score,'audio_decoded':audio,
    'browser_playback':playback,'instrumented_audio_playback':instrumented,
    'visual_review':manual,'visual_review_matches_movie':visual_current,
    'semantic_capture':{'frames_checked':capture['allFramesChecked'],'clicks':capture['clicks'],'graph':capture['graph'],'random_access':capture['randomAccess'],'page_errors':capture['errors'],'blocked_requests':capture['blocked']},
    'subjective_listening':'not_performed_in_this_environment',
    'formatting_changes_from_preview':['页脚“产品演示 / 预览 v1”改为“产品演示 / v1”','品牌淡入期间保留报告镜头的底层文案，审批说明不进入成片'],
}
write(FINAL/'verification-data.json',verification)

max_lag=max(abs(x['lagMilliseconds']) for x in audio['eventAlignment'])
max_graph_error=max(x['maxError'] for x in capture['graph'])
report=f'''# 成片检查记录 · {timeline['version']}

本次成片按用户于 2026-10-25 回复“确认分镜”批准的版本制作。批准记录与原时间轴分别保存在 `../approval.json`、`../preview/approved-timeline.json`。

对应视频：`product-demo.mp4`，SHA-256：`{digest}`。

## 文件与时间

| 项目 | 实际结果 |
| --- | --- |
| 视频 | H.264 High / yuv420p / 1920×1080 |
| 帧率与帧数 | 恒定 30 fps / 解码 360 帧 |
| 时长 | 12.000 秒，首帧 PTS 0，末帧 PTS 11.966667 |
| 音轨 | AAC / 48 kHz / 双声道 / 可播放时长 12.000 秒 |
| 配乐 | 原创代码合成，无歌词，120 BPM / 24 拍 |
| 报告稳定阅读 | 第 225–299 帧，2.5 秒 |
| 品牌稳定停留 | 第 330–359 帧，1 秒 |

所有视频帧时间戳连续，间隔为 1/30 秒。AAC 原始解码得到 {audio['decodedSamplesPerChannel']} 个采样点/声道，其中尾部 {audio['aacTrailingPaddingSamples']} 个为编解码填充；容器限定的有效播放为 576000 个采样点，即 12 秒。填充峰值约 {audio['paddingPeak']:.8f}，未把原始解码填充误称为额外视频时长。

## 内容与交互

- 360 帧逐一检查合成演示标识可见且在画布内，覆盖转场与品牌收尾。
- 问题、报告正文与仓库 `mock.ts` / `demoReport` 逐字比对一致；中文字体加载成功，没有 Unicode 替换字符。
- 使用原生组件、样式、合成状态和 SVG。7 个研究节点、1 个汇总连接点、10 条有向连线逐条核对，保留返回回路；端点最大误差 {max_graph_error:.5f} CSS px。
- 第 150 帧商业节点和第 165 帧执行记录页签均命中真实顶部目标；光标没有点击系统自动推进步骤或禁用的发送按钮。
- 所有离散动作起点在整拍，原生信号流与呼吸动效分别保留 1.8 秒、1.7 秒周期。
- 第 210 帧以后没有运行节点、呼吸动画或可见流动提示。11 个新页面非顺序定位与顺序渲染的状态、文本、相机、路径、滚动及动画相位一致。
- 五张关键帧与已批准预览保持一致，只排除已注明的页脚版本文字差异；少量 Windows 灰色字形抗锯齿差异按原检查约定处理。
- 页面错误 0、外部和后端请求 0。没有使用真实实录、用户资料、模型或搜索服务。

这份合成报告没有真实编号引用或来源原文，因此不显示引用核对操作，也不宣称已生成真实产品评价。全程保留“合成演示 · 流程已压缩”，不将 12 秒时长解释为产品响应速度。

## 从当前 MP4 解码的画面检查

`check-sheet.png` 的五帧全部从上述哈希对应的 MP4 提取，时间分别为 1.5、3.5、6.5、8.5、11.5 秒；没有复用渲染前 PNG 或旧小样作为成片检查图。

同一运行状态的第 100 与 110 帧，图谱局部有 {video['decoded_running_motion']['pixels_over_8']} 个像素变化超过 8/255，确认编码后保留连续运动。报告稳定区间平均通道差为 {video['decoded_report_hold']['mean_absolute_channel_error']:.5f}/255，品牌稳定区间为 {video['decoded_brand_hold']['mean_absolute_channel_error']:.5f}/255，属于编码量化差异。

目视记录：{manual['visual_result']}

## 音频与动作对齐

编码后音频峰值 {audio['peakDbfs']:.2f} dBFS，削波采样数 {audio['clippedSamples']}。FFmpeg 真峰值测得 -3.5 dBFS、综合响度 -19.2 LUFS。音乐首尾自然包络由源码控制，末尾 0.52 秒淡出；最后 10 ms 的 RMS 为 {audio['endRms']:.9f}。

9 个动作音效均由同一时间轴事件生成。对源 PCM 与 AAC 解码波形的事件窗口做相关对齐，最大偏移 {max_lag:.3f} ms；点击位于 5.0、5.5 秒，报告完成位于 7.0 秒，品牌起点位于 10.0 秒。

## 完整播放与验证边界

成片已启用音轨（未静音，音量 1），以 1 倍速在 Chrome 中播放到 12 秒结束。最终交付播放器使用完整缓冲；本次原生复验总帧数为 {playback['totalVideoFrames']}，呈现掉帧为 {playback['droppedDuringPlayback']}，相邻呈现回调没有间断。浏览器累计解码音频 {playback.get('audioDecodedBytes','未知')} 字节；独立 Web Audio 仪表也确认持续有音频信号。

早期本地 HTTP 渐进播放曾记录 20 帧呈现掉帧，带仪表的检查记录为 21 帧。完全缓冲对照和当前交付播放器均为 0 帧。文件内部的 360 帧及时间戳始终完整，没有通过降低帧率、删帧或缩短影片来解决浏览器表现。

**未完成项：当前工具环境无法执行主观听音。** 音频解码、响度、真峰值、削波、时间对齐以及启用音轨的程序播放已检查，但不据此声称听感或音色已经人工验收。画面检查来自编码后的关键帧及转场抽帧；没有将程序播放结束冒充人工逐帧观看。

## 交付与源码

本次没有发布或提交代码。原工作区已有修改保留；新增内容位于 `product-video/2026-10-25-v1/`。复现步骤见 `reproduce.md`，详细数据见 `verification-data.json`，源文件与交付哈希见 `manifest.json`。
'''
(FINAL/'verification.md').write_text(report,encoding='utf8')

brief=read(ROOT/'brief.json')
brief['stage']='final_delivered'
brief['output'].update({'finalFile':'final/product-demo.mp4','finalSha256':digest,'checkSheet':'final/check-sheet.png','finalFrames':360,'finalDurationSeconds':12,'music':'原创代码合成，120 BPM，24 拍，AAC 48 kHz 立体声','validation':'程序及抽帧检查完成；主观听音未执行'})
brief['output'].pop('plannedFinal',None)
write(ROOT/'brief.json',brief)

assets=[p for p in ROOT.rglob('*') if p.is_file() and 'cache' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p!=FINAL/'manifest.json']
manifest={'version':timeline['version'],'approved':True,'movie_sha256':digest,'external_repository_dependencies':brief['sources'],'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(assets)]}
write(FINAL/'manifest.json',manifest)
print(json.dumps({'movie_sha256':digest,'files':len(assets),'nativePlaybackDroppedFrames':playback['droppedDuringPlayback'],'subjectiveListening':'not performed'},ensure_ascii=False))
