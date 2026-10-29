"""Record the v5 revision separately; do not inherit v4 approval."""
from pathlib import Path
import hashlib,json
from timeline import load_plan,write_json
ROOT=Path(__file__).resolve().parent.parent;REPO=ROOT.parents[1]
P=load_plan(ROOT/'plan.json')
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prior=read(ROOT.parent/'2026-10-29-v4/brief.json')
audit=read(ROOT/'cache/capture-audit.json')
media=read(ROOT/'preview/media-verification.json')
playback=read(ROOT/'preview/playback-verification.json')
assert audit['planSha256']==media['planSha256']==playback['planSha256']==P['planSha256']
sources=[{'path':str(p.relative_to(REPO)).replace('\\','/'),'sha256':sha(p)} for p in sorted((ROOT/'source').glob('*')) if p.is_file()]
for path in ['src/deep_research/skills/product-comparison.md','docs/skill-evolution.md','README.md','frontend/src/data/demo.ts','frontend/src/data/mock.ts']:
 sources.append({'path':path,'sha256':sha(REPO/path)})
write_json(ROOT/'brief.json',{
 'version':'2026-10-29-v5','state':'pending','date':'2026-10-29','timezone':'Asia/Shanghai','planSha256':P['planSha256'],
 'request':'前端展示到 Agent 优化的转场突兀，首次了解项目的观众不知道在讲什么。',
 'product':prior['product'],'tagline':prior['tagline'],'scenario':prior['scenario'],
 'audience':'第一次了解项目的观众。先建立研究方法概念，再解释评估和修订的因果。',
 'revision':{'parentVersion':'2026-10-29-v4','durationBefore':42,'durationAfter':50,'changes':['Skills 选择镜头先解释 Skill = 研究方法','报告画面连续缩入，旁边出现前面选择的产品对比 Skill','同一方法卡保持位置，先解释评估怎样发现不足，再接诊断','后续标题改用新观众能理解的语言；最后回到新研究使用新方法'],'approval':'本版新增镜头和时长尚未批准，不继承 v4 批准'},
 'bridgeFacts':[
  {'copy':'Skill 把研究经验写成可重复使用的步骤','source':'README.md / Skills 渐进式披露；src/deep_research/skills/product-comparison.md'},
  {'copy':['优先查哪些来源','怎样组织检索','何时停止，如何引用'],'source':'src/deep_research/skills/product-comparison.md / 信息源优先级、查询模式、停止判据、引用规范','treatment':'忠实概括，不伪造候选修订正文'},
  {'copy':['要求是否覆盖完整？','引用是否有证据支持？'],'source':'docs/skill-evolution.md / coverage、citation grounding、source support','treatment':'评估问题示意，无打分或失败判决；没有宣称片中报告已被评估'},
  {'copy':'问题来自方法时才修订；验证通过、显式采纳后用于新研究','source':'docs/skill-evolution.md / 诊断归因、最终验证、晋升与重启','treatment':'保留操作者审阅；不称系统自动改写生产方法'},
 ],
 'evolution':prior['evolution'],
 'coverage':[
 {'item':'产品全貌','decision':'show','shotIds':['question'],'evidence':'frame-0045.png','reason':'保留原完整工作台'},
 {'item':'关键配置','decision':'show','shotIds':['skills'],'evidence':'context.mp4、frame-0150.png、frame-0210.png','reason':'原生菜单与选中结果；增强方法概念解释，不展开额外模型配置'},
 {'item':'核心操作','decision':'show','shotIds':['parallel','inspect','method','feedback','diagnose','candidate','validate'],'evidence':'context.mp4、bridge.mp4 与完整关键帧','reason':'保留原生流程；新增方法解释和评估动机；机制图解与原 UI 区分'},
 {'item':'结果','decision':'show','shotIds':['report','release','brand'],'evidence':'frame-0435.png、frame-1365.png、frame-1455.png','reason':'原合成报告与采纳决策；无来源原文，未增加引用操作'},
 ],
 'layout':{'measuredNativeWindow':audit['layouts'][0]['bridgeWindow'],'nativeViewport':audit['layouts'][0]['nativeLayout'],'bridgeFinalReportWidth':450,'sharedMethodCard':{'x':1171,'y':410,'width':574,'height':400},'continuity':'使用同一实时原生 iframe，在测得的窗口边界连续缩放；没有切换为旧截图'},
 'spec':{'video':P['video'],'audio':P['audio'],'previewClips':P['previewClips'],'recommendation':'50 秒，新增 8 秒为首次观看者补齐概念与动机，不加速既有讲解。预览无声。'},
 'restrictions':{'modelCalls':0,'searchCalls':0,'realUserData':False,'publication':False,'commitsCreated':False},'sources':sources,
})
results='\n'.join(f"- `{x['clip']}`：{x['duration']:g} 秒，完整播放结束；浏览器呈现回调 {len(x['framesSeen'])} 次，掉帧计数 {x['quality']['dropped']}。" for x in playback['results'])
(ROOT/'preview/verification.md').write_text(f'''# v5 修订预览验证

计划标识：`{P['planSha256']}`。50 秒 / 1500 帧方案，状态为待确认；本版没有制作正式音轨或完整 MP4。

- 18 张分镜关键帧、共 {len(audit['manifest'])} 张状态与转场检查帧实际渲染；原生 Skills 菜单、选择、节点和执行记录 4 次回调检查通过。
- 标题与时间轴精确匹配；输入框和报告实际 DOM 与项目合成数据逐字一致。字体、文字溢出和披露检查通过。
- 转场起点原生窗口位置 570×164、尺寸 1272×814，与前一镜一致，随后连续缩至宽 450；同一 iframe 和报告内容保留。
- 方法卡在 18.5 秒和 23.5 秒实测边界一致。编码后同一区域像素差异均值 {media['sameSkillCardAcrossScenes']['mean']:.6f}，验证同一方法贯穿两镜。
- 编码后报告缩放局部运动检查、原生图谱连续运动和报告完成后停止均通过；未用静态图替代动效小样。
- 新页面非顺序定位 7 帧，文本、节点、连线、报告位置和方法卡边界一致。
- 小样分别为 10.5 秒 / 315 帧、16 秒 / 480 帧，H.264、yuv420p、1920×1080、30 fps；完整解码和时间戳连续性通过。

{results}

目视检查：完整分镜总览、方法与反馈完整画面、转场中间帧、编码后方法与诊断画面。已修正长标题的不自然换行。数值及程序播放不替代逐帧人工全片观看；本阶段无声，主观听音不适用。

内容检查：新增问题是评估标准的说明，没有把演示报告判为失败，没有虚构修订或效果提升。保留“合成演示 · 流程已压缩”和“机制示意 · 非实验结果”。页面错误与外部／后端请求均为 0。
''',encoding='utf-8')
status_path=ROOT.parent/'status.json';status=read(status_path)
entry={'id':ROOT.name,'state':'pending','planSha256':P['planSha256'],'approval':None,'changes':['Skill 选择先解释研究方法','新增 8 秒报告→方法→评估因果衔接','总长建议 50 秒'],'coverage':f'{ROOT.name}/brief.json','preview':{'page':f'{ROOT.name}/preview/index.html','sheet':f'{ROOT.name}/preview/storyboard-overview.png','verification':f'{ROOT.name}/preview/verification.md','clips':[{'label':'报告到方法优化 · 16 秒','path':f'{ROOT.name}/preview/bridge.mp4'},{'label':'Skill 概念铺垫 · 10.5 秒','path':f'{ROOT.name}/preview/context.mp4'}]}}
status['currentVersion']=ROOT.name;status['currentFinalVersion']='2026-10-29-v4';status['versions']=[entry]+[v for v in status['versions'] if v['id']!=ROOT.name]
write_json(status_path,status)
(ROOT.parent/'index.html').write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={ROOT.name}/preview/index.html"><title>当前修订预览</title><p><a href="{ROOT.name}/preview/index.html">v5 衔接预览</a></p><p><a href="2026-10-29-v4/final/index.html">v4 现有成片</a></p></html>',encoding='utf-8')
write_json(ROOT/'preview/manifest.json',{'planSha256':P['planSha256'],'files':[{'path':p.name,'sha256':sha(p)} for p in sorted((ROOT/'preview').iterdir()) if p.is_file() and p.name!='manifest.json']})
print('v5 preview recorded; v4 final and README video retained.')
