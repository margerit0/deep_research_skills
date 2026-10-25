"""Encode the approved-scope motion excerpt and assemble the five-frame preview."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
TIMELINE = json.loads((ROOT / 'timeline.json').read_text(encoding='utf-8-sig'))
PREVIEW = ROOT / 'preview'
CACHE = ROOT / 'cache'

def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, encoding='utf-8', errors='strict')
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:])
    return result.stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def font(size, bold=False):
    override = os.environ.get('VIDEO_CJK_FONT_BOLD' if bold else 'VIDEO_CJK_FONT')
    candidates = [override, 'C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/Noto Sans SC.ttf']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    raise RuntimeError('Set VIDEO_CJK_FONT and VIDEO_CJK_FONT_BOLD to installed Chinese fonts.')

sample = TIMELINE['motion_sample']
first, last = sample['first_frame'], sample['last_frame']
movie = PREVIEW / 'motion-sample.mp4'
command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-framerate', str(TIMELINE['fps']), '-start_number', str(first), '-i', CACHE / 'frames/frame-%03d.png', '-frames:v', str(last-first+1), '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(TIMELINE['fps']), '-movflags', '+faststart', movie]
run(command)
probe = json.loads(run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', movie]))
stream = probe['streams'][0]
assert (stream['codec_name'], stream['width'], stream['height'], stream['avg_frame_rate'], int(stream['nb_read_frames'])) == ('h264', 1920, 1080, '30/1', last-first+1)
assert len(probe['streams']) == 1, 'This is the silent preview excerpt, not the final scored video.'
assert abs(float(stream['duration']) - (last-first+1)/30) < 0.001

decoded = CACHE / 'decoded'
decoded.mkdir(exist_ok=True)
for frame in (100, 110, 150, 165, 195, 225, 239):
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',movie,'-vf',rf'select=eq(n\,{frame-first})','-vsync','0','-frames:v','1',decoded/f'frame-{frame:03d}.png'])

def difference(a, b, box=None):
    im_a, im_b = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    if box:
        im_a, im_b = im_a.crop(box), im_b.crop(box)
    diff = ImageChops.difference(im_a, im_b)
    changed = sum(max(pixel) > 8 for pixel in diff.get_flattened_data())
    return {'pixels_over_8': changed, 'fraction_over_8': changed / (diff.width*diff.height), 'mean_absolute_channel_error': sum(ImageStat.Stat(diff).mean) / 3}

motion = difference(decoded/'frame-100.png', decoded/'frame-110.png', (950,350,1460,940))
assert motion['pixels_over_8'] > 150, 'No meaningful decoded native graph motion was detected.'
stopped = difference(decoded/'frame-225.png', decoded/'frame-239.png')
assert stopped['mean_absolute_channel_error'] < 0.2, 'Stable report hold changed unexpectedly.'

random_access = {}
for f in [255,45,195,105,345,100,110,150,165,239,225]:
    random_access[f] = difference(CACHE/'frames'/f'frame-{f:03d}.png', CACHE/'random-access'/f'frame-{f:03d}.png')
    # Windows compositor can change colored subpixel rims on gray glyphs. Geometry,
    # strings, camera, SVG paths and animation phases are compared exactly by the
    # capture script. Pixel tolerance covers these inspected antialiasing rims only.
    assert random_access[f]['fraction_over_8'] < 0.005 and random_access[f]['mean_absolute_channel_error'] < 0.1, f'Random access pixel mismatch at frame {f}'

width, height = 2060, 2150
canvas = Image.new('RGB', (width,height), '#f5f5f7')
d = ImageDraw.Draw(canvas)
d.text((60,36), '星图工作台 / 12 秒产品演示', font=font(38,True), fill='#202126')
d.text((60,94), '预览 v1 · 五张实渲关键帧 · 同一场景源码与时间轴', font=font(23), fill='#686d78')
labels = [
    ('01 / 提出问题', '1.5 秒 · 第 45 帧', '已填好的原文问题；保持输入区正常比例'),
    ('02 / 并行研究', '3.5 秒 · 第 105 帧', '三个研究方向；保留汇总与返回回路'),
    ('03 / 执行记录', '6.5 秒 · 第 195 帧', '商业节点检查器；执行记录落位后停留'),
    ('04 / 阅读报告', '8.5 秒 · 第 255 帧', '完整合成报告；取景落位后静止 2.5 秒'),
    ('05 / 品牌收尾', '11.5 秒 · 第 345 帧', '候选标语；最终画面静止 1 秒'),
]
for i, (frame, label) in enumerate(zip(TIMELINE['keyframes'], labels)):
    x, y = 60+(i%2)*1000, 160+(i//2)*640
    d.text((x,y), label[0], font=font(25,True), fill='#25282f')
    d.text((x+610,y+2), label[1], font=font(21), fill='#0068d6')
    image = Image.open(PREVIEW/f'frame-{frame:03d}.png').convert('RGB').resize((940,529),Image.Resampling.LANCZOS)
    canvas.paste(image,(x,y+43))
    d.rectangle((x,y+43,x+940,y+572), outline='#daddE3', width=1)
    d.text((x,y+577), label[2], font=font(19), fill='#6c707a')
x,y = 1060,1480
d.text((x,y), '本版方案',font=font(30,True),fill='#25282f')
notes = ['1920 × 1080 / 30 fps / 12 秒', '银白界面 · 原生组件 · 局部取景', '图谱运动 1.8 秒 / 状态呼吸 1.7 秒', '点击：5.0 秒节点 / 5.5 秒执行记录', '本次交付：五帧 + 6 秒无声动效小样', '正式配乐与完整 MP4：确认预览后制作']
for n,text in enumerate(notes):
    d.text((x,y+62+n*52),text,font=font(24),fill='#626670')
d.text((60,2096),'合成演示 · 流程已压缩    |    标语候选：让研究的每一步，看得见。',font=font(23),fill='#626670')
canvas.save(PREVIEW/'storyboard-overview.png')

verification = {'sample_sha256':sha(movie),'sample_frame_range':[first,last],'sample_frame_count':last-first+1,'sample_duration_seconds':(last-first+1)/30,'audio':'not produced at preview stage','video_stream':stream,'decoded_running_motion':motion,'decoded_stable_report':stopped,'random_access_pixels':random_access,'encoding_command':[str(x) for x in command]}
(CACHE/'media-audit.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
items = ''.join(f'<a href="frame-{f:03d}.png"><img src="frame-{f:03d}.png" alt="{label[0]}"><span>{label[1]} · {label[0]}</span></a>' for f,label in zip(TIMELINE['keyframes'],labels))
html = '''<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>星图工作台 · 视频预览 v1</title><style>body{margin:40px auto;max-width:1200px;padding:0 24px;background:#f5f5f7;color:#202126;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}h1{font-size:34px}p{color:#626670}video{width:100%;border-radius:18px;background:#eee}section{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:32px}a{color:#005bbb;text-decoration:none}img{width:100%;border-radius:12px;border:1px solid #ddd}span{display:block}footer{margin:35px 0;padding:18px;border-top:1px solid #ddd}@media(max-width:700px){section{grid-template-columns:1fr}}</style></head><body><h1>星图工作台 · 产品演示预览 v1</h1><p>12 秒方案：问题 → 并行研究 → 执行记录 → 报告 → 品牌。下方为 2–8 秒的无声动效小样。</p><video id="motion" controls preload="metadata" poster="frame-105.png"><source src="motion-sample.mp4" type="video/mp4"></video><p><a href="../source/index.html">播放完整交互分镜 / 拖动逐帧检查</a>　·　<a href="storyboard-overview.png">打开五帧总览</a>　·　<a href="verification.md">检查记录</a></p><section>''' + items + '''</section><footer>合成演示 · 流程已压缩。候选标语：让研究的每一步，看得见。<br>本版等待确认；正式配乐与完整 MP4 尚未制作。仅使用仓库内置原创合成数据。</footer></body></html>'''
(PREVIEW/'index.html').write_text(html,encoding='utf-8')
print(json.dumps({'movie':str(movie),'sha256':sha(movie),'motion':motion,'stopped':stopped,'overview':str(PREVIEW/'storyboard-overview.png')},ensure_ascii=False))
