# -*- coding: utf-8 -*-
"""Таблица «КФ репостов редакторов» в новом формате Telegram (rich message), как в образце канала."""
import json
import math
import re

from telethon.tl import types as T
from telethon.tl.functions.messages import SendMessageRequest

# Ник в таблице (подпись в канале -> как показывать)
DISPLAY_NAMES = {
    "nire'loo": "nireloo",
    "n1xkoo": "n1xkoo",
    "unreliable": "kalash",
    "Who is it?": "Кирилл",
}
# Эмодзи из набора @gabenews ICONS 2 (GabeNewsIcons)
INFO = (5366539817918176291, "ℹ️")      # ℹ️ в заголовке периода
POINTER = (5355129842159361113, "💬")   # жёлтая стрелка у названия таблицы
DOWN = (5328246104255405388, "👇")      # красная стрелка вниз — КФ упал
UP = (5327995939590280358, "👆")        # зелёная стрелка вверх — КФ вырос

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


def P(s):
    return T.TextPlain(text=s)


def E(emoji):
    return T.TextCustomEmoji(document_id=emoji[0], alt=emoji[1])


def B(x):
    return T.TextBold(text=P(x) if isinstance(x, str) else x)


def C(*parts):
    return T.TextConcat(texts=[P(x) if isinstance(x, str) else x for x in parts])


def cell(text, header=False, center=False, colspan=None):
    return T.PageTableCell(header=header or None, align_center=center or None, text=text, colspan=colspan)


def button(label, url, style):
    return T.TextButton(text=P(label), type=T.InlineButtonTypeUrl(url=url),
                        style=T.RichButtonStyle(**{style: True}))


def shown(c):
    """КФ в таблице — всегда целое число, дробная часть отбрасывается, как в таблицах канала:
    174,67 -> 174; 82,96 -> 82."""
    return math.floor(round(c, 6))


def fmt_coef(c):
    return str(shown(c))


def change(cur, prev):
    """« (🔻-37)» / « (🔺+12)» / « (0)». Разница — между числами, которые видны в таблицах."""
    if prev is None:
        return [" (новый)"]
    d = round(shown(cur) - shown(prev))
    if d == 0:
        return [" (0)"]
    return [" (", B(C(E(UP if d > 0 else DOWN), f"{d:+d}")), ")"]


def auto_label(text, limit=26):
    """Короткое название поста из его первой строки."""
    line = ""
    for raw in text.splitlines():
        raw = raw.strip()
        if raw and any(ch.isalpha() for ch in raw) and "gabe news" not in raw.lower():
            line = raw
            break
    line = re.sub(r"[^\w\s«»\"'.,!?%&+/()—–-]", "", line)  # убрать эмодзи
    line = re.sub(r"^[\s.,!?—–-]+", "", line)
    for sep in (" — ", " – ", " - ", ": ", ". ", "! ", "? "):
        if sep in line:
            line = line.split(sep)[0]
            break
    line = " ".join(line.split()).strip(" .,!?")
    # КАПСЛОК -> обычный регистр (короткие аббревиатуры вроде TI, MMR оставляем)
    words = line.split()
    caps = [w for w in words if w.isupper()]
    if len(caps) * 2 >= len(words):  # строка в основном капслоком
        words = [w if (w.isascii() and len(w) <= 3) else w.lower() for w in words]
    else:
        words = [w.lower() if w.isupper() and len(w) > 3 else w for w in words]
    line = " ".join(words)
    line = line[:1].upper() + line[1:]
    if len(line) > limit:
        line = line[:limit].rsplit(" ", 1)[0] + "…"
    return line or "Пост"


TOP_ICON = (5327990948838282588, "👆")    # зелёный квадрат со стрелкой вверх — «Топ постов»
FLOP_ICON = (5328246873054553989, "👇")   # красный квадрат со стрелкой вниз — «Незашедшие посты»
TOP_N, FLOP_N = 20, 10
CHANNEL_URL = "https://t.me/gabenews/{}"


def details(icon, title, lines):
    """Раскрывающийся список."""
    return T.PageBlockDetails(blocks=[T.PageBlockParagraph(text=C(*lines))],
                              title=C(" ", E(icon), " ", B(title)), open=None)


