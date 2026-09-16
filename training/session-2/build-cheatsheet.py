#!/usr/bin/env python3
"""Build the offline Session 2 command reference using the existing course style."""
import argparse
from html import escape
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--public-dir", type=Path,
                    help="Also prepare a local Pages directory; never commits or publishes")
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
reference = (ROOT / "tools" / "cheatsheet-session-1.html").read_text(encoding="utf-8")
style = re.search(r"<style>(.*?)</style>", reference, flags=re.S).group(1)
style += "\nsection {scroll-margin-top:calc(var(--sheet-nav-height, 158px) + 22px)}\n"
style += "header a,footer a,.lead a{color:var(--cyan)} header a:focus-visible,footer a:focus-visible,.lead a:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}\n"
style += ".course-links{display:flex;flex-wrap:wrap;gap:9px 20px;border-bottom:1px solid var(--border,#2b4154);padding-bottom:18px;margin-bottom:24px;font-size:15px}.course-links a{color:var(--cyan)}.course-links a[aria-current=page]{font-weight:700;color:var(--text,#e8f0f5)}\n"
sections = [
    ("prepare", "0 · Підготовка", "Із кореня репозиторію або розпакованого ZIP, до заняття", [
        ("python training/session-2/check-environment.py --database", "PREFLIGHT_PASS. Перевірка підключення лише читає дані.", "sh"),
        ("python training/session-2/setup-workspace.py", "WORKSPACE_READY. Наявну теку скрипт не перезаписує.", "sh"),
        ("cd training/session-2/workspace", "Далі всі команди виконуємо з цієї теки.", "sh"),
    ]),
    ("lab", "1 · Старт лабораторії", "Окреме підключення до власної схеми", [
        ("sql -S -name train @lab/install.sql", "INSTALL_OK. Створено лише навчальні S2_ об'єкти. Повторний install відмовляється від заміни.", "sh"),
        ("sql -S -name train @lab/verify-baseline.sql", "BASELINE_CONFIRMED: 18 перевірок, 5 відомих дефектів, 0 несподіваних результатів.", "sh"),
        ("claude", "Claude запущений у workspace. За потреби підтвердьте довіру до власних навчальних файлів.", "sh"),
    ]),
    ("skill", "2 · Skill", "Поточний контекст · 10–30 хв", [
        ("/oracle-lab-review lab/settlement.pkb.sql", "Знахідки з файлом, рядком, наслідком і перевіркою. Код не змінено.", "prompt"),
        ("Перевір lab/settlement.pkb.sql за lab/SPEC.md. Для кожної знахідки дай файл і рядок, порушену вимогу, конкретний вхід і SQL-перевірку. Файлів не змінюй.", "Статичне рев'ю відділяє докази від припущень.", "prompt"),
    ]),
    ("agent", "3 · Окремий агент", "Ізольований контекст · 30–45 хв", [
        ("Використай oracle-reviewer для незалежного рев'ю lab/settlement.pkb.sql за lab/SPEC.md. Поверни до п'яти підтверджених знахідок. Файлів не змінюй.", "У Claude видно запуск oracle-reviewer. Висновок містить докази, а не обіцянку тестів.", "prompt"),
    ]),
    ("hook", "4 · Hook", "Write/Edit SQL у lab/ · 45–60 хв", [
        ("/hooks", "У Claude видно PreToolUse для Write/Edit і sql_guard.py. Після зміни конфігурації перезапустіть Claude.", "prompt"),
        ("python .claude/hooks/demo.py", "7 PASS, код виходу 0. Це перевірка протоколу без запуску SQL.", "sh"),
        ("Створи lab/hook_probe.sql через інструмент Write із текстом SELECT 1 FROM dual;. Лише запиши файл, SQL не виконуй.", "Файл містить дозволений SELECT.", "prompt"),
        ("Через Write заміни lab/hook_probe.sql текстом DROP TABLE S2_ORDERS;. Це перевірка hook: лише спроба записати текст. SQL не виконуй й іншими інструментами блокування не обходь.", "SQL guard блокує запис. У файлі лишається SELECT. Самостійна відмова моделі не доводить спрацьовування hook.", "prompt"),
    ]),
    ("orchestration", "5 · Оркестрація", "Дві задачі читання · 70–85 хв", [
        ("Запусти два окремі рев'ю через oracle-reviewer. Перше перевіряє бізнес-правила lab/SPEC.md, друге — SQL і транзакції. Об'єднай докази без дублікатів у artifacts/plan.md. Для кожної зміни вкажи тест. Пакет поки не змінюй.", "Два результати рев'ю й один план. Фактичний режим виконання видно у Claude.", "prompt"),
    ]),
    ("refactor", "6 · Реалізація", "Змінюємо лише робоче тіло · 85–105 хв", [
        ("Виконай artifacts/plan.md для lab/settlement.pkb.sql. Збережи публічні сигнатури й контракт lab/SPEC.md. Не редагуй тести та settlement-starter.pkb.sql. Покажи diff і команди компіляції та перевірки.", "Змінено тільки робоче тіло. Немає прихованих винятків, виплата CANCELLED=0.", "prompt"),
        ("sql -S -name train @lab/compile.sql", "COMPILE_OK. Помилка компіляції завершує процес із ненульовим кодом.", "sh"),
        ("sql -S -name train @lab/verify.sql", "ACCEPTANCE_PASS: checks=18, unexpected=0. Стартер на цій перевірці має 5 невідповідностей.", "sh"),
    ]),
    ("reset", "7 · Повторний прогін", "Лише коли свідомо повертаєтесь до початку", [
        ("sql -S -name train @lab/reset-starter.sql", "RESET_OK. Початкові дані й пакет відновлено в БД. Ваш робочий SQL-файл не змінено.", "sh"),
        ("sql -S -name train @lab/verify-baseline.sql", "BASELINE_CONFIRMED. Для відновлення робочого файлу скопіюйте settlement-starter.pkb.sql у settlement.pkb.sql після збереження своєї версії.", "sh"),
    ]),
    ("homework", "8 · Домашнє завдання №2", "Один власний skill або hook", []),
]
parts = ["<!doctype html><html lang='uk'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
         "<title>Сесія 2 · шпаргалка</title><style>" + style + "\n@media print{nav,.copy{display:none}.wrap{max-width:none;padding:0}.row{break-inside:avoid;padding-right:13px}body{background:white;color:#17232d}h1,h2,h3,.row pre{color:#17232d}.row,.lead{background:white;border-color:#aaa}}</style>",
         "<main class='wrap'><div class='course-links' role='navigation' aria-label='Матеріали Сесії 2'><a href='session-2.html'>Початок і файли</a><a href='session-2-slides.html'>Слайди</a><a href='session-2-rehearsal.html'>Демо з поясненнями</a><a href='cheatsheet-session-2.html' aria-current='page'>Шпаргалка</a><a href='https://koldovsky.github.io/claude-code-oracle-training/session-2-video.html'>Відеоурок · 2 години · онлайн</a></div><header><h1>Сесія 2 · <span>шпаргалка</span></h1><p>Власний skill, агент ревʼю, hook і пакет S2_SETTLEMENT.</p><p>Команди можна копіювати. Усі дані та правила розрахунку навчальні.</p><p><a href='session-2.html#downloads'>Завантажити файли заняття</a> · <a href='https://koldovsky.github.io/claude-code-oracle-training/cheatsheet.html'>Шпаргалка Сесії 1</a></p></header>",
         "<nav>" + "".join(f"<a href='#{sid}'>{escape(title)}</a>" for sid, title, _, _ in sections) + "</nav>",
         "<div class='lead'><p><b>Очікування:</b> 1001 → 25,17; CANCELLED → 0; 1005 → 0,67 після округлення загальної виплати. Невідомий ID → −20001; NULL → −20002.</p><p>Hook контролює Write/Edit файлів lab/*.sql. Запуск через Bash, SQLcl чи MCP він не фільтрує. Доступ до бази визначають гранти Oracle.</p></div>"]
