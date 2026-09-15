#!/usr/bin/env python3
"""Build student video pages and copy the completed, verified lesson assets."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ASSETS = ('session-2-lesson-uk.mp4', 'session-2-lesson-uk.srt', 'session-2-lesson-uk.vtt',
          'session-2-lesson-transcript.md', 'session-2-video-poster.png')


def clock(seconds):
    value = round(seconds)
    return f'{value//3600:02}:{value//60%60:02}:{value%60:02}'


def publish(work, destination):
    plan = json.loads((work/'timeline.json').read_text(encoding='utf-8'))
    if plan['duration'] != 7200:
        raise ValueError('Publish requires the complete two-hour lesson')
    verification=json.loads((work/'verification.json').read_text(encoding='utf-8'))
    if (verification.get('durationSeconds') != 7200 or verification.get('fullDecodePass') is not True
            or verification.get('frames') != 72000
            or verification.get('timelineSha256') != hashlib.sha256((work/'timeline.json').read_bytes()).hexdigest()):
        raise ValueError('Final video verification is missing or stale')
    for name in ASSETS:
        if verification['assets'].get(name) != hashlib.sha256((work/name).read_bytes()).hexdigest():
            raise ValueError(f'Unverified or changed video asset: {name}')
    directory = destination/'session-2-video-media'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in ASSETS:
        source = work/name
        if not source.is_file() or source.stat().st_size < 1:
            raise ValueError(f'Missing final asset: {name}')
        shutil.copyfile(source, directory/name)
        manifest[name] = {'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    chapters = ''.join(f'<li><button type="button" data-time="{c["start"]}"><time>{clock(c["start"])}</time> {html.escape(c["title"])}</button></li>' for c in plan['chapters'])
    transcript = []
    for c in plan['chapters']:
        paragraphs = ''.join('<h3>'+html.escape(s['title'])+'</h3><p>'+html.escape(s['narration'])+'</p>' for s in plan['segments'] if s['chapterId']==c['id'])
        transcript.append('<details><summary>'+clock(c['start'])+' · '+html.escape(c['title'])+'</summary>'+paragraphs+'</details>')
    size = manifest['session-2-lesson-uk.mp4']['bytes']/1024/1024
    page = '''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сесія 2 · двогодинний відеоурок українською</title><meta name="description" content="Дві години практики Oracle та Claude Code: український голос, субтитри, розділи й завантаження для перегляду офлайн.">
<style>
:root{color-scheme:dark;--bg:#080d11;--ink:#e7eef2;--muted:#afc0cb;--line:#2a3f4b;--accent:#52df9a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.65 system-ui,"Segoe UI",sans-serif}.wrap{max-width:1180px;margin:auto;padding:28px 24px}a{color:#57d5e2;text-underline-offset:3px}.nav{display:flex;gap:10px 22px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:0 0 20px;margin:0 0 35px;font-size:15px}h1{font-size:clamp(30px,5vw,48px);line-height:1.15;margin:12px 0 20px;max-width:900px}h2{font-size:27px;margin:34px 0 16px}h3{font-size:19px;margin:24px 0 10px}.eyebrow{letter-spacing:2px;color:var(--accent);font-size:13px}.intro{max-width:900px;color:var(--muted)}video{display:block;width:100%;aspect-ratio:16/9;background:#000;border:1px solid var(--line);border-radius:9px;margin:26px 0 15px}.downloads{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.downloads a{padding:10px 16px;border:1px solid var(--line);border-radius:6px;text-decoration:none}.downloads .main{background:#183c2e;color:#c5ffdf;border-color:#3d805f}.chapters{list-style:none;padding:0;columns:2;column-gap:35px}.chapters li{break-inside:avoid;margin:0 0 8px}.chapters button{background:none;border:0;color:var(--ink);font:inherit;text-align:left;cursor:pointer;padding:7px 0;line-height:1.45}.chapters time{color:var(--accent);font:14px Consolas,monospace;margin-right:8px}.chapters button:hover{color:var(--accent)}.note{border-left:3px solid var(--accent);padding-left:18px;color:var(--muted);max-width:1000px}.help{font-size:14px;color:var(--muted)}details{border:1px solid var(--line);border-radius:7px;margin:12px 0;padding:14px 18px}summary{cursor:pointer;font-weight:600}details p{color:var(--muted);max-width:96ch}button:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:4px}footer{border-top:1px solid var(--line);margin-top:40px;padding-top:24px}@media(max-width:700px){.chapters{columns:1}.wrap{padding:22px 16px}}@media print{video,.downloads,.nav,.chapters{display:none}details{break-inside:avoid}}
</style></head><body><main class="wrap">
<nav class="nav" aria-label="Матеріали сесії 2"><a href="session-2.html">Початок і всі файли</a><a href="session-2-slides.html">Слайди</a><a href="session-2-rehearsal.html">Демо з поясненнями</a><a href="cheatsheet-session-2.html">Шпаргалка</a><span aria-current="page">Відеоурок</span></nav>
<p class="eyebrow">CLAUDE CODE · ORACLE · СЕСІЯ 2</p><h1>Двогодинний відеоурок українською</h1>
<p class="intro">Послідовне пояснення роботи на екрані: підготовка, контракт пакета, skill, окремі агенти, hook, виправлення, перевірки Oracle та MCP. Українські субтитри вже містяться у відео. Слайди й код можна роздивлятися, ставлячи відтворення на паузу.</p>
<p class="note">Голос синтезований. Демонстрації використовують справжні записи інструментів і навчальні файли. Це підготовлений відеоурок, а не запис живого викладача. Дві години включають десятихвилинну перерву, час для читання та самостійної практики.</p>
<video id="lesson-video" controls preload="metadata" playsinline poster="session-2-video-media/session-2-video-poster.png"><source src="session-2-video-media/session-2-lesson-uk.mp4" type="video/mp4">Ваш браузер не відтворює відео. Скористайтеся завантаженням MP4 нижче.</video>
<p class="help">Почніть відтворення або виберіть розділ. Швидкість змінюється в меню програвача. Якщо перегляд у браузері недоступний, завантажте MP4 і відкрийте його у своєму відеопрогравачі.</p>
<div class="downloads"><a class="main" download href="session-2-video-media/session-2-lesson-uk.mp4">Завантажити MP4 · __VIDEO_SIZE__ МБ</a><a download href="session-2-video-media/session-2-lesson-uk.srt">Субтитри SRT</a><a download href="session-2-video-media/session-2-lesson-uk.vtt">Субтитри VTT</a><a download href="session-2-video-media/session-2-lesson-transcript.md">Текст пояснень</a></div>
<h2>Розділи відеоуроку</h2><ol class="chapters">__CHAPTERS__</ol>
<h2>Матеріали для практики</h2><p>На сторінці <a href="session-2.html#downloads">усіх завантажень</a> є повний комплект учасника, PDF слайдів, лабораторія та інструкції. Для повторення дій у своїй базі потрібні особисте навчальне з’єднання й інструменти, описані в підготовці. Перегляд завантаженого відео не потребує мережі або доступу до Oracle.</p>
<h2>Текст уроку за розділами</h2>__TRANSCRIPT__
<footer><a href="session-2.html">Повернутися до початку сесії 2</a> · <a href="session-2-rehearsal.html">Покрокові інтерактивні демо</a></footer>
</main><script>const video=document.getElementById('lesson-video');document.querySelectorAll('[data-time]').forEach(button=>button.addEventListener('click',()=>{video.currentTime=Number(button.dataset.time);video.scrollIntoView({behavior:'smooth',block:'center'});video.play().catch(()=>{});}));</script></body></html>'''
    page=page.replace('__VIDEO_SIZE__',f'{size:.1f}').replace('__CHAPTERS__',chapters).replace('__TRANSCRIPT__',''.join(transcript))
    (destination/'session-2-video.html').write_text(page,encoding='utf-8')
    print('VIDEO_PUBLISHED_LOCAL',destination,round(size,1),'MiB')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,default=HERE.parent/'.rehearsal/video')
    parser.add_argument('--destination',type=Path,default=REPO/'tools')
    args=parser.parse_args();publish(args.work.resolve(),args.destination.resolve())
