# -*- coding: utf-8 -*-
"""Собирает сайт статистики: site/index.html (данные внутри зашифрованы паролем).

Запуск:  python build_site.py            — собрать из site/posts.json и reports/*.json
         python build_site.py --export   — сначала выгрузить свежие посты из Telegram (export_posts.py)
Пароль берётся из файла site_password.txt рядом со скриптом."""
import base64
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import schedule
import stats as s
from rich_table import DISPLAY_NAMES

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
TEMPLATE = HERE / "site_template.html"
PASSWORD_FILE = HERE / "site_password.txt"
PBKDF2_ROUNDS = 250_000

# Порядок = цвет на графиках (проверенная палитра): синий, оранжевый, бирюзовый, янтарный
SITE_EDITORS = ["nire'loo", "Who is it?", "n1xkoo", "unreliable"]
SLUGS = {"nire'loo": "nireloo", "Who is it?": "kirill", "n1xkoo": "n1xkoo", "unreliable": "kalash"}
ROLES = {e: "Редактор" for e in SITE_EDITORS}

# «О ком писали»: название -> регулярное выражение (без учёта регистра)
TOPICS = {
    "BetBoom": r"bet\s?boom|\bbb team\b",
    "Team Spirit": r"\bspirit\b|спирит",
    "PARIVISION": r"parivision",
    "1w Team": r"\b1w\b|1win",
    "Tundra": r"tundra",
    "Falcons": r"falcons",
    "Team Liquid": r"\bliquid\b",
    "Aurora": r"aurora",
    "Gaimin Gladiators": r"gaimin",
    "OG": r"\bog\b",
    "Valve": r"valve|вэлв|вальв",
    "Патч": r"патч|patch|обновлени",
    "Collapse": r"collapse|коллапс",
    "Yatoro": r"yatoro|ятор",
    "Satanic": r"satanic|сатаник",
    "Larl": r"\blarl\b|ларл",
    "Malr1ne": r"malr1ne|малрин",
    "RAMZES": r"ramzes|рамзес",
    "Nix": r"\bnix\b|никс",
    "Stariy_Bog": r"stariy_?bog|старый бог|старого бога|старому богу",
    "zxcursed": r"zxcursed|курсед",
    "Папич": r"папич",
    "Головач": r"головач",
    "Dendi": r"dendi|дэнди|денди",
    "TORONTOTOKYO": r"torontotokyo|торонто",
    "Meepo": r"meepo|мипо|мипар",
    "Читеры": r"читер|чит\b|софт",
}
TOPIC_RE = {k: re.compile(v, re.I) for k, v in TOPICS.items()}


def avatar(name):
    doc_id = s.EDITOR_EMOJI.get(name, (None,))[0]
    path = HERE / "emoji" / f"{doc_id}.webp"
    if not doc_id or not path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode()


def shifts_of(posts):
    """Смены как в stats.count_shifts: 3+ поста подряд без перерыва больше 3 часов."""
    times = {}
    for p in posts:
        for a in p["editors"]:
            times.setdefault(a, []).append(datetime.fromisoformat(p["date"]))
    out = []
    for a, ts in times.items():
        ts.sort()
        run = [ts[0]]
        for t in ts[1:] + [None]:
            if t is not None and t - run[-1] <= s.SHIFT_MAX_GAP:
                run.append(t)
                continue
            if len(run) >= s.SHIFT_MIN_POSTS:
                out.append({"e": a, "start": run[0].isoformat(timespec="minutes"),
                            "end": run[-1].isoformat(timespec="minutes"), "n": len(run)})
            if t is not None:
                run = [t]
    return sorted(out, key=lambda x: x["start"])


def weekly_reports():
    """Официальные КФ из недельных отчётов (пн–вс), как они ушли в Telegram."""
    weeks = []
    d = s.FIRST_WEEK
    today = datetime.now(s.MSK).date()
    while d <= today:
        last = d + timedelta(days=6)
        f = s.REPORTS / f"{d:%Y-%m-%d}_{last:%Y-%m-%d}.json"
        w = {"start": d.isoformat(), "end": last.isoformat(), "official": None}
        if f.exists() and last < today:
            data = json.loads(f.read_text(encoding="utf-8"))
            posts = data["posts"]
            w["official"] = {
                "editors": {t["editor"]: {"coef": t["coef"], "posts": t["posts"], "reposts": t["reposts"]}
                            for t in data["table"] if t["editor"] in SITE_EDITORS and t["posts"]},
                "week_coef": data.get("week_coef") or (
                    round(sum(p["reposts"] for p in posts) / len(posts), 2) if posts else 0),
                "total": {"posts": len(posts), "fw": sum(p["reposts"] for p in posts)},
            }
        weeks.append(w)
        d += timedelta(days=7)
    return weeks


