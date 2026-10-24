"""Analyse how a blogger edits reels and pack the style into its own skill.

  python3 reference.py fetch <folder> <instagram-url | video file> [...]
      Instagram via HikerAPI (HIKERAPI_KEY, about $0.001 per request), any other link via yt-dlp
      if installed, local files are copied -> <folder>/raw/NN.mp4
  python3 reference.py measure <folder> [--lang ru]
      per reel: length, cuts (scene changes), average shot, cuts per 10 s, first cut, words per minute,
      loudness; one frame per second as a sheet -> <folder>/sheets/NN.jpg, <folder>/metrics.md
  (then Claude looks at every sheet and writes <folder>/style.md: hook, framing and layouts, captions
   (font, case, size, position, accents), inserts and graphics, sound effects, pace, CTA -
   techniques only, never the blogger's frames, music or text)
  python3 reference.py skill <folder> --handle <name> [--dest ~/.claude/skills]
      -> <dest>/montage-<name>/SKILL.md (+ style.md, metrics.md): "смонтируй в стиле <name>" then
      edits with labops-montage following that style
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import statistics
import subprocess
from pathlib import Path

import requests

from common import duration, key, run, setup_logging, tool
from transcribe import transcribe

log = logging.getLogger("reference")
HIKER = "https://api.instagrapi.com/v2/media/info/by/code"


def fetch_instagram(url: str, dst: Path) -> None:
    """Download an Instagram reel through HikerAPI media info (video_versions URL)."""
    code = re.search(r"/(?:reel|reels|p)/([\w-]+)", url)
    if not code:
        raise SystemExit(f"not an Instagram reel link: {url}")
    secret = key("HIKERAPI_KEY")
    if not secret:
        raise SystemExit("HIKERAPI_KEY is not set: get a key at hikerapi.com or send the video file instead")
    r = requests.get(HIKER, params={"code": code.group(1)}, headers={"x-access-key": secret}, timeout=60)
    r.raise_for_status()
    data = r.json()
    media = data.get("media_or_ad") or data.get("media") or data
    versions = media.get("video_versions") or []
    if not versions:
        raise SystemExit(f"no video in {url} (photo post or private account)")
    with requests.get(versions[0]["url"], stream=True, timeout=300) as v:
        v.raise_for_status()
        with dst.open("wb") as fh:
            for chunk in v.iter_content(1 << 20):
                fh.write(chunk)


def fetch(folder: Path, items: list[str]) -> None:
    """Collect reference reels into folder/raw."""
    raw = folder / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    start = len(list(raw.glob("*.mp4")))
    for n, item in enumerate(items, start + 1):
        dst = raw / f"{n:02d}.mp4"
        if Path(item).exists():
            shutil.copy(item, dst)
        elif "instagram.com" in item:
            fetch_instagram(item, dst)
        elif shutil.which("yt-dlp"):
            subprocess.run(["yt-dlp", "-q", "-f", "mp4", "-o", str(dst), item], check=True)
        else:
            raise SystemExit(f"cannot download {item}: send the file, or install yt-dlp")
        log.info("%s -> %s", item, dst)


def cuts(video: Path, threshold: float = 0.3) -> list[float]:
    """Times of hard cuts (scene score above threshold)."""
    res = run([tool("ffmpeg"), "-nostats", "-i", str(video), "-vf", f"select='gt(scene,{threshold})',showinfo",
               "-an", "-f", "null", "-"], quiet=False)
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", res.stderr)]


def contact_sheet(video: Path, out: Path) -> None:
    """One frame per second, 8 per row, with time labels."""
    n = max(1, int(duration(video)))
    rows = (n + 7) // 8
    run([tool("ffmpeg"), "-y", "-i", str(video), "-vf",
         "fps=1,scale=240:-2,drawtext=text='%{pts\\:hms}':x=6:y=6:fontsize=18:fontcolor=white:box=1:"
         f"boxcolor=black@0.6,tile=8x{rows}:padding=4:color=0x111111", "-frames:v", "1", "-q:v", "3", str(out)])


def measure(folder: Path, lang: str) -> None:
    """Numbers per reel and the sheets Claude looks at."""
    sheets = folder / "sheets"
    sheets.mkdir(exist_ok=True)
    rows = []
    for video in sorted((folder / "raw").glob("*.mp4")):
        d = duration(video)
        c = cuts(video)
        shots = [b - a for a, b in zip([0.0] + c, c + [d])]
        words = transcribe(video, lang)
        res = run([tool("ffmpeg"), "-nostats", "-i", str(video), "-vn", "-af", "ebur128=framelog=quiet",
                   "-f", "null", "-"], quiet=False)
        lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", res.stderr)[-1])
        contact_sheet(video, sheets / f"{video.stem}.jpg")
        rows.append({"reel": video.stem, "length": round(d, 1), "cuts": len(c),
                     "avg_shot": round(statistics.mean(shots), 2), "cuts_per_10s": round(len(c) / d * 10, 1),
                     "first_cut": round(c[0], 2) if c else None, "words_per_min": round(len(words) / d * 60),
                     "lufs": lufs, "text": " ".join(w.text for w in words)})
        log.info("%s: %.1f s, %d cuts", video.stem, d, len(c))
    (folder / "metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    md = ["| reel | length s | cuts | avg shot s | cuts/10 s | first cut s | words/min | LUFS |",
          "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['reel']} | {r['length']} | {r['cuts']} | {r['avg_shot']} | {r['cuts_per_10s']} | "
           f"{r['first_cut']} | {r['words_per_min']} | {r['lufs']} |" for r in rows]
    if rows:
        md.append(f"\nMedian: avg shot {statistics.median(r['avg_shot'] for r in rows)} s, "
                  f"{statistics.median(r['cuts_per_10s'] for r in rows)} cuts per 10 s, "
                  f"{statistics.median(r['words_per_min'] for r in rows)} words/min")
    (folder / "metrics.md").write_text("\n".join(md) + "\n")
    log.info("metrics.md and sheets/ ready: now look at every sheet and write style.md")


def skill(folder: Path, handle: str, dest: Path) -> None:
    """Pack style.md + metrics.md into a small skill that drives labops-montage."""
    style = folder / "style.md"
    if not style.exists():
        raise SystemExit("write style.md first (look at sheets/ and metrics.md)")
    name = f"montage-{re.sub(r'[^a-z0-9-]+', '-', handle.lower()).strip('-')}"
    out = dest.expanduser() / name
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(style, out / "style.md")
    shutil.copy(folder / "metrics.md", out / "metrics.md")
    (out / "SKILL.md").write_text(f"""---
