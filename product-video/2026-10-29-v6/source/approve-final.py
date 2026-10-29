"""Record the user's explicit approval of the current v6 preview."""
from pathlib import Path
import hashlib
import json
import shutil
from timeline import load_plan, write_json

ROOT = Path(__file__).resolve().parent.parent
plan = load_plan(ROOT / 'plan.json')
assert plan['planSha256'] == 'f5252340c47c84f7f832da0c2218a43a72f42260bac29e2e74863d6fe619ad2c'
approval = {
    'status': 'approved', 'version': ROOT.name, 'date': '2026-10-29',
    'timezone': 'Europe/Amsterdam', 'planSha256': plan['planSha256'],
    'evidence': '用户在新增章节卡的 v6 预览后明确回复：制作完整视频',
    'scope': '53 秒、1920×1080、30 fps；沿用已确认的章节卡和镜头安排，制作原创配乐成片；按此前请求更新 README 本地视频入口。',
    'previewSha256': {name: hashlib.sha256((ROOT / 'preview' / name).read_bytes()).hexdigest()
                      for name in ['bridge.mp4', 'context.mp4', 'storyboard-overview.png', 'index.html']},
}
write_json(ROOT / 'approval.json', approval)
for original, saved in [('timeline.json', 'approved-timeline.json'), ('brief.json', 'approved-brief.json'), ('preview/index.html', 'approved-index.html')]:
    destination = ROOT / 'preview' / saved
    if not destination.exists():
        shutil.copyfile(ROOT / original, destination)
status_path = ROOT.parent / 'status.json'
status = json.loads(status_path.read_text(encoding='utf-8'))
current = next(v for v in status['versions'] if v['id'] == ROOT.name)
current.update(state='rendering', approval={'planSha256': plan['planSha256'], 'evidence': approval['evidence']})
write_json(status_path, status)
print('Approved exact v6 plan; final rendering may begin.')
