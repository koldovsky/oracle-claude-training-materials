# Ukrainian two-hour screen lesson

The finished lesson has 16 chapters, Ukrainian synthetic narration, burned-in
subtitles, readable teaching screens, and excerpts from all nine real demo runs.
Its 120 minutes include a ten-minute break, exercises, and labeled reading pauses.
It is a prepared screen lesson, not a recording of a live teacher.

Student entry: https://koldovsky.github.io/claude-code-oracle-training/session-2.html

Video and separate downloads: https://koldovsky.github.io/claude-code-oracle-training/session-2-video.html

## Build

Run from the repository root on Windows with Python 3.11+, Node, Segoe UI,
Playwright Chromium, `edge-tts==7.2.8`, and FFmpeg with libx264, AAC, libass and
drawtext support. `imageio-ffmpeg==0.6.0` provides a compatible FFmpeg binary.
The existing `slides/node_modules/playwright-chromium` installation is used by
default; `PLAYWRIGHT_MODULE` may point to another installed copy.

```powershell
python training/session-2/video/synthesize.py training/session-2/video/script.json --output training/session-2/.rehearsal/video/narration --rate=-3% --concurrency 2
python training/session-2/video/build_video.py plan
node training/session-2/video/render_screens.cjs
python training/session-2/video/build_video.py render --ffmpeg <ffmpeg.exe> --workers 3
python training/session-2/video/verify_video.py --work training/session-2/.rehearsal/video --ffmpeg <ffmpeg.exe>
python training/session-2/video/publish_video.py
python training/session-2/video/publish_video.py --destination .public-repo/docs
python -m unittest discover -s training/session-2/video -p 'test_*.py'
```

Synthesis sends only the public Ukrainian narration text to the speech service.
It uses `uk-UA-OstapNeural` at `-3%`, with timestamped word boundaries. It does not
call Claude or Oracle. Audio and render intermediates stay in ignored
`.rehearsal/video/`. Resuming reuses only takes whose text, voice, settings and
artifact hashes match. Update the script and rerun synthesis before planning.

The planner requires the complete 7,200-second script and rejects stale audio,
overlapping captions and excessive speech acceleration. Screen capture rejects
clipped content. Rendering uses exact video-frame durations and PCM intermediate
audio to avoid drift between clips. Verification decodes the complete video and
audio, checks all 72,000 frames, subtitle timing and media hashes. Publication
requires a matching verification report. The MP4, SRT, VTT, transcript, poster
and checksum manifest are published together in `session-2-video-media/`.
The Pages repository marks `docs/session-2-video-media/* -text` in
`.gitattributes` so Git preserves the verified subtitle and transcript bytes.
Compare staged media bytes with the manifest before pushing; automatic line
ending conversion would otherwise change their checksums on Windows.

Rebuild the student hub and participant ZIP afterwards using
[`../STUDENT-PUBLISHING.md`](../STUDENT-PUBLISHING.md). The participant ZIP has
the lab and offline written materials; the larger video is a separate download.
