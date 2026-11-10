# -*- coding: utf-8 -*-
"""Отправить summary недели в «Избранное».
Запуск: python send_summary.py путь_к_файлу.md
Файл — обычный текст, можно **жирный** и [ссылки](https://t.me/...)."""
import re
import sys
from pathlib import Path

from telethon.sync import TelegramClient

from stats import make_client, send_me

def visible_len(s):
    """Длина текста, как её считает Telegram: адреса ссылок и ** не видны."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return len(s.replace("**", ""))


text = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
with make_client() as client:
    # сообщение Telegram — до 4096 видимых символов; длинный текст режем по абзацам
    chunk = ""
    for para in text.split("\n\n"):
        if chunk and visible_len(chunk) + visible_len(para) + 2 > 3900:
            send_me(client, chunk, "md", link_preview=False)
            chunk = ""
        chunk += ("\n\n" if chunk else "") + para
    if chunk:
        send_me(client, chunk, "md", link_preview=False)
print("Summary отправлено")
