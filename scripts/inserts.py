"""Inserts (logos, screenshots, memes, numbers, text, animated graphics, video) -> transparent tracks in work/overlays/.

  python3 inserts.py <project> [--accent "#8B5CF6"]
Reads work/inserts.json (from plan.py apply): [{"a", "b", "kind", "src", "layout", "text"}]
  kind    image | logo | meme | screenshot: src is a local image file; text: shows "text" big
          gfx: animated graphic, "gfx": {...} (counter, bars, terminal, post, emoji, title, checklist),
          rendered with HyperFrames (graphics.py, needs Node.js 22+) -> track work/overlays/15-gfx.mov
          src may also be a video (.mp4 .mov .webm, e.g. a meme from memes.py): it plays muted for the
          beat (looped if shorter) -> separate track work/overlays/20-video.mov
          broll: the user's own clips (only when the user sent them and asked for it); the voice goes on
  layout  card   white card beside the head, on the side away from the face (needs work/faces.json)
          full   the graphic over the whole frame on a dark veil (the face is hidden for that beat)
          split  the graphic in the top half on a dark panel, the person stays visible below
          cover  (video only) the clip fills the whole frame instead of the face
          behind (text only) big text in the upper part BEHIND the person: run cutout.py after inserts.py
          stack  (video only) 2-3 clips one above the other, the whole frame; src is a list of files
Inserts never cover the face in the card layout; picture inserts enter with a short scale-up ("spring").
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import mimetypes
import shutil
from pathlib import Path
from statistics import median

import graphics
from shared import FPS, H, W, Project, duration, run, setup_logging, tool

log = logging.getLogger("inserts")
POP = (0.8, 0.94, 1.0)
VIDEO = {".mp4", ".mov", ".webm", ".m4v"}
VEIL = "0x0A0A0E"
FONT = "https://fonts.googleapis.com/css2?family=Manrope:wght@600;800&display=swap"


def data_uri(path: Path) -> str:
    """Inline image as a data URI (keeps the page self-contained)."""
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def face_side(faces: list[list[float]], a: float, b: float) -> tuple[float, float]:
    """Median face centre (x, y in 0..1) during [a, b]."""
    hits = [r for r in faces if a - 0.3 <= r[0] <= b + 0.3 and len(r) > 1]
    return (median(r[1] for r in hits), median(r[2] for r in hits)) if hits else (0.5, 0.4)


def content(ins: dict, accent: str, base: Path) -> str:
    """Inner HTML of the insert: an image or big text."""
    if ins["kind"] == "text" and ins.get("layout") == "behind":
        size = min(300, int(1000 / (0.75 * max(len(ins["text"]), 1))))  # one line across the frame
        return (f"<div style='font:800 {size}px/0.95 Manrope;color:#fff;text-align:center;text-transform:uppercase;"
                f"letter-spacing:-.02em;text-shadow:0 8px 40px rgba(0,0,0,.35)'>{html.escape(ins['text'])}</div>")
    if ins["kind"] == "text":
        size = 120 if len(ins["text"]) <= 8 else 84 if len(ins["text"]) <= 16 else 60
        return (f"<div style='font:800 {size}px/1.08 Manrope;color:{accent};text-align:center;"
                f"padding:20px 10px'>{html.escape(ins['text'])}</div>")
    src = Path(ins["src"])
    src = src if src.is_absolute() else base / src
    if not src.exists():
        raise SystemExit(f"insert image not found: {src}")
    return f"<img src='{data_uri(src)}' style='display:block;max-width:100%;max-height:100%;margin:auto'>"


def page(ins: dict, inner: str, face: tuple[float, float], scale: float) -> str:
    """Transparent 1080x1920 page with the insert in its layout."""
    layout = ins.get("layout", "card")
    if layout == "behind":  # the text centre sits a little above the face, so the head covers its lower part
        top = max(80, int(face[1] * H) - 560)
        box = (f"<div class='g' style='position:absolute;left:30px;right:30px;top:{top}px;height:500px;"
               f"display:flex;align-items:center;justify-content:center'>{inner}</div>")
    elif layout == "full":
        box = (f"<div style='position:absolute;inset:0;background:rgba(10,10,14,.82)'></div>"
               f"<div class='g' style='position:absolute;left:70px;right:70px;top:300px;bottom:420px;"
               f"display:flex;align-items:center;justify-content:center'>{inner}</div>")
    elif layout == "split":
        box = (f"<div style='position:absolute;left:0;right:0;top:0;height:880px;background:rgba(10,10,14,.9)'></div>"
               f"<div class='g' style='position:absolute;left:80px;right:80px;top:140px;height:680px;"
               f"display:flex;align-items:center;justify-content:center'>{inner}</div>")
    else:
        fx, fy = face
        left = fx > 0.5  # face on the right -> card on the left
        x = 60 if left else W - 60 - 480
        y = max(160, min(int(fy * H) - 520, 900))
        box = (f"<div class='g' style='position:absolute;left:{x}px;top:{y}px;width:480px;max-height:480px;"
               f"background:#fff;border-radius:28px;padding:26px;box-shadow:0 22px 50px rgba(0,0,0,.45);"
               f"display:flex;align-items:center;justify-content:center'>{inner}</div>")
    return (f"<html><head><meta charset='utf-8'><link href='{FONT}' rel='stylesheet'><style>"
            f"html,body{{margin:0;width:{W}px;height:{H}px;background:transparent}}"
            f".g{{transform:scale({scale});transform-origin:50% 50%}}</style></head><body>{box}</body></html>")


def sources(ins: dict, base: Path) -> list[Path]:
    """Insert source file(s) as absolute paths."""
    srcs = ins["src"] if isinstance(ins["src"], list) else [ins["src"]]
    return [Path(s) if Path(s).is_absolute() else base / s for s in srcs]


def is_video(ins: dict) -> bool:
    """True when the insert source is a video file (or a list of them for stack)."""
    srcs = ins.get("src") if isinstance(ins.get("src"), list) else [ins.get("src") or ""]
    return ins["kind"] != "text" and all(Path(s).suffix.lower() in VIDEO for s in srcs)


def build_video(proj: Project, items: list[dict], faces: list[list[float]], total: float) -> None:
    """Video inserts (memes, b-roll) on a transparent track: full / split / card layouts, muted, looped."""
    out = proj.work / "overlays" / "20-video.mov"
    out.parent.mkdir(exist_ok=True)
    out.unlink(missing_ok=True)
    if not items:
        return
    ins_args = ["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x{H}:r={FPS}:d={total:.3f},format=rgba"]
    graph, v, k = [], "[0:v]", 0
    for i, ins in enumerate(items):
        a, b = ins["a"], ins["b"]
        layout = ins.get("layout", "card")
        srcs = sources(ins, proj.root)
        if len(srcs) > 1 and layout != "stack":
            raise SystemExit(f"insert at {a:.1f} s: several files need layout stack")
        for src in srcs:
            if not src.exists():
                raise SystemExit(f"insert video not found: {src}")
            ins_args += ["-stream_loop", "-1", "-t", f"{b - a:.3f}", "-i", str(src)]
        on = f"enable='between(t,{a:.3f},{b:.3f})'"
        first, k = k + 1, k + len(srcs)
        m = f"[{first}:v]setpts=PTS-STARTPTS+{a:.3f}/TB,fps={FPS},"
        if layout == "stack":
            band = H // len(srcs)
            for j in range(len(srcs)):
                graph += [f"[{first + j}:v]setpts=PTS-STARTPTS+{a:.3f}/TB,fps={FPS},scale={W}:{band}:"
                          f"force_original_aspect_ratio=increase,crop={W}:{band},format=rgba[m{i}_{j}]",
                          f"{v}[m{i}_{j}]overlay=0:{j * band}:eof_action=pass:{on}[v{i}_{j}]"]
                v = f"[v{i}_{j}]"
            continue
        if layout == "cover":
            graph += [f"{m}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=rgba[m{i}]",
                      f"{v}[m{i}]overlay=0:0:eof_action=pass:{on}[v{i}]"]
        elif layout == "full":
            graph += [f"{m}scale={W - 140}:{H - 720}:force_original_aspect_ratio=decrease,format=rgba[m{i}]",
                      f"color=c={VEIL}@0.82:s={W}x{H}:r={FPS}:d={total:.3f},format=rgba[veil{i}]",
                      f"{v}[veil{i}]overlay=0:0:{on}[p{i}]",
                      f"[p{i}][m{i}]overlay=(W-w)/2:300+({H - 720}-h)/2:eof_action=pass:{on}[v{i}]"]
        elif layout == "split":
            graph += [f"{m}scale={W}:880:force_original_aspect_ratio=increase,crop={W}:880,format=rgba[m{i}]",
                      f"{v}[m{i}]overlay=0:0:eof_action=pass:{on}[v{i}]"]
        else:
            fx, fy = face_side(faces, a, b)
            x = 60 if fx > 0.5 else W - 60 - 480
            y = max(160, min(int(fy * H) - 520, 900))
            graph += [f"{m}scale=440:-2,pad=480:ih+40:20:20:white,format=rgba[m{i}]",
                      f"{v}[m{i}]overlay={x}:{y}:eof_action=pass:{on}[v{i}]"]
        v = f"[v{i}]"
    script = proj.work / "video-inserts.filter"
    script.write_text(";".join(graph))
    run([tool("ffmpeg"), "-y", *ins_args, "-/filter_complex", str(script), "-map", v, "-an",
         "-c:v", "png", "-t", f"{total:.3f}", str(out)])
    log.info("%d video inserts -> %s", len(items), out)


def picture_track(proj: Project, items: list[dict], faces: list[list[float]], total: float, accent: str,
                  name: str) -> None:
    """Render picture/text/graphic inserts to PNGs and assemble a transparent track the length of the cut."""
    from playwright.sync_api import sync_playwright

    folder = proj.work / f"inserts-{name}"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    timeline: list[tuple[float, float, Path]] = []
    step = 1 / FPS
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        pg = browser.new_page(viewport={"width": W, "height": H})
        blank = folder / "blank.png"
        pg.set_content("<html><body style='margin:0;background:transparent'></body></html>")
        pg.screenshot(path=str(blank), omit_background=True)
        for i, ins in enumerate(items):
            face = face_side(faces, ins["a"], ins["b"])
            inner = content(ins, accent, proj.root)
            shots = [(inner, s) for s in POP]
            for j, (inner, s) in enumerate(shots):
                png = folder / f"{i:03d}-{j:02d}.png"
                pg.set_content(page(ins, inner, face, s), wait_until="networkidle")
                pg.evaluate("document.fonts.ready")
                pg.screenshot(path=str(png), omit_background=True)
                a = ins["a"] + j * step
                b = ins["b"] if j == len(shots) - 1 else a + step
                timeline.append((a, b, png))
        browser.close()
    lines, t = [], 0.0
    for a, b, png in sorted(timeline, key=lambda x: x[0]):
        a, b = round(max(a, t) * FPS) / FPS, round(b * FPS) / FPS
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
    out_dir = proj.work / "overlays"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{name}.mov"
    run([tool("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS},format=rgba",
         "-c:v", "png", "-t", f"{total:.3f}", str(out)])
    log.info("%d inserts -> %s", len(items), out)


def build_gfx(proj: Project, items: list[dict], faces: list[list[float]], total: float, accent: str) -> None:
    """Animated graphics: one HyperFrames render per insert (graphics.py), placed on track 15-gfx."""
    out = proj.work / "overlays" / "15-gfx.mov"
    out.parent.mkdir(exist_ok=True)
    out.unlink(missing_ok=True)
    if not items:
        return
    ins_args = ["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x{H}:r={FPS}:d={total:.3f},format=rgba"]
    graph, v = [], "[0:v]"
    for i, ins in enumerate(items):
        mov = graphics.render(ins["gfx"], ins.get("layout", "full"), face_side(faces, ins["a"], ins["b"]), accent,
                              ins["b"] - ins["a"], proj.work / "gfx" / f"{i:02d}")
        ins_args += ["-i", str(mov)]
        graph += [f"[{i + 1}:v]setpts=PTS-STARTPTS+{ins['a']:.3f}/TB,format=rgba[g{i}]",
                  f"{v}[g{i}]overlay=0:0:eof_action=pass[v{i}]"]
        v = f"[v{i}]"
    script = proj.work / "gfx.filter"
    script.write_text(";".join(graph))
    run([tool("ffmpeg"), "-y", *ins_args, "-/filter_complex", str(script), "-map", v, "-c:v", "png",
         "-t", f"{total:.3f}", str(out)])
    log.info("%d animated graphics -> %s", len(items), out)


def build(proj: Project, accent: str) -> None:
    """All insert tracks: 05-behind (text behind the head), 10-inserts (pictures, text), 15-gfx (animated
    graphics), 20-video."""
    items = json.loads((proj.work / "inserts.json").read_text())
    faces = json.loads((proj.work / "faces.json").read_text()) if (proj.work / "faces.json").exists() else []
    total = duration(proj.work / "clean.mp4")
    build_video(proj, [x for x in items if is_video(x)], faces, total)
    build_gfx(proj, [x for x in items if x["kind"] == "gfx"], faces, total, accent)
    behind = [x for x in items if x.get("layout") == "behind"]
    pictures = [x for x in items if not is_video(x) and x["kind"] != "gfx" and x.get("layout") != "behind"]
    for name, group in (("05-behind", behind), ("10-inserts", pictures)):
        (proj.work / "overlays" / f"{name}.mov").unlink(missing_ok=True)
        if group:
            picture_track(proj, group, faces, total, accent, name)
    if behind:
        log.info("text behind the head: run cutout.py %s next", proj.root)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--accent", default="#8B5CF6", help="colour of big text inserts")
    a = ap.parse_args()
    build(Project(a.project), a.accent)


if __name__ == "__main__":
    main()
