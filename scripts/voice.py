"""Studio-clean voice through ElevenLabs voice isolation -> work/voice.wav (assemble.py uses it instead of the
camera sound and skips its own denoise).

  python3 voice.py <project>            needs ELEVENLABS_API_KEY; spends ElevenLabs credits: ask the user first
  python3 voice.py <project> --off      remove work/voice.wav, back to the free denoise
Run after trim.py cut (on work/clean.mp4) and again after any re-cut.
"""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from shared import Project, duration, key, run, setup_logging, tool

log = logging.getLogger("voice")
URL = "https://api.elevenlabs.io/v1/audio-isolation"


def envelope(path: Path) -> "numpy.ndarray":
    """Loudness envelope, 10 ms steps."""
    import subprocess

    import numpy as np

    raw = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le",
                          "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float)
    n = len(x) // 160
    return np.sqrt((x[:n * 160].reshape(n, 160) ** 2).mean(1))


def offset(original: Path, isolated: Path) -> float:
    """Seconds to delay the isolated voice to match the original (negative = cut its start)."""
    import numpy as np

    a, b = envelope(original), envelope(isolated)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    best = max(range(-20, 21), key=lambda k: np.corrcoef(a[max(0, k):n + min(0, k)],
                                                         b[max(0, -k):n - max(0, k)])[0, 1])
    return best / 100


def isolate(proj: Project) -> Path:
    """Send the voice of the clean cut to ElevenLabs, save the clean voice aligned to the video."""
    import requests

    secret = key("ELEVENLABS_API_KEY")
    if not secret:
        raise SystemExit("ELEVENLABS_API_KEY is not set (environment or ~/.config/labops-montage/keys.env)")
    clean = proj.work / "clean.mp4"
    if not clean.exists():
        raise SystemExit("run trim.py cut first")
    out = proj.work / "voice.wav"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "voice.mp3"
        got = Path(tmp) / "isolated"
        run([tool("ffmpeg"), "-y", "-i", str(clean), "-vn", "-ac", "1", "-ar", "44100", "-b:a", "192k", str(src)])
        with src.open("rb") as fh:
            r = requests.post(URL, headers={"xi-api-key": secret}, files={"audio": (src.name, fh, "audio/mpeg")},
                              timeout=600)
        if r.status_code != 200:
            raise SystemExit(f"ElevenLabs voice isolation failed: HTTP {r.status_code} {r.text[:300]}")
        got.write_bytes(r.content)
        total = duration(clean)
        shift = offset(src, got)
        # same start and length as the video (pad with silence, trim), so the lips stay in sync
        align = f"adelay={int(shift * 1000)}" if shift > 0 else f"atrim=start={-shift:.3f},asetpts=PTS-STARTPTS"
        run([tool("ffmpeg"), "-y", "-i", str(got), "-af", f"{align},apad,atrim=0:{total:.3f}", "-ar", "48000",
             "-ac", "1", str(out)])
        log.info("aligned by %+.0f ms", shift * 1000)
    log.info("clean voice -> %s", out)
    return out


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--off", action="store_true")
    a = ap.parse_args()
    proj = Project(a.project)
    if a.off:
        (proj.work / "voice.wav").unlink(missing_ok=True)
        log.info("studio voice off: assemble.py uses the camera sound with denoise")
    else:
        isolate(proj)


if __name__ == "__main__":
    main()
