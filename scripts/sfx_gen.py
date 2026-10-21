"""More sound effects with ElevenLabs Sound Effects (your own key; the free plan has monthly credits).

  python3 sfx_gen.py --list
  python3 sfx_gen.py shutter typing                  ready kinds below -> assets/sfx/<kind>.mp3
  python3 sfx_gen.py --name cash --prompt "cash register ding, short, clean" [--seconds 1.0]
Needs ELEVENLABS_API_KEY (environment or ~/.config/labops-montage/keys.env). Every call spends credits:
ask the user before generating. Generated files are the user's own sounds.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import requests

from common import SKILL_DIR, key, setup_logging

log = logging.getLogger("sfx_gen")
URL = "https://api.elevenlabs.io/v1/sound-generation"
READY = {
    "shutter": ("camera shutter click, single, dry, close mic", 0.6),
    "typing": ("fast typing on a laptop keyboard, short burst, close mic", 1.5),
    "notify": ("soft phone notification chime, modern, single", 0.8),
    "send": ("message sent swoosh, short, light, UI sound", 0.6),
    "glass": ("glass shatter, short, bright, no reverb tail", 1.2),
    "cash": ("cash register ding with coins, short", 1.0),
    "toggle": ("switch toggle click, plastic, single", 0.4),
    "boom": ("deep cinematic boom hit, short, punchy", 1.2),
    "record": ("vinyl record scratch, short, comedic", 0.8),
    "laugh": ("small audience laugh, short, light", 1.5),
}


def generate(prompt: str, seconds: float, dst: Path) -> None:
    """One sound from a text description."""
    secret = key("ELEVENLABS_API_KEY")
    if not secret:
        raise SystemExit("ELEVENLABS_API_KEY is not set (environment or ~/.config/labops-montage/keys.env)")
    r = requests.post(URL, headers={"xi-api-key": secret},
                      json={"text": prompt, "duration_seconds": seconds, "prompt_influence": 0.5}, timeout=120)
    if r.status_code != 200:
        raise SystemExit(f"ElevenLabs: HTTP {r.status_code} {r.text[:300]}")
    dst.write_bytes(r.content)
    log.info("%s", dst)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kinds", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--name")
    ap.add_argument("--prompt")
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=SKILL_DIR / "assets" / "sfx")
    a = ap.parse_args()
    if a.list:
        for k, (p, s) in READY.items():
            print(f"{k:<8} {s:>4} s  {p}")
        return
    a.out.mkdir(parents=True, exist_ok=True)
    if a.prompt:
        generate(a.prompt, a.seconds, a.out / f"{a.name or 'custom'}.mp3")
    for k in a.kinds:
        if k not in READY:
            raise SystemExit(f"unknown kind {k}; see --list or use --prompt")
        generate(READY[k][0], READY[k][1], a.out / f"{k}.mp3")


if __name__ == "__main__":
    main()
