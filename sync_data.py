# -*- coding: utf-8 -*-
"""Недельные отчёты (reports/*.json) хранятся на GitHub только в зашифрованном виде: data/reports.enc.

python sync_data.py pack     — зашифровать reports/ в data/reports.enc
python sync_data.py unpack   — расшифровать data/reports.enc в reports/ (так делает облако перед сборкой сайта)
python sync_data.py push     — pack + отправить на GitHub (компьютер после недельного отчёта)
Ключ: переменная DATA_KEY (в облаке — секрет) или data_key из config_local.json."""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
BUNDLE = HERE / "data" / "reports.enc"
ROUNDS = 200_000


def key():
    secret = os.environ.get("DATA_KEY")
    if not secret:
        try:
            secret = json.loads((HERE / "config_local.json").read_text(encoding="utf-8"))["data_key"]
        except (OSError, ValueError, KeyError):
            sys.exit("Нет ключа DATA_KEY: задайте переменную окружения или data_key в config_local.json")
    return secret.encode("utf-8")


def pack():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in sorted(REPORTS.glob("*.json")) + sorted(REPORTS.glob("*_summary.md")):
            tar.add(f, arcname=f.name)
    salt, iv = os.urandom(16), os.urandom(12)
    k = hashlib.pbkdf2_hmac("sha256", key(), salt, ROUNDS, dklen=32)
    BUNDLE.parent.mkdir(exist_ok=True)
    BUNDLE.write_bytes(b"GSD1" + salt + iv + AESGCM(k).encrypt(iv, buf.getvalue(), None))
    print(f"Зашифровано: {BUNDLE} ({BUNDLE.stat().st_size // 1024} КБ)")


def unpack():
    raw = BUNDLE.read_bytes()
    assert raw[:4] == b"GSD1", "неизвестный формат"
    salt, iv, ct = raw[4:20], raw[20:32], raw[32:]
    k = hashlib.pbkdf2_hmac("sha256", key(), salt, ROUNDS, dklen=32)
    data = AESGCM(k).decrypt(iv, ct, None)
    REPORTS.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = Path(m.name).name  # только плоские имена файлов, без путей
            if m.isfile() and (name.endswith(".json") or name.endswith(".md")):
                (REPORTS / name).write_bytes(tar.extractfile(m).read())
    print(f"Расшифровано в {REPORTS}")


def push():
    pack()
    git = ["git", "-C", str(HERE)]
    subprocess.run(git + ["add", "data/reports.enc"], check=True)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
        print("Отчёты не изменились — отправлять нечего")
        return
    subprocess.run(git + ["commit", "-m", "Обновить недельные отчёты"], check=True)
    subprocess.run(git + ["pull", "--rebase", "--quiet"], check=True)
    subprocess.run(git + ["push", "--quiet"], check=True)
    print("Отчёты отправлены на GitHub")


if __name__ == "__main__":
    {"pack": pack, "unpack": unpack, "push": push}[sys.argv[1] if len(sys.argv) > 1 else "pack"]()
