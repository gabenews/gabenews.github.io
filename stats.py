# -*- coding: utf-8 -*-
"""
Статистика репостов канала @gabenews по редакторам за неделю (пн 00:00 – вс 23:59, МСК).

Коэффициент = репосты на постах редактора за неделю / количество его постов за неделю.

Правила:
  - альбом (несколько фото/видео) и статья = один пост;
  - дайджест (есть #дайджест) — не считается;
  - реклама (в тексте нет «Gabe News») — не считается.
  - с 08.11.2026 посты выходят в новом формате (статья / rich message): текст берётся из блоков
    статьи, а подписью канала считается кнопка со ссылкой на t.me/gabenews внизу поста.

Запуск:
  python stats.py             -> прошлая полная неделя (так запускает планировщик в пн 00:01)
  python stats.py now         -> текущая неделя на данный момент
  python stats.py all         -> все полные недели с 28 сентября
  python stats.py 2026-10-07  -> неделя, в которую входит эта дата
  python stats.py 2026-10-26 2026-10-31 -> произвольный период (обе даты включительно)
  python stats.py 2026-11-01 2026-11-08 2026-10-26 2026-10-31
                              -> период и период для сравнения в таблице КФ (по умолчанию — прошлая неделя)
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from telethon.extensions import html as tl_html, markdown as tl_markdown
from telethon.helpers import add_surrogate
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetCustomEmojiDocumentsRequest
from telethon.tl.types import MessageEntityCustomEmoji

# ================= НАСТРОЙКИ =================
# Ключи Telegram: на компьютере — в config_local.json, на GitHub — в секретах TG_API_ID / TG_API_HASH
CHANNEL = "gabenews"
FIRST_WEEK = date(2026, 9, 28)  # понедельник, с которого начинаем считать
EDITORS = [
    "unreliable",
    "nire'loo",
    "n1xkoo",
    "Who is it?",
]
# Кастомное эмодзи перед ником редактора: (номер эмодзи в Telegram, обычное эмодзи-замена)
EDITOR_EMOJI = {
    "nire'loo": (5402627541888439163, "🏃"),
    "Who is it?": (5278682327688457962, "✍️"),
    "n1xkoo": (5237725459424258449, "✍️"),
    "unreliable": (5249414827100631927, "📹"),
}
# Авторы, чьи посты не учитываются вообще (ни в таблице, ни в топах)
EXCLUDED = [
    "alter ego",
    "Zlata",
    "Андрей",
    "Сергей LEGENDWP",
    "mo&krill",
]
# Дайджесты, которые вышли без #дайджест — номера постов (из ссылки t.me/gabenews/НОМЕР)
DIGEST_IDS = {29196, 29260}
# Смена = 3+ поста редактора подряд без перерыва больше 3 часов (одиночные посты — не смена)
SHIFT_MIN_POSTS = 3
SHIFT_MAX_GAP = timedelta(hours=3)
SEND_TO_TELEGRAM = True  # присылать отчёт в «Избранное»
# =============================================

MSK = timezone(timedelta(hours=3))
HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
NO_SIGN = "Без подписи"


def _local_config():
    try:
        return json.loads((HERE / "config_local.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


CONFIG = _local_config()
API_ID = int(os.environ.get("TG_API_ID") or CONFIG.get("api_id") or 0)
API_HASH = os.environ.get("TG_API_HASH") or CONFIG.get("api_hash", "")


def make_client():
    """Клиент Telegram: в облаке — из секрета TG_SESSION, на компьютере — из файла session.session."""
    session = os.environ.get("TG_SESSION")
    return TelegramClient(StringSession(session) if session else str(HERE / "session"), API_ID, API_HASH)
# С этого момента все посты выходят в новом формате (rich message) с кнопкой «GABE NEWS».
# Раньше в этом формате выходили только статьи — у них нет подписи, и они считаются как обычные посты.
FORMAT_SWITCH = datetime(2026, 11, 8, tzinfo=MSK)


def norm(s):
    """Подпись без регистра, лишних пробелов и апострофов (nireloo = nire'loo)."""
    s = (s or "").replace("’", "'").replace("`", "'").replace("'", "")
    return " ".join(s.split()).casefold()


CANON = {norm(e): e for e in EDITORS + EXCLUDED}
EXCLUDED_NORM = {norm(e) for e in EXCLUDED}


def split_authors(author):
    """«n1xkoo + nireloo» -> ["n1xkoo", "nire'loo"]: совместный пост засчитывается каждому."""
    parts = [a.strip() for a in author.split("+") if a.strip()] or [author]
    return [CANON.get(norm(a), a) for a in parts]


def skipped_text(skipped):
    return (f"реклама — {skipped['реклама']}, дайджесты — {skipped['дайджесты']}, "
            f"исключённые авторы — {skipped['исключённые авторы']}")


def add_editor_emoji(text, entities):
    """Ставит кастомное эмодзи редактора перед каждым его ником в тексте."""
    if not EDITOR_EMOJI:
        return text, entities
    t = add_surrogate(text)  # Telegram считает позиции в UTF-16
    names = sorted(EDITOR_EMOJI, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(add_surrogate(n)) for n in names))
    entities = list(entities or [])
    for m in reversed(list(pattern.finditer(t))):
        doc_id, alt = EDITOR_EMOJI[[n for n in names if add_surrogate(n) == m.group()][0]]
        alt = add_surrogate(alt)
        pos, shift = m.start(), len(alt) + 1
        for e in entities:
            if e.offset >= pos:
                e.offset += shift
            elif e.offset + e.length > pos:
                e.length += shift
        t = t[:pos] + alt + " " + t[pos:]
        entities.append(MessageEntityCustomEmoji(offset=pos, length=len(alt), document_id=doc_id))
    entities.sort(key=lambda e: e.offset)
    return t.encode("utf-16", "surrogatepass").decode("utf-16"), entities


