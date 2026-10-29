"""Compile the editable timeline; adapt the native scene to the same frame plan."""
from pathlib import Path
from timeline import compile_timeline, read_json, write_json

ROOT = Path(__file__).resolve().parent.parent
plan = compile_timeline(read_json(ROOT / 'timeline.json'))
write_json(ROOT / 'plan.json', plan)
fps = float(plan['video']['fps'])
events = plan['events']
focus = next(e['frame'] for e in events if e['id']=='focus-input')
legacy = {
    'fps':fps,'frame_count':plan['video']['totalFrames'],
    'duration_seconds':plan['video']['durationSeconds'],
    'camera':{'opening_start':focus,'opening_end':focus+round(fps)-1,
              'copy_reveal_start':focus+round(fps),'copy_reveal_end':focus+round(fps*1.5)-1},
    'events':events,
    'shots':[{**s['data'],'id':s['id'],'label':s['label'],'start':s['startFrame'],'end':s['endFrameExclusive']-1} for s in plan['shots']],
}
write_json(ROOT/'native-timeline.json',legacy)
print(plan['video'], plan['planSha256'])
