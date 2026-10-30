"""Package the report-card revision as a reviewable excerpt, compared with the parent film."""
from pathlib import Path
import hashlib,html,json,math,shutil,subprocess,textwrap
from PIL import Image,ImageDraw,ImageFont,ImageChops,ImageStat
from timeline import load_plan,read_json,write_json
from parent_compare import PARENT,PARENT_FRAMES,compare,report_windows
ROOT=Path(__file__).resolve().parent.parent
PRE=ROOT/'preview';CACHE=ROOT/'cache';DECODED=CACHE/'decoded'
PRE.mkdir(exist_ok=True);DECODED.mkdir(exist_ok=True)
P=load_plan(ROOT/'plan.json');FPS=float(P['video']['fps'])
revision=read_json(ROOT/'source/revision.json')
shots={s['id']:s for s in P['shots']}
at=lambda shot,seconds=0:shots[shot]['startFrame']+round(seconds*FPS)
hold=next(h for h in P['holds'] if h['shot']=='report')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
name=lambda f:f'frame-{f:04d}.png'
def run(args):
 r=subprocess.run([str(x) for x in args],capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.decode('utf-8')[-5000:])
 return r.stdout.decode('utf-8')
def font(size,bold=False):return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',size)
def delta(a,b,box=None):
 x,y=Image.open(a).convert('RGB'),Image.open(b).convert('RGB')
 if box:x,y=x.crop(box),y.crop(box)
 d=ImageChops.difference(x,y)
 return {'changedPixels':sum(max(p)>8 for p in d.get_flattened_data()),'mean':sum(ImageStat.Stat(d).mean)/3}

