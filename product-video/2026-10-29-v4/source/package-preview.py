"""Encode preview excerpts, verify decoded motion, and build the review page."""
from pathlib import Path
import hashlib
import html
import json
import math
import subprocess
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat
from timeline import load_plan, write_json

ROOT=Path(__file__).resolve().parent.parent
REPO=ROOT.parents[1]
P=load_plan(ROOT/'plan.json')
FPS=float(P['video']['fps'])
PRE=ROOT/'preview'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(args):
    result=subprocess.run([str(x) for x in args],capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr.decode('utf-8')[-5000:])
    return result.stdout.decode('utf-8')
def font(size,bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',size)
def delta(a,b,box=None):
    x,y=Image.open(a).convert('RGB'),Image.open(b).convert('RGB')
    if box:x,y=x.crop(box),y.crop(box)
    diff=ImageChops.difference(x,y)
    return {'changedPixels':sum(max(p)>8 for p in diff.get_flattened_data()),'mean':sum(ImageStat.Stat(diff).mean)/3}

media=[]
for clip in P['previewClips']:
    folder=ROOT/'cache'/clip['id']
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['planSha256']==P['planSha256']
    assert [x['frame'] for x in manifest['frames']]==list(range(clip['startFrame'],clip['endFrameExclusive']))
    assert not manifest['errors'] and not manifest['blocked']
    for entry in manifest['frames']:assert sha(folder/entry['file'])==entry['sha256']
    movie=PRE/f"{clip['id']}.mp4"
    command=['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(FPS),'-start_number',clip['startFrame'],'-i',folder/'frame-%04d.png','-frames:v',clip['frameCount'],'-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-r',str(FPS),'-movflags','+faststart',movie]
    run(command)
    probe=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]))
    stream=probe['streams'][0]
    assert len(probe['streams'])==1
    assert (stream['codec_name'],stream['width'],stream['height'],stream['avg_frame_rate'],int(stream['nb_read_frames']))==('h264',1920,1080,'30/1',clip['frameCount'])
    assert abs(float(stream['duration'])-clip['durationSeconds'])<.001
    frames=json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',movie]))['frames']
    pts=[float(f['best_effort_timestamp_time']) for f in frames]
    assert len(pts)==clip['frameCount'] and all(abs(b-a-1/FPS)<.000002 for a,b in zip(pts,pts[1:]))
    chosen=[285,295,420,430] if clip['id']=='workflow' else [650,655,945,1125]
    for f in chosen:
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf',rf'select=eq(n\,{f-clip["startFrame"]})','-fps_mode','vfr','-frames:v','1',ROOT/'cache'/f'decoded-{f}.png'])
    media.append({'clip':clip,'sha256':sha(movie),'stream':stream,'constantPTS':True,'encodingCommand':[str(x) for x in command]})
motion=delta(ROOT/'cache/decoded-285.png',ROOT/'cache/decoded-295.png',box=(950,350,1460,940))
stopped=delta(ROOT/'cache/decoded-420.png',ROOT/'cache/decoded-430.png')
new_motion=delta(ROOT/'cache/decoded-650.png',ROOT/'cache/decoded-655.png')
assert motion['changedPixels']>150 and stopped['mean']<.2 and new_motion['changedPixels']>500
write_json(PRE/'media-verification.json',{'planSha256':P['planSha256'],'media':media,'decodedNativeMotion':motion,'decodedStoppedState':stopped,'decodedNewAnimation':new_motion,'audio':'Not produced at preview stage'})

