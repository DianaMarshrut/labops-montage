"""Numbered catalogues on a real frame of the user's video (step 3 of SKILL.md: the user picks numbers).

  python3 catalogs.py accents <frame.jpg> <out.png> [--word "ремонт"]
  python3 catalogs.py grey <frame.jpg> <out.png>
  python3 catalogs.py layouts <frame.jpg> <out.png>
  python3 catalogs.py effects <frame.jpg> <out.png>
  (subtitles: python3 subtitles.py sheet <frame.jpg> <out.png>)

Accent looks are used by subtitles.py render --accent-look N: they replace the style's own accent (.e).
Grey moment: 1 = black-and-white, 2 = black-and-white + loading spinner (finish.py reads work/grey.json).
Layouts (how the frame is arranged) map to plan.json: 1 face close = zoom 1.6, 2 card = insert layout
"card", 3 full = "full", 4 split = "split".
Effects map to plan.json "fx": 1 shake, 2 glitch, 3 flash, 4 freeze. A still frame only hints at motion:
show the moving version too (effects.py demo).
"""
from __future__ import annotations

import argparse
import base64
import html
import logging
from pathlib import Path

from common import setup_logging
from effects import KINDS as FX_KINDS

log = logging.getLogger("catalogs")
FONTS = ("https://fonts.googleapis.com/css2?family=Manrope:wght@600;800&family=Caveat:wght@700"
         "&display=swap")
# hand-drawn shapes as base64 SVG backgrounds (no quotes, safe inside style="..."), one styled <span> per accent
def _svg(body: str, box: str) -> str:
    """CSS url() of an inline SVG."""
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='{box}' preserveAspectRatio='none'>{body}</svg>"
    return f"url(data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()})"


BRUSH = _svg("<path d='M6 46 C 40 18, 120 10, 210 16 S 296 22, 292 40 C 288 60, 200 70, 120 66 "
             "S 10 70, 6 46 Z' fill='#FFE14D' opacity='.95'/>", "0 0 300 80")
UNDERLINE = _svg("<path d='M4 20 C 70 6, 150 28, 296 10' fill='none' stroke='#FF5FA0' stroke-width='7' "
                 "stroke-linecap='round'/>", "0 0 300 30")
ACCENTS: list[tuple[str, str]] = [
    ("Мазок кисти", f"color:#2b2118;text-shadow:none;background:{BRUSH} center/112% 120% no-repeat;"
                    "padding:0 .25em;display:inline-block;transform:rotate(-3deg)"),
    ("Маркер-выделитель", "background:linear-gradient(transparent 52%,rgba(255,214,0,.9) 52%,"
                          "rgba(255,214,0,.9) 92%,transparent 92%);padding:0 .12em"),
    ("Фиолетовая пилюля", "background:#8B5CF6;color:#fff;border-radius:999px;padding:0 .4em;text-shadow:none;"
                          "box-shadow:0 10px 26px rgba(0,0,0,.35)"),
    ("Подчёркивание от руки", f"background:{UNDERLINE} bottom/100% .35em no-repeat;padding-bottom:.18em"),
    ("Рамка-обводка", "border:.08em solid #fff;border-radius:.22em;padding:0 .3em"),
    ("Крупное слово + свечение", "font-size:1.28em;text-shadow:0 0 18px rgba(255,240,200,.95),"
                                 "0 0 42px rgba(255,200,120,.75),0 4px 14px rgba(0,0,0,.4)"),
    ("Стикер-наклейка", "background:#FFF4B8;color:#2b2118;padding:0 .3em;border-radius:.16em;text-shadow:none;"
                        "display:inline-block;transform:rotate(-5deg);border:.05em solid #fff;"
                        "box-shadow:0 12px 24px rgba(0,0,0,.35)"),
    ("Рукописное слово", "font-family:Caveat;font-weight:700;font-size:1.35em;color:#FFE08A"),
]
SPIN = ('<svg width="150" height="150" viewBox="0 0 50 50" style="position:absolute;left:465px;top:300px">'
        '<circle cx="25" cy="25" r="20" fill="none" stroke="rgba(255,255,255,.3)" stroke-width="5"/>'
        '<path d="M25 5 A20 20 0 0 1 45 25" fill="none" stroke="#fff" stroke-width="5" '
        'stroke-linecap="round"/></svg>')
CARD = ('<div style="background:#fff;border-radius:28px;box-shadow:0 22px 50px rgba(0,0,0,.45);padding:30px;'
        'font:800 64px/1.1 Manrope;color:#1d2433;text-align:center">вставка<br>'
        '<span style="color:#8B5CF6">логотип / цифра</span></div>')


