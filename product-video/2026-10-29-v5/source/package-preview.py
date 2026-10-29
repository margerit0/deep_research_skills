"""Package the revised cause-and-effect transition as reviewable excerpts."""
from pathlib import Path
import hashlib,html,json,math,subprocess,textwrap
from PIL import Image,ImageDraw,ImageFont,ImageChops,ImageStat
from timeline import load_plan,write_json
ROOT=Path(__file__).resolve().parent.parent
PRE=ROOT/'preview';CACHE=ROOT/'cache'
P=load_plan(ROOT/'plan.json');FPS=float(P['video']['fps'])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
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
media=[]
for clip in P['previewClips']:
 folder=CACHE/clip['id'];m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
 assert m['planSha256']==P['planSha256'] and not m['errors'] and not m['blocked']
 assert [f['frame'] for f in m['frames']]==list(range(clip['startFrame'],clip['endFrameExclusive']))
 for f in m['frames']:assert sha(folder/f['file'])==f['sha256']
 movie=PRE/f"{clip['id']}.mp4"
 command=['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(FPS),'-start_number',clip['startFrame'],'-i',folder/'frame-%04d.png','-frames:v',clip['frameCount'],'-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-r',str(FPS),'-movflags','+faststart',movie]
 run(command)
 stream=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',movie]))['streams'][0]
 assert (stream['codec_name'],stream['width'],stream['height'],stream['avg_frame_rate'],int(stream['nb_read_frames']))==('h264',1920,1080,'30/1',clip['frameCount'])
 assert abs(float(stream['duration'])-clip['durationSeconds'])<.001
 pts=[float(f['best_effort_timestamp_time']) for f in json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',movie]))['frames']]
 assert len(pts)==clip['frameCount'] and all(abs(b-a-1/FPS)<.000002 for a,b in zip(pts,pts[1:]))
 for f in ([285,295,420,430] if clip['id']=='context' else [479,480,495,500,555,705,825]):
  run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf',rf'select=eq(n\,{f-clip["startFrame"]})','-fps_mode','vfr','-frames:v','1',CACHE/f'decoded-{f}.png'])
 media.append({'clip':clip,'sha256':sha(movie),'stream':stream,'constantPTS':True,'command':[str(x) for x in command]})
motion=delta(CACHE/'decoded-285.png',CACHE/'decoded-295.png',(950,350,1460,940))
stopped=delta(CACHE/'decoded-420.png',CACHE/'decoded-430.png')
bridge=delta(CACHE/'decoded-495.png',CACHE/'decoded-500.png')
same_card=delta(CACHE/'decoded-555.png',CACHE/'decoded-705.png',(1170,410,1744,810))
raw_card=delta(CACHE/'bridge/frame-0555.png',CACHE/'bridge/frame-0705.png',(1171,410,1745,810))
assert motion['changedPixels']>150 and stopped['mean']<.2 and bridge['changedPixels']>1000 and raw_card['mean']==0
# Cross-scene H.264 prediction can slightly change pixels on an identical card.
# Prove raw identity, and verify both encoded appearances against that source.
same_card['rawMean']=raw_card['mean']
same_card['lumaPSNR']=[]
for frame in [555,705]:
 a=Image.open(CACHE/f'decoded-{frame}.png').convert('L').crop((1171,410,1745,810))
 b=Image.open(CACHE/f'bridge/frame-{frame:04d}.png').convert('L').crop((1171,410,1745,810))
 rms=ImageStat.Stat(ImageChops.difference(a,b)).rms[0]
 psnr=20*math.log10(255/rms) if rms else 100
 assert psnr>45
 same_card['lumaPSNR'].append(psnr)
audit=json.loads((CACHE/'capture-audit.json').read_text(encoding='utf-8'))
get=lambda f:next(s for s in audit['layouts'] if s['frame']==f)
assert get(555)['methodCard']==get(705)['methodCard']
assert all(abs(get(480)['shell'][k]-get(480)['bridgeWindow'][k])<.1 for k in ('x','y','width','height'))
assert abs(get(540)['shell']['width']-450)<.1
write_json(PRE/'media-verification.json',{'planSha256':P['planSha256'],'media':media,'nativeMotion':motion,'nativeStopped':stopped,'reportShrinkMotion':bridge,'sameSkillCardAcrossScenes':same_card,'nativeWindowMatchesAtTransition':True,'skillCardPositionUnchanged':True,'audio':'silent preview'})
keys=P['keyframes'];height=150+math.ceil(len(keys)/2)*540
sheet=Image.new('RGB',(1660,height),'#f5f5f7');d=ImageDraw.Draw(sheet)
d.text((40,24),'星图工作台 · 50 秒修订方案 · v5 待确认',font=font(32,True),fill='#202126')
d.text((40,82),'先解释 Skill → 保留报告引出方法 → 评估为何改进 → 验证与采纳',font=font(21),fill='#68788b')
for i,k in enumerate(keys):
 x,y=40+(i%2)*810,140+(i//2)*540
 s=next(s for s in P['shots'] if s['id']==k['shot'])
 d.text((x,y),f"{k['frame']/FPS:g}s · {k['label']}",font=font(21,True),fill='#294b72')
 sheet.paste(Image.open(PRE/f"frame-{k['frame']:04d}.png").convert('RGB').resize((770,433),Image.Resampling.LANCZOS),(x,y+37))
 for n,line in enumerate(textwrap.wrap(s['data']['transition'],39)):
  d.text((x,y+477+n*22),line,font=font(15),fill='#747b87')
sheet.save(PRE/'storyboard-overview.png')
focus=Image.new('RGB',(1600,1020),'#f5f5f7');d=ImageDraw.Draw(focus)
d.text((30,18),'补上因果关系 · 报告背后的方法，如何进入改进流程',font=font(27,True),fill='#202126')
for i,(f,label) in enumerate([(210,'先解释：Skill 就是研究方法'),(555,'同一份报告，引出同一份方法'),(705,'再解释：评估为什么推动改进'),(825,'最后进入：怎样诊断和修订')]):
 x,y=20+(i%2)*800,76+(i//2)*470
 d.text((x+10,y),label,font=font(21,True),fill='#315e8e')
 focus.paste(Image.open(PRE/f'frame-{f:04d}.png').resize((760,428),Image.Resampling.LANCZOS),(x,y+34))
focus.save(PRE/'bridge-overview.png')
rows=''.join(f'<tr><td>{s["startSeconds"]:g}–{s["startSeconds"]+s["durationSeconds"]:g} 秒</td><td>{html.escape(s["label"])}</td><td>{html.escape(s["data"]["focus"])}</td></tr>' for s in P['shots'])
cards=''.join(f'<a href="frame-{k["frame"]:04d}.png"><img src="frame-{k["frame"]:04d}.png"><span>{k["frame"]/FPS:g} 秒 · {html.escape(k["label"])}</span></a>' for k in keys)
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>星图工作台 · v5 衔接预览</title><style>body{{font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif;color:#252b36;background:#f5f5f7;margin:0}}main{{max-width:1180px;margin:auto;padding:50px 30px}}h1{{font-size:38px}}h2{{margin-top:40px;font-size:25px}}p{{color:#687181}}a{{color:#1465ad}}video{{width:100%;display:block;border:1px solid #dce0e6;border-radius:12px;background:white}}.badge{{background:#e7edf8;color:#37577c;padding:6px 12px;border-radius:6px}}.cards{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.cards img{{width:100%;display:block}}.cards a{{background:white;text-decoration:none;border-radius:8px;overflow:hidden}}.cards span{{display:block;padding:12px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border-bottom:1px solid #e2e5eb;text-align:left}}@media(max-width:700px){{.cards{{grid-template-columns:1fr}}}}</style><main><span class="badge">v5 · 修订预览待确认</span><h1>先让观众明白：为什么要改进 Skill。</h1><p>建议全片从 42 秒调整为 {P['video']['durationSeconds']:g} 秒。新增 8 秒解释“Skill 是什么、它与报告有什么关系、为什么评估会推动修订”，再进入原有优化流程。</p><h2>重点看这里 · 报告到方法优化的衔接</h2><video controls preload="metadata" poster="frame-0555.png" src="bridge.mp4"></video><p>这段 16 秒无声小样覆盖全片 13–29 秒：报告 → 方法 → 评估动机 → 诊断。报告由原生页面连续缩入；两镜之间保留同一张产品对比方法卡。评估问题为机制解释，没有伪造这份演示报告的失败结果。</p><h2>前面先铺垫 · Skill 就是研究方法</h2><video controls preload="metadata" poster="frame-0210.png" src="context.mp4"></video><p>这段 10.5 秒小样覆盖 Skills 选择、并行研究、检查器和报告。修改选择时的讲解，避免观众先记住一个陌生术语。</p><p><a href="../source/index.html">可拖动的完整 50 秒分镜（需本地服务）</a> · <a href="bridge-overview.png">修改概览</a> · <a href="storyboard-overview.png">完整分镜</a> · <a href="verification.md">验证记录</a></p><h2>这版解决什么</h2><ul><li>进入机制动画前，先建立“Skill = 研究方法”的理解。</li><li>沿用刚才的报告和产品对比 Skill，让画面与概念都有连续关系。</li><li>先问研究做得怎么样，再解释为什么要修订，最后讲怎样修订和验证。</li><li>明确优化对象是 Skill，且只有验证通过并经操作者采纳后才用于新研究。</li></ul><h2>完整内容覆盖</h2><table><tr><th>内容</th><th>处理</th></tr><tr><td>产品全貌</td><td>保留 0–2 秒完整工作台</td></tr><tr><td>关键配置</td><td>保留原生 Skills 打开与选中，讲解改为“研究方法”；不额外展开模型配置</td></tr><tr><td>核心操作</td><td>保留并行研究与检查器；新增方法解释和评估动机</td></tr><tr><td>结果</td><td>保留合成报告、独立验证、显式采纳与回退、品牌收尾</td></tr></table><h2>时长与镜头</h2><table><tr><th>时间</th><th>镜头</th><th>焦点</th></tr>{rows}</table><h2>关键帧</h2><div class="cards">{cards}</div><p>合成演示 · 流程已压缩。新增图解来自项目文档与产品对比 Skill 正文，不是前端新增界面或实测优化结果。当前 README 仍指向 v4 成片；v5 时长与叙事变更等待确认后再制作完整配乐视频。</p><p>计划标识：{P['planSha256']}</p></main></html>'''
(PRE/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'clips':[x['clip'] for x in media],'motion':motion,'bridge':bridge,'sameCard':same_card},ensure_ascii=False))