def send_me(client, text, parse_mode="md", file=None, **kwargs):
    """Отправить в «Избранное» с эмодзи редакторов. parse_mode: "md" или "html"."""
    plain, entities = (tl_html if parse_mode == "html" else tl_markdown).parse(text)
    plain, entities = add_editor_emoji(plain, entities)
    if file:
        return client.send_file("me", file, caption=plain, formatting_entities=entities, **kwargs)
    return client.send_message("me", plain, formatting_entities=entities, **kwargs)


def editor_icons(client):
    """Картинки эмодзи редакторов для таблицы: {ник: путь}. Скачивает недостающие."""
    folder = HERE / "emoji"
    folder.mkdir(exist_ok=True)
    paths = {name: folder / f"{doc_id}.webp" for name, (doc_id, _) in EDITOR_EMOJI.items()}
    missing = [EDITOR_EMOJI[n][0] for n, p in paths.items() if not p.exists()]
    if missing:
        try:
            for doc in client(GetCustomEmojiDocumentsRequest(document_id=missing)):
                if doc.mime_type == "image/webp":
                    client.download_media(doc, file=str(folder / f"{doc.id}.webp"))
        except Exception as e:  # без картинки эмодзи таблица всё равно соберётся
            print("Не удалось скачать эмодзи:", e)
    return {n: p for n, p in paths.items() if p.exists()}


def week_bounds(d):
    monday = d - timedelta(days=d.weekday())
    start = datetime.combine(monday, time.min, MSK)
    return start, start + timedelta(days=7)


