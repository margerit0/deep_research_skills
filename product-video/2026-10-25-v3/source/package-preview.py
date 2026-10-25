"""Encode the silent revision excerpt and inspect its decoded frames."""
from pathlib import Path
import hashlib
import json
import math
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
T = json.loads((ROOT / 'timeline.json').read_text(encoding='utf-8-sig'))
PREVIEW, CACHE = ROOT / 'preview', ROOT / 'cache'

def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, encoding='utf-8', errors='strict')
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:])
    return result.stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def font(size, bold=False):
    custom = os.environ.get('VIDEO_CJK_FONT_BOLD' if bold else 'VIDEO_CJK_FONT')
    path = custom or ('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc')
    return ImageFont.truetype(path, size)

def difference(a, b, box=None):
    a, b = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    if box:
        a, b = a.crop(box), b.crop(box)
    delta = ImageChops.difference(a, b)
    changed = sum(max(pixel) > 8 for pixel in delta.get_flattened_data())
    return {'pixels_over_8': changed, 'fraction_over_8': changed / (delta.width * delta.height), 'mean_absolute_channel_error': sum(ImageStat.Stat(delta).mean) / 3}

first, last = T['motion_sample']['first_frame'], T['motion_sample']['last_frame']
count = last - first + 1
seconds = count / T['fps']
movie = PREVIEW / 'motion-sample.mp4'
command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', str(T['fps']), '-start_number', str(first), '-i', CACHE / 'frames/frame-%03d.png', '-frames:v', str(count), '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(T['fps']), '-movflags', '+faststart', movie]
run(command)
probe = json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', movie]))
stream = probe['streams'][0]
assert (stream['codec_name'], stream['width'], stream['height'], stream['avg_frame_rate'], int(stream['nb_read_frames'])) == ('h264', T['width'], T['height'], f"{T['fps']}/1", count)
assert len(probe['streams']) == 1 and abs(float(stream['duration']) - seconds) < .001
frame_data = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', movie]))['frames']
pts = [float(frame['best_effort_timestamp_time']) for frame in frame_data]
assert len(pts) == count and all(abs(b-a-1/T['fps']) < .000002 for a,b in zip(pts, pts[1:]))

decoded = CACHE / 'decoded'
decoded.mkdir(exist_ok=True)
frames = sorted({first, last, *T['keyframes'], *T['verification']['extra_frames'], *T['verification']['motion_pair'], *T['verification']['stable_pair']})
for frame in frames:
    if first <= frame <= last:
        run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf',rf'select=eq(n\,{frame-first})','-vsync','0','-frames:v','1',decoded/f'frame-{frame:03d}.png'])

motion_pair, stable_pair = T['verification']['motion_pair'], T['verification']['stable_pair']
motion = difference(*(decoded/f'frame-{f:03d}.png' for f in motion_pair), box=(950,350,1460,940))
stopped = difference(*(decoded/f'frame-{f:03d}.png' for f in stable_pair))
assert motion['pixels_over_8'] > 150
assert stopped['mean_absolute_channel_error'] < .2
random_access = {}
for frame in T['verification']['random_frames']:
    delta = difference(CACHE/'frames'/f'frame-{frame:03d}.png', CACHE/'random-access'/f'frame-{frame:03d}.png')
    random_access[frame] = delta
    # Semantic state is compared exactly by the renderer. Tolerance only covers
    # inspected Windows text antialiasing differences between fresh pages.
    assert delta['fraction_over_8'] < .005 and delta['mean_absolute_channel_error'] < .1, f'Random access mismatch at {frame}'

labels = [
    ('完整工作台', '全屏完整 UI 稳定 2 秒，保持正常浏览器比例'),
    ('聚焦输入框', '2–3 秒连续聚焦；3–4 秒展示原文问题'),
    ('展开 Skills', '显示原生菜单及 5 个真实选项，当前为自动选择'),
    ('选择产品对比', '点击后关闭菜单，展示选中标签和说明 2 秒'),
    ('并行研究', '三个方向同时展开，保留汇总和返回回路'),
    ('查看执行记录', '商业节点检查器；执行记录落位后停留'),
    ('阅读报告', '完整合成报告；相机落位后稳定阅读 2.5 秒'),
    ('品牌收尾', '沿用已确认标语；最终画面静止 1 秒'),
]
height = 230 + math.ceil(len(labels)/2)*640
canvas = Image.new('RGB', (2060, height), '#f5f5f7')
draw = ImageDraw.Draw(canvas)
draw.text((60,36), f"星图工作台 / {T['duration_seconds']} 秒产品演示", font=font(38,True), fill='#202126')
draw.text((60,94), '预览 v3 · 完整 UI 2 秒 → 聚焦输入框 → 选择 Skills → 开始研究', font=font(23), fill='#686d78')
for index, (frame, label) in enumerate(zip(T['keyframes'], labels)):
    x,y = 60+(index%2)*1000,160+(index//2)*640
    draw.text((x,y), f'{index+1:02d} / {label[0]}', font=font(25,True), fill='#25282f')
    draw.text((x+610,y+2), f"{frame/T['fps']:.1f} 秒 · 第 {frame} 帧", font=font(21), fill='#0068d6')
    canvas.paste(Image.open(PREVIEW/f'frame-{frame:03d}.png').convert('RGB').resize((940,529),Image.Resampling.LANCZOS), (x,y+43))
    draw.rectangle((x,y+43,x+940,y+572), outline='#dadde3', width=1)
    draw.text((x,y+577), label[1], font=font(19), fill='#6c707a')
draw.text((60,height-54), f"合成演示 · 流程已压缩    |    {T['duration_seconds']} 秒方案 · {seconds:g} 秒无声小样 · 等待 v3 预览确认", font=font(23), fill='#626670')
canvas.save(PREVIEW/'storyboard-overview.png')

contact_frames = [45,59,60,75,89,105,119,120,123,150,175,179,180,181,210,239]
contact = Image.new('RGB', (1920,1200), '#eceef2')
draw = ImageDraw.Draw(contact)
for index,frame in enumerate(contact_frames):
    x,y = (index%4)*480,(index//4)*300
    draw.text((x+8,y+2),f"{frame} / {frame/T['fps']:.3f}s",font=font(17),fill='#25282f')
    contact.paste(Image.open(decoded/f'frame-{frame:03d}.png').resize((480,270)),(x,y+26))
contact.save(CACHE/'opening-and-skills-check.png')

audit = {'sample_sha256':sha(movie),'sample_frame_range':[first,last],'sample_frame_count':count,'sample_duration_seconds':seconds,'audio':'not produced at preview stage','video_stream':stream,'constant_frame_timestamps':True,'decoded_running_motion':motion,'decoded_stable_report':stopped,'random_access_pixels':random_access,'encoding_command':[str(x) for x in command]}
(CACHE/'media-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
cards = ''.join(f'<a href="frame-{frame:03d}.png"><img src="frame-{frame:03d}.png" alt="{label[0]}"><span>{frame/T["fps"]:.1f} 秒 · {label[0]}</span></a>' for frame,label in zip(T['keyframes'],labels))
template = (ROOT/'source/preview.html').read_text(encoding='utf-8')
(PREVIEW/'index.html').write_text(template.replace('{{cards}}',cards),encoding='utf-8')
print(json.dumps({'movie':str(movie),'sha256':sha(movie),'frames':count,'seconds':seconds,'motion':motion,'stopped':stopped},ensure_ascii=False))
