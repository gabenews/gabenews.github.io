# -*- coding: utf-8 -*-
"""Выгрузка всех постов канала с FIRST_WEEK в site/posts.json — данные для сайта статистики.
Правила те же, что у stats.py: альбом = один пост, реклама/дайджесты/исключённые авторы помечаются."""
import json
from datetime import datetime, time

from telethon.sync import TelegramClient

import stats as s

OUT = s.HERE / "site" / "posts.json"


def reactions_of(m):
    out = {}
    for r in (m.reactions.results if m.reactions else []):
        key = getattr(r.reaction, "emoticon", None) or "custom"
        out[key] = out.get(key, 0) + r.count
    return out


def media_of(m):
    if m.rich_message is not None:
        return "article" if m.date < s.FORMAT_SWITCH else "rich"
    if m.photo:
        return "photo"
    if m.video or m.gif:
        return "video"
    if m.document:
        return "file"
    return "text" if m.message else "none"


def main():
    start = datetime.combine(s.FIRST_WEEK, time.min, s.MSK)
    groups = {}
    with s.make_client() as client:
        for m in client.iter_messages(s.CHANNEL):
            if m.date < start:
                break
            if m.action:
                continue
            g = groups.setdefault(m.grouped_id or f"id{m.id}", {
                "id": m.id, "date": m.date, "author": s.NO_SIGN, "fw": 0, "views": 0, "text": "",
                "brand": False, "article": False, "reactions": {}, "media": set(), "parts": 0})
            if g["author"] == s.NO_SIGN:
                g["author"] = " + ".join(s.split_authors(m.post_author or s.NO_SIGN))
            g["fw"] = max(g["fw"], m.forwards or 0)
            g["views"] = max(g["views"], m.views or 0)
            rich_text, brand = s.rich_content(m)
            g["text"] += "\n" + (m.message or rich_text)
            g["brand"] = g["brand"] or brand
            if m.rich_message is not None and m.date < s.FORMAT_SWITCH:
                g["article"] = True
            for k, v in reactions_of(m).items():
                g["reactions"][k] = max(g["reactions"].get(k, 0), v)
            g["media"].add(media_of(m))
            g["parts"] += 1
            if m.id < g["id"]:
                g["id"], g["date"] = m.id, m.date

    posts = []
    for g in groups.values():
        if not g["article"] and s.is_ad(g["text"], g["brand"]):
            kind = "ad"
        elif g["id"] in s.DIGEST_IDS or (not g["article"] and s.is_digest(g["text"])):
            kind = "digest"
        elif all(s.norm(a) in s.EXCLUDED_NORM for a in s.split_authors(g["author"])):
            kind = "excluded"
        else:
            kind = "post"
        authors = s.split_authors(g["author"])
        text = g["text"].strip()
        posts.append({
            "id": g["id"],
            "date": g["date"].astimezone(s.MSK).isoformat(timespec="minutes"),
            "authors": authors,
            "editors": [a for a in authors if s.norm(a) not in s.EXCLUDED_NORM and a != s.NO_SIGN],
            "kind": kind,
            "fw": g["fw"],
            "views": g["views"],
            "reactions": g["reactions"],
            "media": sorted(g["media"] - {"none"}),
            "album": g["parts"] > 1,
            "length": len(text),
            "title": s.post_title(text, 120),
            "text": text[:600],
        })
    posts.sort(key=lambda p: p["id"])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"exported": datetime.now(s.MSK).isoformat(timespec="minutes"),
                               "posts": posts}, ensure_ascii=False), encoding="utf-8")
    kinds = {}
    for p in posts:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(f"Выгружено {len(posts)} постов: {kinds} -> {OUT}")


if __name__ == "__main__":
    main()
