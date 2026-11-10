# -*- coding: utf-8 -*-
"""Расписание смен из Google Таблицы «Gabe News | INFO».

Листы «Расписание <Месяц>»: два календаря (сверху — дневная смена, снизу — вечерняя),
редактор смены отмечен цветом клетки с числом. Цвета расшифровываются по легенде на том же листе
(клетка с ником, закрашенная цветом редактора).
Адрес таблицы — секрет SCHEDULE_SHEET_ID (на компьютере — schedule_sheet_id в config_local.json)."""
import io
import json
import os
import re
import urllib.request
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
          "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
# Календари на листе сверху вниз
SHIFTS = [{"key": "day", "name": "День", "time": "09:00–17:00"},
          {"key": "evening", "name": "Вечер", "time": "17:00–00:00"}]
# Ник в таблице -> подпись редактора в канале
ALIASES = {"nirel": "nire'loo", "nirelo": "nire'loo", "nireloo": "nire'loo", "nire'loo": "nire'loo",
           "kalash": "unreliable", "unreliable": "unreliable",
           "кирилл": "Who is it?", "who is it?": "Who is it?",
           "n1xkoo": "n1xkoo"}


def sheet_id():
    sid = os.environ.get("SCHEDULE_SHEET_ID")
    if not sid:
        try:
            sid = json.loads((HERE / "config_local.json").read_text(encoding="utf-8")).get("schedule_sheet_id")
        except (OSError, ValueError):
            sid = None
    return sid


def color(cell):
    f = cell.fill
    if not f or f.fill_type != "solid" or f.fgColor is None or f.fgColor.type != "rgb":
        return None
    rgb = (f.fgColor.rgb or "").upper()
    return None if rgb in ("", "00000000", "FFFFFFFF") else rgb[-6:]


def parse_sheet(ws, year, month):
    cells = [c for row in ws.iter_rows() for c in row]
    legend, nameless = {}, []
    for c in cells:
        text = c.value.strip() if isinstance(c.value, str) else ""
        # ник в легенде; заметки вроде «13x3650» (ставки, суммы) — пропускаем
        if not text or text.lower() in WEEKDAYS or re.fullmatch(r"[\d\s×xх*,.:/+-]+", text):
            continue
        col = color(c)
        if col and col not in legend:      # первая клетка с этим цветом — легенда
            legend[col] = text
        elif not col:
            nameless.append(text)          # ник без читаемого цвета (например, цвет из темы)
    headers = sorted({c.row for c in cells if isinstance(c.value, str) and c.value.strip().lower() == "понедельник"})
    # один ник без цвета и один цвет дня без ника — это одно и то же
    unknown = {color(c) for c in cells if isinstance(c.value, (int, float)) and color(c) and color(c) not in legend}
    nameless = [n for n in nameless if n not in legend.values()]
    if len(unknown) == 1 and len(nameless) == 1:
        legend[unknown.pop()] = nameless[0]
    days = {}
    for shift, header_row in zip(SHIFTS, headers):
        first_col = next(c.column for c in cells if c.row == header_row and isinstance(c.value, str)
                         and c.value.strip().lower() == "понедельник")
        r = header_row + 1
        while True:
            row = [ws.cell(row=r, column=first_col + i) for i in range(7)]
            nums = [c for c in row if isinstance(c.value, (int, float))]
            if not nums:
                break
            for c in nums:
                d = date(year, month, int(c.value)).isoformat()
                who = legend.get(color(c))
                days.setdefault(d, {})[shift["key"]] = (
                    {"editor": ALIASES.get(who.lower(), None), "label": who} if who else None)
            r += 1
    return {"legend": sorted(set(legend.values())), "days": days}


def load(today=None):
    """[{month: 'ГГГГ-ММ', title, days: {дата: {day: {...}, evening: {...}}}}]; пустой список, если таблица недоступна."""
    sid = sheet_id()
    if not sid:
        return []
    today = today or date.today()
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            wb = load_workbook(io.BytesIO(r.read()))
    except Exception as e:  # таблица недоступна — сайт соберётся без расписания
        print("Расписание не загружено:", type(e).__name__)
        return []
    out = []
    for name in wb.sheetnames:
        words = name.lower().split()
        if len(words) != 2 or words[0] != "расписание" or words[1] not in MONTHS:
            continue
        month = MONTHS.index(words[1]) + 1
        year = today.year + (1 if month - today.month < -6 else -1 if month - today.month > 6 else 0)
        try:
            parsed = parse_sheet(wb[name], year, month)
        except Exception as e:
            print(f"Лист «{name}» не разобран:", type(e).__name__, e)
            continue
        out.append({"month": f"{year}-{month:02d}", "title": f"{MONTHS[month - 1].capitalize()} {year}", **parsed})
    out.sort(key=lambda m: m["month"])
    return out


if __name__ == "__main__":
    for m in load():
        filled = sum(1 for d in m["days"].values() for v in d.values() if v)
        print(m["month"], m["title"], "легенда:", m["legend"], "дней:", len(m["days"]), "смен с редактором:", filled)
        for d in sorted(m["days"])[:3] + sorted(m["days"])[-2:]:
            print("  ", d, {k: (v or {}).get("label") for k, v in m["days"][d].items()})