keys=P['keyframes']
sheet=Image.new('RGB',(1660,150+math.ceil(len(keys)/2)*540),'#f5f5f7')
draw=ImageDraw.Draw(sheet)
draw.text((40,24),f"星图工作台 · {P['video']['durationSeconds']:g} 秒方案 · v4 待确认",font=font(33,True),fill='#202126')
draw.text((40,80),'完整工作台 → 选择 Skills → 并行研究 → 报告 → 评估驱动的 Skill 持续优化',font=font(21),fill='#6b7280')
for i,k in enumerate(keys):
    x,y=40+(i%2)*810,140+(i//2)*540
    shot=next(s for s in P['shots'] if s['id']==k['shot'])
    draw.text((x,y),f"{k['frame']/FPS:g}s · {k['label']}",font=font(21,True),fill='#273346')
    pic=Image.open(PRE/f"frame-{k['frame']:04d}.png").convert('RGB').resize((770,433),Image.Resampling.LANCZOS)
    sheet.paste(pic,(x,y+37))
    transition=shot['data']['transition']
    for n,line in enumerate(textwrap.wrap(transition,40)):
        draw.text((x,y+477+n*22),line,font=font(15),fill='#747b87')
sheet.save(PRE/'storyboard-overview.png')

detail=Image.new('RGB',(1600,1020),'#f5f5f7');d=ImageDraw.Draw(detail)
d.text((32,19),'新增动画 · 评估驱动的 Skill 持续优化',font=font(29,True),fill='#202126')
for i,(f,label) in enumerate([(585,'01 失败证据与诊断'),(735,'02 生成候选并保存差异'),(945,'03 冻结后独立验证'),(1125,'04 人工晋升与回退')]):
    x,y=20+(i%2)*800,76+(i//2)*470
    d.text((x+10,y),label,font=font(22,True),fill='#315e8e')
    detail.paste(Image.open(PRE/f'frame-{f:04d}.png').resize((760,428),Image.Resampling.LANCZOS),(x,y+34))
detail.save(PRE/'feature-overview.png')

rows=''.join(f'<tr><td>{s["startSeconds"]:g}–{s["startSeconds"]+s["durationSeconds"]:g} 秒</td><td>{html.escape(s["label"])}</td><td>{html.escape(s["data"]["focus"])}</td></tr>' for s in P['shots'])
cards=''.join(f'<a href="frame-{k["frame"]:04d}.png"><img src="frame-{k["frame"]:04d}.png"><span>{k["frame"]/FPS:g} 秒 · {html.escape(k["label"])}</span></a>' for k in keys)
holds=''.join(f'<li>{h["startFrame"]/FPS:g}–{h["endFrameExclusive"]/FPS:g} 秒 · {html.escape(h["label"])}</li>' for h in P['holds'])
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>星图工作台 · v4 动画预览</title><style>body{{font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif;color:#252b36;background:#f5f5f7;margin:0}}main{{max-width:1180px;margin:auto;padding:54px 30px}}h1{{font-size:40px;line-height:1.35}}h2{{font-size:25px;margin-top:46px}}p{{color:#687181}}a{{color:#1465ad}}.badge{{background:#e7edf8;color:#37577c;padding:7px 13px;border-radius:6px;display:inline-block}}video{{display:block;width:100%;border:1px solid #dce0e6;border-radius:12px;background:white}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:13px;text-align:left;border-bottom:1px solid #e2e5eb}}.cards{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.cards a{{background:white;border-radius:8px;overflow:hidden;text-decoration:none}}.cards img{{width:100%;display:block}}.cards span{{display:block;padding:12px}}.links{{display:flex;gap:24px;flex-wrap:wrap}}@media(max-width:700px){{.cards{{grid-template-columns:1fr}}h1{{font-size:30px}}}}</style><main><span class="badge">v4 · 等待本版预览确认</span><h1>研究方法，也能持续改进。</h1><p>建议总长 {P['video']['durationSeconds']:g} 秒 · 1920 × 1080 · 30 fps。保留前 16 秒产品演示，新增 23 秒机制动画，最后 3 秒品牌收尾。原发布版 v3 仍保留在 README。</p><h2>先看新增部分 · 23 秒无声小样</h2><video controls preload="metadata" poster="frame-0585.png" src="evolution.mp4"></video><p>证据汇聚 → 候选分支 → 配对比较与冻结 → 独立最终验证 → 报告、晋升与回退。此处是已实现机制的图解，不是工作台的新界面或实测实验结果。</p><h2>原生配置与运行 · 11 秒无声小样</h2><video controls preload="metadata" poster="frame-0150.png" src="workflow.mp4"></video><p>覆盖打开 Skills、选择产品对比、并行运行、节点检查器与完成后停止的状态。</p><div class="links"><a href="../source/index.html">打开可拖动的完整分镜（需本地服务）</a><a href="storyboard-overview.png">分镜总览</a><a href="verification.md">验证记录</a><a href="../brief.json">内容依据与覆盖表</a></div><h2>四项内容覆盖</h2><table><tr><th>内容</th><th>处理</th><th>依据</th></tr><tr><td>产品全貌</td><td>展示</td><td>0–2 秒完整工作台</td></tr><tr><td>关键配置</td><td>展示</td><td>4–8 秒原生 Skills 菜单与选中状态；模型选择不额外展开，沿用原内置模拟配置</td></tr><tr><td>核心操作</td><td>展示</td><td>8–13 秒并行研究与节点检查；16–39 秒优化机制动画</td></tr><tr><td>结果</td><td>展示</td><td>13–16 秒合成报告；33–39 秒默认报告、显式晋升／回退。原合成报告无引用原文，不新增引用操作</td></tr></table><h2>镜头与时长</h2><table><tr><th>时间</th><th>镜头</th><th>视觉焦点</th></tr>{rows}</table><h2>关键帧</h2><div class="cards">{cards}</div><details><summary>稳定阅读区间</summary><ul>{holds}</ul></details><p>合成演示 · 流程已压缩。首版优化能力仅支持 product-comparison，每个实验最多一轮改进、两个候选。尚未运行真实模型优化实验，暂无效果提升结论；评估对象是研究员 compressed_research，不能直接代表 final_report 质量。</p><p>本阶段仅制作预览；配乐与完整 MP4 将在本版内容、时长及镜头确认后制作。计划标识：{P['planSha256']}</p></main></html>'''
(PRE/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'videos':[m['clip']['id'] for m in media],'nativeMotion':motion,'stopped':stopped,'newMotion':new_motion},ensure_ascii=False))
