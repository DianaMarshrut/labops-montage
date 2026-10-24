"""Check a rendered reel before sending it -> printed report, exit 1 on errors.

  python3 verify.py <project> [video] [--engine auto]
Default video: the newest file in out/. Checks:
  E  format 1080x1920 (final) or 720x1280 (preview), 30 fps, has sound
  E  voice loudness -16..-13 LUFS, true peak below -1 dBTP
  E  words lost at the joins: the render is recognised again and compared with work/words.json;
     a missing word within 0.4 s of a cut means the cut clipped it (re-run trim.py cut with a larger
     --pause or move the join); missing words elsewhere are only warnings (recognition varies)
  E  captions present (work/captions.json not empty) for a talking-head reel
  W  first visual change later than 1.5 s
  W  length outside 7-90 s
"""
from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sys
from pathlib import Path

from shared import Project, load_words, probe, run, setup_logging, tool
from transcribe import transcribe

log = logging.getLogger("verify")


def norm(t: str) -> str:
    """Lowercase word without punctuation, ё -> е."""
    return re.sub(r"[^\w]", "", t.lower()).replace("ё", "е")


def loud(video: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP)."""
    res = run([tool("ffmpeg"), "-nostats", "-i", str(video), "-vn", "-af",
               "ebur128=peak=true:framelog=quiet", "-f", "null", "-"], quiet=False)
    i = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", res.stderr)[-1])
    peaks = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", res.stderr)
    return i, float(peaks[-1]) if peaks and peaks[-1] != "-inf" else -99.0


def first_change(video: Path) -> float:
    """Time of the first scene change above 0.25 (or of the stream end)."""
    res = run([tool("ffmpeg"), "-nostats", "-t", "5", "-i", str(video), "-vf",
               "select='gt(scene,0.25)',showinfo", "-f", "null", "-"], quiet=False)
    hits = re.findall(r"pts_time:([\d.]+)", res.stderr)
    return float(hits[0]) if hits else 5.0


def joins(proj: Project) -> list[float]:
    """Times of the cuts on the clean timeline (from work/edl.json and the speed)."""
    edl = json.loads((proj.work / "edl.json").read_text()) if (proj.work / "edl.json").exists() else []
    speed = float(proj.meta().get("speed", 1.0))
    out, t = [], 0.0
    for s in edl[:-1]:
        t += s["b"] - s["a"]
        out.append(t / speed)
    return out


def lost_words(proj: Project, video: Path, engine: str) -> tuple[list[str], list[str]]:
    """Words of words.json missing in the render's recognition: (next to a join, elsewhere)."""
    meta = proj.meta()
    words = load_words(proj.work / "words.json")
    want = [norm(w.text) for w in words]
    got = [norm(w.text) for w in transcribe(video, meta.get("lang", "ru"), engine)]
    cuts = joins(proj)
    at_join, other = [], []
    for op, i1, i2, _, _ in difflib.SequenceMatcher(None, want, got, autojunk=False).get_opcodes():
        if op not in ("delete", "replace"):
            continue
        line = " ".join(want[max(i1 - 2, 0):i2 + 2]) + f"  <- missing: {' '.join(want[i1:i2])}"
        near = any(abs(c - t) < 0.4 for c in cuts for w in words[i1:i2] for t in (w.start, w.end))
        (at_join if near else other).append(f"{words[i1].start:.1f}s  {line}")
    return at_join, other


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("video", type=Path, nargs="?")
    ap.add_argument("--engine", default="auto")
    a = ap.parse_args()
    proj = Project(a.project)
    video = a.video or max(proj.out.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    err, warn = [], []
    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    size = (v["width"], v["height"])
    if size not in ((1080, 1920), (720, 1280)):
        err.append(f"size {size[0]}x{size[1]}, expected 1080x1920")
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    if abs(num / den - 30) > 0.1:
        err.append(f"{num / den:.2f} fps, expected 30")
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        err.append("no sound")
    else:
        i, peak = loud(video)
        if not -16 <= i <= -13:
            err.append(f"loudness {i:.1f} LUFS, expected -16..-13 (assemble.py --target)")
        if peak > -1:
            err.append(f"true peak {peak:.1f} dBTP, expected below -1")
    caps = proj.work / "captions.json"
    if not caps.exists() or not json.loads(caps.read_text()):
        err.append("no captions (subtitles.py render)")
    dur = float(info["format"]["duration"])
    if not 7 <= dur <= 90:
        warn.append(f"length {dur:.1f} s")
    fc = first_change(video)
    if fc > 1.5:
        warn.append(f"first visual change at {fc:.1f} s (hook should change within 1.5 s)")
    at_join, other = lost_words(proj, video, a.engine)
    err += [f"word clipped at a join: {x}" for x in at_join]
    warn += [f"not recognised in the render (listen to check): {x}" for x in other]
    print(f"{video.name}: {size[0]}x{size[1]}, {dur:.1f} s")
    for e in err:
        print(f"ERROR  {e}")
    for w in warn:
        print(f"WARN   {w}")
    print(f"{len(err)} errors, {len(warn)} warnings")
    sys.exit(1 if err else 0)


if __name__ == "__main__":
    main()
