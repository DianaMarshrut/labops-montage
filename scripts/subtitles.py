"""Subtitles in a catalogue style -> transparent caption track (work/subs.mov) + preview.

  python3 subtitles.py list
  python3 subtitles.py sheet <frame.jpg> <out.png> [--text "я попросила ии|сделать ремонт"]
      numbered catalogue of all styles on a real frame of the user's video (step 3 of SKILL.md)
  python3 subtitles.py render <project> --style <id> [--accent "ремонт,ИИ"] [--accent-look N] [--top 1250]
                              [--case lower|keep|upper] [--words 3] [--chars 18] [--no-pop]
      reads work/words.json (fix typos there first), writes work/captions.json, work/subs.mov
      (PNG frames with alpha) and out/subs-preview.mp4 (captions over work/clean.mp4, 720p)

Rules: captions sit in the lower third above the Instagram caption and nickname (top ~1250 px of 1920),
2-3 words per chunk, broken at punctuation and pauses. Accent words get the style's accent look (.e).
Karaoke styles highlight the current word. Fonts load from Google Fonts (free, SIL OFL).
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from shared import FPS, H, W, Project, Word, load_words, run, setup_logging, tool

log = logging.getLogger("subtitles")
SHADOW = "text-shadow:0 4px 22px rgba(0,0,0,.55),0 1px 3px rgba(0,0,0,.4);"
POP = (0.86, 0.95, 1.0)  # scale of the first frames of a chunk ("spring" entrance)


@dataclass
class Style:
    """One subtitle style: Google Fonts family query, CSS font, extra CSS (.c block, .l line, .e accent, .k word)."""
    id: str
    name: str
    google: str
    font: str
    css: str
    karaoke: bool = False


GRAD = (".e{color:transparent;background:linear-gradient(180deg,#fffef6,#F49AAE);-webkit-background-clip:text;"
        "background-clip:text;text-shadow:none;filter:drop-shadow(0 4px 16px rgba(0,0,0,.45))}")
CLONE = "-webkit-box-decoration-break:clone;box-decoration-break:clone;"

STYLES: list[Style] = [
    Style("inter-gradient", "Inter жирный, акцент градиентом", "Inter:wght@800", "800 84px/1.05 Inter",
          f".c{{color:#fff;letter-spacing:-.025em;{SHADOW}}}{GRAD}.e{{font-size:1.18em}}"),
    Style("manrope-light", "Manrope тонкий", "Manrope:wght@600", "600 72px/1.15 Manrope",
          f".c{{color:#fff;{SHADOW}}}{GRAD}"),
    Style("montserrat-caps", "Montserrat капс", "Montserrat:wght@900", "900 78px/1.05 Montserrat",
          f".c{{color:#fff;text-transform:uppercase;letter-spacing:-.01em;{SHADOW}}}.e{{color:#FFD84D}}"),
    Style("unbounded-wide", "Unbounded широкий", "Unbounded:wght@700", "700 66px/1.12 Unbounded",
          f".c{{color:#fff;{SHADOW}}}.e{{color:#C6FF4D}}"),
    Style("caveat-hand", "Caveat рукописный", "Caveat:wght@700", "700 112px/1 Caveat",
          f".c{{color:#fff;{SHADOW}}}.e{{color:#FFB3C4}}"),
    Style("marck-script", "Marck Script пропись", "Marck+Script", "400 104px/1.05 'Marck Script'",
          f".c{{color:#fff;{SHADOW}}}.e{{color:#FFE08A}}"),
    Style("amatic-caps", "Amatic карандаш", "Amatic+SC:wght@700", "700 124px/1 'Amatic SC'",
          f".c{{color:#fff;letter-spacing:.02em;{SHADOW}}}.e{{color:#9FE7FF}}"),
    Style("playfair-italic", "Playfair курсив", "Playfair+Display:ital,wght@1,600",
          "italic 600 92px/1.05 'Playfair Display'", f".c{{color:#fff;{SHADOW}}}.e{{color:#F6C9A0}}"),
    Style("prata-classic", "Prata классика", "Prata", "400 84px/1.12 Prata",
          f".c{{color:#fff;{SHADOW}}}.e{{border-bottom:4px solid #E3A15B}}"),
    Style("yeseva-display", "Yeseva журнал", "Yeseva+One", "400 96px/1.05 'Yeseva One'",
          f".c{{color:#fff;{SHADOW}}}.e{{color:#FF8FA3}}"),
    Style("outline", "Обводка", "Russo+One", "400 90px/1.08 'Russo One'",
          ".c{text-transform:uppercase;color:transparent;-webkit-text-stroke:3px #fff;"
          "filter:drop-shadow(0 3px 10px rgba(0,0,0,.6))}.e{color:#fff;-webkit-text-stroke:0}"),
    Style("sticker-pill", "Стикер-пилюли", "Rubik:wght@700", "700 64px/1.55 Rubik",
          f".l{{background:#fff;color:#111;padding:.08em .42em;border-radius:.55em;{CLONE}"
          "box-shadow:0 6px 18px rgba(0,0,0,.35)}.e{background:#FFD84D}"),
    Style("comic-stroke", "Комикс-обводка", "Comfortaa:wght@700", "700 84px/1.1 Comfortaa",
          ".c{color:#fff;-webkit-text-stroke:14px #7C3AED;paint-order:stroke fill;"
          "filter:drop-shadow(0 6px 0 rgba(0,0,0,.35))}.e{-webkit-text-stroke-color:#111;color:#FFE14D}"),
    Style("neon", "Неон", "Rubik:wght@600", "600 84px/1.1 Rubik",
          ".c{color:#fff;text-shadow:0 0 6px #fff,0 0 18px #FF4FD8,0 0 38px #FF4FD8,0 0 70px #FF4FD8}"
          ".e{text-shadow:0 0 6px #fff,0 0 18px #3DF5FF,0 0 38px #3DF5FF,0 0 70px #3DF5FF}"),
    Style("highlighter", "Маркер", "Golos+Text:wght@700", "700 70px/1.45 'Golos Text'",
          f".c{{color:#fff;{SHADOW}}}.e{{color:#111;text-shadow:none;background:linear-gradient(transparent 12%,"
          f"#FFE600 12%,#FFE600 92%,transparent 92%);padding:0 .18em;{CLONE}}}"),
    Style("black-box", "Чёрная плашка", "Onest:wght@700", "700 64px/1.6 Onest",
          f".l{{background:rgba(0,0,0,.82);color:#fff;padding:.06em .36em;border-radius:.18em;{CLONE}}}"
          ".e{color:#FFD84D}"),
    Style("karaoke-box", "Караоке-плашка", "Montserrat:wght@800", "800 78px/1.15 Montserrat",
          f".c{{color:#fff;text-transform:uppercase;{SHADOW}}}"
          ".k{background:#22C55E;padding:0 .14em;border-radius:.14em;text-shadow:none}", True),
    Style("karaoke-color", "Караоке-цвет", "Inter:wght@900", "900 82px/1.08 Inter",
          f".c{{color:rgba(255,255,255,.92);text-transform:uppercase;letter-spacing:-.02em;{SHADOW}}}"
          ".k{color:#FFD84D;display:inline-block;margin:0 .1em;transform:scale(1.14) rotate(-2deg)}", True),
    Style("typewriter", "Печатная машинка", "JetBrains+Mono:wght@700", "700 62px/1.3 'JetBrains Mono'",
          f".l{{background:#F6F1E3;color:#1a1a1a;padding:.06em .3em;{CLONE}}}.e{{color:#C2410C}}"),
    Style("meme", "Мем", "Oswald:wght@700", "700 104px/1.02 Oswald",
          ".c{color:#fff;text-transform:uppercase;-webkit-text-stroke:10px #000;paint-order:stroke fill}"),
    Style("pixel", "Пиксель", "Pixelify+Sans:wght@700", "700 80px/1.15 'Pixelify Sans'",
          ".c{color:#fff;text-shadow:5px 5px 0 #000}.e{color:#5CFF7A}"),
    Style("extrude-3d", "Объём 3D", "Dela+Gothic+One", "400 84px/1.1 'Dela Gothic One'",
          ".c{color:#fff;text-shadow:2px 2px 0 #E85D9A,4px 4px 0 #E85D9A,6px 6px 0 #C13E7A,8px 8px 0 #C13E7A,"
          "10px 10px 0 #9B2A60,14px 16px 18px rgba(0,0,0,.45)}.e{color:#FFE14D}"),
    Style("russo-sport", "Спорт-наклон", "Russo+One", "400 84px/1.08 'Russo One'",
          f".c{{color:#fff;text-transform:uppercase;transform:skewX(-8deg);{SHADOW}}}.e{{color:#FF6B2C}}"),
    Style("tektur-tech", "Тех-HUD", "Tektur:wght@700", "700 74px/1.15 Tektur",
          f".l{{border:3px solid #3DF5FF;color:#fff;padding:.02em .3em;background:rgba(0,20,30,.55);{CLONE}}}"
          ".e{color:#3DF5FF}"),
    Style("mini-caps", "Мелкий капс", "Montserrat:wght@800", "800 46px/1.1 Montserrat",
          ".c{color:#E8FF6A;text-transform:uppercase;letter-spacing:.02em;text-shadow:0 2px 6px rgba(0,0,0,.55)}"
          ".e{color:#fff}"),
]
BY_ID = {s.id: s for s in STYLES}
CAVEAT = '<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@700&display=swap" rel="stylesheet">'


def scoped(style: Style, scope: str) -> str:
    """Prefix every rule of the style with a scope selector so many styles share one page."""
    out = [f"{scope} .c{{font:{style.font}}}"]
    for rule in style.css.split("}"):
        if "{" in rule:
            sel, body = rule.split("{", 1)
            out.append(",".join(f"{scope} {s.strip()}" for s in sel.split(",")) + "{" + body + "}")
    return "".join(out)


def fonts_link(styles: list[Style]) -> str:
    """One Google Fonts stylesheet link for the given styles."""
    q = "&".join(f"family={f}" for f in sorted({s.google for s in styles}))
    return f'<link href="https://fonts.googleapis.com/css2?{q}&display=swap" rel="stylesheet">'


@dataclass
class Chunk:
    """Words shown together on screen."""
    words: list[Word]
    start: float
    end: float


def clean(text: str, case: str) -> str:
    """Strip punctuation at the edges, apply the letter case."""
    t = text.strip().strip('.,…:;!?»"«–—')
    return t.lower() if case == "lower" else t.upper() if case == "upper" else t


def chunks(words: list[Word], max_words: int, max_chars: int, gap: float = 0.3, hold: float = 0.35) -> list[Chunk]:
    """Greedy groups of 2-3 words, broken at punctuation, pauses and length; no overlap between groups."""
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            text = " ".join(x.text for x in cur + [w])
            if (len(cur) >= max_words or len(text) > max_chars or w.start - cur[-1].end > gap
                    or cur[-1].text.rstrip()[-1:] in ".,?!…:;"):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        nxt = groups[i + 1][0].start if i + 1 < len(groups) else g[-1].end + hold
        out.append(Chunk(g, g[0].start, min(nxt, g[-1].end + hold)))
    return out


def markup(words: list[str], accents: set[str], karaoke_index: int | None = None) -> str:
    """Caption HTML: words split into at most two balanced lines, accents in .e, current word in .k."""
    spans = []
    for i, w in enumerate(words):
        cls = []
        if re.sub(r"\W", "", w.lower()) in accents:
            cls.append("e")
        if karaoke_index == i:
            cls.append("k")
        spans.append(f'<span class="{" ".join(cls)}">{html.escape(w)}</span>' if cls else html.escape(w))
    if len(" ".join(words)) <= 14 or len(words) < 2:
        lines = [spans]
    else:
        cut = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
        lines = [spans[:cut], spans[cut:]]
    return "<br>".join(f'<span class="l">{" ".join(l)}</span>' for l in lines)


def page(style: Style, body: str, top: int, scale: float = 1.0, extra: str = "") -> str:
    """Full transparent 1080x1920 page with one caption block."""
    return (f"<html><head><meta charset='utf-8'>{fonts_link([style])}{CAVEAT}<style>"
            f"html,body{{margin:0;width:{W}px;height:{H}px;background:transparent}}"
            f"#cap .wrap{{position:absolute;left:60px;right:60px;top:{top}px;text-align:center;"
            f"transform:scale({scale});transform-origin:50% 50%}}{scoped(style, '#cap')}{extra}</style></head>"
            f"<body><div id='cap'><div class='wrap'><div class='c'>{body}</div></div></div></body></html>")


def frames_needed(c: Chunk, style: Style, pop: bool) -> list[tuple[float, float, int | None, float]]:
    """(start, end, karaoke word index, scale) pieces of one chunk."""
    pieces: list[tuple[float, float, int | None, float]] = []
    if style.karaoke:
        for i, w in enumerate(c.words):
            a = c.start if i == 0 else w.start
            b = c.words[i + 1].start if i + 1 < len(c.words) else c.end
            pieces.append((a, b, i, 1.0))
    else:
        pieces.append((c.start, c.end, None, 1.0))
    if pop:
        a, b, k, _ = pieces[0]
        step = 1 / FPS
        lead = [(a + j * step, a + (j + 1) * step, k, s) for j, s in enumerate(POP[:-1]) if a + (j + 1) * step < b]
        pieces[0] = (a + len(lead) * step, b, k, 1.0)
        pieces = lead + pieces
    return pieces


def render(proj: Project, style_id: str, accents: set[str], top: int, case: str,
           max_words: int, max_chars: int, pop: bool, accent_look: int = 0) -> None:
    """Caption PNGs -> work/subs.mov track + 720p preview over the clean cut."""
    from playwright.sync_api import sync_playwright

    from catalogs import ACCENTS

    style = BY_ID[style_id]
    extra = f"#cap .e{{{ACCENTS[accent_look - 1][1]}}}" if accent_look else ""
    words = load_words(proj.work / "words.json")
    total = float(run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                       str(proj.work / "clean.mp4")]).stdout)
    cs = chunks(words, max_words, max_chars)
    folder = proj.work / "captions"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    timeline: list[tuple[float, float, Path]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        pg = browser.new_page(viewport={"width": W, "height": H})
        blank = folder / "blank.png"
        pg.set_content(f"<html><body style='margin:0;background:transparent'></body></html>")
        pg.screenshot(path=str(blank), omit_background=True)
        n = 0
        for c in cs:
            texts = [clean(w.text, case) for w in c.words]
            for a, b, k, scale in frames_needed(c, style, pop):
                png = folder / f"{n:05d}.png"
                pg.set_content(page(style, markup(texts, accents, k), top, scale, extra), wait_until="networkidle")
                pg.evaluate("document.fonts.ready")
                pg.screenshot(path=str(png), omit_background=True)
                timeline.append((a, b, png))
                n += 1
        browser.close()
    # concat list: blank between captions, frame-rounded durations
    lines, t = [], 0.0
    for a, b, png in timeline:
        a, b = round(a * FPS) / FPS, round(b * FPS) / FPS
        if a > t + 1e-6:
            lines += [f"file '{blank}'", f"duration {a - t:.4f}"]
        if b > a:
            lines += [f"file '{png}'", f"duration {b - a:.4f}"]
            t = b
    if total > t:
        lines += [f"file '{blank}'", f"duration {total - t:.4f}"]
    lines.append(f"file '{blank}'")
    lst = folder / "list.txt"
    lst.write_text("\n".join(lines) + "\n")
    track = proj.work / "subs.mov"
    run([tool("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS},format=rgba",
         "-c:v", "png", "-t", f"{total:.3f}", str(track)])
    (proj.work / "captions.json").write_text(json.dumps(
        [{"start": c.start, "end": c.end, "text": " ".join(clean(w.text, case) for w in c.words)} for c in cs],
        ensure_ascii=False, indent=1))
    preview = proj.out / "subs-preview.mp4"
    run([tool("ffmpeg"), "-y", "-i", str(proj.work / "clean.mp4"), "-i", str(track), "-filter_complex",
         "[0:v][1:v]overlay=0:0:format=auto,scale=720:1280:flags=lanczos[v]", "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", str(preview)])
    proj.update(subs={"style": style_id, "accents": sorted(accents), "accent_look": accent_look, "top": top,
                      "case": case})
    log.info("%d chunks, %d caption frames -> %s, preview %s", len(cs), len(timeline), track, preview)


def sheet(frame: Path, out: Path, text: str) -> None:
    """Numbered catalogue: every style rendered over the same real frame, 6 per row."""
    from playwright.sync_api import sync_playwright
    import base64

    words = text.split("|")
    body = (f'<span class="l">{html.escape(words[0])}</span><br>'
            f'<span class="l"><span class="e">{html.escape(words[-1])}</span></span>')
    img = base64.b64encode(frame.read_bytes()).decode()
    cells = []
    for i, s in enumerate(STYLES, 1):
        cells.append(f"<div class='cell' id='s{i}'><div class='wrap'><div class='c'>{body}</div></div><b>{i}. {html.escape(s.name)}</b></div>")
    css = "".join(scoped(s, f"#s{i}") for i, s in enumerate(STYLES, 1))
    doc = (f"<html><head><meta charset='utf-8'>{fonts_link(STYLES)}<style>body{{margin:0;background:#111;"
           "display:grid;grid-template-columns:repeat(6,360px);gap:8px;padding:8px}"
           f".cell{{position:relative;width:360px;height:640px;background:url(data:image/jpeg;base64,{img}) center/cover;"
           "overflow:hidden}.cell .wrap{position:absolute;left:0;width:1080px;top:416px;text-align:center;"
           "transform:scale(.3333);transform-origin:0 0}"
           ".cell b{position:absolute;left:8px;top:8px;font:700 22px/1.2 sans-serif;color:#fff;background:#000a;"
           f"padding:4px 8px;border-radius:6px}}{css}</style></head><body>{''.join(cells)}</body></html>")
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 6 * 368 + 8, "height": 800})
        pg.set_content(doc, wait_until="networkidle")
        pg.evaluate("document.fonts.ready")
        pg.wait_for_timeout(300)
        pg.screenshot(path=str(out), full_page=True)
        b.close()
    log.info("sheet -> %s", out)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("sheet")
    s.add_argument("frame", type=Path)
    s.add_argument("out", type=Path)
    s.add_argument("--text", default="я попросила ии|сделать ремонт")
    r = sub.add_parser("render")
    r.add_argument("project", type=Path)
    r.add_argument("--style", required=True, choices=list(BY_ID))
    r.add_argument("--accent", default="", help="comma-separated accent words")
    r.add_argument("--top", type=int, default=1250)
    r.add_argument("--case", default="lower", choices=["lower", "keep", "upper"])
    r.add_argument("--words", type=int, default=3)
    r.add_argument("--chars", type=int, default=18)
    r.add_argument("--no-pop", action="store_true")
    r.add_argument("--accent-look", type=int, default=0, help="number from `catalogs.py accents` (0 = style's own)")
    a = ap.parse_args()
    if a.cmd == "list":
        for i, st in enumerate(STYLES, 1):
            print(f"{i:>2}. {st.id:<16} {st.name}{'  (караоке)' if st.karaoke else ''}")
    elif a.cmd == "sheet":
        sheet(a.frame, a.out, a.text)
    else:
        acc = {re.sub(r"\W", "", x.lower()) for x in a.accent.split(",") if x.strip()}
        render(Project(a.project), a.style, acc, a.top, a.case, a.words, a.chars, not a.no_pop, a.accent_look)


if __name__ == "__main__":
    main()
