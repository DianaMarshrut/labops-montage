"""Animated graphics rendered with HyperFrames (HTML + GSAP -> transparent video); inserts.py places them.

  python3 graphics.py sheet <frame.jpg> <out.png>     catalogue: every type on the user's frame, numbered
  python3 graphics.py demo <out.mov> --type counter   render one example (check that HyperFrames works)

Needs Node.js 22+ (npx) and HyperFrames, which npx fetches on the first run (SKILL.md, step 0).
An insert {"kind": "gfx", "layout": "full|split|card", "gfx": {...}} becomes a HyperFrames composition the length
of its beat (work/gfx/NN/index.html -> work/gfx/NN.mov, ProRes 4444 with transparency). Types (catalogue numbers):
  1 counter    {"type": "counter", "to": 200, "from": 0, "prefix": "", "suffix": "×", "label": "быстрее"}
  2 bars       {"type": "bars", "items": [["январь", 30], ["март", 120]], "unit": "%"}
  3 terminal   {"type": "terminal", "lines": ["$ claude", "готово: 12 файлов"]}
  4 post       {"type": "post", "name": "Имя", "handle": "@name", "text": "текст поста"}
  5 emoji      {"type": "emoji", "char": "🔥", "label": "подпись"}
  6 title      {"type": "title", "text": "ГЛАВНОЕ", "sub": "подзаголовок"}
  7 checklist  {"type": "checklist", "items": ["пункт 1", "пункт 2", "пункт 3"]}
Numbers and texts must be real (from the speech or the user), never invented.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
from pathlib import Path

from shared import FPS, H, W, run, setup_logging, tool

log = logging.getLogger("graphics")
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
FONTS = ("https://fonts.googleapis.com/css2?family=Manrope:wght@500;800&family=JetBrains+Mono:wght@500"
         "&family=Noto+Color+Emoji&display=swap")
INK = "#1d2433"
PANEL = "background:#fff;border-radius:36px;padding:40px 56px;box-shadow:0 20px 50px rgba(0,0,0,.35)"
NAMES = {"counter": "Счётчик", "bars": "Столбики", "terminal": "Терминал", "post": "Пост", "emoji": "Эмодзи",
         "title": "Заголовок", "checklist": "Список"}
EXAMPLES: list[dict] = [
    {"type": "counter", "to": 200, "suffix": "×", "label": "быстрее"},
    {"type": "bars", "items": [["было", 30], ["стало", 120]], "unit": "%"},
    {"type": "terminal", "lines": ["$ claude", "готово: 12 файлов"]},
    {"type": "post", "name": "Имя Фамилия", "handle": "@name", "text": "Короткий текст поста"},
    {"type": "emoji", "char": "🔥", "label": "огонь"},
    {"type": "title", "text": "ГЛАВНОЕ", "sub": "подзаголовок"},
    {"type": "checklist", "items": ["пункт 1", "пункт 2", "пункт 3"]},
]


def body(spec: dict, accent: str) -> tuple[str, str]:
    """(HTML of the graphic in its final state, GSAP tweens on timeline `tl` that bring it in)."""
    kind = spec.get("type")
    esc = html.escape
    if kind == "counter":
        start, end = float(spec.get("from", 0)), float(spec["to"])
        digits = 0 if end.is_integer() else 1
        return (f"<div style='text-align:center;font-family:Manrope;color:{INK};{PANEL}'>"
                f"<div style='font-weight:800;font-size:200px;line-height:1;color:{accent}'>"
                f"{esc(spec.get('prefix', ''))}<span id='num'>{end:.{digits}f}</span>{esc(spec.get('suffix', ''))}"
                f"</div><div style='font-weight:500;font-size:56px;margin-top:16px'>{esc(spec.get('label', ''))}"
                f"</div></div>",
                f"const c={{v:{start}}};const n=document.getElementById('num');"
                f"tl.to(c,{{v:{end},duration:0.9,ease:'power3.out',onUpdate:()=>{{n.textContent="
                f"c.v.toFixed({digits}).replace(/\\B(?=(\\d{{3}})+(?!\\d))/g,' ')}}}},0.1);")
    if kind == "bars":
        items = spec["items"]
        top = max(v for _, v in items) or 1
        unit = esc(spec.get("unit", ""))
        width = min(220, 760 // len(items))
        bars = "".join(
            f"<div style='display:flex;flex-direction:column;align-items:center;justify-content:flex-end;"
            f"width:{width}px;height:620px'><div style='font:800 54px Manrope;color:{INK}'><span class='bv' "
            f"data-v='{v}'>{v}</span>{unit}</div><div class='bar' style='width:100%;height:{int(480 * v / top)}px;"
            f"background:{accent};border-radius:18px 18px 0 0;margin-top:10px;transform-origin:50% 100%'></div>"
            f"<div style='font:500 40px Manrope;color:{INK};margin-top:14px'>{esc(str(n))}</div></div>"
            for n, v in items)
        return (f"<div style='display:flex;gap:40px;align-items:flex-end;{PANEL}'>{bars}</div>",
                "tl.fromTo('.bar',{scaleY:0},{scaleY:1,duration:0.8,ease:'power3.out',stagger:0.12},0.1);"
                "document.querySelectorAll('.bv').forEach((el,i)=>{const t=+el.dataset.v;const c={v:0};"
                "tl.to(c,{v:t,duration:0.8,ease:'power3.out',onUpdate:()=>{el.textContent="
                "Number.isInteger(t)?Math.round(c.v):c.v.toFixed(1)}},0.1+i*0.12);});")
    if kind == "terminal":
        text = "\n".join(spec["lines"])
        dots = "".join(f"<i style='display:block;width:20px;height:20px;border-radius:50%;background:{c}'></i>"
                       for c in ("#ff5f57", "#febc2e", "#28c840"))
        return (f"<div style='width:860px;background:#16181d;border-radius:22px;overflow:hidden;"
                f"box-shadow:0 20px 50px rgba(0,0,0,.4)'><div style='height:56px;background:#2a2d34;display:flex;"
                f"gap:14px;align-items:center;padding-left:24px'>{dots}</div><div id='term' style='padding:34px;"
                f"font:500 44px/1.45 \"JetBrains Mono\";color:#e6e6e6;min-height:220px;white-space:pre-wrap'>"
                f"{esc(text)}</div></div>",
                f"const full={json.dumps(text)};const t=document.getElementById('term');const c={{n:0}};"
                f"tl.to(c,{{n:full.length,duration:{min(1.6, 0.04 * len(text)):.2f},ease:'none',onUpdate:()=>{{"
                f"t.textContent=full.slice(0,Math.round(c.n))+(c.n<full.length?'▌':'')}}}},0.2);")
    if kind == "post":
        return (f"<div id='post' style='width:840px;background:#fff;border-radius:28px;padding:40px;"
                f"font-family:Manrope;color:{INK};box-shadow:0 20px 50px rgba(0,0,0,.35)'><div style='display:flex;"
                f"gap:22px;align-items:center'><div style='width:96px;height:96px;border-radius:50%;"
                f"background:{accent}'></div><div><div style='font-weight:800;font-size:44px'>"
                f"{esc(spec.get('name', ''))}</div><div style='font-size:36px;color:#667'>"
                f"{esc(spec.get('handle', ''))}</div></div></div><div style='font-size:48px;line-height:1.3;"
                f"margin-top:28px'>{esc(spec.get('text', ''))}</div></div>",
                "tl.fromTo('#post',{y:90,opacity:0},{y:0,opacity:1,duration:0.6,ease:'power3.out'},0.05);")
    if kind == "emoji":
        return (f"<div style='text-align:center'><div id='emo' style='font:320px/1 \"Noto Color Emoji\"'>"
                f"{esc(spec['char'])}</div><div id='emol' style='font:800 64px Manrope;color:#fff;"
                f"text-shadow:0 4px 20px rgba(0,0,0,.6)'>{esc(spec.get('label', ''))}</div></div>",
                "tl.fromTo('#emo',{scale:0,rotation:-20},{scale:1,rotation:0,duration:0.7,ease:'back.out(2.6)'},0);"
                "tl.fromTo('#emol',{opacity:0,y:20},{opacity:1,y:0,duration:0.4},0.35);")
    if kind == "title":
        letters = "".join(f"<span class='ch' style='display:inline-block'>{esc(c) if c != ' ' else '&nbsp;'}</span>"
                          for c in spec["text"])
        return (f"<div style='text-align:center;font-family:Manrope'><div style='font-weight:800;font-size:150px;"
                f"line-height:1.05;color:#fff;text-shadow:0 6px 30px rgba(0,0,0,.5)'>{letters}</div>"
                f"<div id='sub' style='display:inline-block;margin-top:24px;background:{accent};color:#fff;"
                f"font-weight:800;font-size:52px;padding:8px 30px;border-radius:999px'>{esc(spec.get('sub', ''))}"
                f"</div></div>",
                "tl.fromTo('.ch',{y:60,opacity:0},{y:0,opacity:1,duration:0.4,ease:'back.out(2)',stagger:0.04},0);"
                "tl.fromTo('#sub',{scale:0.6,opacity:0},{scale:1,opacity:1,duration:0.4,ease:'back.out(2)'},0.45);")
    if kind == "checklist":
        rows = "".join(
            f"<div class='row' style='display:flex;gap:28px;align-items:center;margin:22px 0'><div style='width:84px;"
            f"height:84px;border-radius:22px;background:{accent};color:#fff;font:800 60px/84px Manrope;"
            f"text-align:center'><span class='tick' style='display:inline-block'>✓</span></div>"
            f"<div style='font:800 60px Manrope;color:{INK}'>{esc(it)}</div></div>" for it in spec["items"])
        return (f"<div style='background:#fff;border-radius:32px;padding:30px 50px;box-shadow:0 20px 50px "
                f"rgba(0,0,0,.35)'>{rows}</div>",
                "tl.fromTo('.row',{x:-70,opacity:0},{x:0,opacity:1,duration:0.45,ease:'power3.out',stagger:0.25},0.1);"
                "tl.fromTo('.tick',{scale:0},{scale:1,duration:0.3,ease:'back.out(3)',stagger:0.25},0.35);")
    raise SystemExit(f"unknown graphic type: {kind} (see graphics.py --help)")


def box_style(layout: str, face: tuple[float, float]) -> tuple[str, str]:
    """(backdrop HTML, CSS position of the graphic box) for a layout; card goes beside the head."""
    if layout == "full":
        return ("<div id='veil' style='position:absolute;inset:0;background:rgba(10,10,14,.82)'></div>",
                "left:70px;right:70px;top:300px;bottom:420px")
    if layout == "split":
        return ("<div id='veil' style='position:absolute;left:0;right:0;top:0;height:880px;"
                "background:rgba(10,10,14,.9)'></div>", "left:60px;right:60px;top:110px;height:740px")
    x = 40 if face[0] > 0.5 else W - 40 - 520
    y = max(140, min(int(face[1] * H) - 560, 860))
    return "", f"left:{x}px;top:{y}px;width:520px;height:560px"


def composition(spec: dict, layout: str, face: tuple[float, float], accent: str, dur: float) -> str:
    """Standalone HyperFrames composition, transparent, the length of the beat."""
    inner, tweens = body(spec, accent)
    backdrop, box = box_style(layout, face)
    scale = 0.7 if layout == "card" else 1.0  # the card slot is 520 px wide
    veil = "tl.fromTo('#veil',{opacity:0},{opacity:1,duration:0.2},0);" if backdrop else ""
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width={W}, height={H}">
<link href="{FONTS}" rel="stylesheet"><script src="{GSAP}"></script>
<style>body{{margin:0;background:transparent}}#root{{position:relative;width:100%;height:100%;overflow:hidden}}
#box{{position:absolute;{box};display:flex;align-items:center;justify-content:center}}</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-width="{W}" data-height="{H}"
data-duration="{dur:.3f}">{backdrop}<div id="box"><div id="g"><div style="zoom:{scale}">{inner}</div></div></div></div>
<script>
document.fonts.ready.then(() => {{
  const tl = gsap.timeline({{paused: true}});
  {veil}
  tl.fromTo('#g', {{scale: 0.86, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.35, ease: 'back.out(2)'}}, 0);
  {tweens}
  window.__timelines["main"] = tl;
}});
</script></body></html>"""


