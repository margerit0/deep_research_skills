"""Bind the revision preview to its actual capture, decode and playback evidence."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
PREVIEW, CACHE = ROOT / 'preview', ROOT / 'cache'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

timeline = read(ROOT / 'timeline.json')
brief = read(ROOT / 'brief.json')
capture = read(CACHE / 'capture-audit.json')
media = read(CACHE / 'media-audit.json')
playback = read(CACHE / 'playback-audit.json')
manual = read(CACHE / 'manual-review.json')
layout = read(CACHE / 'native-layout.json')
digest = sha(PREVIEW / 'motion-sample.mp4')
assert timeline['approval']['status'] == 'pending'
assert digest == media['sample_sha256']
assert digest == playback['sample_sha256'] == manual['sample_sha256']
assert sha(PREVIEW / 'storyboard-overview.png') == manual['storyboard_sha256']
assert capture['allFramesChecked'] == 360 and not capture['errors'] and not capture['blocked']
assert all(item['equal'] for item in capture['randomAccess'])
assert all(item['hit'] and item['insideViewport'] for item in capture['clicks'])
assert all(item['insideViewport'] and item['opacity'] == 1 for item in layout['nativeElements'])
assert playback['ended'] and playback['duration'] == 8 and playback['totalVideoFrames'] == 240
assert playback['droppedDuringPlayback'] == 0 and playback['frameCallbackGaps'] == 0
assert not list((ROOT / 'final').glob('*.mp4'))

verification = {
    'version': timeline['version'], 'stage': 'preview', 'approval': timeline['approval'],
    'sample_sha256': digest, 'sample': media, 'playback': playback,
    'native_opening_layout': layout,
    'capture': {key: capture[key] for key in ['allFramesChecked', 'clicks', 'graph', 'randomAccess', 'errors', 'blocked', 'cameras']},
    'visual_review': manual,
}
write(PREVIEW / 'verification-data.json', verification)

report = f'''# 预览检查记录 · v2

新增开场：完整浏览器画面 1 秒 → 连续聚焦 1 秒 → 输入框停留 1 秒。全片方案仍为 12 秒；交付小样为前 8 秒、1920×1080、30 fps、H.264、240 帧，无音轨。

小样 SHA-256：`{digest}`。

## 已执行检查

- 检查全部 360 帧：合成演示标识始终可见；问题与报告逐字匹配源数据，字体加载成功，无替换字符。
- 初始浏览器容器实际为 1920×1080，原生工作台为 1920×1032，加 48px 容器栏；侧栏、标题、输入框、图谱均完整位于视口内，透明度为 1。
- 初始展示原生待执行状态；研究员在任务派发后出现，没有提前伪造执行结果。
- 17 个新页面非顺序定位的语义、相机、原生路径和动效状态一致；像素差异在原有抗锯齿容差内。
- 第 150、165 帧点击均命中真实可见控件；7 个研究节点和 10 条有向连线按原组件校验，保留返回回路。
- 同一运行状态的解码帧 125/145，图谱局部有 {media['decoded_running_motion']['pixels_over_8']} 个像素变化超过 8/255；完成后没有运行提示，报告稳定帧 225/239 的平均通道差为 {media['decoded_stable_report']['mean_absolute_channel_error']:.5f}/255。
- 8 秒小样完整缓冲后以 1 倍速程序播放：240 帧、呈现掉帧 0、回调缺口 0、播放错误 0。
- 目视检查实渲总览和 MP4 抽帧。全屏开场及输入框落位清楚，说明文字在窗口落位后出现；检查器点击与后续画面衔接正常。
- 外部网络请求、后端请求及浏览器页面错误均为 0。没有调用真实模型或使用真实用户数据。

## 版本与验证边界

五个默认时间点均已实际渲染，另补充 0.5、2.5、4.5 秒。总览展示六个主要画面；1.5、3.5 秒转场帧单独保留。

报告稳定阅读 2.5 秒、品牌稳定停留 1 秒沿用原方案。本版尚未编码完整成片及制作正式配乐；本次没有进行音频验收。程序播放与抽帧目视检查分别记录，不宣称人工连续观看或主观听音已完成。

v1 成片保留。本版时间轴批准状态为 pending，等待对这次修订预览的明确确认。源码及文件哈希见 `manifest.json`，详细数据见 `verification-data.json`。
'''
(PREVIEW / 'verification.md').write_text(report, encoding='utf-8')
brief['stage'] = 'preview_delivered'
write(ROOT / 'brief.json', brief)
assets = [p for p in ROOT.rglob('*') if p.is_file() and 'cache' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p != PREVIEW / 'manifest.json']
write(PREVIEW / 'manifest.json', {
    'version': timeline['version'], 'approval_status': 'pending', 'sample_sha256': digest,
    'timeline_sha256': sha(ROOT / 'timeline.json'), 'repository_dependencies': brief['sources'],
    'files': [{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(assets)],
})
print(json.dumps({'version': timeline['version'], 'sample_sha256': digest, 'files': len(assets), 'approval_status': 'pending'}, ensure_ascii=False))
