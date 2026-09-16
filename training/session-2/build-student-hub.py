#!/usr/bin/env python3
"""Build Ukrainian student entry points and stage verified public downloads."""

from __future__ import annotations

import argparse
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_URL = "https://koldovsky.github.io/claude-code-oracle-training/"
SLIDE_TITLES = [
    "Claude Code: розширення", "Дві години практики", "Доказ результату",
    "Розрахунок виплати продавцю", "Контракт пакета", "Очікувані результати",
    "Власний skill", "Структура skill", "Ревʼю стартового пакета", "Якість знахідки",
    "Агент ревʼю", "Завдання агенту", "Межі ізоляції", "Hook перед записом",
    "Перевірка SQL-файлу", "Позитивний і негативний приклади", "Що контролює цей hook",
    "Перерва 10 хвилин", "Два незалежні ревʼю", "Завдання для паралельної роботи",
    "План перед реалізацією", "Реалізація й Oracle", "Приймання результату",
    "Орієнтація у великій системі", "Домашнє завдання №2", "Від правил до перевірки",
]
STYLE = """
:root{color-scheme:dark;--bg:#090e15;--panel:#121d29;--line:#2b4154;--text:#e8f0f5;--muted:#b2c3d2;--cyan:#62dbd5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:17px/1.65 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1080px;margin:auto;padding:32px 24px 70px}a{color:var(--cyan);text-underline-offset:4px}a:focus-visible,summary:focus-visible{outline:3px solid var(--cyan);outline-offset:5px}
.course-nav{display:flex;flex-wrap:wrap;gap:9px 20px;border-bottom:1px solid var(--line);padding-bottom:20px;margin-bottom:34px;font-size:15px}
.course-nav a[aria-current=page]{color:white;font-weight:700}h1{font-size:clamp(30px,5vw,49px);line-height:1.15;max-width:850px;margin:12px 0 20px}h2{font-size:27px;line-height:1.25;margin-top:42px}h3{font-size:20px;margin:0 0 12px}.eyebrow{color:var(--cyan);font-size:14px;letter-spacing:.1em;text-transform:uppercase}.lead{font-size:21px;color:var(--muted);max-width:850px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.card,.notice,details{padding:23px;background:var(--panel);border:1px solid var(--line);border-radius:14px}.card p{color:var(--muted);margin:0 0 15px}.card p:last-child{margin-bottom:0}.button{display:inline-block;background:var(--cyan);color:#062028;font-weight:700;padding:11px 17px;border-radius:8px;text-decoration:none}.notice{border-left:4px solid var(--cyan);margin:26px 0}.muted{color:var(--muted)}.downloads{width:100%;border-collapse:collapse}.downloads td,.downloads th{text-align:left;padding:14px 12px;border-bottom:1px solid var(--line);vertical-align:top}.downloads th{color:var(--muted);font-size:14px}.downloads td:first-child{width:40%}code{font-family:Consolas,monospace;font-size:.92em}pre{overflow:auto;background:#080e14;padding:17px;border:1px solid var(--line);border-radius:9px;line-height:1.6}summary{cursor:pointer;font-weight:700}details{margin:14px 0}details p:last-child{margin-bottom:0}li{margin:8px 0}.pdf{width:100%;height:76vh;min-height:480px;background:white;border:1px solid var(--line);border-radius:10px}footer{border-top:1px solid var(--line);margin-top:45px;padding-top:20px;font-size:14px;color:var(--muted)}.table-wrap{overflow:auto}@media(max-width:620px){.wrap{padding:24px 17px 45px}.grid{grid-template-columns:1fr}.course-nav{gap:10px 16px}.downloads td,.downloads th{padding:12px 7px}.lead{font-size:19px}.pdf{min-height:420px}.card,.notice,details{padding:18px}}@media print{body{background:white;color:#17232d}.course-nav,.button,.pdf{display:none}.wrap{max-width:none;padding:0}.card,.notice,details{background:white;border-color:#aaa;break-inside:avoid}a{color:#164e6b}.muted,.lead,.card p{color:#345}}
.slide-viewer{background:#070a0e;border:1px solid var(--line);border-radius:12px;overflow:hidden}.slide-viewer img{display:block;width:100%;height:auto;aspect-ratio:16/9;object-fit:contain}.slide-controls{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:14px}.slide-controls button,.slide-controls select{font:inherit;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:8px 12px}.slide-controls select{flex:1;min-width:160px;max-width:100%}.slide-controls button{cursor:pointer}.slide-controls button:disabled{opacity:.4;cursor:default}.slide-viewer:fullscreen{border:0;border-radius:0;display:flex;flex-direction:column;justify-content:center}.slide-viewer:fullscreen img{max-height:calc(100vh - 100px);width:100%;object-fit:contain}.slide-viewer:fullscreen .slide-controls{justify-content:center}.slide-caption{padding:0 14px 12px;color:var(--muted);font-size:14px;margin:0}
"""