def rich_content(m):
    """Новый формат постов (rich message, с 08.11.2026).
    Возвращает (текст, есть ли кнопка-подпись со ссылкой на канал)."""
    rich = getattr(m, "rich_message", None)
    if rich is None:
        return "", False
    parts, brand = [], False

    def walk(o, in_button=False):
        nonlocal brand
        if isinstance(o, dict):
            t = o.get("_") or ""
            if t == "PageButton":
                in_button = True
            if in_button:  # текст кнопки не нужен, только её ссылка
                url = o.get("url")
                if isinstance(url, str) and url.rstrip("/").lower().endswith(f"t.me/{CHANNEL}"):
                    brand = True
            elif t == "TextPlain":
                parts.append(o.get("text") or "")
                return
            elif t == "TextCustomEmoji":
                parts.append(o.get("alt") or "")
                return
            elif t.startswith("PageBlock"):
                parts.append("\n")
            for k, v in o.items():
                if k not in ("photos", "documents"):
                    walk(v, in_button)
        elif isinstance(o, list):
            for v in o:
                walk(v, in_button)

    walk(rich.to_dict())
    return "".join(parts).strip(), brand


def is_ad(text, brand=False):
    """Реклама: есть текст, но нет подписи канала («Gabe News» в тексте или кнопка на канал)."""
    return bool(text.strip()) and not brand and "gabe news" not in text.lower()


def is_digest(text):
    """Дайджест: в тексте есть #дайджест."""
    return "#дайджест" in text.lower()


def count_shifts(posts):
    """Сколько смен у каждого автора. Учитываются все его посты (и дайджесты, и реклама)."""
    times = {}
    for p in posts:
        for a in split_authors(p["author"]):
            times.setdefault(a, []).append(p["date"])
    shifts = {}
    for a, ts in times.items():
        ts.sort()
        n, run = 0, 1
        for prev, t in zip(ts, ts[1:]):
            if t - prev <= SHIFT_MAX_GAP:
                run += 1
            else:
                n += run >= SHIFT_MIN_POSTS
                run = 1
        shifts[a] = n + (run >= SHIFT_MIN_POSTS)
    return shifts


def collect(client, start, end):
    """Возвращает (статистика {редактор: [постов, репостов]},
    не учтено {"реклама": n, "дайджесты": n}, всего постов в канале за период)."""
    posts = {}  # альбом из нескольких фото/видео = один пост
    for m in client.iter_messages(CHANNEL, offset_date=end):
        if m.date < start:
            break
        if m.action:  # служебные сообщения (закреп и т.п.)
            continue
        author = " + ".join(split_authors(m.post_author or NO_SIGN))
        p = posts.setdefault(m.grouped_id or f"id{m.id}",
                             {"author": NO_SIGN, "fw": 0, "views": 0, "text": "", "brand": False, "article": False,
                              "id": m.id, "date": m.date})
        if p["author"] == NO_SIGN:
            p["author"] = author
        p["fw"] = max(p["fw"], m.forwards or 0)
        p["views"] = max(p["views"], m.views or 0)
        rich_text, brand = rich_content(m)
        p["text"] += "\n" + (m.message or rich_text)
        p["brand"] = p["brand"] or brand
        if m.rich_message is not None and m.date < FORMAT_SWITCH:
            p["article"] = True  # старая статья: не реклама и не дайджест
        if m.id < p["id"]:  # ссылка на альбом — по первому сообщению
            p["id"], p["date"] = m.id, m.date

    stats = {e: [0, 0] for e in EDITORS}
    skipped = {"реклама": 0, "дайджесты": 0, "исключённые авторы": 0}
    counted = []
    for p in posts.values():
        if not p["article"] and is_ad(p["text"], p["brand"]):
            skipped["реклама"] += 1
        elif p["id"] in DIGEST_IDS or (not p["article"] and is_digest(p["text"])):
            skipped["дайджесты"] += 1
        elif all(norm(a) in EXCLUDED_NORM for a in split_authors(p["author"])):
            skipped["исключённые авторы"] += 1
        else:
            for a in split_authors(p["author"]):
                if norm(a) in EXCLUDED_NORM:
                    continue
                s = stats.setdefault(a, [0, 0])
                s[0] += 1
                s[1] += p["fw"]
            counted.append(p)
    return stats, skipped, len(posts), counted, count_shifts(posts.values())


