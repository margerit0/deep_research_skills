"""Record the user's explicit approval of the current v8 preview."""
from pathlib import Path
import hashlib
import shutil
from timeline import load_plan, read_json, write_json

ROOT = Path(__file__).resolve().parent.parent
PRE = ROOT / 'preview'
plan = load_plan(ROOT / 'plan.json')
assert plan['planSha256'] == 'ee144eb8a1cf0b7550aaa673a327f4eac7b36835ca29560725f1fd8998831f80'
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
revision = read_json(ROOT / 'source/revision.json')
# Keep the page, timeline and brief exactly as the user saw them.
for original, saved in [('timeline.json', 'approved-timeline.json'), ('brief.json', 'approved-brief.json'), ('preview/index.html', 'approved-index.html')]:
    destination = PRE / saved
    if not destination.exists():
        shutil.copyfile(ROOT / original, destination)
approval = {
    'status': 'approved', 'version': ROOT.name, 'date': '2026-10-31',
    'timezone': 'Asia/Shanghai', 'planSha256': plan['planSha256'], 'basis': 'user-approved-preview',
    'evidence': '用户在 v8 预览后明确回复：确认 v8 预览：左侧文案改为「下一步单独列出。」，卡片保留「51 秒」和「Qwen3.5」，开始制作完整视频。',
    'scope': '53 秒、1920×1080、30 fps；沿用 v7 的镜头顺序、时长与配乐，报告片段同步为新版报告卡片，左侧说明第二行改为「下一步单独列出。」，卡片保留原生元信息。不包含发布、提交或修改根 README；听感验收另行记录。',
    'previewSha256': {name: sha(PRE / 'approved-index.html' if name == 'index.html' else PRE / name) for name in ['report.mp4', 'storyboard-overview.png', 'v7-v8-comparison.png', 'index.html']},
}
write_json(ROOT / 'approval.json', approval)
# The preview must stop asking for a decision that has been made.
page = (PRE / 'approved-index.html').read_text(encoding='utf-8')
for old, new in [
    ('v8 · 预览待确认', 'v8 · 预览已确认'),
    ('<h2>需要你确认的文案</h2>', '<h2>已确认的文案</h2>'),
    ('确认后才制作完整视频。', '用户已于 2026-10-31 确认本预览，<a href="../final/index.html">完整视频</a>据此制作。'),
    ("<td class='state'>待确认</td>", "<td class='state'>已确认</td>"),
    ('左侧第二行提出修改方案，等你确认。', '左侧第二行按用户确认改为「下一步单独列出。」。'),
    ('默认保留原生界面，片中没有把它说成响应速度。', '用户确认保留原生界面，片中没有把它说成响应速度。'),
    ('根 README 仍指向 v6，产品演示入口仍指向 v7，v8 完成前不切换。', ''),
]:
    assert old in page or old.startswith('<td class'), old
    page = page.replace(old, new)
page = page.replace('<td class="state">待确认</td>', '<td class="state">已确认</td>')
assert '待确认' not in page
(PRE / 'index.html').write_text(page, encoding='utf-8')
record = (PRE / 'verification.md').read_text(encoding='utf-8')
for old, new in [
    ('## 未完成', '## 预览之外'),
    ('- 完整视频、配乐核对与听感验收都要等你确认预览后进行；预览无音轨，主观听音不适用。', '- 预览无音轨，主观听音不适用。用户已于 2026-10-31 确认本预览；完整视频、配乐核对与听感验收的结果见 `../final/verification.md`。'),
]:
    assert old in record or new in record, old
    record = record.replace(old, new)
(PRE / 'verification.md').write_text(record, encoding='utf-8')
brief = read_json(ROOT / 'brief.json')
brief['state'] = 'approved'
brief['revision'].update(approval=approval['evidence'], findings=revision['findings'], copyProposal=revision['copyProposal'], attention=revision['attention'], changes=revision['changes'])
write_json(ROOT / 'brief.json', brief)
status_path = ROOT.parent / 'status.json'
status = read_json(status_path)
current = next(v for v in status['versions'] if v['id'] == ROOT.name)
current.update(state='rendering', approval={'planSha256': plan['planSha256'], 'evidence': approval['evidence']}, changes=revision['changes'])
write_json(status_path, status)
write_json(PRE / 'manifest.json', {'planSha256': plan['planSha256'], 'files': [{'path': p.name, 'sha256': sha(p)} for p in sorted(PRE.iterdir()) if p.is_file() and p.name != 'manifest.json']})
print('Approved exact v8 plan; final rendering may begin.')