def nav(*, online: bool, current: str) -> str:
    items = [
        ("session-2.html", "Початок і файли"),
        ("session-2-slides.html", "Слайди"),
        ("session-2-rehearsal.html", "Демо з поясненнями"),
        ("cheatsheet-session-2.html", "Шпаргалка"),
        ("session-2-video.html", "Відеоурок · 2 години" + (" · онлайн" if not online else "")),
    ]
    return "<nav class='course-nav' aria-label='Матеріали Сесії 2'>" + "".join(
        f"<a href='{PUBLIC_URL + href if not online and href == 'session-2-video.html' else href}'"
        + (" aria-current='page'" if href == current else "") + f">{escape(label)}</a>"
        for href, label in items
    ) + "</nav>"


def page(title: str, body: str, *, online: bool, current: str) -> str:
    return "<!doctype html>\n<html lang='uk'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" + f"<title>{escape(title)}</title><style>{STYLE}</style></head><body><main class='wrap'>" + nav(online=online, current=current) + body + f"<footer>Claude Code для Oracle-розробки · Сесія 2<br><a href='session-2.html'>Усі матеріали й файли</a> · <a href='{PUBLIC_URL}cheatsheet.html'>Підготовка із Сесії 1 · онлайн</a></footer></main></body></html>\n"


