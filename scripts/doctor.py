"""Self-test after installation: tools, Python packages, keys, and a 5-second synthetic reel end to end.

  python3 doctor.py [--keep]
Builds a test project in a temporary folder (no API keys needed): coloured video with a tone as the
"voice", known words, captions, a text insert, a grey moment with spinner, a sound effect and the
four video effects -> preview.
Prints OK/FAIL per check and the path of the preview to look at (with --keep).
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path

from shared import Project, Word, key, run, save_words, setup_logging, tool

log = logging.getLogger("doctor")
results: list[tuple[bool, str]] = []


def check(ok: bool, text: str) -> bool:
    """Record and print one result."""
    results.append((ok, text))
    print(f"{'OK  ' if ok else 'FAIL'}  {text}")
    return ok


def tools() -> bool:
    """ffmpeg 7.1+ with libx264 and libass-free PNG overlay; ffprobe."""
    try:
        out = run([tool("ffmpeg"), "-version"], quiet=False).stdout
    except SystemExit as e:
        return check(False, str(e))
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", out)
    ver = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    ok = check(ver >= (7, 1) or not m, f"ffmpeg {'.'.join(map(str, ver)) if m else '(dev build)'} (need 7.1+)")
    ok &= check("--enable-libx264" in out, "ffmpeg has libx264")
    tool("ffprobe")
    return ok


def node() -> bool:
    """Node.js 22+ for HyperFrames (animated graphics)."""
    from graphics import npx

    try:
        exe = npx()
        ver = run([str(Path(exe).parent / "node"), "--version"], quiet=False).stdout.strip()
    except (SystemExit, RuntimeError, FileNotFoundError):
        print("--    Node.js not found: animated graphics need Node.js 22+ (SKILL.md, step 0)")
        return False
    major = int(ver.lstrip("v").split(".")[0]) if ver.lstrip("v")[:1].isdigit() else 0
    if major < 22:
        print(f"--    Node.js {ver}: animated graphics need 22+ (SKILL.md, step 0)")
        return False
    return check(True, f"Node.js {ver} (animated graphics)")


def packages() -> bool:
    """Required and optional Python packages."""
    ok = True
    for name in ("numpy", "requests", "playwright"):
        try:
            importlib.import_module(name)
            check(True, f"python package {name}")
        except ImportError:
            ok &= check(False, f"python package {name}: pip install -r requirements.txt")
    for name, why in (("cv2", "face tracking: pip install opencv-python"),
                      ("mediapipe", "person cut-out for text behind the head: pip install mediapipe"),
                      ("faster_whisper", "free local speech recognition: pip install faster-whisper")):
        try:
            importlib.import_module(name)
            check(True, f"optional {name}")
        except ImportError:
            print(f"--    optional {name} not installed ({why})")
    return ok


def keys() -> None:
    """Which services are available (never prints the keys)."""
    for name, what in (("GROQ_API_KEY", "speech recognition, free tier"),
                       ("OPENAI_API_KEY", "speech recognition, paid"),
                       ("HIKERAPI_KEY", "download Instagram references"),
                       ("ELEVENLABS_API_KEY", "studio voice and more sound effects")):
        print(f"{'set ' if key(name) else '--  '}  {name} ({what})")


def synthetic(root: Path, with_gfx: bool) -> bool:
    """5-second reel through subtitles, inserts (+ animated graphic, text behind the head) and assembly."""
    from assemble import finish
    from cutout import cutout
    from inserts import build
    from subtitles import render

    proj = Project(root / "test-reel")
    run([tool("ffmpeg"), "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=5", "-f", "lavfi",
         "-i", "sine=frequency=220:sample_rate=48000:duration=5", "-shortest", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(proj.work / "clean.mp4")])
    words = [Word(t, round(0.3 + i * 0.55, 2), round(0.75 + i * 0.55, 2))
             for i, t in enumerate("это тест скилла монтажа всё работает отлично".split())]
    save_words(proj.work / "words.json", words)
    proj.update(lang="ru", speed=1.0)
    inserts = [{"a": 1.0, "b": 2.5, "kind": "text", "src": "", "layout": "card", "text": "100%"},
               {"a": 2.6, "b": 3.4, "kind": "text", "src": "", "layout": "behind", "text": "ТЕСТ"}]
    if with_gfx:
        inserts.append({"a": 3.5, "b": 4.9, "kind": "gfx", "layout": "full",
                        "gfx": {"type": "counter", "to": 100, "suffix": "%", "label": "тест"}})
    (proj.work / "inserts.json").write_text(json.dumps(inserts, ensure_ascii=False))
    (proj.work / "grey.json").write_text(json.dumps([{"a": 3.0, "b": 4.0, "spinner": True}]))
    (proj.work / "sfx.json").write_text(json.dumps([{"t": 1.0, "kind": "pop", "gain": -8}]))
    (proj.work / "fx.json").write_text(json.dumps([{"a": 0.5, "b": 0.9, "kind": "shake"},
                                                   {"a": 1.5, "b": 1.8, "kind": "glitch"},
                                                   {"a": 2.6, "b": 2.9, "kind": "flash"},
                                                   {"a": 4.2, "b": 4.8, "kind": "freeze"}]))
    steps = [("captions (subtitles.py)", lambda: render(proj, "montserrat-caps", {"скилла"}, 1250, "lower",
                                                         3, 18, True, 1)),
             ("inserts (inserts.py" + (", HyperFrames graphic)" if with_gfx else ")"),
              lambda: build(proj, "#8B5CF6")),
             ("person cut-out (cutout.py)", lambda: cutout(proj)),
             ("assembly (assemble.py)", lambda: finish(proj, False, -15.0, True, "test-reel"))]
    for name, fn in steps:
        try:
            fn()
            check(True, name)
        except Exception as e:  # report every failing step, keep going
            check(False, f"{name}: {str(e).splitlines()[-1] if str(e) else type(e).__name__}")
            return False
    out = proj.out / "preview.mp4"
    return check(out.exists() and out.stat().st_size > 10_000, f"preview rendered: {out}")


def main() -> None:
    """CLI entry."""
    setup_logging()
    logging.getLogger().setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="keep the test project to look at the preview")
    a = ap.parse_args()
    tools()
    packages()
    with_gfx = node()
    keys()
    tmp = Path(tempfile.mkdtemp(prefix="labops-montage-"))
    try:
        synthetic(tmp, with_gfx)
    finally:
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    failed = [t for ok, t in results if not ok]
    print(f"\n{'ALL OK' if not failed else f'{len(failed)} FAILED'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