def build(start_day, last_day, rows, posts, week_coef, prev_coefs, prev_week_coef,
          editor_emoji, split_authors, labels=None):
    """rows: [(подпись, постов, репостов, КФ)] по убыванию КФ;
    posts: учтённые посты [{id, fw, text, author}]; prev_coefs: {подпись: КФ прошлого периода}."""
    labels = labels or {}

    def name_of(p):
        return labels.get(str(p["id"])) or auto_label(p["text"])

    def emojis(p):
        out = []
        for a in split_authors(p["author"]):
            if a in editor_emoji:
                out += [T.TextCustomEmoji(document_id=editor_emoji[a][0], alt=editor_emoji[a][1]), " "]
        return out

    def post_lines(items):
        lines = []
        for k, p in enumerate(items):
            lines += emojis(p) + [T.TextUrl(text=P(name_of(p)), url=CHANNEL_URL.format(p["id"]), webpage_id=0),
                                  f" {p['fw']}" + ("\n" if k < len(items) - 1 else "")]
        return lines

    best = {}
    for p in posts:
        for a in split_authors(p["author"]):
            if a not in best or (p["fw"], -p["id"]) > (best[a]["fw"], -best[a]["id"]):
                best[a] = p
    by_top = sorted(posts, key=lambda p: (-p["fw"], p["id"]))
    by_flop = sorted(posts, key=lambda p: (p["fw"], p["id"]))

    period = f"{start_day.day} {MONTHS[start_day.month - 1]} — {last_day.day} {MONTHS[last_day.month - 1]}."
    table = [T.PageTableRow(cells=[
        cell(P("Редактор"), header=True, center=True),
        cell(P("КФ"), header=True, center=True),
        cell(P("Лучший пост недели"), header=True),
    ])]
    for name, n_posts, _reposts, coef in rows:
        if not n_posts or name not in best:
            continue
        shown_name = DISPLAY_NAMES.get(name, name)
        emoji = editor_emoji.get(name)
        who = C(T.TextCustomEmoji(document_id=emoji[0], alt=emoji[1]), " " + shown_name) if emoji else P(shown_name)
        p = best[name]
        table.append(T.PageTableRow(cells=[
            cell(who, center=True),
            cell(C(B(fmt_coef(coef)), *change(coef, prev_coefs.get(name))), center=True),
            cell(button(f"{name_of(p)} ({p['fw']})", CHANNEL_URL.format(p["id"]), "bg_success")),
        ]))
    table.append(T.PageTableRow(cells=[cell(
        C("КФ репостов недели: ", B(fmt_coef(week_coef)), *change(week_coef, prev_week_coef)),
        center=True, colspan=3)]))
    table.append(T.PageTableRow(cells=[cell(
        button("Самый успешный пост недели", CHANNEL_URL.format(by_top[0]["id"]), "bg_primary"),
        center=True, colspan=3)]))

    return T.InputRichMessage(blocks=[
        T.PageBlockBlockquoteBlocks(blocks=[T.PageBlockHeading4(text=C(B(E(INFO)), " " + period))],
                                    caption=T.TextEmpty()),
        T.PageBlockParagraph(text=T.TextEmpty()),
        T.PageBlockTable(title=C(E(POINTER), " КФ репостов редакторов:"), rows=table, bordered=True),
        T.PageBlockParagraph(text=T.TextEmpty()),
        details(TOP_ICON, f"Топ-{TOP_N} постов недели", post_lines(by_top[:TOP_N])),
        details(FLOP_ICON, f"Топ-{FLOP_N} незашедших постов недели", post_lines(by_flop[:FLOP_N])),
    ])


def send(client, rich, peer="me"):
    return client(SendMessageRequest(peer=client.get_input_entity(peer), message="", rich_message=rich))


def load_labels(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_report(path):
    """Сохранённый отчёт периода (.json, его пишет stats.py)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    posts = [{"id": int(p["link"].rsplit("/", 1)[1]), "fw": p["reposts"], "text": p["text"], "author": p["editor"]}
             for p in data["posts"]]
    week = data.get("week_coef") or (sum(p["fw"] for p in posts) / len(posts) if posts else 0)
    rows = [(t["editor"], t["posts"], t["reposts"], t["coef"]) for t in data["table"]]
    return rows, posts, week


def previous_report(reports, start_day):
    """Последний отправленный отчёт, который заканчивается накануне start_day."""
    from datetime import timedelta
    prev_last = start_day - timedelta(days=1)
    files = [f for f in reports.glob(f"????-??-??_{prev_last:%Y-%m-%d}.json")]
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def main():
    """python rich_table.py reports/2026-11-01_2026-11-08.json [отчёт_для_сравнения.json]
    Названия постов берутся из reports/<тот же период>_labels.json ({номер поста: название})."""
    import sys
    from datetime import date
    from pathlib import Path

    from telethon.sync import TelegramClient

    import stats

    cur = Path(sys.argv[1]).resolve()
    first, last = (date.fromisoformat(x) for x in cur.stem.split("_")[:2])
    prev = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else previous_report(cur.parent, first)
    rows, posts, week = load_report(cur)
    prev_coefs, prev_week = {}, None
    if prev and prev.exists():
        prows, pposts, prev_week = load_report(prev)
        prev_coefs = {n: c for n, p, r, c in prows if p}
        print("Сравнение с", prev.name)
    else:
        print("Отчёта за прошлый период нет — разница не показывается")
    labels = load_labels(cur.with_name(cur.stem + "_labels.json"))
    missing = [p["id"] for p in sorted(posts, key=lambda p: -p["fw"])[:TOP_N]
               + sorted(posts, key=lambda p: p["fw"])[:FLOP_N] if str(p["id"]) not in labels]
    if missing:
        print("Без ручного названия (будет автоматическое):", missing)
    rich = build(first, last, rows, posts, week, prev_coefs, prev_week,
                 stats.EDITOR_EMOJI, stats.split_authors, labels)
    with stats.make_client() as client:
        send(client, rich)
    print("Таблица отправлена")


if __name__ == "__main__":
    main()
