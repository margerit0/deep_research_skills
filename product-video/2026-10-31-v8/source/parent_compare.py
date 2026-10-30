"""The parent film is the reference: outside the report windows a revision must not change the picture."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

PARENT = Path(__file__).resolve().parent.parent.parent / '2026-10-30-v7'
PARENT_FRAMES = PARENT / 'cache/final/frames'
LABEL = (1600, 990, 1920, 1080)  # The edition label names the version by design.
THRESHOLD = 8  # Per-channel difference a viewer could notice; below it only raster noise remains.
COVER_DIP = 8  # scene.js: the chapter cover is opaque this many frames after the shot starts and before it ends.


def report_windows(plan):
    """Half-open frame ranges in which the report (or its left copy) is on screen."""
    shots = {s['id']: s for s in plan['shots']}
    fps = float(plan['video']['fps'])
    chapter = shots['chapter-card']
    return [
        (shots['report']['startFrame'], chapter['startFrame'] + COVER_DIP),
        (chapter['endFrameExclusive'] - COVER_DIP, shots['feedback']['startFrame'] + round(.5 * fps)),
    ]


def masked(path):
    image = Image.open(path).convert('RGB')
    ImageDraw.Draw(image).rectangle(LABEL, fill='white')
    return image


def frame_change(frames, frame):
    name = f'frame-{frame:04d}.png'
    red, green, blue = ImageChops.difference(masked(frames / name), masked(PARENT_FRAMES / name)).split()
    peak = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    histogram = peak.histogram()
    changed = sum(histogram[THRESHOLD + 1:])
    return {
        'frame': frame,
        'changedPixels': changed,
        'peak': max(value for value, count in enumerate(histogram) if count),
        'box': peak.point(lambda value: 255 if value > THRESHOLD else 0).getbbox() if changed else None,
    }


def ranges(frames):
    runs = []
    for frame in frames:
        if runs and runs[-1][1] == frame:
            runs[-1][1] = frame + 1
        else:
            runs.append([frame, frame + 1])
    return runs


def compare(frames, plan):
    """Compare a full render with the parent's cached frames; raises when a change escapes the windows."""
    frames = Path(frames)
    if not PARENT_FRAMES.exists():
        return {'version': PARENT.name, 'status': 'skipped', 'reason': 'Parent frame cache is not present; regenerate it from the parent version to repeat this comparison.'}
    total = plan['video']['totalFrames']
    with ThreadPoolExecutor(8) as pool:
        changes = list(pool.map(lambda frame: frame_change(frames, frame), range(total)))
    windows = report_windows(plan)
    changed = [c for c in changes if c['changedPixels']]
    outside = [c['frame'] for c in changed if not any(a <= c['frame'] < b for a, b in windows)]
    assert not outside, ('Picture changed outside the report windows', ranges(outside))
    quiet = [c['peak'] for c in changes if not c['changedPixels']]
    return {
        'version': PARENT.name,
        'status': 'compared',
        'method': f'Per-channel difference above {THRESHOLD} of 255 on any pixel, edition label masked',
        'intendedWindows': windows,
        'changedRanges': ranges([c['frame'] for c in changed]),
        'changedFrames': len(changed),
        'unchangedFrames': total - len(changed),
        'changedOutsideWindows': 0,
        'peakDifferenceInUnchangedFrames': max(quiet),
        'perFrame': [{key: c[key] for key in ('frame', 'changedPixels', 'box')} for c in changed],
    }
