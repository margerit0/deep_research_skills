"""Encode the approved movie and verify frames decoded from that exact MP4."""
from pathlib import Path
import hashlib
import json
import math
import os
import re
import subprocess
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parent.parent
T = json.loads((ROOT/'timeline.json').read_text(encoding='utf-8-sig'))
assert T['approval']['status'] == 'approved'
CACHE, FINAL = ROOT/'cache/final', ROOT/'final'
DECODED = CACHE/'decoded'
FINAL.mkdir(exist_ok=True)
DECODED.mkdir(exist_ok=True)

def run(args):
    result = subprocess.run([str(x) for x in args],capture_output=True,encoding='utf-8',errors='strict')
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    return result.stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def difference(a,b,box=None):
    a,b = Image.open(a).convert('RGB'),Image.open(b).convert('RGB')
    if box:
        a,b = a.crop(box),b.crop(box)
    delta = ImageChops.difference(a,b)
    changed = sum(max(pixel)>8 for pixel in delta.get_flattened_data())
    return {'pixels_over_8':changed,'fraction_over_8':changed/(delta.width*delta.height),'mean_absolute_channel_error':sum(ImageStat.Stat(delta).mean)/3}

def font(size,bold=False):
    custom = os.environ.get('VIDEO_CJK_FONT_BOLD' if bold else 'VIDEO_CJK_FONT')
    return ImageFont.truetype(custom or ('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc'),size)