def npx() -> str:
    """npx of Node.js 22+: LABOPS_NPX, else ~/.local/opt/node22/bin/npx if present, else npx on PATH."""
    local = Path.home() / ".local" / "opt" / "node22" / "bin" / "npx"
    exe = str(local) if not os.environ.get("LABOPS_NPX") and local.exists() else tool("npx")
    os.environ["PATH"] = str(Path(exe).parent) + os.pathsep + os.environ.get("PATH", "")  # node next to npx
    return exe


def render(spec: dict, layout: str, face: tuple[float, float], accent: str, dur: float, folder: Path) -> Path:
    """Write the composition to folder/index.html and render it to folder.mov (transparent)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(composition(spec, layout, face, accent, dur))
    out = folder.with_suffix(".mov")
    run([npx(), "--yes", "hyperframes", "render", str(folder), "--format", "mov", "--fps", str(FPS),
         "--quiet", "--output", str(out)])
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError(f"HyperFrames did not render {out}")
    return out


def sheet(frame: Path, out: Path, accent: str) -> None:
    """Every graphic type (final state) on the user's frame, numbered (drawn in a headless browser)."""
    import base64

    from playwright.sync_api import sync_playwright

    img = f"data:image/jpeg;base64,{base64.b64encode(frame.read_bytes()).decode()}"
    cells = "".join(
        f"<div class='c'><div class='f'><div class='bg'></div><div class='v'></div><div class='g'>"
        f"{body(s, accent)[0]}</div></div><b>{i}. {NAMES[s['type']]}</b></div>" for i, s in enumerate(EXAMPLES, 1))
    doc = (f"<html><head><meta charset='utf-8'><link href='{FONTS}' rel='stylesheet'><style>"
           "body{margin:0;padding:8px;background:#111;display:grid;grid-template-columns:repeat(4,360px);gap:8px}"
           ".c{position:relative;width:360px;height:640px;overflow:hidden}.f{position:absolute;width:1080px;"
           "height:1920px;transform:scale(.3333);transform-origin:0 0}"
           f".bg{{position:absolute;inset:0;background:url({img}) center/cover}}"
           ".v{position:absolute;inset:0;background:rgba(10,10,14,.6)}"
           ".g{position:absolute;left:70px;right:70px;top:300px;bottom:420px;display:flex;align-items:center;"
           "justify-content:center}b{position:absolute;left:8px;top:8px;font:700 22px sans-serif;color:#fff;"
           "background:#000a;padding:4px 8px;border-radius:6px}</style></head>"
           f"<body>{cells}</body></html>")
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 4 * 368 + 8, "height": 2 * 648 + 16})
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
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("frame", type=Path)
    s.add_argument("out", type=Path)
    s.add_argument("--accent", default="#8B5CF6")
    d = sub.add_parser("demo")
    d.add_argument("out", type=Path)
    d.add_argument("--type", default="counter", choices=list(NAMES))
    d.add_argument("--layout", default="full", choices=["full", "split", "card"])
    a = ap.parse_args()
    if a.cmd == "sheet":
        sheet(a.frame, a.out, a.accent)
    else:
        spec = next(e for e in EXAMPLES if e["type"] == a.type)
        mov = render(spec, a.layout, (0.5, 0.4), "#8B5CF6", 2.0, a.out.with_suffix(""))
        log.info("-> %s", mov)


if __name__ == "__main__":
    main()
