#!/usr/bin/env python3
"""Verify final streams, full decoding, exact timeline, subtitles and media hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import wave


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(work, ffmpeg):
    plan_path = work/'timeline.json'
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    movie=work/'session-2-lesson-uk.mp4'
    if plan['duration'] != 7200 or sum(c['duration'] for c in plan['chapters']) != 7200:
        raise ValueError('Expected the complete 7200-second lesson')
    probe=subprocess.run([str(ffmpeg),'-hide_banner','-i',str(movie)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (work/'probe.log').write_text(probe.stderr,encoding='utf-8')
    match=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',probe.stderr)
    if not match:raise ValueError('Missing media duration')
    hours,minutes,seconds=map(float,match.groups());duration=hours*3600+minutes*60+seconds
    if abs(duration-7200)>0.12:raise ValueError(f'Final video is not two hours: {duration}')
    if not re.search(r'Video: h264.*1600x900.*10 fps',probe.stderr):raise ValueError('Unexpected video encoding')
    if not re.search(r'Audio: aac.*24000 Hz, mono',probe.stderr):raise ValueError('Unexpected audio encoding')
    total_samples=0
    for s in plan['segments']:
        with wave.open(str(work/'parts'/(s['id']+'.wav')),'rb') as f:
            if f.getframerate()!=24000 or f.getnchannels()!=1:raise ValueError('Invalid scene audio format')
            expected=round(s['duration']*24000)
            if f.getnframes()!=expected:raise ValueError(f"Scene audio duration mismatch: {s['id']}")
            total_samples+=f.getnframes()
    if total_samples!=7200*24000:raise ValueError('PCM timeline does not total 7200 seconds')
    result=subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-xerror','-i',str(movie),
        '-map','0:v:0','-map','0:a:0','-f','null','-','-progress','pipe:1','-nostats'],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (work/'decode.log').write_text(result.stderr,encoding='utf-8')
    if result.returncode or result.stderr.strip():raise ValueError('Final video/audio failed full decoding')
    frames=re.findall(r'^frame=(\d+)',result.stdout,re.M)
    if not frames or int(frames[-1])!=72000:raise ValueError('Expected exactly 72000 video frames')
    timestamps=re.findall(r'^out_time_us=(\d+)',result.stdout,re.M)
    if not timestamps or abs(int(timestamps[-1])/1e6-7200)>.12:raise ValueError('Decoded timeline has wrong duration')
    def seconds(text):
        h,m,s=text.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(s)
    srt=(work/'session-2-lesson-uk.srt').read_text(encoding='utf-8')
    ranges=re.findall(r'(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})',srt)
    previous=0
    for a,b in ranges:
        start,end=seconds(a),seconds(b)
        if start<previous or end<=start or end>7200:raise ValueError('Invalid final subtitle timing')
        previous=end
    if len(ranges)<500:raise ValueError('Unexpectedly few subtitle cues')
    assets=('session-2-lesson-uk.mp4','session-2-lesson-uk.srt','session-2-lesson-uk.vtt','session-2-lesson-transcript.md','session-2-video-poster.png')
    report={'durationSeconds':duration,'frames':72000,'fullDecodePass':True,'pcmSamples':total_samples,
            'subtitleCues':len(ranges),'timelineSha256':digest(plan_path),
            'assets':{name:digest(work/name) for name in assets}}
    (work/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('VIDEO_VERIFIED',json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--work',type=Path,required=True);p.add_argument('--ffmpeg',type=Path,required=True)
    a=p.parse_args();verify(a.work.resolve(),a.ffmpeg.resolve())
