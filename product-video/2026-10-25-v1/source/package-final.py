"""Encode and inspect the approved twelve-second movie; all QA frames decode the MP4."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parent.parent
T = json.loads((ROOT/'timeline.json').read_text(encoding='utf-8-sig'))
assert T['approval']['status'] == 'approved'
CACHE, FINAL = ROOT/'cache/final', ROOT/'final'
FINAL.mkdir(exist_ok=True)
DECODED = CACHE/'decoded'
DECODED.mkdir(exist_ok=True)

def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, encoding='utf-8', errors='strict')
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    return result.stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def difference(a, b, box=None):
    a, b = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    if box:
        a,b = a.crop(box),b.crop(box)
    delta = ImageChops.difference(a,b)
    changed = sum(max(px)>8 for px in delta.get_flattened_data())
    return {'pixels_over_8':changed,'fraction_over_8':changed/(delta.width*delta.height),'mean_absolute_channel_error':sum(ImageStat.Stat(delta).mean)/3}

def font(size, bold=False):
    candidate = os.environ.get('VIDEO_CJK_FONT_BOLD' if bold else 'VIDEO_CJK_FONT')
    return ImageFont.truetype(candidate or ('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc'), size)

movie = FINAL/'product-demo.mp4'
assert len(list((CACHE/'frames').glob('frame-*.png'))) == T['frame_count']
command = ['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(T['fps']),'-start_number','0','-i',CACHE/'frames/frame-%03d.png','-i',CACHE/'music.wav','-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','17','-profile:v','high','-level:v','4.1','-pix_fmt','yuv420p','-r',str(T['fps']),'-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-t',str(T['duration_seconds']),'-movflags','+faststart',movie]
run(command)
probe = json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]))
video = next(s for s in probe['streams'] if s['codec_type']=='video')
audio = next(s for s in probe['streams'] if s['codec_type']=='audio')
assert (video['codec_name'],video['width'],video['height'],video['avg_frame_rate'],video['pix_fmt'],int(video['nb_read_frames'])) == ('h264',1920,1080,'30/1','yuv420p',360)
assert (audio['codec_name'],int(audio['sample_rate']),audio['channels']) == ('aac',48000,2)
assert abs(float(video['duration'])-12)<0.00001 and abs(float(audio['duration'])-12)<0.0001
assert abs(float(video['start_time'])-float(audio['start_time']))<0.001
frames = json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',movie]))['frames']
pts = [float(f['best_effort_timestamp_time']) for f in frames]
assert len(pts)==360 and abs(pts[0])<0.000001 and abs(pts[-1]-359/30)<0.000001
assert all(abs((b-a)-1/30)<0.000002 for a,b in zip(pts,pts[1:]))

checks = sorted(set(T['keyframes']+[0,59,60,74,89,100,110,149,150,151,164,165,176,209,210,224,225,239,299,300,306,315,329,330,359]))
for frame in checks:
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf',rf'select=eq(n\,{frame})','-vsync','0','-frames:v','1',DECODED/f'frame-{frame:03d}.png'])
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-map','0:a:0','-acodec','pcm_f32le','-f','f32le',CACHE/'decoded-audio.f32'])
meter = subprocess.run(['ffmpeg','-hide_banner','-i',str(movie),'-vn','-af','ebur128=peak=true','-f','null','-'],capture_output=True,encoding='utf8',errors='strict',check=True)
(CACHE/'audio-loudness.log').write_text(meter.stderr,encoding='utf8')

motion = difference(DECODED/'frame-100.png',DECODED/'frame-110.png',(950,350,1460,940))
assert motion['pixels_over_8']>150
report_hold = difference(DECODED/'frame-225.png',DECODED/'frame-239.png')
brand_hold = difference(DECODED/'frame-330.png',DECODED/'frame-359.png')
assert report_hold['mean_absolute_channel_error']<0.3 and brand_hold['mean_absolute_channel_error']<0.3
random_access={}
for frame in [255,45,195,105,345,100,110,150,165,239,225]:
    diff=difference(CACHE/'frames'/f'frame-{frame:03d}.png',CACHE/'random-access'/f'frame-{frame:03d}.png')
    random_access[frame]=diff
    assert diff['fraction_over_8']<0.005 and diff['mean_absolute_channel_error']<0.15
approved_match={}
for frame in T['keyframes']:
    # The final edition changes only the review marker in the bottom-right footer.
    diff=difference(CACHE/'frames'/f'frame-{frame:03d}.png',ROOT/'preview'/f'frame-{frame:03d}.png',(0,0,1920,990))
    approved_match[frame]=diff
    assert diff['fraction_over_8']<0.005 and diff['mean_absolute_channel_error']<0.15, f'Approved keyframe changed: {frame}'

sheet=Image.new('RGB',(2060,2150),'#f5f5f7');draw=ImageDraw.Draw(sheet)
draw.text((60,36),'星图工作台 / 成片检查图',font=font(38,True),fill='#202126')
draw.text((60,94),'以下五帧均从本次 product-demo.mp4 解码提取',font=font(23),fill='#686d78')
names=['提出问题','并行研究','执行记录','阅读报告','品牌收尾']
for i,frame in enumerate(T['keyframes']):
    x,y=60+(i%2)*1000,160+(i//2)*640
    draw.text((x,y),f'{i+1:02d} / {names[i]}',font=font(25,True),fill='#25282f')
    draw.text((x+610,y+2),f'{frame/30:.1f} 秒 · 第 {frame} 帧',font=font(21),fill='#0068d6')
    shot=Image.open(DECODED/f'frame-{frame:03d}.png').convert('RGB').resize((940,529),Image.Resampling.LANCZOS)
    sheet.paste(shot,(x,y+43));draw.rectangle((x,y+43,x+940,y+572),outline='#dadee3',width=1)
digest=sha(movie)
notes=['1920 × 1080 / 30 fps / 360 帧','12 秒 / H.264 + AAC / 立体声','代码合成配乐 / 120 BPM / 24 拍','报告停留 2.5 秒 / 品牌停留 1 秒','2026-10-25-v1 / 已确认分镜',f'视频 SHA-256：{digest[:24]}…']
draw.text((1060,1480),'成片规格',font=font(30,True),fill='#25282f')
for i,note in enumerate(notes):draw.text((1060,1542+i*52),note,font=font(24),fill='#626670')
draw.text((60,2096),'合成演示 · 流程已压缩    |    本图来自编码后的最终 MP4',font=font(23),fill='#626670')
sheet.save(FINAL/'check-sheet.png')
Image.open(DECODED/'frame-105.png').save(FINAL/'poster.png')

contact=Image.new('RGB',(1920,2400),'#e8e9ed');d=ImageDraw.Draw(contact)
for i,frame in enumerate(checks):
    x,y=(i%4)*480,(i//4)*300
    contact.paste(Image.open(DECODED/f'frame-{frame:03d}.png').resize((480,270)),(x,y+26))
    d.text((x+9,y+3),f'{frame} / {frame/30:.3f}s',font=font(18),fill='#24262c')
contact.save(CACHE/'transition-check-sheet.png')
audit={'movie_sha256':digest,'video':video,'audio':audio,'container_duration':probe['format']['duration'],'video_frames':len(pts),'video_pts_first':pts[0],'video_pts_last':pts[-1],'constant_frame_timestamps':True,'decoded_running_motion':motion,'decoded_report_hold':report_hold,'decoded_brand_hold':brand_hold,'random_access_pixels':random_access,'approved_keyframe_match':approved_match,'encoding_command':[str(x) for x in command],'check_sheet_source':'decoded frames of this exact product-demo.mp4'}
(CACHE/'video-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
run(['node', ROOT/'source/build-player.mjs'])
print(json.dumps({'movie':str(movie),'sha256':digest,'frames':360,'audio':audio['codec_name'],'motion':motion,'holds':[report_hold,brand_hold]},ensure_ascii=False))
