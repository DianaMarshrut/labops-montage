"""Video effects on the picture: shake, glitch, flash, freeze frame (assemble.py reads work/fx.json).

  python3 effects.py demo <video> <out.mp4> [--start 2]
      8 seconds of the user's video with every effect in turn, numbered as in the catalogue
      (catalogs.py effects shows the same on a still frame). The user picks numbers.

work/fx.json (from plan.py apply): [{"a": 3.2, "b": 3.6, "kind": "shake"}, ...]
  1 shake   the picture trembles (an accent, a "boom" moment)
  2 glitch  colour split and noise, like a broken TV (a joke, "the brain broke")
  3 flash   a white flash that fades (a cut to a new thought)
  4 freeze  the picture stops for a moment, the voice goes on (a pause for effect)
Effects go under captions and graphics: those stay steady on top.
"""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from shared import FPS, H, W, run, setup_logging, tool

log = logging.getLogger("effects")
# kind -> (catalogue name, default length in seconds)
KINDS: dict[str, tuple[str, float]] = {
    "shake": ("Тряска", 0.4),
    "glitch": ("Глитч (помехи)", 0.35),
    "flash": ("Вспышка", 0.3),
    "freeze": ("Стоп-кадр", 0.8),
}


def _cond(items: list[dict]) -> str:
    """ffmpeg enable expression: true inside any of the windows."""
    return "+".join(f"between(t,{e['a']:.3f},{e['b']:.3f})" for e in items)


def freeze_frames(picture: Path, fx: list[dict], work: Path) -> list[Path]:
    """Still frame at the start of every freeze, slightly zoomed in (one PNG per freeze)."""
    out = []
    for i, e in enumerate(f for f in fx if f["kind"] == "freeze"):
        png = work / f"freeze-{i}.png"
        run([tool("ffmpeg"), "-y", "-ss", f"{e['a']:.3f}", "-i", str(picture), "-frames:v", "1",
             "-vf", f"scale={round(W * 1.04 / 2) * 2}:-2,crop={W}:{H}", str(png)])
        out.append(png)
    return out


def graph(v: str, fx: list[dict], first_input: int) -> tuple[list[str], str]:
    """Filter lines applying fx to stream v; freeze PNGs are inputs first_input, first_input+1, ...

    Returns (lines, label of the resulting stream).
    """
    unknown = {e["kind"] for e in fx} - KINDS.keys()
    if unknown:
        raise SystemExit(f"unknown effect: {', '.join(sorted(unknown))} (known: {', '.join(KINDS)})")
    lines: list[str] = []
    by = {k: [e for e in fx if e["kind"] == k] for k in KINDS}
    for i, e in enumerate(by["freeze"]):
        lines.append(f"{v}[{first_input + i}:v]overlay=0:0:shortest=1:enable='{_cond([e])}'[fz{i}]")
        v = f"[fz{i}]"
    if by["shake"]:
        lines += [f"{v}split[sh0][sh1]",
                  f"[sh1]scale={round(W * 1.08 / 2) * 2}:-2,crop={W}:{H}:x='(iw-ow)/2+18*sin(t*70)'"
                  f":y='(ih-oh)/2+14*cos(t*55)'[sh2]",
                  f"[sh0][sh2]overlay=0:0:enable='{_cond(by['shake'])}'[vsh]"]
        v = "[vsh]"
    if by["glitch"]:
        lines += [f"{v}split[gl0][gl1]",
                  f"[gl1]rgbashift=rh=-16:bh=16:rv=4,noise=alls=28:allf=t,"
                  f"scale={round(W * 1.04 / 2) * 2}:-2,crop={W}:{H}:x='(iw-ow)/2+40*(random(1)-0.5)'[gl2]",
                  f"[gl0][gl2]overlay=0:0:enable='{_cond(by['glitch'])}'[vgl]"]
        v = "[vgl]"
    if by["flash"]:
        fade = "+".join(f"between(t,{e['a']:.3f},{e['b']:.3f})*0.8*(1-(t-{e['a']:.3f})/{e['b'] - e['a']:.3f})"
                        for e in by["flash"])
        lines.append(f"{v}eq=brightness='{fade}':eval=frame[vfl]")
        v = "[vfl]"
    return lines, v


def labels(names: list[str], work: Path) -> list[Path]:
    """Transparent PNG captions "N. name" for the demo, drawn in a headless browser."""
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": W, "height": 200})
        for i, n in enumerate(names, 1):
            pg.set_content("<html><body style='margin:0;background:transparent'><div style='margin:40px auto;"
                           "width:fit-content;font:800 72px sans-serif;color:#fff;background:#000a;"
                           f"padding:10px 30px;border-radius:24px'>{i}. {n}</div></body></html>")
            path = work / f"label-{i}.png"
            pg.screenshot(path=str(path), omit_background=True)
            out.append(path)
        b.close()
    return out


def demo(video: Path, out: Path, start: float) -> Path:
    """8 s of the video, every effect once (at 0.8, 2.8, 4.8, 6.8 s) with its catalogue number on top."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        clip = work / "clip.mp4"
        run([tool("ffmpeg"), "-y", "-ss", f"{start}", "-t", "8", "-i", str(video), "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
             "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(clip)])
        fx = [{"a": 0.8 + 2 * i, "b": 0.8 + 2 * i + KINDS[k][1], "kind": k} for i, k in enumerate(KINDS)]
        stills = freeze_frames(clip, fx, work)
        tags = labels([n for n, _ in KINDS.values()], work)
        ins = ["-i", str(clip)]
        for f in stills + tags:
            ins += ["-loop", "1", "-framerate", str(FPS), "-i", str(f)]
        lines, v = graph("[0:v]", fx, 1)
        for i, _ in enumerate(tags):
            k = 1 + len(stills) + i
            lines.append(f"{v}[{k}:v]overlay=0:120:shortest=1:enable='between(t,{2 * i},{2 * i + 2})'[lb{i}]")
            v = f"[lb{i}]"
        lines.append(f"{v}format=yuv420p[v]")
        script = work / "demo.filter"
        script.write_text(";".join(lines))
        run([tool("ffmpeg"), "-y", *ins, "-/filter_complex", str(script), "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-t", "8", str(out)])
    log.info("-> %s", out)
    return out


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("video", type=Path)
    d.add_argument("out", type=Path)
    d.add_argument("--start", type=float, default=2.0, help="where in the video to take the 8 s from")
    a = ap.parse_args()
    demo(a.video, a.out, a.start)


if __name__ == "__main__":
    main()
