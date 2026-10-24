"""Raw talking-head take -> clean cut with word timings.

  python3 trim.py init <raw.mov> <project> [--lang ru] [--engine auto] [--prompt "Claude, labopsai"]
      vertical 1080x1920 @30 (work/source.mp4), word timings (work/words.raw.json),
      numbered phrases for review (work/phrases.txt)
  python3 trim.py cut <project> [--drop 3.2-7.9,20.1-22.4] [--max-gap 0.35] [--pause 0.2] [--speed 1.2]
      cuts only in pauses between phrases (edges follow the real end of the sound, not Whisper word ends),
      keeps a natural pause of --pause seconds, drops the given source ranges (retakes, slips),
      applies the speed -> work/clean.mp4, work/words.json (clean timeline), work/edl.json

Review step between init and cut: read work/phrases.txt, find repeated takes and slips, pass their
source ranges in --drop (keep the last good take). Re-run cut as often as needed; it never touches init.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from shared import FPS, H, W, Project, Word, duration, load_words, run, save_words, setup_logging, tool
from transcribe import transcribe

log = logging.getLogger("trim")
ASR = 16000  # sample rate of the analysis audio


@dataclass
class Seg:
    """A kept range of the source, seconds."""
    a: float
    b: float


def init(raw: Path, proj: Project, lang: str, engine: str, prompt: str) -> None:
    """Normalise the take, recognise words, write the phrase list."""
    src = proj.work / "source.mp4"
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H},fps={FPS},setsar=1,format=yuv420p")
    run([tool("ffmpeg"), "-y", "-i", str(raw), "-vf", vf, "-c:v", "libx264", "-preset", "medium",
         "-crf", "16", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", str(src)])
    words = transcribe(src, lang, engine, prompt)
    save_words(proj.work / "words.raw.json", words)
    write_phrases(words, proj.work / "phrases.txt")
    proj.update(raw=str(raw.resolve()), lang=lang, source_duration=round(duration(src), 3))
    log.info("init done: %d words, read %s", len(words), proj.work / "phrases.txt")


def write_phrases(words: list[Word], path: Path, gap: float = 0.5) -> None:
    """Phrases split at pauses longer than gap: 'N  start-end  text' per line."""
    lines, cur = [], []
    for w in words:
        if cur and w.start - cur[-1].end > gap:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    path.write_text("".join(f"{i:>3}  {p[0].start:7.2f}-{p[-1].end:7.2f}  {' '.join(w.text for w in p)}\n"
                            for i, p in enumerate(lines, 1)))


def parse_ranges(spec: str) -> list[Seg]:
    """'3.2-7.9,20.1-22.4' -> segments."""
    out = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        a, b = part.split("-")
        out.append(Seg(float(a), float(b)))
    return out


def load_audio(path: Path) -> np.ndarray:
    """Mono 16 kHz float samples of a media file."""
    res = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", str(ASR), "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(res.stdout, dtype="<f4")


def speech_mask(audio: np.ndarray, hop: int = 160, margin_db: float = 6.0) -> np.ndarray:
    """True per 10 ms frame where the level is above the noise floor (10th percentile) + margin."""
    frames = audio[: len(audio) // hop * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    return db > np.percentile(db, 10) + margin_db


def silence_after(mask: np.ndarray, t: float, limit: float, hold: int = 8) -> float:
    """First time after t where `hold` frames in a row are quiet (Whisper word ends are often early)."""
    i, stop = int(t * 100), min(int(limit * 100), len(mask))
    while i < stop:
        if not mask[i:i + hold].any():
            return i / 100
        i += 1
    return limit


def silence_before(mask: np.ndarray, t: float, limit: float, hold: int = 8) -> float:
    """Last time before t where `hold` frames in a row are quiet (scanning backwards)."""
    i, stop = int(t * 100), max(int(limit * 100), 0)
    while i > stop:
        if not mask[max(i - hold, 0):i].any():
            return i / 100
        i -= 1
    return limit


def plan_segments(words: list[Word], drop: list[Seg], audio: np.ndarray, total: float,
                  max_gap: float, pause: float) -> list[Seg]:
    """Speech ranges to keep. Edges follow the real end of the sound, not Whisper's word ends,
    so a cut never clips a word; each kept range carries half of the natural pause on both sides."""
    kept = [w for w in words if not any(d.a <= (w.start + w.end) / 2 <= d.b for d in drop)]
    if not kept:
        raise SystemExit("nothing left to keep: check --drop")
    mask = speech_mask(audio)
    runs, cur = [], [kept[0]]
    for w in kept[1:]:
        dropped_between = any(cur[-1].end <= d.a and d.b <= w.start + 0.01 for d in drop)
        if w.start - cur[-1].end > max_gap or dropped_between:
            runs.append(cur)
            cur = [w]
        else:
            cur.append(w)
    runs.append(cur)
    half = pause / 2
    segs = []
    for k, r in enumerate(runs):
        prev_end = runs[k - 1][-1].end if k else 0.0
        next_start = runs[k + 1][0].start if k + 1 < len(runs) else total
        # look for the real silence at most 0.6 s from Whisper's edge; in steady room noise
        # there may be none, then keep 0.25 s past the word
        on = silence_before(mask, r[0].start, max(prev_end, r[0].start - 0.6))
        if on <= max(prev_end, r[0].start - 0.6):
            on = r[0].start - 0.15
        off = silence_after(mask, r[-1].end, min(next_start, r[-1].end + 0.6))
        if off >= min(next_start, r[-1].end + 0.6):
            off = r[-1].end + 0.25
        a = max(on - half, prev_end if k else 0.0)
        b = min(off + half, next_start)
        segs.append(Seg(round(max(a, 0.0), 3), round(min(b, total), 3)))
    for s, n in zip(segs, segs[1:]):  # never overlap
        if s.b > n.a:
            s.b = n.a = round((s.b + n.a) / 2, 3)
    return segs


def remap(words: list[Word], segs: list[Seg], speed: float) -> list[Word]:
    """Words of the kept segments on the clean timeline."""
    out, t = [], 0.0
    for s in segs:
        for w in words:
            mid = (w.start + w.end) / 2
            if s.a <= mid <= s.b:
                out.append(Word(w.text, round((t + max(w.start, s.a) - s.a) / speed, 3),
                                round((t + min(w.end, s.b) - s.a) / speed, 3)))
        t += s.b - s.a
    return out


def render(src: Path, segs: list[Seg], speed: float, out: Path, work: Path) -> None:
    """One ffmpeg pass: trim every segment, 5 ms audio fades at the joins, concat, speed."""
    parts, labels = [], []
    for i, s in enumerate(segs):
        d = s.b - s.a
        parts.append(f"[0:v]trim={s.a:.3f}:{s.b:.3f},setpts=PTS-STARTPTS[v{i}];"
                     f"[0:a]atrim={s.a:.3f}:{s.b:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.005,afade=t=out:st={max(d - 0.005, 0):.3f}:d=0.005[a{i}];")
        labels.append(f"[v{i}][a{i}]")
    graph = "".join(parts) + "".join(labels) + f"concat=n={len(segs)}:v=1:a=1[vc][ac];"
    if abs(speed - 1) > 1e-3:
        graph += f"[vc]setpts=PTS/{speed},fps={FPS}[v];[ac]atempo={speed}[a]"
    else:
        graph += "[vc]null[v];[ac]anull[a]"
    script = work / "cut.filter"
    script.write_text(graph)
    run([tool("ffmpeg"), "-y", "-i", str(src), "-/filter_complex", str(script), "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "aac", "-b:a", "256k", str(out)])


def cut(proj: Project, drop: str, max_gap: float, pause: float, speed: float) -> None:
    """Build the clean cut from the normalised source."""
    src = proj.work / "source.mp4"
    if not src.exists():
        raise SystemExit("run `trim.py init` first")
    words = load_words(proj.work / "words.raw.json")
    total = duration(src)
    segs = plan_segments(words, parse_ranges(drop), load_audio(src), total, max_gap, pause)
    render(src, segs, speed, proj.work / "clean.mp4", proj.work)
    clean = remap(words, segs, speed)
    save_words(proj.work / "words.json", clean)
    (proj.work / "edl.json").write_text(json.dumps([asdict(s) for s in segs], indent=1))
    proj.update(drop=drop, max_gap=max_gap, pause=pause, speed=speed)
    kept = sum(s.b - s.a for s in segs)
    log.info("cut: %d segments, %.1f s -> %.1f s (speed x%g)", len(segs), total, kept / speed, speed)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("raw", type=Path)
    i.add_argument("project", type=Path)
    i.add_argument("--lang", default="ru")
    i.add_argument("--engine", default="auto", choices=["auto", "local", "groq", "openai"])
    i.add_argument("--prompt", default="")
    c = sub.add_parser("cut")
    c.add_argument("project", type=Path)
    c.add_argument("--drop", default="")
    c.add_argument("--max-gap", type=float, default=0.35, help="pauses longer than this are cut (s)")
    c.add_argument("--pause", type=float, default=0.2, help="natural pause kept at each cut (s)")
    c.add_argument("--speed", type=float, default=1.2)
    a = ap.parse_args()
    if a.cmd == "init":
        init(a.raw, Project(a.project), a.lang, a.engine, a.prompt)
    else:
        cut(Project(a.project), a.drop, a.max_gap, a.pause, a.speed)


if __name__ == "__main__":
    main()
