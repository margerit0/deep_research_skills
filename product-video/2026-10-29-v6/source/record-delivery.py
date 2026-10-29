"""Record the chapter-card revision and update the current preview entry."""
from pathlib import Path
import hashlib,json
from timeline import load_plan,write_json
ROOT=Path(__file__).resolve().parent.parent;REPO=ROOT.parents[1]
P=load_plan(ROOT/'plan.json')
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prior=read(ROOT.parent/'2026-10-29-v5/brief.json')
audit=read(ROOT/'cache/capture-audit.json');media=read(ROOT/'preview/media-verification.json');play=read(ROOT/'preview/playback-verification.json')
assert all(x['planSha256']==P['planSha256'] for x in [audit,media,play])
chapter=next(s for s in P['shots'] if s['id']=='chapter-card')
brief={**prior,'version':ROOT.name,'planSha256':P['planSha256'],'state':'pending','request':'总体不错，在前端演示与优化介绍之间增加画面，告知观众接下来介绍 Agent 自动进化。',
 'revision':{'parentVersion':'2026-10-29-v5','durationBefore':50,'durationAfter':53,'changes':['16–19 秒新增全屏章节卡','主题：Agent 自动进化；副标题：评估驱动的 Skill 持续优化','保留上一版报告、方法与评估因果衔接'],'approval':'用户认可总体方向并要求新增章节卡；本次新增画面已制作预览，尚未据此生成完整配乐视频。'},
 'chapterCard':{'copy':chapter['data'],'startSeconds':chapter['startSeconds'],'durationSeconds':chapter['durationSeconds'],'scope':'标题沿用用户提出的介绍主题；副标题和流程说明将具体能力限定为 Skill 优化，并保留人工采纳。未新增无人审批晋升能力。'},
 'spec':{'video':P['video'],'audio':P['audio'],'previewClips':P['previewClips'],'recommendation':'53 秒；章节卡 3 秒，淡入淡出各 0.5 秒、稳定阅读 2 秒；原 50 秒内容保留。'},
 'sources':[{'path':str(p.relative_to(REPO)).replace('\\','/'),'sha256':sha(p)} for p in sorted((ROOT/'source').glob('*')) if p.is_file()]}
for c in brief['coverage']:
 if c['item']=='核心操作':c['shotIds']=['chapter-card',*c['shotIds']]
 if c['item']=='结果':c['evidence']='frame-0435.png、frame-1455.png、frame-1545.png'
write_json(ROOT/'brief.json',brief)
play_lines='\n'.join(f"- {x['clip']}：{x['duration']:g} 秒；呈现回调 {len(x['framesSeen'])} 次；掉帧 {x['quality']['dropped']}；完整播放结束。" for x in play['results'])
(ROOT/'preview/verification.md').write_text(f'''# v6 章节卡预览验证

计划标识：`{P['planSha256']}`。全片 53 秒 / 1590 帧方案；本阶段仅制作无声小样与关键帧。

- 原生组件重新渲染，4 次原生点击命中和回调检查通过；标题、输入值和原始合成报告校验通过。
- 新章节卡位于 16–19 秒；淡入、淡出各 0.5 秒，稳定阅读 2 秒。标题与副标题从同一时间轴派生并逐帧核对。
- 共 {len(P['keyframes'])} 张分镜关键帧与 {len(audit['manifest'])} 张状态检查帧；无中文替换字符、文本溢出或披露缺失。
- 8 帧在新页面非顺序定位，文本、节点、连线、窗口与卡片边界一致。
- 编码后章节稳定帧均值差 {media['chapterStableHold']['mean']:.6f}；原生运行运动、完成后停止、报告连续缩入均通过。
- 跨镜头方法卡原始像素保持一致，编码后亮度 PSNR 检查通过；新增章节结束后继续同一份报告与方法。
- 两段小样为 10.5 秒 / 315 帧、19 秒 / 570 帧；均为 1920×1080、30 fps、H.264、yuv420p，完整解码和时间戳连续性通过。

{play_lines}

目视检查章节卡完整画面、关键帧总览和解码后的章节进入／退出帧；未发现缺字或越界。程序播放不代替人工逐帧全片观看；预览无音轨，主观听音不适用。

全程保留“合成演示 · 流程已压缩”，新章节明确“评估驱动的 Skill 持续优化”及“人工采纳”，没有虚构无人审批的生产晋升、实验分数或提升结论。未调用模型、搜索或外部服务。
''',encoding='utf-8')
status_path=ROOT.parent/'status.json';s=read(status_path)
s['currentVersion']=ROOT.name
for entry in s['versions']:
 if entry['id']=='2026-10-29-v5':entry['supersededBy']=ROOT.name
s['versions']=[{'id':ROOT.name,'state':'pending','planSha256':P['planSha256'],'approval':None,'changes':['新增 3 秒 Agent 自动进化章节卡','完整方案 53 秒，保留 v5 因果衔接'],'coverage':f'{ROOT.name}/brief.json','preview':{'page':f'{ROOT.name}/preview/index.html','sheet':f'{ROOT.name}/preview/storyboard-overview.png','verification':f'{ROOT.name}/preview/verification.md','clips':[{'label':'章节卡与衔接 · 19 秒','path':f'{ROOT.name}/preview/bridge.mp4'},{'label':'研究方法铺垫 · 10.5 秒','path':f'{ROOT.name}/preview/context.mp4'}]}}]+[v for v in s['versions'] if v['id']!=ROOT.name]
write_json(status_path,s)
old_page=ROOT.parent/'2026-10-29-v5/preview/index.html'
old_text=old_page.read_text(encoding='utf-8')
old_text=old_text.replace('v5 · 修订预览待确认','v5 · 历史预览')
if 'v6-chapter-current' not in old_text:
 old_text=old_text.replace('<main>','<main><p id="v6-chapter-current">本页已归档，<a href="../../2026-10-29-v6/preview/index.html">查看新增章节卡的 v6 当前预览</a>。</p>',1)
old_page.write_text(old_text,encoding='utf-8')
old_manifest=old_page.parent/'manifest.json'
if old_manifest.exists():
 old=read(old_manifest)
 for entry in old['files']:
  if entry['path']=='index.html':entry['sha256']=sha(old_page)
 write_json(old_manifest,old)
(ROOT.parent/'index.html').write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={ROOT.name}/preview/index.html"><title>当前视频修订预览</title><p><a href="{ROOT.name}/preview/index.html">v6 章节卡预览</a></p><p><a href="2026-10-29-v4/final/index.html">v4 已完成成片</a></p></html>',encoding='utf-8')
write_json(ROOT/'preview/manifest.json',{'planSha256':P['planSha256'],'files':[{'path':p.name,'sha256':sha(p)} for p in sorted((ROOT/'preview').iterdir()) if p.is_file() and p.name!='manifest.json']})
print('v6 recorded. Prior previews and v4 movie retained.')
