# -*- coding: utf-8 -*-
"""Картинка-таблица со статистикой недели для отправки в Telegram."""
import os

from PIL import Image, ImageDraw, ImageFont

S = 2  # масштаб для чёткости
FONTS = r"C:\Windows\Fonts"

BG = "#F4F6FA"
HEAD = "#1F2A44"
HEAD_SUB = "#AEB8D0"
COL_BG = "#E3E8F2"
ROW_A = "#FFFFFF"
ROW_B = "#F8F9FC"
LINE = "#E3E7EF"
TEXT = "#1F2A44"
MUTED = "#8A93A6"
ACCENT = "#2F6FED"
MEDALS = ["#F2B705", "#A7B1C2", "#CD7F32"]


def font(bold, size):
    for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
        try:
            return ImageFont.truetype(os.path.join(FONTS, name), size * S)
        except OSError:
            pass
    return ImageFont.load_default()


def num(n):
    return f"{n:,}".replace(",", " ")


def coef(c):
    """КФ — всегда целое, дробная часть отбрасывается (174,67 -> 174)."""
    return str(int(round(c, 6) // 1))


def render(path, title, period, rows, footer_lines, shifts=None, icons=None):
    """icons: {ник: путь к картинке эмодзи} — рисуется слева от ника."""
    icons = icons or {}
    """rows: [(имя, постов, репостов, коэффициент)], уже отсортированы."""
    W, pad = 900 * S, 40 * S
    head_h, col_h, row_h = 130 * S, 50 * S, 60 * S
    foot_h = (30 + 34 * len(footer_lines)) * S
    H = head_h + col_h + row_h * max(len(rows), 1) + foot_h

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, head_h], fill=HEAD)
    d.text((pad, 30 * S), title, font=font(True, 34), fill="white")
    d.text((pad, 82 * S), period, font=font(False, 22), fill=HEAD_SUB)

    x_rank, x_name = pad + 18 * S, pad + 60 * S
    x_shifts, x_posts, x_rep, x_coef = 440 * S, 560 * S, 715 * S, W - pad

    y = head_h
    d.rectangle([0, y, W, y + col_h], fill=COL_BG)
    cy = y + col_h // 2
    f_col = font(True, 18)
    d.text((x_rank, cy), "#", font=f_col, fill=MUTED, anchor="mm")
    d.text((x_name, cy), "Редактор", font=f_col, fill=MUTED, anchor="lm")
    if shifts is not None:
        d.text((x_shifts, cy), "Смен", font=f_col, fill=MUTED, anchor="rm")
    d.text((x_posts, cy), "Постов", font=f_col, fill=MUTED, anchor="rm")
    d.text((x_rep, cy), "Репостов", font=f_col, fill=MUTED, anchor="rm")
    d.text((x_coef, cy), "Коэффициент", font=f_col, fill=MUTED, anchor="rm")

    y += col_h
    f_row, f_bold = font(False, 24), font(True, 24)
    rank = 0
    for i, (name, posts, reposts, c) in enumerate(rows):
        d.rectangle([0, y, W, y + row_h], fill=ROW_A if i % 2 == 0 else ROW_B)
        d.line([0, y + row_h - 1, W, y + row_h - 1], fill=LINE, width=S)
        cy = y + row_h // 2
        active = posts > 0
        color = TEXT if active else MUTED
        if active:
            rank += 1
            if rank <= 3:
                r = 17 * S
                d.ellipse([x_rank - r, cy - r, x_rank + r, cy + r], fill=MEDALS[rank - 1])
                d.text((x_rank, cy), str(rank), font=font(True, 18), fill="white", anchor="mm")
            else:
                d.text((x_rank, cy), str(rank), font=font(False, 20), fill=MUTED, anchor="mm")
        else:
            d.text((x_rank, cy), "–", font=font(False, 20), fill=MUTED, anchor="mm")
        x_text = x_name
        if name in icons:
            size = 34 * S
            icon = Image.open(icons[name]).convert("RGBA").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)  # скруглённые углы, как в Telegram
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=8 * S, fill=255)
            alpha = Image.composite(icon.getchannel("A"), mask, mask)
            icon.putalpha(alpha)
            img.paste(icon, (x_name, cy - size // 2), icon)
            x_text = x_name + size + 12 * S
        d.text((x_text, cy), name, font=f_bold if active else f_row, fill=color, anchor="lm")
        if shifts is not None:
            d.text((x_shifts, cy), num(shifts.get(name, 0)), font=f_row, fill=color, anchor="rm")
        d.text((x_posts, cy), num(posts), font=f_row, fill=color, anchor="rm")
        d.text((x_rep, cy), num(reposts), font=f_row, fill=color, anchor="rm")
        d.text((x_coef, cy), coef(c), font=f_bold, fill=ACCENT if active else MUTED, anchor="rm")
        y += row_h

    y += 18 * S
    f_foot = font(False, 19)
    for line in footer_lines:
        d.text((pad, y), line, font=f_foot, fill=MUTED)
        y += 34 * S

    img.save(path)
    return path
