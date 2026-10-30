"""Encode the approved frame sequence and verify the final MP4 itself."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat
from timeline import load_plan, write_json

ROOT=Path(__file__).resolve().parent.parent
PARENT=ROOT.parent/'2026-10-29-v6'
P=load_plan(ROOT/'plan.json')
CACHE=ROOT/'cache/final'
FINAL=ROOT/'final'
FINAL.mkdir(exist_ok=True)
FPS=float(P['video']['fps'])
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(args):
    result=subprocess.run([str(x) for x in args],capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr.decode('utf-8')[-5000:])
    return result.stdout.decode('utf-8')
def font(size,bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',size)
def delta(a,b,box=None):
    x,y=Image.open(a).convert('RGB'),Image.open(b).convert('RGB')
    if box:x,y=x.crop(box),y.crop(box)
    d=ImageChops.difference(x,y)
    return {'changedPixels':sum(max(p)>8 for p in d.get_flattened_data()),'fraction':sum(max(p)>8 for p in d.get_flattened_data())/(d.width*d.height),'mean':sum(ImageStat.Stat(d).mean)/3}

approval=json.loads((ROOT/'approval.json').read_text(encoding='utf-8'))
assert approval['status']=='approved' and approval['planSha256']==P['planSha256']
frames=json.loads((CACHE/'frames/manifest.json').read_text(encoding='utf-8'))
audio=json.loads((CACHE/'audio-source.json').read_text(encoding='utf-8'))
assert frames['planSha256']==audio['planSha256']==P['planSha256']
assert not frames['errors'] and not frames['blocked'] and len(frames['clicks'])==4
assert [f['frame'] for f in frames['frames']]==list(range(P['video']['totalFrames']))
for f in frames['frames']:assert sha(CACHE/'frames'/f['file'])==f['sha256']
assert sha(CACHE/'music.wav')==audio['sourceSha256']
movie=FINAL/'product-demo.mp4'
command=['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(FPS),'-start_number','0','-i',CACHE/'frames/frame-%04d.png','-i',CACHE/'music.wav','-map','0:v:0','-map','1:a:0','-frames:v',P['video']['totalFrames'],'-t',P['video']['durationSeconds'],'-c:v','libx264','-preset','medium','-crf','17','-pix_fmt','yuv420p','-r',str(FPS),'-c:a','aac','-b:a','192k','-ar',P['audio']['sampleRate'],'-ac','2','-movflags','+faststart',movie]
run(command)
probe=json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]))
v=next(s for s in probe['streams'] if s['codec_type']=='video')
a=next(s for s in probe['streams'] if s['codec_type']=='audio')
assert (v['codec_name'],v['width'],v['height'],v['avg_frame_rate'],v['pix_fmt'],int(v['nb_read_frames']))==('h264',1920,1080,'30/1','yuv420p',P['video']['totalFrames'])
assert (a['codec_name'],int(a['sample_rate']),a['channels'])==('aac',P['audio']['sampleRate'],2)
assert abs(float(v['duration'])-P['video']['durationSeconds'])<.001
assert abs(float(a['duration'])-P['video']['durationSeconds'])<.025
pts=[float(x['best_effort_timestamp_time']) for x in json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',movie]))['frames']]
assert len(pts)==P['video']['totalFrames'] and all(abs(b-a-1/FPS)<.000002 for a,b in zip(pts,pts[1:]))
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vn','-c:a','pcm_f32le','-f','f32le',CACHE/'decoded-audio.f32'])
extracted=CACHE/'extracted';shutil.rmtree(extracted,ignore_errors=True);extracted.mkdir()
shots={s['id']:s for s in P['shots']}
at=lambda shot,seconds=0:shots[shot]['startFrame']+round(seconds*FPS)
native_pair=[at('parallel',1.5),at('parallel',1.5)+10]
stopped_pair=[at('report',1),at('report',1)+10]
brand_pair=[at('brand',1.5),at('brand',2.5)]
shrink_pair=[at('method',.5),at('method',.5)+5]
chapter_pair=[at('chapter-card',1.5),at('chapter-card',2)]
transition_frames=[at('parallel'),at('parallel',.25),at('parallel',.5),at('parallel',.75),at('parallel',1),at('report'),at('report',.15),at('report',.3),at('report',.5),at('chapter-card')-1,at('chapter-card'),at('chapter-card')+7,at('chapter-card',.5),at('chapter-card',2.5),at('chapter-card',2.5)+7,at('method')-1,at('method'),at('method',.25),at('method',.5),at('method',1),at('feedback'),at('feedback')+3,at('feedback')+6,at('diagnose'),at('brand')-1,at('brand'),at('brand')+7,at('brand',.5),*brand_pair,P['video']['totalFrames']-1]
selected=sorted(set([k['frame'] for k in P['keyframes']]+transition_frames+native_pair+stopped_pair+shrink_pair+chapter_pair+[e['frame'] for e in P['events'] if e['kind']=='click']))
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf','select='+'+'.join(rf'eq(n\,{f})' for f in selected),'-fps_mode','vfr',extracted/'pick-%04d.png'])
for index,frame in enumerate(selected,1):(extracted/f'pick-{index:04d}.png').replace(extracted/f'frame-{frame:04d}.png')
def pair_delta(pair,box=None):
    return delta(*(extracted/f'frame-{f:04d}.png' for f in pair),box=box)
motion=pair_delta(native_pair,(950,350,1460,940))
stopped=pair_delta(stopped_pair)
closing=pair_delta(brand_pair)
new_motion=pair_delta(shrink_pair)
chapter_hold=pair_delta(chapter_pair)
assert motion['changedPixels']>150 and new_motion['changedPixels']>500
assert stopped['mean']<.2 and closing['mean']<.2 and chapter_hold['mean']<.2
similarity=[]
for key in P['keyframes']:
    f=key['frame']
    encoded=delta(extracted/f'frame-{f:04d}.png',CACHE/f'frames/frame-{f:04d}.png')
    # yuv420p subsamples chroma by design. Measure luma PSNR for detail quality
    # instead of treating every colored antialiased edge as a layout change.
    luma=ImageStat.Stat(ImageChops.difference(Image.open(extracted/f'frame-{f:04d}.png').convert('L'),Image.open(CACHE/f'frames/frame-{f:04d}.png').convert('L')))
    encoded['lumaPSNR']=20*math.log10(255/luma.rms[0]) if luma.rms[0] else 100
    assert encoded['lumaPSNR']>45 and encoded['mean']<1.2,(f,'encoding',encoded)
    similarity.append({'frame':f,'encodedAgainstRendered':encoded})
# v7 keeps the v6 storyboard, so picture changes must stay inside the revised transitions.
# Averaging 4x4 luma cells leaves glyph antialiasing below the threshold and any real change above it.
intended=[(at('parallel'),at('parallel',1)),(at('report'),at('report',.5)),(at('chapter-card'),at('chapter-card',.55)),(at('chapter-card',2.5),at('method',.6)),*[(at(s),at(s,.25)) for s in ('feedback','diagnose','candidate','validate','release')],(at('brand'),at('brand',.55))]
def coarse(path):
    image=Image.open(path).convert('L')
    ImageDraw.Draw(image).rectangle((1600,990,1920,1080),fill=255)
    return image.reduce(4)
def parent_change(frame):
    name=f'frame-{frame:04d}.png'
    histogram=ImageChops.difference(coarse(PARENT/'cache/final/frames'/name),coarse(CACHE/'frames'/name)).histogram()
    return frame,sum(histogram[25:])
if (PARENT/'cache/final/frames').exists():
    with ThreadPoolExecutor(8) as pool:changes=list(pool.map(parent_change,range(P['video']['totalFrames'])))
    changed=[f for f,n in changes if n]
    outside=[f for f in changed if not any(a<=f<b for a,b in intended)]
    assert not outside,('Picture changed outside the revised transitions',outside)
    parent={'version':PARENT.name,'status':'compared','method':'4x4 luma cell mean difference above 24 of 255, edition label masked','intendedWindows':intended,'changedFrames':len(changed),'unchangedFrames':P['video']['totalFrames']-len(changed),'changedOutsideWindows':0}
else:
    parent={'version':PARENT.name,'status':'skipped','reason':'Parent frame cache is not present; regenerate it from the parent version to repeat this comparison.'}
BANDS={'under80Hz':'lowpass=f=80','80-250Hz':'highpass=f=80,lowpass=f=250','250-2000Hz':'highpass=f=250,lowpass=f=2000','2-6kHz':'highpass=f=2000,lowpass=f=6000','over6kHz':'highpass=f=6000'}
def stderr(path,chain):
    return subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vn','-af',chain,'-f','null','-'],capture_output=True).stderr.decode('utf-8','replace')
def measure(path):
    text=stderr(path,'ebur128=peak=true:framelog=quiet')
    number=lambda pattern:float(re.findall(pattern,text)[-1])
    bands={label:float(re.findall(r'RMS level dB: (-?[\d.]+)',stderr(path,f'{chain},astats=metadata=0:measure_overall=RMS_level:measure_perchannel=0'))[-1]) for label,chain in BANDS.items()}
    return {'integratedLufs':number(r'I:\s+(-?[\d.]+) LUFS'),'loudnessRangeLu':number(r'LRA:\s+(-?[\d.]+) LU'),'truePeakDbtp':number(r'Peak:\s+(-?[\d.]+) dBFS'),'bandRmsDb':bands}
loudness={'current':measure(movie),'parent':measure(PARENT/'final/product-demo.mp4')}
now=loudness['current']
assert -16.5<=now['integratedLufs']<=-15.5 and now['truePeakDbtp']<=-1 and 4<=now['loudnessRangeLu']<=7,now
def sheet(frames,output,cols,width,thumb_w,title,labels=None):
    thumb_h=round(thumb_w*1080/1920);cell_h=thumb_h+70
    canvas=Image.new('RGB',(width,120+math.ceil(len(frames)/cols)*cell_h),'#f5f5f7');draw=ImageDraw.Draw(canvas)
    draw.text((30,24),title,font=font(29,True),fill='#202126')
    for i,f in enumerate(frames):
        x=30+(i%cols)*(width-40)//cols;y=90+(i//cols)*cell_h
        label=labels[i] if labels else f'{f/FPS:g} 秒 · 第 {f} 帧'
        draw.text((x,y),label,font=font(18),fill='#315e8e')
        canvas.paste(Image.open(extracted/f'frame-{f:04d}.png').convert('RGB').resize((thumb_w,thumb_h),Image.Resampling.LANCZOS),(x,y+32))
    canvas.save(output)
sheet([k['frame'] for k in P['keyframes']],FINAL/'check-sheet.png',2,1660,770,f"星图工作台 · v7 成片解码检查 · {P['video']['durationSeconds']:g} 秒",labels=[f"{k['frame']/FPS:g}s · {k['label']}" for k in P['keyframes']])
sheet(sorted(set(transition_frames)),CACHE/'transitions.png',4,1920,450,'镜头弧线、章节卡、方法衔接与收尾 · 从最终 MP4 解码')
Image.open(extracted/f'frame-{chapter_pair[0]:04d}.png').save(FINAL/'poster.png')
audit={'planSha256':P['planSha256'],'movieSha256':sha(movie),'sizeBytes':movie.stat().st_size,'encodingCommand':[str(x) for x in command],'probe':probe,'constantFrameTimestamps':True,'frameCount':len(pts),'firstPTS':pts[0],'lastPTS':pts[-1],'decodedNativeMotion':motion,'decodedNewMotion':new_motion,'decodedStoppedState':stopped,'decodedBrandHold':closing,'encodedSimilarity':similarity,'parentComparison':parent,'loudness':loudness,'extractedFrames':selected,'allFramesValidated':len(frames['frames']),'nativeClicks':frames['clicks']}
audit['decodedChapterHold']=chapter_hold
audit['motionFramePairs']={'native':native_pair,'stopped':stopped_pair,'brand':brand_pair,'shrink':shrink_pair,'chapter':chapter_pair}
write_json(FINAL/'verification-data.json',audit)
page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>星图工作台 · 产品演示 v7</title><style>body{{margin:0;background:#f5f5f7;color:#202126;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}}main{{max-width:1200px;margin:auto;padding:42px 28px}}h1{{font-size:36px}}p,footer{{color:#687181}}video{{width:100%;background:white;border-radius:14px;border:1px solid #dce0e6}}a{{color:#1465ad}}.links{{display:flex;gap:24px;flex-wrap:wrap}}footer{{font-size:14px;margin-top:28px}}</style><main><h1>星图工作台</h1><p>{P['video']['durationSeconds']:g} 秒 · 1920 × 1080 · 30 fps · 原创配乐<br>从研究问题到结构化报告，再到评估驱动的 Skill 持续优化。</p><video id="movie" controls preload="auto" playsinline poster="poster.png" src="product-demo.mp4"></video><p class="links"><a href="product-demo.mp4" download>下载 MP4</a><a href="check-sheet.png">成片检查图</a><a href="verification.md">验证记录</a><a href="reproduce.md">制作与复现</a><a href="../../{PARENT.name}/final/index.html">上一版 v6</a></p><footer>合成演示 · 流程已压缩。研究界面使用项目内置模拟数据；新增优化部分为机制示意，尚无真实模型优化实验的效果提升结论。</footer></main><script>const movie=document.getElementById('movie');movie.addEventListener('canplaythrough',()=>movie.dataset.ready='true');if(movie.readyState>=3)movie.dataset.ready='true';</script></html>'''
(FINAL/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'movie':str(movie),'sha256':audit['movieSha256'],'frames':len(pts),'sizeBytes':movie.stat().st_size,'motion':motion,'stopped':stopped,'brand':closing,'parent':parent,'loudness':loudness},ensure_ascii=False,indent=1))
