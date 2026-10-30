"""Compile one editable timeline into frame/sample coordinates. Python 3.10+."""

import argparse
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def number(value, name, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f"{name}: expected a number, not a boolean")
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"{name}: expected a finite number or rational string") from error
    if result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{name}: must be {'non-negative' if allow_zero else 'positive'}")
    return result


def integer(value, name):
    result = number(value, name)
    if result.denominator != 1:
        raise ValueError(f"{name}: must be an integer")
    return int(result)


def nearest(value):
    """Round non-negative fractions half up; never accumulate rounded intervals."""
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def compile_timeline(source):
    if source.get("schemaVersion") != 1:
        raise ValueError("timeline.schemaVersion must be 1")
    video = source["video"]
    fps = number(video["fps"], "video.fps")
    width = integer(video["width"], "video.width")
    height = integer(video["height"], "video.height")
    if width % 2 or height % 2:
        raise ValueError("yuv420p requires even video dimensions")
    audio = source.get("audio", {})
    bpm = number(audio.get("bpm", 120), "audio.bpm")
    sample_rate = integer(audio.get("sampleRate", 48000), "audio.sampleRate")
    if sample_rate not in (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000):
        raise ValueError("audio.sampleRate must be supported by AAC")
    originals = source.get("shots", [])
    if not originals:
        raise ValueError("timeline needs at least one shot")
    shots, events, keyframes, holds = [], [], [], []
    shot_map, event_ids = {}, set()
    elapsed = Fraction(0)
    for original in originals:
        shot_id = original["id"]
        if not isinstance(shot_id, str) or not shot_id or shot_id in shot_map:
            raise ValueError(f"invalid/duplicate shot id: {shot_id}")
        duration = number(original["durationSeconds"], f"{shot_id}.durationSeconds")
        start = nearest(elapsed * fps)
        elapsed += duration
        end = nearest(elapsed * fps)
        if end <= start:
            raise ValueError(f"{shot_id}: shot is shorter than one frame")
        shot = {"id": shot_id, "label": original.get("label", shot_id),
                "startFrame": start, "endFrameExclusive": end,
                "frameCount": end - start, "startSeconds": float(Fraction(start, 1) / fps),
                "durationSeconds": float(Fraction(end - start, 1) / fps),
                "data": original.get("data", {})}
        shot_map[shot_id] = (shot, duration)
        shots.append(shot)

        def local_frame(value, allow_end=False):
            at = number(value, f"{shot_id}.atSeconds", allow_zero=True)
            if at > duration or (at == duration and not allow_end):
                raise ValueError(f"{shot_id}: offset outside the shot: {value}")
            if at == duration:
                return end
            return min(end if allow_end else end - 1, start + nearest(at * fps))

        selected = original.get("keyframes", [])
        if not selected:
            raise ValueError(f"{shot_id}: choose at least one representative keyframe")
        for item in selected:
            keyframes.append({"shot": shot_id, "frame": local_frame(item["atSeconds"]),
                              "label": item.get("label", shot["label"])})
        for item in original.get("events", []):
            event_id = item["id"]
            if not isinstance(event_id, str) or not event_id or event_id in event_ids:
                raise ValueError(f"invalid/duplicate event id: {event_id}")
            event_ids.add(event_id)
            requested = number(item["atSeconds"], event_id, allow_zero=True)
            local_frame(requested)  # Validate the requested offset before snapping.
            exact_time = Fraction(start, 1) / fps + requested
            snap = item.get("snapToBeat", True)
            if not isinstance(snap, bool):
                raise ValueError(f"{event_id}: snapToBeat must be boolean")
            if not snap and not item.get("reason"):
                raise ValueError(f"{event_id}: unsnapped actions need a reason")
            beat_index = nearest(exact_time * bpm / 60) if snap else None
            frame = nearest(Fraction(beat_index * 60, 1) / bpm * fps) if snap else local_frame(requested)
            if not start <= frame < end:
                raise ValueError(f"{event_id}: beat snapping leaves its shot; adjust the offset")
            events.append({**item, "shot": shot_id, "frame": frame, "beatIndex": beat_index,
                           "seconds": float(Fraction(frame, 1) / fps),
                           "sample": nearest(Fraction(frame * sample_rate, 1) / fps)})
        for item in original.get("holds", []):
            hold_at = number(item["atSeconds"], "hold.atSeconds", allow_zero=True)
            hold_duration = number(item["durationSeconds"], "hold.durationSeconds")
            hold_start = local_frame(hold_at)
            hold_end = local_frame(hold_at + hold_duration, allow_end=True)
            minimum = number(item.get("minSeconds", 0), "hold.minSeconds", allow_zero=True)
            if hold_end <= hold_start or Fraction(hold_end - hold_start, 1) / fps < minimum:
                raise ValueError(f"{shot_id}: stable hold is shorter than its minimum")
            holds.append({"shot": shot_id, "label": item.get("label", ""),
                          "startFrame": hold_start, "endFrameExclusive": hold_end,
                          "durationSeconds": float(Fraction(hold_end - hold_start, 1) / fps)})

    total_frames = shots[-1]["endFrameExclusive"]
    duration = Fraction(total_frames, 1) / fps
    beats = []
    beat_index = 0
    while Fraction(beat_index * 60, 1) / bpm < duration:
        ideal = Fraction(beat_index * 60, 1) / bpm
        frame = nearest(ideal * fps)
        if frame < total_frames:
            if beats and frame == beats[-1]["frame"]:
                raise ValueError("BPM too high for this fps: multiple beats map to one frame")
            beats.append({"index": beat_index, "frame": frame,
                          "seconds": float(Fraction(frame, 1) / fps), "idealSeconds": float(ideal),
                          "sample": nearest(Fraction(frame * sample_rate, 1) / fps)})
        beat_index += 1

    def anchor(point):
        shot, requested_duration = shot_map[point["shot"]]
        at = number(point["atSeconds"], "clip.atSeconds", allow_zero=True)
        if at > requested_duration:
            raise ValueError("preview clip anchor outside shot")
        if at == requested_duration:
            return shot["endFrameExclusive"]
        return min(shot["endFrameExclusive"], shot["startFrame"] + nearest(at * fps))

    clips, clip_ids = [], set()
    for item in source.get("previewClips", []):
        clip_id = item["id"]
        if not isinstance(clip_id, str) or not clip_id or clip_id in clip_ids:
            raise ValueError(f"invalid/duplicate clip id: {clip_id}")
        clip_ids.add(clip_id)
        start, end = anchor(item["start"]), anchor(item["end"])
        if not 0 <= start < end <= total_frames:
            raise ValueError(f"invalid preview clip range: {clip_id}")
        clips.append({"id": clip_id, "startFrame": start, "endFrameExclusive": end,
                      "frameCount": end - start, "durationSeconds": float(Fraction(end - start, 1) / fps)})
    plan = {"schemaVersion": 1, "title": source.get("title", "产品演示"),
            "timelineSha256": digest(source),
            "video": {"width": width, "height": height, "fps": str(fps),
                      "totalFrames": total_frames, "durationSeconds": float(duration)},
            "audio": {"bpm": float(bpm), "sampleRate": sample_rate,
                      "sampleCount": nearest(duration * sample_rate)},
            "shots": shots, "events": sorted(events, key=lambda x: x["frame"]),
            "beats": beats, "holds": holds,
            "keyframes": sorted(keyframes, key=lambda x: x["frame"]), "previewClips": clips}
    plan["planSha256"] = digest(plan)
    return plan


def load_plan(path):
    plan = read_json(path)
    claimed = plan.get("planSha256")
    if plan.get("schemaVersion") != 1 or claimed != digest({k: v for k, v in plan.items() if k != "planSha256"}):
        raise ValueError("invalid or manually changed plan.json; recompile timeline.json")
    return plan


def frame_range(plan, clip_id=None):
    if clip_id is None:
        return 0, plan["video"]["totalFrames"]
    for clip in plan["previewClips"]:
        if clip["id"] == clip_id:
            return clip["startFrame"], clip["endFrameExclusive"]
    raise ValueError(f"unknown preview clip: {clip_id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if Path(args.timeline).resolve() == Path(args.out).resolve():
        raise ValueError("timeline input and generated plan must be different files")
    plan = compile_timeline(read_json(args.timeline))
    write_json(args.out, plan)
    print(json.dumps(plan["video"], ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print(f"timeline: {error}", file=sys.stderr)
        sys.exit(1)