def post_title(text, limit=60):
    """Первая содержательная строка поста без подписи канала."""
    for line in text.splitlines():
        line = line.strip()
        if line and any(ch.isalpha() for ch in line) and "gabe news" not in line.lower():
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return "Пост без текста (статья / медиа)"


def top_message(title, period, posts, label="Неделя"):
    lines = [f"<b>{title}</b>", f"<i>{label} {period}</i>", ""]
    for i, p in enumerate(posts, 1):
        link = f"https://t.me/{CHANNEL}/{p['id']}"
        lines.append(f"{i}. <b>{p['fw']}</b> 🔁 · {html.escape(p['author'])}")
        lines.append(f"<a href=\"{link}\">{html.escape(post_title(p['text']))}</a>")
    return "\n".join(lines)


def build_rows(stats):
    rows = []
    for name, (posts, reposts) in stats.items():
        if posts == 0 and name not in EDITORS:
            continue
        coef = round(reposts / posts, 2) if posts else 0
        rows.append((name, posts, reposts, coef))
    rows.sort(key=lambda r: (-r[3], -r[2]))
    return rows


def verify(client, start, end, stats, skipped, total, rows, counted_posts):
    """Перепроверка. Возвращает (всё ли в порядке, строки для отчёта)."""
    problems, notes = [], []
    counted = len(counted_posts)
    joint = sum(1 for p in counted_posts if "+" in p["author"])
    # строки таблицы = учтённые посты + лишние строки за совместные посты
    extra = sum(len([a for a in split_authors(p["author"]) if norm(a) not in EXCLUDED_NORM]) - 1
                for p in counted_posts)
    if sum(p for _, p, _, _ in rows) != counted + extra:
        problems.append("сумма постов в таблице не сходится с учтёнными постами")

    # 1. Каждый пост канала попал ровно в одну группу
    if counted + sum(skipped.values()) != total:
        problems.append(f"посты не сходятся: {total} ≠ {counted} учтено + {sum(skipped.values())} не учтено")

    # 2. Независимый повторный подсчёт даёт те же посты
    stats2, skipped2, total2 = collect(client, start, end)[:3]
    posts1 = {a: v[0] for a, v in stats.items() if v[0]}
    posts2 = {a: v[0] for a, v in stats2.items() if v[0]}
    if posts1 != posts2 or skipped != skipped2 or total != total2:
        problems.append("повторный подсчёт дал другой результат")

    # 3. Коэффициенты пересчитаны заново
    for name, p, r, c in rows:
        if p and abs(r / p - c) > 0.006:
            problems.append(f"коэффициент {name} посчитан неверно")

    # 4. Похоже на дайджест, но нет #дайджест — такой пост учтён как обычный
    for p in counted_posts:
        if not p["article"] and "дайджест" in p["text"].lower():
            notes.append(f"⚠️ Похоже на дайджест без #дайджест (учтён как обычный пост): "
                         f"https://t.me/{CHANNEL}/{p['id']}")

    # 5. Подписи не из списка редакторов
    others = [n for n, p, _, _ in rows if p and n not in EDITORS]
    if others:
        notes.append("⚠️ Подписи не из списка редакторов: " + ", ".join(others))

    if problems:
        lines = ["❗ Проверка НЕ пройдена: " + "; ".join(problems)]
    else:
        lines = [f"✅ Проверено: {total} постов = {counted} учтено + {skipped['реклама']} реклама "
                 f"+ {skipped['дайджесты']} дайджесты + {skipped['исключённые авторы']} исключённые авторы, "
                 f"повторный подсчёт совпал"]
        if joint:
            lines.append(f"👥 Совместных постов: {joint} — засчитаны каждому соавтору")
    return not problems, lines + notes