def hub(*, online: bool) -> str:
    full_zip = "downloads/session-2-participant.zip" if online else PUBLIC_URL + "downloads/session-2-participant.zip"
    pdf = "downloads/session-2.pdf" if online else "../slides/session-2.pdf"
    materials = "session-2-materials/" if online else "../training/"
    handout = materials + "HANDOUT-SESSION-2.md"
    homework = materials + "HOMEWORK-SESSION-2.md"
    spec = materials + "SPEC.md" if online else "../training/session-2/lab/SPEC.md"
    lab_readme = materials + "LAB-README.md" if online else "../training/session-2/README.md"
    video = "session-2-video.html" if online else PUBLIC_URL + "session-2-video.html"
    archive_note = "Один архів для практики та навчання без мережі." if online else "Ви вже відкрили локальні матеріали. Повний архів можна повторно завантажити з сайту."
    def size_suffix(path: str) -> str:
        source = ROOT / path
        return f" · {source.stat().st_size / 1024 / 1024:.1f} МБ".replace(".", ",") if online and source.is_file() else ""
    zip_size = size_suffix("tools/session-2-participant.zip")
    pdf_size = size_suffix("slides/session-2.pdf")
    body = f"""
<p class='eyebrow'>Claude Code для Oracle · Сесія 2</p>
<h1>Усе для заняття в одному місці</h1>
<p class='lead'>Skills, окремий агент ревʼю, hooks і виправлення PL/SQL за контрактом. Оберіть формат, завантажте файли та працюйте у власному темпі.</p>
<div class='notice' id='repository'><h3>Який репозиторій використовуємо?</h3><p>Той самий, що й у Сесії 1: <a href='https://github.com/koldovsky/oracle-claude-training-materials'>oracle-claude-training-materials</a>. Файли цього заняття — у <code>training/session-2/</code>.</p><p><strong>Корінь репозиторію або ZIP</strong> — тека, у якій безпосередньо є каталог <code>training/</code> і файл <code>training/session-2/setup-workspace.py</code>. Саме звідси запускайте перші команди підготовки.</p><details><summary>У мене вже є репозиторій із Сесії 1</summary><p>Відкрийте термінал у корені своєї наявної копії та отримайте матеріали Сесії 2:</p><pre><code>git pull --ff-only</code></pre><p>Далі перейдіть до <a href='#prepare'>підготовки нижче</a>.</p></details><details><summary>Хочу завантажити репозиторій уперше</summary><p>У терміналі перейдіть до теки, де зберігаєте навчальні проєкти, та виконайте:</p><pre><code>git clone https://github.com/koldovsky/oracle-claude-training-materials.git
cd oracle-claude-training-materials</code></pre><p>Ви в корені репозиторію. Продовжуйте <a href='#prepare'>підготовку нижче</a>.</p></details><p>Альтернатива — повний ZIP нижче. Розпакуйте його й працюйте з теки <code>START-HERE.html</code>: додаткове клонування для практики не потрібне.</p></div>
<div class='notice'><h3>Почніть із повного архіву учасника</h3><p>{archive_note} Усередині: лабораторія, стартовий пакет, перевірки, skill, агент, hook, робочий листок, домашнє завдання, шпаргалка, інтерактивні демо та 26 слайдів PDF.</p><p><a class='button' href='{full_zip}' download='session-2-participant.zip'>Завантажити всі матеріали ZIP{' · онлайн' if not online else zip_size}</a></p><p class='muted'>Розпакуйте весь архів, потім відкрийте START-HERE.html. Відеоурок завантажується окремо зі своєї сторінки. Паролі й особисті доступи тренер надає окремо.</p></div>
<h2>Як проходити заняття</h2>
<div class='grid'>
<section class='card'><h3>Разом із викладачем</h3><p>Відкрийте слайди. Під час вправ тримайте поруч шпаргалку та робочий листок. Демо допоможе повторити окремий крок.</p><p><a href='session-2-slides.html'>Відкрити слайди</a> · <a href='{handout}'>Робочий листок</a></p></section>
<section class='card'><h3>Самостійно з відеоуроком</h3><p>Двогодинне заняття українською: показ на екрані, голосовий супровід, субтитри та паузи для власної практики. Завантаження й розділи є на сторінці відео.</p><p><a href='{video}'>Відкрити відеоурок{' · онлайн' if not online else ''}</a></p></section>
<section class='card'><h3>Самостійно у своєму темпі</h3><p>Повний текстовий урок із поясненнями, записами виконання, вправами та відповідями у блоках, які можна згортати. Працює офлайн.</p><p><a href='session-2-rehearsal.html'>Відкрити демо з поясненнями</a></p></section>
<section class='card'><h3>Швидко знайти команду</h3><p>Шпаргалка містить готові команди, промпти та ознаки правильного результату. Кнопка біля команди копіює її до буфера.</p><p><a href='cheatsheet-session-2.html'>Відкрити шпаргалку</a></p></section>
</div>
<h2 id='downloads'>Окремі файли</h2>
<div class='table-wrap'><table class='downloads'><thead><tr><th>Файл</th><th>Для чого</th></tr></thead><tbody>
<tr><td><a href='{full_zip}' download='session-2-participant.zip'>Повний архів ZIP{' · онлайн' if not online else zip_size}</a></td><td>Усі файли практики зі збереженою структурою тек. Це рекомендований спосіб почати.</td></tr>
<tr><td><a href='{pdf}' download='session-2.pdf'>Слайди PDF · 26 сторінок{pdf_size}</a></td><td>Перегляд, друк і робота офлайн.</td></tr>
<tr><td><a href='session-2-rehearsal.html' download>Урок і демо HTML</a></td><td>Пояснення та записи в одному файлі. Усередині є додаткова кнопка завантаження лише практичних файлів.</td></tr>
<tr><td><a href='cheatsheet-session-2.html' download>Шпаргалка HTML</a></td><td>Команди й очікувані результати. Щоб усі її локальні посилання працювали офлайн, використовуйте повний ZIP.</td></tr>
<tr><td><a href='{handout}' download>Робочий листок Markdown</a></td><td>Вправи протягом заняття та файли, у які записувати результати.</td></tr>
<tr><td><a href='{spec}' download>Контракт пакета Markdown</a></td><td>Правила розрахунків, помилок і транзакцій.</td></tr>
<tr><td><a href='{homework}' download>Домашнє завдання Markdown</a></td><td>Власний skill або hook, три випадки перевірки та критерії оцінювання.</td></tr>
<tr><td><a href='{lab_readme}' download>Інструкція лабораторії Markdown</a></td><td>Підготовка, запуск, компіляція, перевірка та свідоме повернення до початку.</td></tr>
<tr><td><a href='{video}'>Відео, субтитри й текст уроку{' · онлайн' if not online else ''}</a></td><td>Окремі завантаження на сторінці відеоуроку.</td></tr>
</tbody></table></div>
<h2 id='prepare'>Перші кроки після завантаження</h2>
<ol><li>Оберіть один спосіб отримання файлів: <a href='#repository'>оновіть або клонуйте репозиторій</a> чи розпакуйте <strong>весь</strong> ZIP зі збереженням структури тек.</li><li>Для власної практики потрібні Python 3.10+, Git, SQLcl, Claude Code та збережене навчальне зʼєднання SQLcl <code>train</code> із Сесії 1. У Windows для Claude Code також потрібен Git Bash.</li><li>Відкрийте термінал у корені обраної копії: тут є <code>training/session-2/setup-workspace.py</code>; у ZIP поруч також лежить <code>START-HERE.html</code>. Виконайте наведені команди.</li></ol>
<pre><code>python training/session-2/check-environment.py
python training/session-2/check-environment.py --database
python training/session-2/setup-workspace.py
cd training/session-2/workspace</code></pre>
<p>Очікуйте <code>PREFLIGHT_PASS</code>, а після підготовки теки — <code>WORKSPACE_READY</code>. Якщо Python запускається як <code>python3</code>, використовуйте цю назву. Наявну робочу теку скрипт не перезаписує.</p>
<p>Далі відкрийте <a href='session-2-rehearsal.html#preparation'>підготовку й пояснення в уроці</a> або <a href='cheatsheet-session-2.html#lab'>команди початку лабораторії</a>.</p>
<details><summary>Що працює без мережі, а що потребує доступу</summary><p>PDF, шпаргалка, повний текстовий урок, записи та локальна підготовка теки працюють із розпакованого архіву. Для підготовки теки потрібні встановлені Python і Git. Для запуску Claude потрібні мережа й власний вхід. Для SQL потрібні SQLcl і ваш навчальний доступ до Oracle. Wallet, пароль та обліковий запис у публічний архів не входять.</p><p>Відеоурок має окремі завантаження. Посилання на нього з офлайн-архіву відкриває сайт.</p></details>
<details><summary>Як повернутися до потрібного матеріалу</summary><p>На початку кожної HTML-сторінки є посилання «Початок і файли», «Слайди», «Демо з поясненнями», «Шпаргалка» та «Відеоурок». У браузері використовуйте кнопку «Назад», якщо відкрили окремий PDF або Markdown. Для початку знову відкрийте <code>START-HERE.html</code> у розпакованому архіві.</p></details>
"""
    return page("Сесія 2 · матеріали й завантаження", body, online=online, current="session-2.html")


