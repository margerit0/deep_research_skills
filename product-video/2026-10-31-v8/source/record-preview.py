"""Record the pending v8 preview. The current entry, README and v7 stay as they are until v8 is complete."""
from pathlib import Path
import hashlib,json
from timeline import load_plan,read_json,write_json
ROOT=Path(__file__).resolve().parent.parent;REPO=ROOT.parents[1];PRE=ROOT/'preview'
P=load_plan(ROOT/'plan.json')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
revision=read_json(ROOT/'source/revision.json')
parent_dir=ROOT.parent/revision['parentVersion']
parent_brief=read_json(parent_dir/'brief.json')
audit=read_json(ROOT/'cache/capture-audit.json');media=read_json(PRE/'media-verification.json');play=read_json(PRE/'playback-verification.json');guards=read_json(PRE/'guard-verification.json');parent=read_json(PRE/'parent-comparison.json')
assert all(x['planSha256']==P['planSha256'] for x in [audit,media,play,guards,parent])
# Older versions keep their exact bytes, local caches included.
baseline=read_json(ROOT/'cache/baseline-hashes.json')
older={p.relative_to(ROOT.parent).as_posix() for d in ROOT.parent.iterdir() if d.is_dir() and d.name<ROOT.name for p in d.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
assert older==set(baseline) and all(sha(ROOT.parent/path)==digest for path,digest in baseline.items()),'An older version changed'
texts=read_json(ROOT/'cache/source-texts.json')
shots={s['id']:s for s in P['shots']}
chapter=shots['chapter-card']
framing=media['reportFraming']
clip=media['media']['clip']
brief={**{k:v for k,v in parent_brief.items() if k!='finalDelivery'},
 'version':ROOT.name,'state':'pending','date':'2026-10-31','planSha256':P['planSha256'],'request':revision['request'],
 'revision':{'parentVersion':revision['parentVersion'],'durationBefore':parent_brief['spec']['video']['durationSeconds'],'durationAfter':P['video']['durationSeconds'],'findings':revision['findings'],'copyProposal':revision['copyProposal'],'copyKept':revision['copyKept'],'attention':revision['attention'],'changes':revision['changes'],'unchanged':revision['unchanged'],'approval':None},
 'spec':{'video':P['video'],'audio':P['audio'],'previewClips':P['previewClips'],'recommendation':f"{P['video']['durationSeconds']:g} 秒，与 v7 相同；镜头顺序和时长不变，配乐沿用 v7。"},
 'restrictions':{**parent_brief['restrictions'],'commitsCreated':False},
 'chapterCard':{**parent_brief['chapterCard'],'copy':chapter['data'],'startSeconds':chapter['startSeconds'],'durationSeconds':chapter['durationSeconds']},
 'sources':[{'path':p.relative_to(REPO).as_posix(),'sha256':sha(p)} for p in sorted((ROOT/'source').glob('*')) if p.is_file()]}
brief['scenario']={**parent_brief['scenario'],'report':texts['demoReport'],'limitation':'合成报告没有编号引用或真实来源原文，卡片显示「暂无来源」；不新增引用操作，也不出现引用角标、折叠和来源列表。'}
brief['layout']={**parent_brief['layout'],'nativeViewport':audit['layouts'][0]['nativeLayout'],'reportCard':{'framing':framing,'viewport':{'width':1270,'height':766},'stableFrames':media['rawIdenticalHolds']['report']}}
evidence={'产品全貌':'preview/frame-0045.png','关键配置':'preview/frame-0150.png、preview/frame-0210.png','核心操作':'preview/frame-0285.png、preview/frame-0375.png、preview/frame-0795.png、preview/frame-1170.png','结果':'preview/frame-0435.png、preview/frame-1455.png、preview/frame-1545.png'}
reason={'产品全貌':'沿用 v7：完整工作台开场','关键配置':'沿用 v7：原生菜单与选中结果','核心操作':'沿用 v7：原生流程、方法解释与优化机制；报告缩略图同步为新卡片','结果':'报告改为新版卡片；无来源，未增加引用操作；采纳决策与品牌收尾沿用 v7'}
brief['coverage']=[{**c,'evidence':evidence[c['item']],'reason':reason[c['item']]} for c in parent_brief['coverage']]
write_json(ROOT/'brief.json',brief)
playback=play['results'][0]
ranges='、'.join(f'{a}–{b-1}' for a,b in parent['changedRanges'])
windows='、'.join(f'{a}–{b-1}' for a,b in parent['intendedWindows'])
(PRE/'verification.md').write_text(f'''# v8 报告卡片同步预览验证

计划标识：`{P['planSha256']}`。全片 {P['video']['durationSeconds']:g} 秒 / {P['video']['totalFrames']} 帧不变；本阶段只有无声小样和关键帧，没有完整视频或配乐。

## 数值与程序验证

- 全片 {P['video']['totalFrames']} 帧逐帧通过校验：披露文案、无文本溢出、无替换字符；375 帧起都是报告卡片，没有回退态或原始 #，没有引用、来源、折叠控件；390 帧起标题、状态、三个编号章节、下一步正文和免责声明与 `demoReport` 及组件源码一致。
- 4 次原生点击命中与回调检查通过；{len(audit['random'])} 帧在新页面乱序定位，文本、节点、连线和报告结构一致；无外部或 API 请求。
- 反向用例：{len(guards['rejected'])} 种错误状态（回退态、残留 #、缺少免责声明、卡片出画、输入框压住卡片、窗口压住顶栏等）全部被 `validate()` 拒绝；屏蔽卡片代码块后渲染直接失败（`{guards['blockedChunk']['message']}`），不会拍到回退态。
- 冷启动：清空 Vite 缓存并重启服务后，同一套校验通过，报告机位不变，没有拍到回退态。
- 报告机位：卡片在 1270×766 镜头内位于 x {framing['card']['x']:.0f}–{framing['card']['right']:.0f}、y {framing['card']['y']:.0f}–{framing['card']['bottom']:.0f}，底部说明止于 y {framing['foot']['bottom']:.0f}，输入框上沿 y {framing['composerTop']:.0f}（画面外），放大 {framing['scale']:.2f} 倍。
- 稳定性：第 {media['rawIdenticalHolds']['report'][0]}–{media['rawIdenticalHolds']['report'][1]-1} 帧（报告）、第 {media['rawIdenticalHolds']['chapter'][0]}–{media['rawIdenticalHolds']['chapter'][1]-1} 帧（章节卡）、第 {media['rawIdenticalHolds']['method'][0]}–{media['rawIdenticalHolds']['method'][1]-1} 帧（方法卡）逐帧哈希相同；解码后报告稳定帧均值差 {media['reportHoldStopped']['mean']:.6f}。
- 与 v7 `cache/final/frames` 逐帧比较（版本标记遮盖，任一通道差值超过 8/255 记为变化）：有差异的帧 {ranges}，共 {parent['changedFrames']} 帧，全部在报告窗口 {windows} 内；窗口外 0 帧。其余 {parent['unchangedFrames']} 帧的最大通道差值为 {parent['peakDifferenceInUnchangedFrames']}/255。
- 小样 `{clip['id']}.mp4`：{clip['durationSeconds']:g} 秒 / {clip['frameCount']} 帧，1920×1080、30 fps、H.264、yuv420p，完整解码与时间戳连续性通过；小样与全片审计是两次独立渲染，{media['clipFramesIdenticalToAuditRender']}/{clip['frameCount']} 帧哈希相同，其余帧任一通道差值不超过 {media['renderNoisePeak']}/255，属于光栅噪声。
- 运行中的动效：并行研究第 285 与 295 帧的图谱局部差异 {media['nativeMotion']['changedPixels']} 像素；镜头移动与报告缩入都有连续变化。
- v7 及更早版本的 {len(baseline)} 个文件（含本地缓存）与开工前的哈希逐个相同。
- 程序播放：{playback['duration']:g} 秒；呈现回调 {len(playback['framesSeen'])} 次；掉帧 {playback['quality']['dropped']}；完整播放结束。

## 目视检查

查看了 v7 与 v8 对照图、转场逐帧图、完整分镜，以及报告镜头的 1:1 帧：卡片内容完整，无缺字或裁切，章节卡进出场和报告缩入没有压住文字。程序播放只证明小样能完整解码播放，没有人工观看视频。

## 未完成

- 完整视频、配乐核对与听感验收都要等你确认预览后进行；预览无音轨，主观听音不适用。
- v7 的批准和听感验收不适用于 v8。

全程保留「合成演示 · 流程已压缩」。未调用模型、搜索或外部服务。
''',encoding='utf-8')
(PRE/'reproduce.md').write_text(f'''# v8 预览复现

在仓库根目录运行，沿用 frontend/node_modules、Node、Python + Pillow、Chrome、FFmpeg/ffprobe 与 Microsoft YaHei，没有新增依赖。依赖原仓库组件、样式和合成数据。与 v7 比较需要本地的 `product-video/{revision['parentVersion']}/cache/final/frames`。

```powershell
python product-video/{ROOT.name}/source/build.py
node product-video/{ROOT.name}/source/serve.mjs
```

另开终端：

```powershell
node product-video/{ROOT.name}/source/capture.mjs
node product-video/{ROOT.name}/source/capture.mjs --clips
node product-video/{ROOT.name}/source/capture.mjs --audit
node product-video/{ROOT.name}/source/check-guards.mjs
python product-video/{ROOT.name}/source/package-preview.py
node product-video/{ROOT.name}/source/check-playback.mjs
python product-video/{ROOT.name}/source/record-preview.py
```

服务仅监听 127.0.0.1:5192；捕获脚本禁止外部及后端 API 请求。`CHROME_PATH` 可指定 Chrome。

`--audit` 只把全片渲染到 `cache/audit/` 用于和 v7 比较，不生成视频，也不需要批准；`--final` 必须有绑定当前计划标识的 `approval.json`。`timeline.json` 改动后计划标识随之变化，需要重新确认。
''',encoding='utf-8')
status_path=ROOT.parent/'status.json';status=read_json(status_path)
entry={'id':ROOT.name,'state':'pending','planSha256':P['planSha256'],'approval':None,'changes':revision['changes'],'coverage':f'{ROOT.name}/brief.json','preview':{'page':f'{ROOT.name}/preview/index.html','sheet':f'{ROOT.name}/preview/storyboard-overview.png','verification':f'{ROOT.name}/preview/verification.md','clips':[{'label':f"报告片段 · {clip['durationSeconds']:g} 秒",'path':f"{ROOT.name}/preview/{clip['id']}.mp4"}]}}
status['versions']=[entry]+[v for v in status['versions'] if v['id']!=ROOT.name]
status['pendingVersion']=ROOT.name
write_json(status_path,status)
write_json(PRE/'manifest.json',{'planSha256':P['planSha256'],'files':[{'path':p.name,'sha256':sha(p)} for p in sorted(PRE.iterdir()) if p.is_file() and p.name!='manifest.json']})
print(json.dumps({'plan':P['planSha256'],'pending':ROOT.name,'current':status['currentVersion'],'published':status['publishedVersion']},ensure_ascii=False))
