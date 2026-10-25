"""Bind preview evidence to this revision's exact MP4 and editable sources."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
PREVIEW, CACHE = ROOT/'preview', ROOT/'cache'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def write(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

t = read(ROOT/'timeline.json')
brief = read(ROOT/'brief.json')
capture = read(CACHE/'capture-audit.json')
media = read(CACHE/'media-audit.json')
playback = read(CACHE/'playback-audit.json')
manual = read(CACHE/'manual-review.json')
layout = read(CACHE/'native-layout.json')
digest = sha(PREVIEW/'motion-sample.mp4')
sample_count = t['motion_sample']['last_frame']-t['motion_sample']['first_frame']+1
assert t['approval']['status'] == 'pending'
assert digest == media['sample_sha256'] == playback['sample_sha256'] == manual['sample_sha256']
assert sha(PREVIEW/'storyboard-overview.png') == manual['storyboard_sha256']
assert capture['allFramesChecked'] == t['frame_count'] and not capture['errors'] and not capture['blocked']
assert all(item['equal'] for item in capture['randomAccess'])
assert len(capture['clicks']) == 4 and all(item['hit'] and item['visible'] and item['insideViewport'] and item['callbackMatches'] for item in capture['clicks'])
assert all(item['insideViewport'] and item['opacity'] == 1 for item in layout['nativeElements'])
assert playback['ended'] and playback['duration'] == sample_count/t['fps'] and playback['totalVideoFrames'] == sample_count
assert playback['droppedDuringPlayback'] == 0 and playback['frameCallbackGaps'] == 0
assert not list((ROOT/'final').glob('*.mp4'))
verification = {'version':t['version'],'stage':'preview','approval':t['approval'],'sample_sha256':digest,'sample':media,'playback':playback,'native_opening_layout':layout,'capture':{key:capture[key] for key in ['allFramesChecked','clicks','graph','randomAccess','errors','blocked','cameras']},'visual_review':manual}
write(PREVIEW/'verification-data.json',verification)

report = f'''# 预览检查记录 · v3

按用户要求将完整 UI 的停留改为 2 秒，并在开始任务前展示 Skills 选择。本版方案为 {t['duration_seconds']} 秒、{t['frame_count']} 帧、{t['bpm']} BPM / {t['beat_count']} 拍。小样为前 {sample_count/t['fps']:g} 秒、{sample_count} 帧、1920×1080、30 fps、H.264，无音轨。

小样 SHA-256：`{digest}`。

## 时间与真实交互

| 时间 | 画面或动作 |
| --- | --- |
| 0–2 秒 | 完整浏览器画面，所有主区域均在视口内 |
| 2–3 秒 | 连续聚焦同一个输入框 |
| 3–4 秒 | 展示仓库原文问题，Skills 为自动选择 |
| 4 秒 | 点击原生 Skills 触发器 |
| 4–6 秒 | 显示自动选择、产品对比、学术研究、事件时间线、人物调研 |
| 6 秒 | 选择产品对比，菜单关闭 |
| 6–8 秒 | 显示 Skills · 产品对比及原生说明 |
| 8–11 秒 | 简报、派发和三路研究自动推进 |
| 11 / 11.5 秒 | 点击商业节点 / 执行记录页签 |
| 13–16 秒 | 展示报告，其中稳定阅读 2.5 秒 |
| 16–18 秒 | 品牌收尾，其中静止 1 秒 |

Skills 菜单来自原生 `Picker.tsx`，选项和说明来自 `mock.ts / skills`，场景依据为 `demoScenes[2]`。原生菜单入场周期保持 130ms。没有复制制作一套功能面板，也没有添加新选项。

四次点击均在动作发生前测量真实目标和顶部命中元素，并实际触发组件回调。菜单选项在点击后立即关闭，因此在关闭前验证命中；选择回调为 `config.skill = product-comparison`，同时触发原生关闭回调。帧状态由同一时间轴确定，选择后的标签和说明逐帧核验。演示中发送按钮禁用，研究由合成事件推进，不虚构发送点击。

## 已执行检查

- 全部 {t['frame_count']} 帧检查披露标识、源文案、字体、完成状态和布局。第 0–59 帧相机、窗口尺寸保持全屏，构成完整 2 秒。
- 初始容器为 1920×1080，包含 48px 容器栏与 1920×1032 原生工作台。侧栏、标题、输入框及图谱均可见并位于视口内。
- 菜单开放期间，所有选项标签匹配仓库原文，整个菜单位于取景窗口内。选择前状态为自动选择，选择后为产品对比；菜单关闭行为符合原组件。
- {len(capture['randomAccess'])} 个新页面非顺序定位的语义、相机、路径与动效状态一致，像素误差位于既有字体抗锯齿容差内。
- 7 个研究节点与 10 条有向连线按原组件逐一核验，保留返回回路。所有离散动作起点在 15 帧的整拍网格。
- 同一运行状态的解码帧 {t['verification']['motion_pair']}，图谱局部有 {media['decoded_running_motion']['pixels_over_8']} 个像素变化超过 8/255；完成后无运行提示，稳定报告帧的平均通道差为 {media['decoded_stable_report']['mean_absolute_channel_error']:.5f}/255。
- 小样实际解码 {sample_count} 帧，时间戳连续。以 1 倍速播放：呈现掉帧 0、回调缺口 0、播放错误 0。播放字节的 SHA-256 与本文件一致；本次使用播放器的原生文件播放回退路径。
- 外部请求、后端请求及页面错误均为 0；没有真实模型调用或真实用户数据。

## 目视检查与边界

{manual['result']}

检查方式：{manual['method']}

八张关键帧按新增时长重新安排，覆盖完整 UI、输入框、菜单、选中结果、执行、检查器、报告和品牌。总览来自本版实渲 PNG，动效核查来自同一个 MP4 的解码抽帧。

本阶段是无声预览；完整成片、正式配乐及音画同步验收需在 v3 确认后进行。旧版本保留，本版批准状态为 pending，没有沿用旧批准。

源码与文件哈希见 `manifest.json`；复现方法见 `reproduce.md`；详细数据见 `verification-data.json`。
'''
(PREVIEW/'verification.md').write_text(report,encoding='utf-8')
brief['stage'] = 'preview_delivered'
write(ROOT/'brief.json',brief)
assets = [p for p in ROOT.rglob('*') if p.is_file() and 'cache' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p != PREVIEW/'manifest.json']
write(PREVIEW/'manifest.json',{'version':t['version'],'approval_status':'pending','sample_sha256':digest,'timeline_sha256':sha(ROOT/'timeline.json'),'repository_dependencies':brief['sources'],'files':[{'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(assets)]})
print(json.dumps({'version':t['version'],'sample_sha256':digest,'files':len(assets),'approval_status':'pending'},ensure_ascii=False))