for sid, title, subtitle, cards in sections:
    parts.append(f"<section id='{sid}'><h2>{escape(title)}</h2><p class='tagline'>{escape(subtitle)}</p>")
    if sid == "prepare":
        parts.append("<div class='lead'><p><b>Репозиторій той самий, що в Сесії 1:</b> <a href='https://github.com/koldovsky/oracle-claude-training-materials'>oracle-claude-training-materials</a>. Спочатку <a href='session-2.html#repository'>оновіть наявну копію, клонуйте нову або завантажте ZIP</a>.</p><p>Корінь — тека, де є <code>training/session-2/setup-workspace.py</code>. Запускайте перші дві команди звідси; третя переводить у створену робочу теку.</p></div>")
    for command, expected, kind in cards:
        parts.append(f"<div class='row {kind}'><pre>{escape(command)}</pre><button type='button' class='copy' aria-label='Копіювати команду'>Копіювати</button><span class='note'>{escape(expected)}</span></div>")
    if sid == "homework":
        parts.append("""<div class='lead'>
<p>Оберіть одну повторювану задачу й зробіть власний <b>skill або hook</b>. Працюйте із синтетичними прикладами.</p>
<ul>
<li><b>Позитивний випадок:</b> коректний код або дозволена дія проходять; skill не вигадує порушень.</li>
<li><b>Негативний випадок:</b> навмисне порушення знайдено з доказом або заборонену дію заблоковано.</li>
<li><b>Граничний випадок:</b> для skill — бракує потрібного контексту; для hook — неповний або неправильний вхід. Заздалегідь визначте очікувану поведінку.</li>
</ul>
<p><b>Докази:</b> README з кроками запуску, файл розширення, очікування до запуску, фактичні відповіді або коди завершення, відомі межі. Негативний hook-тест подає текст як тестові дані; небезпечну команду не виконуємо.</p>
<p><b>Рубрика — 5 × 2 бали:</b> конкретна задача; відтворювані інструкції; позитивний і негативний приклади; контекст і межі; перевірюваний результат. Готовність — <b>від 8/10</b>, обидва основні приклади обов'язкові.</p>
<p><a href='../training/HOMEWORK-SESSION-2.md'>Повний опис домашнього завдання →</a></p>
</div>""")
    parts.append("</section>")
