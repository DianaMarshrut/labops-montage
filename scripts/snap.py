"""Frame sheet: one still per beat, labelled -> out/snap.jpg. Seconds, not minutes: look before the final render.

  python3 snap.py <project> [video] [--at 0.5,4.2]
Default video: out/preview.mp4; default times: middle of every beat of plan.json, else one per second.
Look for: empty or repeated framing, text cut off at the edges, inserts over the face, unreadable captions.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import tempfile
from pathlib import Path

from common import Project, duration, run, setup_logging, tool

log = logging.getLogger("snap")


def times(proj: Project, video: Path) -> list[float]:
    """Middle of each beat, or one per second."""
    plan = proj.root / "plan.json"
    if plan.exists():
        return [round((b["a"] + b["b"]) / 2, 2) for b in json.loads(plan.read_text())["beats"]]
    return [t + 0.5 for t in range(int(duration(video)))]


def sheet(video: Path, at: list[float], out: Path, cols: int = 6) -> None:
    """Grab frames at the given times and tile them with time labels."""
    ff = tool("ffmpeg")
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(at):
            run([ff, "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf",
                 f"scale=270:480,drawtext=text='{i + 1}  {t:.1f}s':x=8:y=8:fontsize=22:fontcolor=white:"
                 "box=1:boxcolor=black@0.6:boxborderw=6", f"{tmp}/{i:03d}.png"])
        rows = math.ceil(len(at) / cols)
        run([ff, "-y", "-framerate", "1", "-i", f"{tmp}/%03d.png", "-vf",
             f"tile={cols}x{rows}:padding=6:margin=6:color=0x111111", "-frames:v", "1", "-q:v", "3", str(out)])
    log.info("%d frames -> %s", len(at), out)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("video", type=Path, nargs="?")
    ap.add_argument("--at", default="")
    a = ap.parse_args()
    proj = Project(a.project)
    video = a.video or proj.out / "preview.mp4"
    at = [float(x) for x in a.at.split(",") if x] or times(proj, video)
    sheet(video, at, proj.out / "snap.jpg")


if __name__ == "__main__":
    main()