def cells_page(frame: Path, cells: list[tuple[str, str]], cols: int) -> str:
    """Grid of 1080x1920 frames shown at 1/3 scale, each with a number and a name."""
    img = f"data:image/jpeg;base64,{base64.b64encode(frame.read_bytes()).decode()}"
    out = []
    for i, (name, inner) in enumerate(cells, 1):
        out.append(f"<div class='cell'><div class='fr'>{inner}</div>"
                   f"<b>{i}. {html.escape(name)}</b></div>")
    return (f"<html><head><meta charset='utf-8'><link href='{FONTS}' rel='stylesheet'><style>"
            f"body{{margin:0;background:#111;display:grid;grid-template-columns:repeat({cols},360px);gap:8px;"
            "padding:8px;font-family:Manrope}.cell{position:relative;width:360px;height:640px;overflow:hidden}"
            ".fr{position:absolute;left:0;top:0;width:1080px;height:1920px;transform:scale(.3333);"
            f"transform-origin:0 0}}.bg{{position:absolute;inset:0;background:url({img}) center/cover}}"
            ".cell b{position:absolute;left:8px;top:8px;font:700 22px/1.2 sans-serif;color:#fff;"
            "background:#000a;padding:4px 8px;border-radius:6px}"
            ".acc{position:absolute;left:0;right:0;top:1250px;text-align:center;font:800 96px/1.2 Manrope;"
            "color:#fff;text-shadow:0 4px 22px rgba(0,0,0,.55)}</style></head>"
            f"<body>{''.join(out)}</body></html>")


def accents(word: str) -> list[tuple[str, str]]:
    """Accent looks on a caption line."""
    return [(n, f"<div class='bg'></div><div class='acc'>это <span style=\"{css}\">{html.escape(word)}</span>"
                f"</div>") for n, css in ACCENTS]


def grey() -> list[tuple[str, str]]:
    """Grey moment variants."""
    g = "<div class='bg' style='filter:grayscale(1)'></div>"
    return [("Ч/б", g), ("Ч/б + значок загрузки", g + SPIN)]


def layouts() -> list[tuple[str, str]]:
    """Frame layouts used by plan.json."""
    return [
        ("Лицо крупно (zoom 1.6)", "<div class='bg' style='transform:scale(1.6);transform-origin:50% 35%'></div>"),
        ("Карточка рядом с головой (card)", "<div class='bg'></div><div style='position:absolute;left:560px;"
                                            f"top:300px;width:460px;transform:scale(.8);transform-origin:0 0'>{CARD}</div>"),
        ("Графика на весь экран (full)", "<div class='bg' style='filter:blur(14px) brightness(.35)'></div>"
                                         f"<div style='position:absolute;left:70px;right:70px;top:600px'>{CARD}</div>"),
        ("Графика сверху, человек снизу (split)", "<div class='bg'></div><div style='position:absolute;left:0;"
                                                   "right:0;top:0;height:880px;background:rgba(10,10,14,.9)'></div>"
                                                   f"<div style='position:absolute;left:80px;right:80px;top:250px'>{CARD}</div>"),
    ]


def effects() -> list[tuple[str, str]]:
    """Video effects as still hints, in effects.KINDS order."""
    tint = "background-color:{c};background-blend-mode:multiply;mix-blend-mode:screen;opacity:.75"
    look = {
        "shake": "<div class='bg' style='filter:blur(3px)'></div>"
                 "<div class='bg' style='transform:translate(-28px,8px);opacity:.45'></div>"
                 "<div class='bg' style='transform:translate(28px,-8px);opacity:.45'></div>",
        "glitch": "<div class='bg'></div>"
                  f"<div class='bg' style='transform:translateX(-22px);{tint.format(c='#f00')}'></div>"
                  f"<div class='bg' style='transform:translateX(22px);{tint.format(c='#0ff')}'></div>"
                  "<div style='position:absolute;inset:0;background:repeating-linear-gradient(0deg,"
                  "transparent 0 40px,rgba(255,255,255,.18) 40px 52px)'></div>",
        "flash": "<div class='bg'></div><div style='position:absolute;inset:0;background:#fff;opacity:.7'></div>",
        "freeze": "<div class='bg' style='transform:scale(1.04)'></div>"
                  "<div style='position:absolute;inset:0;border:28px solid #fff'></div>",
    }
    return [(name, look[k]) for k, (name, _) in FX_KINDS.items()]


def render(doc: str, out: Path, cols: int) -> None:
    """Screenshot the catalogue page."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": cols * 368 + 8, "height": 700})
        pg.set_content(doc, wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out), full_page=True)
        b.close()
    log.info("-> %s", out)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["accents", "grey", "layouts", "effects"])
    ap.add_argument("frame", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--word", default="ремонт")
    a = ap.parse_args()
    cells = {"accents": lambda: accents(a.word), "grey": grey, "layouts": layouts, "effects": effects}[a.kind]()
    cols = 4
    render(cells_page(a.frame, cells, cols), a.out, cols)


if __name__ == "__main__":
    main()