def payload():
    raw = json.loads((SITE / "posts.json").read_text(encoding="utf-8"))
    all_posts = raw["posts"]
    editor_posts = [p for p in all_posts if any(e in SITE_EDITORS for e in p["editors"])]
    for p in editor_posts:
        p["editors"] = [e for e in p["editors"] if e in SITE_EDITORS]
    posts = []
    for p in editor_posts:
        text = p["text"]
        posts.append({
            "id": p["id"], "d": p["date"][:16], "e": p["editors"], "k": p["kind"],
            "fw": p["fw"], "v": p["views"],
            "r": sum(p["reactions"].values()), "rx": p["reactions"],
            "m": p["media"], "len": p["length"], "t": p["title"],
            "tags": [k for k, rx in TOPIC_RE.items() if rx.search(text)],
        })
    return {
        "exported": raw["exported"],
        "channel": s.CHANNEL,
        "firstDay": s.FIRST_WEEK.isoformat(),
        "editors": [{"key": e, "slug": SLUGS[e], "name": DISPLAY_NAMES.get(e, e), "signature": e,
                     "role": ROLES[e], "avatar": avatar(e)} for e in SITE_EDITORS],
        "posts": posts,
        "shifts": shifts_of(editor_posts),
        "weeks": weekly_reports(),
        # прошлые месяцы не нужны — только текущий (и следующий, если его уже внесли в таблицу)
        "schedule": {"shifts": schedule.SHIFTS,
                     "months": [m for m in schedule.load(datetime.now(s.MSK).date())
                                if m["month"] >= datetime.now(s.MSK).strftime("%Y-%m")]},
        "rules": {"shiftMin": s.SHIFT_MIN_POSTS, "shiftGapH": s.SHIFT_MAX_GAP.seconds // 3600},
    }


def encrypt(data, password):
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS, dklen=32)
    ct = AESGCM(key).encrypt(iv, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"salt": b64(salt), "iv": b64(iv), "rounds": PBKDF2_ROUNDS, "data": b64(ct)}


def main():
    if "--export" in sys.argv:
        import export_posts
        export_posts.main()
    password = os.environ.get("SITE_PASSWORD") or PASSWORD_FILE.read_text(encoding="utf-8").strip()
    data = payload()
    box = encrypt(data, password)
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__VAULT__*/null", json.dumps(box))
    # логотип не секретный — он нужен уже на экране пароля, поэтому лежит вне шифра
    brand = HERE / "brand"
    for token, name, mime in (("__FACE__", "face.webp", "image/webp"), ("__MASK__", "face_mask.png", "image/png"),
                              ("__LOGO__", "logo_small.webp", "image/webp")):
        uri = f"data:{mime};base64," + base64.b64encode((brand / name).read_bytes()).decode()
        html = html.replace(token, uri)
    SITE.mkdir(exist_ok=True)
    # preview.html — тело страницы для черновика на claude.ai (там своя обёртка);
    # index.html — полноценный документ для хостинга.
    (SITE / "preview.html").write_text(html, encoding="utf-8")
    head_end = html.index("</style>") + len("</style>")
    page = ('<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + html[:head_end] + "\n</head>\n<body>\n" + html[head_end:] + "\n</body>\n</html>\n")
    (SITE / "index.html").write_text(page, encoding="utf-8")
    n = sum(1 for p in data["posts"] if p["k"] == "post")
    print(f"Сайт собран: {SITE / 'index.html'} — {n} учтённых постов, {len(data['shifts'])} смен, "
          f"{sum(1 for w in data['weeks'] if w['official'])} недель с отчётами, {len(html) // 1024} КБ")


if __name__ == "__main__":
    main()