parts.append("<footer>Матеріали: <a href='../training/HANDOUT-SESSION-2.md'>робочий листок</a> · <a href='../training/HOMEWORK-SESSION-2.md'>домашнє завдання №2</a> · <a href='../training/session-2/lab/SPEC.md'>специфікація</a> · <a href='session-2-rehearsal.html'>демонстрація заняття</a><p id='copy-status' role='status' aria-live='polite'></p></footer></main>")
parts.append("""<script>
const sheetNav = document.querySelector('nav');
const measureSheetNav = () => document.documentElement.style.setProperty('--sheet-nav-height', Math.ceil(sheetNav.getBoundingClientRect().height) + 'px');
if ('ResizeObserver' in window) new ResizeObserver(measureSheetNav).observe(sheetNav);
window.addEventListener('resize', measureSheetNav);
measureSheetNav();
document.querySelectorAll('.copy').forEach(button => button.addEventListener('click', async () => {
  const value = button.parentElement.querySelector('pre').textContent;
  let copied = false;
  try { await navigator.clipboard.writeText(value); copied = true; } catch (_) {
    const field = document.createElement('textarea'); field.value = value;
    field.style.position = 'fixed'; field.style.opacity = '0'; document.body.appendChild(field);
    field.select(); copied = document.execCommand('copy'); field.remove();
  }
  button.textContent = copied ? 'Скопійовано' : 'Виділіть текст';
  document.getElementById('copy-status').textContent = copied ? 'Команду скопійовано.' : 'Буфер недоступний. Виділіть і скопіюйте текст команди.';
  setTimeout(() => { button.textContent = 'Копіювати'; }, 1800);
}));
</script></html>""")
destination = ROOT / "tools" / "cheatsheet-session-2.html"
html = "\n".join(parts)
destination.write_text(html, encoding="utf-8")
print(f"Built {destination.name}: {sum(len(s[3]) for s in sections)} copyable commands")

if args.public_dir:
    public_dir = args.public_dir.resolve()
    materials_dir = public_dir / "session-2-materials"
    materials_dir.mkdir(parents=True, exist_ok=True)
    public_html = html.replace("href='https://koldovsky.github.io/claude-code-oracle-training/cheatsheet.html'", "href='cheatsheet.html'")
    public_html = public_html.replace("href='https://koldovsky.github.io/claude-code-oracle-training/session-2-video.html'>Відеоурок · 2 години · онлайн", "href='session-2-video.html'>Відеоурок · 2 години")
    material_sources = {
        "../training/HANDOUT-SESSION-2.md": ROOT / "training" / "HANDOUT-SESSION-2.md",
        "../training/HOMEWORK-SESSION-2.md": ROOT / "training" / "HOMEWORK-SESSION-2.md",
        "../training/session-2/lab/SPEC.md": ROOT / "training" / "session-2" / "lab" / "SPEC.md",
    }
    for offline_link, source in material_sources.items():
        public_html = public_html.replace(f"href='{offline_link}'",
                                          f"href='session-2-materials/{source.name}'")
        material = source.read_text(encoding="utf-8")
        if source.name == "HANDOUT-SESSION-2.md":
            material = material.replace("(session-2/lab/SPEC.md)", "(SPEC.md)")
            material = material.replace("(session-2/README.md#підготовка-робочої-теки)",
                                        "(../cheatsheet-session-2.html#prepare)")
        (materials_dir / source.name).write_text(material, encoding="utf-8")
    (public_dir / "cheatsheet-session-2.html").write_text(public_html, encoding="utf-8")
    print(f"Prepared local Pages files in {public_dir}; nothing was committed or published")