name: {name}
description: Edit a talking-head reel in the style of {handle}. Use when the user asks "смонтируй в стиле {handle}" or "edit like {handle}".
---

# Montage in the style of {handle}

1. Read `style.md` and `metrics.md` in this folder: they are the measured style (techniques only).
2. Edit with the `labops-montage` skill, all its steps and OK gates, with these settings:
   - pace: match the median shot length and cuts per 10 s from metrics.md (prep.py cut --speed, plan beats);
   - captions, accents, layouts, inserts, sound and video effects, hook and CTA: as described in style.md,
     picked from the labops-montage catalogues (closest numbers), shown to the user on their own frame;
3. Never copy the blogger's frames, music or text.
""")
    log.info("skill -> %s", out)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("folder", type=Path)
    f.add_argument("items", nargs="+")
    m = sub.add_parser("measure")
    m.add_argument("folder", type=Path)
    m.add_argument("--lang", default="ru")
    s = sub.add_parser("skill")
    s.add_argument("folder", type=Path)
    s.add_argument("--handle", required=True)
    s.add_argument("--dest", type=Path, default=Path("~/.claude/skills"))
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.folder, a.items)
    elif a.cmd == "measure":
        measure(a.folder, a.lang)
    else:
        skill(a.folder, a.handle, a.dest)


if __name__ == "__main__":
    main()
