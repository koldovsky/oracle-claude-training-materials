#!/usr/bin/env python3
"""Assemble a timed Ukrainian screen lesson from verified sources and synthesized speech."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FPS = 10
LEAD = 0.5
SITE = "https://koldovsky.github.io/claude-code-oracle-training/"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def timestamp(value, comma=False):
    total = round(value * 1000)
    hours, rest = divmod(total, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, ms = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{',' if comma else '.'}{ms:03}"


def chapter_timing(durations, target, weights=None):
    """Whole video frames, bounded speech adjustment and exact chapter duration."""
    if not durations or target <= 0 or any(d < 0 for d in durations):
        raise ValueError("Invalid chapter durations")
    target_frames = round(target * FPS)
    available = target - len(durations) * (LEAD + 0.6)
    if available <= 0:
        raise ValueError("Chapter has too many scenes")
    speed = max(1.0, sum(durations) / available)
    if speed > 1.12:
        raise ValueError(f"Narration exceeds chapter budget: needs {speed:.2f}x. Shorten the script.")
    frames = [math.ceil((d / speed + LEAD + 0.4) * FPS) for d in durations]
    extra = target_frames - sum(frames)
    if extra < 0:
        raise ValueError("Rounding exceeded chapter budget")
    weights = weights or [max(1, d) for d in durations]
    shares = [extra * w / sum(weights) for w in weights]
    additions = [math.floor(n) for n in shares]
    remainder = extra - sum(additions)
    order = sorted(range(len(shares)), key=lambda i: shares[i] - additions[i], reverse=True)
    for i in order[:remainder]:
        additions[i] += 1
    return speed, [(f + a) / FPS for f, a in zip(frames, additions)]


def source_lines(screen, runs):
    kind = screen["kind"]
    label, context = "", ""
    if kind == "code" and "path" in screen:
        rel = screen["path"]
        path = (REPO / rel).resolve()
        allowed = [REPO / "training/session-2/lab", REPO / "training/session-2/extensions"]
        if not any(path.is_relative_to(p.resolve()) for p in allowed) or path.is_symlink():
            raise ValueError(f"Not a public teaching source: {rel}")
        value = path.read_text(encoding="utf-8")
        label = "КОД ЛАБОРАТОРІЇ"
        context = rel.replace("training/session-2/", "")
        start, end = screen.get("lineStart", 1), screen.get("lineEnd")
    elif kind == "recording":
        run = runs[screen["runId"]]
        index = screen["frameIndex"]
        frame = run["frames"][index]
        value = frame["text"]
        if screen.get("contentField"):
            value = json.loads(value)[screen["contentField"]]
            if not isinstance(value, str):
                raise ValueError("Recorded content field must be text")
        label = "ФРАГМЕНТ СПРАВЖНЬОГО ЗАПИСУ · " + frame.get("tool", frame["kind"])
        context = f"{run['title']} · кадр {index + 1} / {len(run['frames'])}"
        start, end = screen.get("excerptStartLine", 1), screen.get("excerptEndLine")
    else:
        value = screen.get("code", "")
        start, end = 1, None
        label = {"text": "ПОЯСНЕННЯ", "code": "КОМАНДА АБО НАВЧАЛЬНИЙ ПРИКЛАД", "exercise": "САМОСТІЙНА ПРАКТИКА", "break": "ПЕРЕРВА"}[kind]
    lines = value.splitlines()
    end = len(lines) if end is None else min(end, len(lines))
    if lines and (not isinstance(start, int) or start < 1 or start > len(lines) or end < start):
        raise ValueError(f"Invalid source excerpt: {context} {start}:{end}")
    rows = [{"number": i if kind == "code" and "path" in screen else None, "text": lines[i-1],
             "focus": i in screen.get("focusLines", [])} for i in range(start, end + 1)]
    return rows, label, context


def make_plan(script_path, narration_dir, work):
    script = read_json(script_path)
    narration = read_json(narration_dir / "manifest.json")
    takes = {s["id"]: s for s in narration["segments"]}
    script_hash = hashlib.sha256(Path(script_path).read_bytes()).hexdigest()
    if narration.get('sourceSha256') != script_hash:
        raise ValueError('Narration manifest does not match the current script; resume synthesis first')
    if len(takes) != len(narration['segments']):
        raise ValueError('Duplicate narration segment IDs')
    if narration.get('voice') != 'uk-UA-OstapNeural' or narration.get('rate') != '-3%':
        raise ValueError('Narration must use the reviewed Ukrainian voice and rate')
    expected_ids = {c['id']+'--'+s['id'] for c in script['chapters'] for s in c['segments']}
    if set(takes) != expected_ids:
        raise ValueError('Narration segment set does not match the script')
    recorded = read_json(REPO / "tools/session-2-rehearsal-data.json")
    runs = {r["id"]: r for r in recorded["runs"]}
    if sum(c["targetSeconds"] for c in script["chapters"]) != 7200:
        raise ValueError("The full lesson must be exactly 7200 seconds")
    segments, chapters, screens, cues = [], [], [], []
    start = 0.0
    for chapter in script["chapters"]:
        ids = [chapter["id"] + "--" + s["id"] for s in chapter["segments"]]
        if any(not re.fullmatch(r"[a-zA-Z0-9_-]+", sid) for sid in ids):
            raise ValueError("Unsafe segment identifier")
        samples = [takes[sid] for sid in ids]
        for source, sid, take in zip(chapter['segments'], ids, samples):
            expected_text_hash = hashlib.sha256(source['narration'].strip().encode('utf-8')).hexdigest()
            if take.get('textSha256') != expected_text_hash:
                raise ValueError(f'Stale narration text for {sid}')
            if take.get('voice') != narration['voice'] or take.get('rate') != narration['rate']:
                raise ValueError(f'Inconsistent voice provenance for {sid}')
            for field, digest_field in [('audio','audioSha256'),('subtitles','subtitlesSha256')]:
                file = (narration_dir/take[field]).resolve()
                if not file.is_relative_to(narration_dir.resolve()) or file.is_symlink():
                    raise ValueError(f'Unsafe narration artifact path for {sid}')
                if hashlib.sha256(file.read_bytes()).hexdigest() != take.get(digest_field):
                    raise ValueError(f'Changed narration artifact for {sid}: {field}')
            last_end = 0
            for cue in take['captions']:
                if cue['start'] < last_end or cue['end'] <= cue['start'] or cue['end'] > take['durationSeconds'] + .01:
                    raise ValueError(f'Invalid or overlapping narration captions for {sid}')
                last_end = cue['end']
        durations = [t.get("durationSeconds", t.get("duration")) for t in samples]
        weights = [max(1, d) * (3 if s["screen"]["kind"] == "exercise" else 1)
                   for s, d in zip(chapter["segments"], durations)]
        speed, lengths = chapter_timing(durations, chapter["targetSeconds"], weights)
        chapter_start = start
        chapters.append({"id": chapter["id"], "title": chapter["title"], "start": start,
                         "duration": chapter["targetSeconds"], "speechSpeed": speed,
                         "speechSeconds": sum(durations) / speed})
        for source, sid, take, raw_duration, length in zip(chapter["segments"], ids, samples, durations, lengths):
            speech = raw_duration / speed
            item = {"id": sid, "chapterId": chapter["id"], "chapterTitle": chapter["title"],
                    "title": source["title"], "narration": source["narration"], "start": round(start, 3),
                    "duration": length, "speechDuration": speech, "lead": LEAD, "speechSpeed": speed,
                    "audio": str((narration_dir / take["audio"]).resolve()), "kind": source["screen"]["kind"]}
            segments.append(item)
            rows, label, context = source_lines(source["screen"], runs)
            screen = {"title": source["screen"].get("heading", source["title"]),
                      "chapterTitle": chapter["title"], "kind": item["kind"], "label": label,
                      "context": context or "Сесія 2 · Oracle та Claude Code", "start": start}
            if rows:
                screen["lines"] = rows
            if source["screen"].get("bullets"):
                screen["bullets"] = source["screen"]["bullets"]
            screens.append(screen)
            segment_cues = []
            for cue in take["captions"]:
                local_start = LEAD + cue["start"] / speed
                local_end = min(length, LEAD + cue["end"] / speed)
                if local_end <= local_start:
                    raise ValueError("Invalid caption timing")
                local = {"start": round(local_start, 3), "end": round(local_end, 3), "text": cue["text"]}
                segment_cues.append(local)
                cues.append({**local, "start": round(start + local_start, 3), "end": round(start + local_end, 3)})
            write_ass(work / "captions" / (sid + ".ass"), segment_cues)
            start = round(start + length, 3)
        if abs(start - chapter_start - chapter["targetSeconds"]) > 0.01:
            raise ValueError("Chapter rounding mismatch")
    if len({s['id'] for s in segments}) != len(segments) or start != 7200:
        raise ValueError("Invalid final timeline")
    plan = {"title": script["title"], "duration": start, "voice": narration["voice"],
            "rate": narration["rate"], "chapters": chapters, "segments": segments,
            "scriptSha256": hashlib.sha256(Path(script_path).read_bytes()).hexdigest()}
    write_json(work / "timeline.json", plan)
    template = (HERE / "screen.template.html").read_text(encoding="utf-8")
    encoded = json.dumps(screens, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    (work / "screens.html").write_text(template.replace("__SCREEN_DATA__", encoded), encoding="utf-8")
    srt = "\n\n".join(f"{i+1}\n{timestamp(c['start'], True)} --> {timestamp(c['end'], True)}\n{c['text']}" for i, c in enumerate(cues)) + "\n"
    vtt = "WEBVTT\n\n" + "\n\n".join(f"{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}" for c in cues) + "\n"
    (work / "session-2-lesson-uk.srt").write_text(srt, encoding="utf-8")
    (work / "session-2-lesson-uk.vtt").write_text(vtt, encoding="utf-8")
    transcript = [f"# {script['title']}", "", "Синтезований український голос. Тривалість 2 години, включно з перервою та практикою.", ""]
    for chapter in chapters:
        transcript += [f"## {timestamp(chapter['start'])[:8]} · {chapter['title']}", ""]
        for s in segments:
            if s['chapterId'] == chapter['id']:
                transcript += [f"### {s['title']}", "", s['narration'], ""]
    (work / "session-2-lesson-transcript.md").write_text("\n".join(transcript), encoding="utf-8")
    print(f"VIDEO_PLAN_READY: {len(segments)} screens, {len(cues)} cues, {start:.1f} seconds")
    for c in chapters:
        print(f"{c['id']}: speech={c['speechSeconds']:.1f}s / {c['duration']}s, speed={c['speechSpeed']:.3f}")


def write_ass(path, cues):
    def ass_time(value):
        centiseconds = round(value * 100)
        hours, rest = divmod(centiseconds, 360000)
        minutes, rest = divmod(rest, 6000)
        seconds, fraction = divmod(rest, 100)
        return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1600
PlayResY: 900
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI,31,&H00F4F8FA,&H000000FF,&H0003080B,&H0003080B,0,0,0,0,100,100,0,0,1,1,0,2,78,78,18,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = []
    for c in cues:
        text = c["text"].replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", r"\N")
        body.append(f"Dialogue: 0,{ass_time(c['start'])},{ass_time(c['end'])},Default,,0,0,0,,{text}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(body) + "\n", encoding="utf-8-sig")


def run_ffmpeg(command, log):
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    log.write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"FFmpeg failed; see {log}")


def render(work, ffmpeg, workers):
    plan = read_json(work / "timeline.json")
    validation = read_json(work / 'screen-validation.json')
    for name, field in [('timeline.json', 'timelineSha256'), ('screens.html', 'htmlSha256')]:
        if validation.get(field) != hashlib.sha256((work/name).read_bytes()).hexdigest():
            raise ValueError('Screen validation is stale; recapture all screens')
    for s in plan['segments']:
        image = work/'screens'/(s['id']+'.png')
        if validation.get('screens', {}).get(s['id']) != hashlib.sha256(image.read_bytes()).hexdigest():
            raise ValueError('Screen capture is unverified: '+s['id'])
    parts = work / "parts"
    parts.mkdir(exist_ok=True)
    fonts = work / 'fonts'
    fonts.mkdir(exist_ok=True)
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/segoeui.ttf'
    if not font.is_file():
        raise ValueError('Segoe UI font required for Ukrainian video subtitles')
    shutil.copyfile(font, fonts / 'segoeui.ttf')
    render_fingerprint = hashlib.sha256(Path(__file__).read_bytes() + font.read_bytes() +
        subprocess.check_output([str(ffmpeg), '-version'])).hexdigest()
    def one(s):
        image = work / "screens" / (s['id'] + '.png')
        caption = work / "captions" / (s['id'] + '.ass')
        output = parts / (s['id'] + '.mp4')
        wave = output.with_suffix('.wav')
        key = hashlib.sha256(render_fingerprint.encode() + json.dumps(s, sort_keys=True).encode() + image.read_bytes() + caption.read_bytes() + Path(s['audio']).read_bytes()).hexdigest()
        marker = output.with_suffix('.sha256')
        if output.is_file() and wave.is_file() and marker.is_file():
            try:
                saved = read_json(marker)
                if (saved['request'] == key and saved['video'] == hashlib.sha256(output.read_bytes()).hexdigest()
                        and saved['audio'] == hashlib.sha256(wave.read_bytes()).hexdigest()):
                    return s['id'] + ' cached'
            except (ValueError, KeyError, TypeError):
                pass
        # Subtitle paths are generated identifiers, relative to a fixed working directory.
        subtitle_filter = 'subtitles=filename=captions/' + s['id'] + '.ass:fontsdir=fonts'
        end_of_voice = s['lead'] + s['speechDuration']
        pause = s['duration'] - end_of_voice
        if pause > 8:
            pause_text = 'Перерва' if s['kind'] == 'break' else 'Час для читання та практики'
            pause_file = work / ('pause-' + s['id'] + '.txt')
            pause_file.write_text(pause_text, encoding='utf-8')
            subtitle_filter += f",drawtext=textfile={pause_file.name}:fontfile=fonts/segoeui.ttf:fontsize=27:fontcolor=0xc4d8e2:x=(w-tw)/2:y=824:enable='gte(t,{end_of_voice + 0.1:.3f})'"
            subtitle_filter += f",drawtext=text='До продовження %{{eif\\:ceil({s['duration']:.3f}-t)\\:d}} с':fontfile=fonts/segoeui.ttf:fontsize=22:fontcolor=0x87a5b5:x=(w-tw)/2:y=863:enable='gte(t,{end_of_voice + 0.1:.3f})'"
        command = [str(ffmpeg), '-y', '-hide_banner', '-loglevel', 'warning', '-loop', '1', '-framerate', str(FPS), '-i', str(image), '-i', s['audio'],
                   '-map', '0:v', '-vf', subtitle_filter,
                   '-t', f"{s['duration']:.3f}", '-c:v', 'libx264', '-preset', 'veryfast', '-tune', 'stillimage', '-crf', '25',
                   '-r', str(FPS), '-g', '600', '-keyint_min', '600', '-sc_threshold', '0', '-pix_fmt', 'yuv420p', '-threads', '2',
                   '-movflags', '+faststart', str(output), '-map', '1:a',
                   '-af', f"atempo={s['speechSpeed']:.8f},adelay=500,apad,alimiter=limit=0.95",
                   '-t', f"{s['duration']:.3f}", '-c:a', 'pcm_s16le', '-ac', '1', '-ar', '24000', str(wave)]
        result = subprocess.run(command, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        output.with_suffix('.log').write_text(result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f"Render failed for {s['id']}: {result.stderr[-1200:]}")
        write_json(marker, {'request': key, 'video': hashlib.sha256(output.read_bytes()).hexdigest(),
                            'audio': hashlib.sha256(wave.read_bytes()).hexdigest()})
        return s['id']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, s) for s in plan['segments']]
        for i, future in enumerate(as_completed(futures), 1):
            print(f"RENDERED {i}/{len(futures)} {future.result()}", flush=True)
    listing = work / 'parts.txt'
    listing.write_text('\n'.join("file 'parts/"+s['id']+".mp4'" for s in plan['segments'])+'\n', encoding='utf-8')
    audio_listing = work / 'audio-parts.txt'
    audio_listing.write_text('\n'.join("file 'parts/"+s['id']+".wav'" for s in plan['segments'])+'\n', encoding='utf-8')
    metadata = [';FFMETADATA1', 'title=Сесія 2: практичний відеоурок українською', 'language=ukr']
    for c in plan['chapters']:
        title=c['title'].replace('=', r'\=').replace(';', r'\;').replace('#', r'\#')
        metadata += ['[CHAPTER]', 'TIMEBASE=1/1000', f"START={round(c['start']*1000)}", f"END={round((c['start']+c['duration'])*1000)}", 'title='+title]
    (work/'chapters.txt').write_text('\n'.join(metadata)+'\n',encoding='utf-8')
    run_ffmpeg([str(ffmpeg),'-y','-hide_banner','-f','concat','-safe','0','-i',str(listing),
                '-f','concat','-safe','0','-i',str(audio_listing),'-i',str(work/'chapters.txt'),
                '-map','0:v','-map','1:a','-map_metadata','2','-map_chapters','2','-c:v','copy',
                '-c:a','aac','-b:a','48k','-ac','1','-ar','24000','-t',str(plan['duration']),
                '-movflags','+faststart',str(work/'session-2-lesson-uk.mp4')],work/'concat.log')
    shutil.copyfile(work/'screens'/f"{plan['segments'][0]['id']}.png",work/'session-2-video-poster.png')
    print('VIDEO_RENDERED',work/'session-2-lesson-uk.mp4',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['plan','render'])
    p.add_argument('--script',type=Path,default=HERE/'script.json')
    p.add_argument('--narration',type=Path,default=HERE.parent/'.rehearsal/video/narration')
    p.add_argument('--work',type=Path,default=HERE.parent/'.rehearsal/video')
    p.add_argument('--ffmpeg',type=Path)
    p.add_argument('--workers',type=int,default=3)
    a=p.parse_args();a.work=a.work.resolve();a.work.mkdir(parents=True,exist_ok=True)
    if a.action=='plan':make_plan(a.script.resolve(),a.narration.resolve(),a.work)
    else:
        if not a.ffmpeg:raise ValueError('--ffmpeg required for rendering')
        render(a.work,a.ffmpeg.resolve(),a.workers)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    main()