movie = FINAL/'product-demo.mp4'
assert len(list((CACHE/'frames').glob('frame-*.png'))) == T['frame_count']
command = ['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(T['fps']),'-start_number','0','-i',CACHE/'frames/frame-%03d.png','-i',CACHE/'music.wav','-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','17','-profile:v','high','-level:v','4.1','-pix_fmt','yuv420p','-r',str(T['fps']),'-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-t',str(T['duration_seconds']),'-movflags','+faststart',movie]
run(command)
probe = json.loads(run(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',movie]))
video = next(s for s in probe['streams'] if s['codec_type']=='video')
audio = next(s for s in probe['streams'] if s['codec_type']=='audio')
assert (video['codec_name'],video['width'],video['height'],video['avg_frame_rate'],video['pix_fmt'],int(video['nb_read_frames'])) == ('h264',T['width'],T['height'],f"{T['fps']}/1",'yuv420p',T['frame_count'])
assert (audio['codec_name'],int(audio['sample_rate']),audio['channels']) == ('aac',48000,2)
assert abs(float(video['duration'])-T['duration_seconds'])<.00001 and abs(float(audio['duration'])-T['duration_seconds'])<.0001
assert abs(float(video['start_time'])-float(audio['start_time']))<.001
frames = json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',movie]))['frames']
pts = [float(frame['best_effort_timestamp_time']) for frame in frames]
assert len(pts)==T['frame_count'] and abs(pts[0])<.000001 and abs(pts[-1]-(T['frame_count']-1)/T['fps'])<.000001
assert all(abs(b-a-1/T['fps'])<.000002 for a,b in zip(pts,pts[1:]))

checks = sorted({0,*T['keyframes'],*T['verification']['extra_frames'],*T['verification']['motion_pair'],*T['verification']['stable_pair']})
for frame in checks:
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf',rf'select=eq(n\,{frame})','-vsync','0','-frames:v','1',DECODED/f'frame-{frame:03d}.png'])
run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-map','0:a:0','-acodec','pcm_f32le','-f','f32le',CACHE/'decoded-audio.f32'])
meter = subprocess.run(['ffmpeg','-hide_banner','-i',str(movie),'-vn','-af','ebur128=peak=true','-f','null','-'],capture_output=True,encoding='utf-8',errors='strict',check=True)
(CACHE/'audio-loudness.log').write_text(meter.stderr,encoding='utf-8')
summary = meter.stderr.rsplit('Summary:',1)[-1]
loudness = {'integratedLUFS':float(re.search(r'I:\s+(-?[\d.]+) LUFS',summary).group(1)),'truePeakDbfs':float(re.search(r'Peak:\s+(-?[\d.]+) dBFS',summary).group(1))}
assert loudness['truePeakDbfs'] < -1

motion = difference(*(DECODED/f'frame-{f:03d}.png' for f in T['verification']['motion_pair']),box=(950,350,1460,940))
report_hold = difference(*(DECODED/f'frame-{f:03d}.png' for f in T['verification']['stable_pair']))
brand = next(hold for hold in T['read_holds'] if hold['kind']=='brand')
brand_hold = difference(DECODED/f"frame-{brand['first']:03d}.png",DECODED/f"frame-{brand['last']:03d}.png")
assert motion['pixels_over_8']>150
assert report_hold['mean_absolute_channel_error']<.3 and brand_hold['mean_absolute_channel_error']<.3
random_access = {}
for frame in T['verification']['random_frames']:
    delta = difference(CACHE/'frames'/f'frame-{frame:03d}.png',CACHE/'random-access'/f'frame-{frame:03d}.png')
    random_access[frame] = delta
    assert delta['fraction_over_8']<.005 and delta['mean_absolute_channel_error']<.15
approved_match = {}
for frame in T['keyframes']:
    # Only the bottom-right review-edition marker changes in the final edition.
    delta = difference(CACHE/'frames'/f'frame-{frame:03d}.png',ROOT/'preview'/f'frame-{frame:03d}.png',(0,0,1920,990))
    approved_match[frame] = delta
    assert delta['fraction_over_8']<.005 and delta['mean_absolute_channel_error']<.15,f'Approved keyframe changed: {frame}'

names = ['完整工作台','聚焦输入框','展开 Skills','选择产品对比','并行研究','查看执行记录','阅读报告','品牌收尾']
height = 230 + math.ceil(len(T['keyframes'])/2)*640
sheet = Image.new('RGB',(2060,height),'#f5f5f7')
draw = ImageDraw.Draw(sheet)
draw.text((60,36),'星图工作台 / 成片检查图',font=font(38,True),fill='#202126')
draw.text((60,94),f"{T['duration_seconds']} 秒 · {T['frame_count']} 帧 · 以下八帧均从本次 MP4 解码提取",font=font(23),fill='#686d78')
for index,frame in enumerate(T['keyframes']):
    x,y = 60+(index%2)*1000,160+(index//2)*640
    draw.text((x,y),f'{index+1:02d} / {names[index]}',font=font(25,True),fill='#25282f')
    draw.text((x+610,y+2),f"{frame/T['fps']:.1f} 秒 · 第 {frame} 帧",font=font(21),fill='#0068d6')
    sheet.paste(Image.open(DECODED/f'frame-{frame:03d}.png').convert('RGB').resize((940,529),Image.Resampling.LANCZOS),(x,y+43))
    draw.rectangle((x,y+43,x+940,y+572),outline='#dadee3',width=1)
digest = sha(movie)
draw.text((60,height-54),f'合成演示 · 流程已压缩    |    H.264 + AAC    |    SHA-256：{digest[:24]}…',font=font(23),fill='#626670')
sheet.save(FINAL/'check-sheet.png')
Image.open(DECODED/'frame-045.png').save(FINAL/'poster.png')
for name,selected in [
    ('opening-skills',[45,59,60,75,89,105,119,120,123,150,175,179,180,181,210,239]),
    ('execution-closing',[240,255,270,285,329,330,344,345,356,375,390,405,435,480,510,539]),
]:
    contact = Image.new('RGB',(1920,math.ceil(len(selected)/4)*300),'#e8e9ed')
    draw = ImageDraw.Draw(contact)
    for index,frame in enumerate(selected):
        x,y = (index%4)*480,(index//4)*300
        contact.paste(Image.open(DECODED/f'frame-{frame:03d}.png').resize((480,270)),(x,y+26))
        draw.text((x+9,y+3),f"{frame} / {frame/T['fps']:.3f}s",font=font(18),fill='#24262c')
    contact.save(CACHE/f'{name}-check.png')
audit = {'movie_sha256':digest,'video':video,'audio':audio,'container_duration':probe['format']['duration'],'video_frames':len(pts),'video_pts_first':pts[0],'video_pts_last':pts[-1],'constant_frame_timestamps':True,'decoded_running_motion':motion,'decoded_report_hold':report_hold,'decoded_brand_hold':brand_hold,'random_access_pixels':random_access,'approved_keyframe_match':approved_match,'loudness':loudness,'encoding_command':[str(x) for x in command],'check_sheet_source':'decoded frames of this exact product-demo.mp4'}
(CACHE/'video-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
run(['node',ROOT/'source/build-player.mjs'])
print(json.dumps({'movie':str(movie),'sha256':digest,'frames':len(pts),'audio':audio['codec_name'],'loudness':loudness},ensure_ascii=False))