# The single excerpt: verified frames in, verified MP4 out.
clip=P['previewClips'][0];folder=CACHE/clip['id']
manifest=read_json(folder/'manifest.json')
assert manifest['planSha256']==P['planSha256'] and not manifest['errors'] and not manifest['blocked']
assert [f['frame'] for f in manifest['frames']]==list(range(clip['startFrame'],clip['endFrameExclusive']))
for f in manifest['frames']:assert sha(folder/f['file'])==f['sha256']
hashes={f['frame']:f['sha256'] for f in manifest['frames']}
movie=PRE/f"{clip['id']}.mp4"
command=['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(FPS),'-start_number',clip['startFrame'],'-i',folder/'frame-%04d.png','-frames:v',clip['frameCount'],'-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-r',str(FPS),'-movflags','+faststart',movie]
run(command)
stream=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',movie]))['streams'][0]
assert (stream['codec_name'],stream['width'],stream['height'],stream['avg_frame_rate'],int(stream['nb_read_frames']),stream['pix_fmt'])==('h264',1920,1080,'30/1',clip['frameCount'],'yuv420p')
assert abs(float(stream['duration'])-clip['durationSeconds'])<.001
pts=[float(f['best_effort_timestamp_time']) for f in json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',movie]))['frames']]
assert len(pts)==clip['frameCount'] and all(abs(b-a-1/FPS)<.000002 for a,b in zip(pts,pts[1:]))

# Numeric checks on frames decoded back from the MP4.
report,chapter,method,feedback=at('report'),at('chapter-card'),at('method'),at('feedback')
transition_frames=[report-1,report,report+3,report+6,report+9,report+12,hold['startFrame'],chapter-1,chapter+4,chapter+8,method-8,method-4,method,method+7,method+15,method+20,at('method',1),at('method',2),feedback,feedback+7,at('feedback',.5)]
picked=sorted({*transition_frames,report+5,report+10,hold['startFrame']+15,hold['startFrame']+25,hold['endFrameExclusive']-1,chapter+15,chapter+60,method+15,method+20})
assert all(clip['startFrame']<=f<clip['endFrameExclusive'] for f in picked)
for stale in DECODED.glob('*.png'):stale.unlink()
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf','select='+'+'.join(rf"eq(n\,{f-clip['startFrame']})" for f in picked),'-fps_mode','vfr',DECODED/'pick-%04d.png'])
for index,f in enumerate(picked,1):(DECODED/f'pick-{index:04d}.png').replace(DECODED/name(f))
decoded=lambda f:DECODED/name(f)
travel=delta(decoded(report+5),decoded(report+10))
stopped=delta(decoded(hold['startFrame']+15),decoded(hold['startFrame']+25))
hold_ends=delta(decoded(hold['startFrame']),decoded(hold['endFrameExclusive']-1))
chapter_hold=delta(decoded(chapter+15),decoded(chapter+60))
shrink=delta(decoded(method+15),decoded(method+20))
assert travel['changedPixels']>1000 and shrink['changedPixels']>1000
assert stopped['mean']<.2 and hold_ends['mean']<.2 and chapter_hold['mean']<.2
# The running state must still move on screen; its frames match the parent, so check them in the full render.
native_motion=delta(CACHE/'audit'/name(at('parallel',1.5)),CACHE/'audit'/name(at('parallel',1.5)+10),(950,350,1460,940))
assert native_motion['changedPixels']>150
stable=lambda a,b:len({hashes[f] for f in range(a,b)})==1
assert stable(report+14,hold['endFrameExclusive']),'Report hold is not frame-identical'
assert stable(chapter+15,chapter+75),'Chapter hold is not frame-identical'
method_hold=(at('method',2),feedback)
assert stable(*method_hold),'Method hold is not frame-identical'

# Report framing and the bridge window, measured frame by frame during capture.
audit=read_json(CACHE/'capture-audit.json')
assert audit['planSha256']==P['planSha256'] and not audit['errors'] and not audit['blocked']
layout=lambda f:next(s for s in audit['layouts'] if s['frame']==f)
framing=layout(hold['startFrame']+30)['reportFraming']
assert all(layout(f)['reportFraming']==framing for f in (hold['startFrame'],hold['startFrame']+15,hold['endFrameExclusive']-1))
assert all(abs(layout(method)['shell'][k]-layout(method)['bridgeWindow'][k])<.1 for k in ('x','y','width','height'))
assert abs(layout(at('method',2))['shell']['width']-450)<.1
assert all(s['report'] and s['report']['status'] for s in audit['layouts'] if s['frame']>=at('inspect',1.5))
writing=layout(at('inspect',1.5))
assert writing['report']['status']=='正在撰写' and writing['reportFraming']['card']['right']<0

# Whole-film comparison with the parent, from a separate unencoded render of every frame.
full=read_json(CACHE/'audit/manifest.json')
assert full['planSha256']==P['planSha256'] and not full['errors'] and not full['blocked'] and len(full['frames'])==P['video']['totalFrames']
parent=compare(CACHE/'audit',P)
assert parent['status']=='compared','Parent frames are required at the preview stage'
# Two renders from different start frames may differ by raster noise only.
same_render=sum(full['frames'][f]['sha256']==h for f,h in hashes.items())
peak=lambda a,b:max(high for _,high in ImageChops.difference(Image.open(a).convert('RGB'),Image.open(b).convert('RGB')).getextrema())
render_noise=max((peak(folder/name(f),CACHE/'audit'/name(f)) for f,h in hashes.items() if full['frames'][f]['sha256']!=h),default=0)
assert render_noise<=8,render_noise
write_json(PRE/'parent-comparison.json',{'planSha256':P['planSha256'],**parent})
write_json(PRE/'media-verification.json',{'planSha256':P['planSha256'],'media':{'clip':clip,'sha256':sha(movie),'stream':stream,'constantPTS':True,'command':[str(x) for x in command]},'nativeMotion':native_motion,'cameraTravel':travel,'reportHoldStopped':stopped,'reportHoldEnds':hold_ends,'chapterHold':chapter_hold,'reportShrink':shrink,'rawIdenticalHolds':{'report':[report+14,hold['endFrameExclusive']],'chapter':[chapter+15,chapter+75],'method':list(method_hold)},'clipFramesIdenticalToAuditRender':same_render,'clipFrames':clip['frameCount'],'renderNoisePeak':render_noise,'reportFraming':framing,'audio':'silent preview'})

# Keyframes, storyboard and comparison sheets.
keys=P['keyframes'];inspection={m['frame']:m for m in audit['manifest']}
for k in keys:
 m=inspection[k['frame']];source=ROOT/m['file']
 assert sha(source)==m['sha256']
 shutil.copyfile(source,PRE/name(k['frame']))
changed=lambda f:any(a<=f<b for a,b in report_windows(P))
sheet=Image.new('RGB',(1660,150+math.ceil(len(keys)/2)*540),'#f5f5f7');d=ImageDraw.Draw(sheet)
d.text((40,24),f"星图工作台 · {P['video']['durationSeconds']:g} 秒 · v8 待确认",font=font(32,True),fill='#202126')
d.text((40,82),'只更新报告相关片段；镜头顺序、时长与配乐沿用 v7。蓝色标题为有更新的镜头。',font=font(21),fill='#68788b')
for i,k in enumerate(keys):
 x,y=40+(i%2)*810,140+(i//2)*540
 s=shots[k['shot']]
 d.text((x,y),f"{k['frame']/FPS:g}s · {k['label']}"+(' · 已更新' if changed(k['frame']) else ''),font=font(21,True),fill='#1465ad' if changed(k['frame']) else '#294b72')
 sheet.paste(Image.open(PRE/name(k['frame'])).convert('RGB').resize((770,433),Image.Resampling.LANCZOS),(x,y+37))
 for n,line in enumerate(textwrap.wrap(s['data']['transition'],39)):
  d.text((x,y+477+n*22),line,font=font(15),fill='#747b87')
sheet.save(PRE/'storyboard-overview.png')
pairs=[(report+7,'镜头移向报告'),(hold['startFrame']+30,'报告稳定阅读'),(chapter+4,'章节卡进场'),(method-4,'章节卡退场'),(method+15,'报告缩入'),(at('method',2.5),'报告与方法卡'),(feedback+7,'报告淡出')]
compare_sheet=Image.new('RGB',(1660,100+len(pairs)*500),'#f5f5f7');d=ImageDraw.Draw(compare_sheet)
d.text((40,24),'v7（左）与 v8（右）· 只有报告片段不同',font=font(30,True),fill='#202126')
for i,(f,label) in enumerate(pairs):
 y=90+i*500
 d.text((40,y),f'{f/FPS:.1f}s · 第 {f} 帧 · {label}',font=font(20,True),fill='#315e8e')
 for x,image in ((40,PARENT_FRAMES/name(f)),(850,folder/name(f))):
  compare_sheet.paste(Image.open(image).convert('RGB').resize((770,433),Image.Resampling.LANCZOS),(x,y+36))
compare_sheet.save(PRE/'v7-v8-comparison.png')
cols=4;thumb_w=450;thumb_h=round(thumb_w*1080/1920);cell_h=thumb_h+44
frames=sorted(set(transition_frames))
contact=Image.new('RGB',(1920,84+math.ceil(len(frames)/cols)*cell_h),'#f5f5f7');d=ImageDraw.Draw(contact)
d.text((30,20),'报告片段转场 · 从小样 MP4 解码',font=font(28,True),fill='#202126')
for i,f in enumerate(frames):
 x,y=30+(i%cols)*470,76+(i//cols)*cell_h
 d.text((x,y),f'{f/FPS:.2f} 秒 · 第 {f} 帧',font=font(17),fill='#315e8e')
 contact.paste(Image.open(decoded(f)).convert('RGB').resize((thumb_w,thumb_h),Image.Resampling.LANCZOS),(x,y+28))
contact.save(PRE/'report-transitions.png')

# Review page.
e=html.escape
findings=''.join(f"<tr><td>{e(x['risk'])}</td><td>{e(x['result'])}</td><td>{e(x['handling'])}</td></tr>" for x in revision['findings'])
copy_rows=''.join(f"<tr><td>{e(x['where'])}</td><td>{e(x['v7'])}</td><td><b>{e(x['proposed'])}</b></td><td>{e(x['why'])}</td><td class='state'>{e(x['state'])}</td></tr>" for x in revision['copyProposal'])
attention=''.join(f"<li>{e(x)}</li>" for x in revision['attention'])
rows=''.join(f'<tr><td>{s["startSeconds"]:g}–{s["startSeconds"]+s["durationSeconds"]:g} 秒</td><td>{e(s["label"])}</td><td>{"已更新" if s["id"] in ("report","chapter-card","method") else "沿用 v7"}</td><td>{e(s["data"]["focus"])}</td></tr>' for s in P['shots'])
cards=''.join(f'<a href="{name(k["frame"])}"><img src="{name(k["frame"])}" loading="lazy"><span>{k["frame"]/FPS:g} 秒 · {e(k["label"])}{" · 已更新" if changed(k["frame"]) else ""}</span></a>' for k in keys)
ranges='、'.join(f'{a}–{b-1}' for a,b in parent['changedRanges'])
windows='、'.join(f'{a}–{b-1}' for a,b in parent['intendedWindows'])
card=framing['card'];foot=framing['foot']
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>星图工作台 · v8 报告卡片同步预览</title><style>body{{font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif;color:#252b36;background:#f5f5f7;margin:0}}main{{max-width:1180px;margin:auto;padding:50px 30px}}h1{{font-size:38px}}h2{{margin-top:40px;font-size:25px}}p{{color:#687181}}a{{color:#1465ad}}video{{width:100%;display:block;border:1px solid #dce0e6;border-radius:12px;background:white}}.badge{{background:#e7edf8;color:#37577c;padding:6px 12px;border-radius:6px}}.cards{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.cards img{{width:100%;display:block}}.cards a{{background:white;text-decoration:none;border-radius:8px;overflow:hidden}}.cards span{{display:block;padding:12px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border-bottom:1px solid #e2e5eb;text-align:left;vertical-align:top}}img.wide{{width:100%;display:block;border-radius:8px}}td.state{{white-space:nowrap}}@media(max-width:700px){{.cards{{grid-template-columns:1fr}}}}</style><main><span class="badge">v8 · 预览待确认</span><h1>把报告片段同步到新的报告卡片。</h1><p>只更新报告相关片段。全片仍为 {P['video']['durationSeconds']:g} 秒 / {P['video']['totalFrames']} 帧，镜头顺序和时长不变，配乐沿用 v7（成片阶段核对逐位相同后复用）。这里只有无声小样和关键帧；确认后才制作完整视频。v7 的批准和听感验收不适用于 v8。</p><h2>小样 · 报告片段</h2><video controls preload="metadata" poster="{name(hold['startFrame']+30)}" src="{clip['id']}.mp4"></video><p>{clip['durationSeconds']:g} 秒无声小样，覆盖全片 {clip['startFrame']/FPS:g}–{clip['endFrameExclusive']/FPS:g} 秒：节点检查器 → 报告 → 章节卡 → 报告缩入与方法卡 → 淡出。</p><h2>需要你确认的文案</h2><table><tr><th>位置</th><th>v7</th><th>提议</th><th>依据</th><th>状态</th></tr>{copy_rows}</table><p>{e(revision['copyKept'])}</p><h2>五项风险的核对结果</h2><table><tr><th>风险</th><th>结果</th><th>处理</th></tr>{findings}</table><h2>实测</h2><table><tr><th>项目</th><th>结果</th></tr><tr><td>报告卡片在镜头内的位置（镜头 1270×766）</td><td>x {card['x']:.0f}–{card['right']:.0f}，y {card['y']:.0f}–{card['bottom']:.0f}；底部说明止于 y {foot['bottom']:.0f}；放大 {framing['scale']:.2f} 倍</td></tr><tr><td>输入框上沿</td><td>y {framing['composerTop']:.0f}，在画面外（卡片下方 {framing['composerTop']-card['bottom']:.0f} 个镜头像素）</td></tr><tr><td>报告稳定阅读</td><td>第 {report+14}–{hold['endFrameExclusive']-1} 帧逐帧哈希相同</td></tr><tr><td>与 v7 逐帧比较（全部 {P['video']['totalFrames']} 帧，版本标记遮盖）</td><td>有差异的帧：{ranges}，共 {parent['changedFrames']} 帧，均在报告窗口 {windows} 内；窗口外 0 帧。其余 {parent['unchangedFrames']} 帧任一通道差值不超过 {parent['peakDifferenceInUnchangedFrames']}/255</td></tr></table><h2>请一并留意</h2><ul>{attention}</ul><h2>v7 与 v8 对照</h2><a href="v7-v8-comparison.png"><img class="wide" src="v7-v8-comparison.png"></a><p><a href="report-transitions.png">转场逐帧图</a> · <a href="storyboard-overview.png">完整分镜</a> · <a href="../source/index.html">可拖动的完整分镜（需本地服务）</a> · <a href="verification.md">验证记录</a> · <a href="reproduce.md">复现步骤</a> · <a href="../../{PARENT.name}/final/index.html">v7 成片</a></p><h2>内容覆盖</h2><table><tr><th>内容</th><th>处理</th></tr><tr><td>产品全貌</td><td>沿用 v7：0–2 秒完整工作台</td></tr><tr><td>关键配置</td><td>沿用 v7：原生 Skills 打开与选中</td></tr><tr><td>核心操作</td><td>沿用 v7：并行研究、检查器与优化机制图解</td></tr><tr><td>结果</td><td>报告改为新版卡片；演示数据没有来源，不增加引用操作；采纳决策与品牌收尾沿用 v7</td></tr></table><h2>时长与镜头</h2><table><tr><th>时间</th><th>镜头</th><th>本版</th><th>焦点</th></tr>{rows}</table><h2>关键帧</h2><div class="cards">{cards}</div><p>合成演示 · 流程已压缩。报告为项目内置模拟内容，不含真实来源或结论；未调用模型或搜索。根 README 仍指向 v6，产品演示入口仍指向 v7，v8 完成前不切换。</p><p>计划标识：{P['planSha256']}</p></main></html>'''
(PRE/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'clip':clip,'sha256':sha(movie),'travel':travel,'stopped':stopped,'holdEnds':hold_ends,'chapterHold':chapter_hold,'shrink':shrink,'clipFramesIdenticalToAuditRender':same_render,'renderNoisePeak':render_noise,'nativeMotion':native_motion,'framing':framing,'parent':{k:v for k,v in parent.items() if k!='perFrame'}},ensure_ascii=False,indent=1))