def slides(*, online: bool) -> str:
    pdf = "downloads/session-2.pdf" if online else "../slides/session-2.pdf"
    options = "".join(f"<option value='{i}'>{i} / 26 · {escape(title)}</option>" for i, title in enumerate(SLIDE_TITLES, 1))
    body = f"""<p class='eyebrow'>Сесія 2 · презентація</p><h1>Слайди заняття</h1><p class='lead'>26 слайдів: від правил ревʼю до перевіреного PL/SQL. Під час вправ відкрийте <a href='cheatsheet-session-2.html'>шпаргалку</a> та <a href='session-2-rehearsal.html'>демо з поясненнями</a>.</p><p><a class='button' href='{pdf}' download='session-2.pdf'>Завантажити PDF</a> &nbsp; <a href='{pdf}'>Відкрити окремий PDF</a></p>
<section class='slide-viewer' aria-label='Перегляд слайдів'><img id='slide-image' src='session-2-slides/slide-01.png' width='1600' height='900' alt='Слайд 1: Claude Code: розширення'><div class='slide-controls'><button id='previous-slide' type='button' aria-label='Попередній слайд'>← Назад</button><select id='slide-select' aria-label='Оберіть слайд'>{options}</select><button id='next-slide' type='button' aria-label='Наступний слайд'>Далі →</button><button id='fullscreen' type='button'>На весь екран</button></div><p class='slide-caption' id='slide-status' aria-live='polite'>Слайд 1 із 26</p></section>
<p class='muted'>Гортайте кнопками або стрілками ← → на клавіатурі. Список дозволяє одразу перейти до теми. Переглядач працює офлайн із повного архіву учасника.</p>
<noscript><p>Для гортання слайдів увімкніть JavaScript або <a href='{pdf}'>відкрийте PDF</a>.</p></noscript>
<script>
(() => {{
  const titles = {json.dumps(SLIDE_TITLES, ensure_ascii=False)};
  const image = document.getElementById('slide-image'), select = document.getElementById('slide-select');
  const previous = document.getElementById('previous-slide'), next = document.getElementById('next-slide');
  let current = 1;
  function show(value, updateHash = true) {{
    current = Math.max(1, Math.min(titles.length, Number.isFinite(value) ? value : 1));
    image.src = 'session-2-slides/slide-' + String(current).padStart(2,'0') + '.png';
    image.alt = 'Слайд ' + current + ': ' + titles[current - 1]; select.value = current;
    previous.disabled = current === 1; next.disabled = current === titles.length;
    document.getElementById('slide-status').textContent = 'Слайд ' + current + ' із 26 · ' + titles[current - 1];
    if (updateHash) history.replaceState(null, '', '#slide-' + current);
  }}
  function fromHash() {{ const match = location.hash.match(/^#slide-(\\d+)$/); show(match ? Number(match[1]) : 1, false); }}
  previous.addEventListener('click', () => show(current - 1)); next.addEventListener('click', () => show(current + 1));
  select.addEventListener('change', () => show(Number(select.value)));
  document.addEventListener('keydown', event => {{
    if (event.target.matches('input,textarea,select') || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {{event.preventDefault();show(current + (event.key === 'ArrowRight' ? 1 : -1));}}
  }});
  const fullscreen = document.getElementById('fullscreen'), viewer = document.querySelector('.slide-viewer');
  if (!viewer.requestFullscreen) fullscreen.hidden = true;
  fullscreen.addEventListener('click', async () => {{try {{if(document.fullscreenElement) await document.exitFullscreen();else await viewer.requestFullscreen();}} catch {{document.getElementById('slide-status').textContent = 'Браузер не дозволив повний екран. Використайте масштабування браузера.';}}}});
  document.addEventListener('fullscreenchange', () => fullscreen.textContent = document.fullscreenElement ? 'Вийти з повного екрана' : 'На весь екран');
  window.addEventListener('hashchange', fromHash); fromHash();
}})();
</script>"""
    return page("Сесія 2 · слайди", body, online=online, current="session-2-slides.html")