def save_xlsx(path, period, rows, skipped, check_lines, label="Неделя", totals=None, shifts=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Статистика"
    ws.append([f"@{CHANNEL}, {label.lower()} {period}"])
    ws["A1"].font = Font(bold=True)
    shifts = shifts or {}
    ws.append(["Редактор", "Смен", "Постов", "Репостов", "Коэффициент"])
    for c in ws[2]:
        c.font = Font(bold=True)
    for name, p, r, c in rows:
        ws.append([name, shifts.get(name, 0), p, r, c])
    ws.append(["Итого (уникальные посты)", "",
               *(totals or (sum(r[1] for r in rows), sum(r[2] for r in rows)))])
    ws.append([])
    ws.append(["Не учтено: " + skipped_text(skipped)])
    for line in check_lines:
        ws.append([line])
    ws.column_dimensions["A"].width = 22
    for col in "BCDE":
        ws.column_dimensions[col].width = 14
    wb.save(path)


def caption(period, rows, skipped, check_lines, ongoing, label="Неделя", totals=None):
    medals = ["🥇", "🥈", "🥉"]
    active = [r for r in rows if r[1]]
    lines = [f"📊 **Репосты @{CHANNEL}**", f"🗓 **{label} {period}**"]
    if ongoing:
        lines.append(f"_({label.lower()} ещё идёт — данные на текущий момент)_")
    lines.append("")
    for i, (name, p, r, c) in enumerate(active[:3]):
        lines.append(f"{medals[i]} **{name}** — {int(round(c, 6) // 1)}")
    n_posts, n_reposts = totals or (sum(r[1] for r in rows), sum(r[2] for r in rows))
    reposts = f"{n_reposts:,}".replace(",", " ")
    lines += [
        "",
        f"Учтено постов: **{n_posts}**, репостов: **{reposts}**",
        "Не учтено: " + skipped_text(skipped),
        "",
    ] + check_lines
    return "\n".join(lines)


def save_json(path, period, rows, skipped, counted, shifts=None):
    """Данные недели для summary: таблица и все учтённые посты."""
    data = {
        "period": period,
        "table": [{"editor": n, "shifts": (shifts or {}).get(n, 0), "posts": p, "reposts": r, "coef": c}
                  for n, p, r, c in rows],
        "skipped": skipped,
        # КФ недели = все репосты учтённых постов / число учтённых постов (на момент отчёта)
        "week_coef": round(sum(p["fw"] for p in counted) / len(counted), 2) if counted else 0,
        "posts": [
            {"link": f"https://t.me/{CHANNEL}/{p['id']}", "editor": p["author"], "reposts": p["fw"],
             "views": p["views"], "date": p["date"].astimezone(MSK).strftime("%a %d.%m %H:%M"),
             "text": p["text"].strip()[:700]}
            for p in sorted(counted, key=lambda p: -p["fw"])
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def report_week(client, d, parts=("table", "top")):
    start, end = week_bounds(d)
    return report_period(client, start, end, parts, "Неделя", prev=(start - timedelta(days=7), start))


def report_period(client, start, end, parts=("table", "top"), label="Период", prev=None):
    from table_img import render

    last_day = (end - timedelta(days=1)).date()
    period = f"{start:%d.%m} – {last_day:%d.%m.%Y}"
    ongoing = end > datetime.now(MSK)

    stats, skipped, total, counted, shifts = collect(client, start, end)
    rows = build_rows(stats)
    REPORTS.mkdir(exist_ok=True)
    base = REPORTS / f"{start:%Y-%m-%d}_{last_day:%Y-%m-%d}"
    save_json(base.with_suffix(".json"), period, rows, skipped, counted, shifts)

    by_fw = sorted(counted, key=lambda p: (-p["fw"], p["id"]))
    top = top_message("🔥 Топ-20 постов по репостам", period, by_fw[:20], label)
    low = top_message("🧊 20 постов с наименьшим числом репостов", period,
                      sorted(counted, key=lambda p: (p["fw"], p["id"]))[:20], label)

    if "table" not in parts:
        if SEND_TO_TELEGRAM:
            send_me(client, top, "html", link_preview=False)
            send_me(client, low, "html", link_preview=False)
        print(f"{label} {period}: отправлены топ-20 и антитоп-20")
        return True
    ok, check_lines = verify(client, start, end, stats, skipped, total, rows, counted)

    xlsx, png = base.with_suffix(".xlsx"), base.with_suffix(".png")
    totals = (len(counted), sum(p["fw"] for p in counted))
    save_xlsx(xlsx, period, rows, skipped, check_lines, label, totals, shifts)
    footer = [
        f"Учтено постов: {totals[0]}  ·  репостов: {totals[1]:,}".replace(",", " "),
        "Не учтено: " + skipped_text(skipped),
        "Коэффициент = репосты ÷ посты" + (f"  ·  {label.lower()} ещё идёт" if ongoing else ""),
        f"Смена = {SHIFT_MIN_POSTS}+ поста подряд без перерыва больше {SHIFT_MAX_GAP.seconds // 3600} ч",
    ]
    render(png, f"Репосты @{CHANNEL}", f"{label} {period}", rows, footer, shifts, editor_icons(client))
    text = caption(period, rows, skipped, check_lines, ongoing, label, totals)

    print(f"{label} {period}")
    for name, p, r, c in rows:
        print(f"  {name:<17}{shifts.get(name, 0):>4} смен{p:>5}{r:>8}{c:>9.2f}")
    print("  " + "\n  ".join(check_lines))
    print(f"  Сохранено: {png.name}, {xlsx.name}\n")

    if SEND_TO_TELEGRAM:
        msg = send_me(client, text, "md", file=str(png))
        client.send_file("me", str(xlsx), reply_to=msg)
        if "top" in parts:
            send_me(client, top, "html", link_preview=False)
            send_me(client, low, "html", link_preview=False)
    return ok


def main():
    arg = sys.argv[1].strip().lower() if len(sys.argv) > 1 else ""
    # второй параметр "top" — прислать только топ-20 / антитоп-20, без таблицы
    parts = ("top",) if len(sys.argv) > 2 and sys.argv[2].lower() == "top" else ("table", "top")
    today = datetime.now(MSK).date()
    # две даты — произвольный период, обе включительно
    if arg[:1].isdigit() and len(sys.argv) > 2 and sys.argv[2][:1].isdigit():
        first, last = date.fromisoformat(arg), date.fromisoformat(sys.argv[2])
        parts = ("top",) if len(sys.argv) > 3 and sys.argv[3].lower() == "top" else ("table", "top")
        start = datetime.combine(first, time.min, MSK)
        end = datetime.combine(last + timedelta(days=1), time.min, MSK)
        prev = None
        if len(sys.argv) > 4 and sys.argv[3][:1].isdigit() and sys.argv[4][:1].isdigit():
            p1, p2 = date.fromisoformat(sys.argv[3]), date.fromisoformat(sys.argv[4])
            prev = (datetime.combine(p1, time.min, MSK), datetime.combine(p2 + timedelta(days=1), time.min, MSK))
        with make_client() as client:
            report_period(client, start, end, parts, prev=prev)
        return
    if arg == "all":
        weeks, d = [], FIRST_WEEK
        while d + timedelta(days=7) <= today:
            weeks.append(d)
            d += timedelta(days=7)
    elif arg == "now":
        weeks = [today]
    elif arg:
        weeks = [date.fromisoformat(arg)]
    else:
        weeks = [today - timedelta(days=7)]  # прошлая полная неделя

    with make_client() as client:
        for d in weeks:
            if week_bounds(d)[0].date() < FIRST_WEEK:
                print(f"Неделя {d} раньше {FIRST_WEEK:%d.%m} — пропускаю")
                continue
            report_week(client, d, parts)


if __name__ == "__main__":
    main()