def slide_assets(*, render: bool) -> dict:
    directory = ROOT / "tools/session-2-slides"
    manifest_path = directory / "manifest.json"
    pdf = ROOT / "slides/session-2.pdf"
    if render:
        executable = shutil.which("pdftoppm")
        if not executable:
            raise RuntimeError("Rendering slides requires Poppler pdftoppm on PATH.")
        directory.mkdir(exist_ok=True)
        subprocess.run([executable, "-png", "-scale-to", "1600", str(pdf), str(directory / "slide")], check=True, timeout=120)
        manifest = {"sourcePdfSha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "slides": []}
        for i, title in enumerate(SLIDE_TITLES, 1):
            source = directory / f"slide-{i:02d}.png"
            blob = source.read_bytes()
            manifest["slides"].append({"path": source.name, "title": title, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if pdf.is_file() and hashlib.sha256(pdf.read_bytes()).hexdigest() != manifest["sourcePdfSha256"]:
        raise RuntimeError("PDF has changed; regenerate slides with --render-slides.")
    if len(manifest["slides"]) != len(SLIDE_TITLES):
        raise RuntimeError("Slide manifest does not contain exactly 26 pages.")
    for i, slide in enumerate(manifest["slides"], 1):
        expected_name = f"slide-{i:02d}.png"
        if slide["path"] != expected_name:
            raise RuntimeError("Unexpected slide asset path.")
        blob = (directory / expected_name).read_bytes()
        if not blob.startswith(b"\x89PNG\r\n\x1a\n") or len(blob) != slide["bytes"] or hashlib.sha256(blob).hexdigest() != slide["sha256"]:
            raise RuntimeError(f"Invalid slide image: {expected_name}")
    return manifest


def add_session_one_link(public_dir: Path) -> None:
    """Idempotent post-build decoration: never replace the Session 1 application."""
    target = public_dir / "index.html"
    if not target.is_file():
        return
    html = target.read_text(encoding="utf-8")
    html = re.sub(r"\n?<!-- SESSION2-LINK:START -->.*?<!-- SESSION2-LINK:END -->\n?", "\n", html, flags=re.S)
    banner = """<!-- SESSION2-LINK:START -->
<a href="session-2.html" aria-label="Сесія 2: усі матеріали, слайди, демо, відео й завантаження" style="position:fixed;top:10px;right:12px;z-index:10000;background:#092f35;color:#8df1e4;border:1px solid #477c82;border-radius:8px;padding:8px 13px;font:600 14px/1.4 system-ui;text-decoration:none;max-width:calc(100vw - 24px)">Сесія 2 · усі матеріали й файли ↗</a>
<!-- SESSION2-LINK:END -->"""
    if "</body>" not in html:
        raise RuntimeError("Session 1 index has no body terminator; refusing to patch it.")
    target.write_text(html.replace("</body>", banner + "\n</body>"), encoding="utf-8")


def stage_downloads(public_dir: Path) -> None:
    files = {"session-2-participant.zip": ROOT / "tools/session-2-participant.zip", "session-2.pdf": ROOT / "slides/session-2.pdf"}
    for name, source in files.items():
        if not source.is_file():
            raise RuntimeError(f"Build required download first: {source}")
    if not files["session-2.pdf"].read_bytes().startswith(b"%PDF-"):
        raise RuntimeError("Slides download is not a PDF.")
    with zipfile.ZipFile(files["session-2-participant.zip"]) as bundle:
        if bundle.testzip() or "START-HERE.html" not in bundle.namelist():
            raise RuntimeError("Build the updated participant archive before staging downloads.")
    destination = public_dir / "downloads"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, source in files.items():
        target = destination / name
        shutil.copyfile(source, target)
        blob = target.read_bytes()
        manifest.append({"path": "downloads/" + name, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
    (public_dir / "session-2-downloads.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pages = slide_assets(render=False)
    slides_dir = public_dir / "session-2-slides"
    slides_dir.mkdir(exist_ok=True)
    for name in ["manifest.json", *(slide["path"] for slide in pages["slides"])]:
        shutil.copyfile(ROOT / "tools/session-2-slides" / name, slides_dir / name)


class LocalLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"href", "src"} and value:
                parsed = urlsplit(value)
                if not parsed.scheme and not parsed.netloc and parsed.path:
                    self.links.append(unquote(parsed.path))


def validate_links(directory: Path) -> None:
    checked = 0
    pages = ("session-2.html", "session-2-slides.html", "cheatsheet-session-2.html", "session-2-rehearsal.html", "session-2-video.html")
    failures = []
    for name in pages:
        path = directory / name
        if not path.is_file():
            failures.append(f"Missing course page: {name}")
            continue
        parser = LocalLinks()
        parser.feed(path.read_text(encoding="utf-8"))
        for target in parser.links:
            if target.startswith("/"):
                failures.append(f"Use a portable relative course link in {name}: {target}")
            elif not (path.parent / target).resolve().is_file():
                failures.append(f"Broken link in {name}: {target}")
            checked += 1
    if failures:
        raise RuntimeError("\n".join(failures))
    print(f"STUDENT_LINKS_PASS {checked} local links across {len(pages)} pages")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", type=Path, help="Stage pages and final downloads in the Pages checkout")
    parser.add_argument("--validate-links", action="store_true", help="After all course pages exist, verify their local links")
    parser.add_argument("--render-slides", action="store_true", help="Render the original PDF to 26 portable slide images using Poppler")
    args = parser.parse_args()
    output = ROOT / "tools"
    output.mkdir(exist_ok=True)
    slide_assets(render=args.render_slides)
    (output / "session-2.html").write_text(hub(online=False), encoding="utf-8")
    (output / "session-2-slides.html").write_text(slides(online=False), encoding="utf-8")
    if args.public_dir:
        public_dir = args.public_dir.resolve()
        public_dir.mkdir(parents=True, exist_ok=True)
        stage_downloads(public_dir)
        (public_dir / "session-2.html").write_text(hub(online=True), encoding="utf-8")
        (public_dir / "session-2-slides.html").write_text(slides(online=True), encoding="utf-8")
        materials = public_dir / "session-2-materials"
        materials.mkdir(exist_ok=True)
        lab_readme = (ROOT / "training/session-2/README.md").read_text(encoding="utf-8")
        for old, new in {"../HANDOUT-SESSION-2.md": "HANDOUT-SESSION-2.md", "../HOMEWORK-SESSION-2.md": "HOMEWORK-SESSION-2.md", "lab/SPEC.md": "SPEC.md", "../../tools/": "../"}.items():
            lab_readme = lab_readme.replace("](" + old, "](" + new)
        (materials / "LAB-README.md").write_text(lab_readme, encoding="utf-8")
        add_session_one_link(public_dir)
        if args.validate_links:
            validate_links(public_dir)
        print(f"STUDENT_DOWNLOADS_STAGED {public_dir}")
    elif args.validate_links:
        parser.error("--validate-links requires --public-dir")
    print("STUDENT_HUB_READY tools/session-2.html; tools/session-2-slides.html")


if __name__ == "__main__":
    main()
