"""Procedural sound effects (numpy only, free, deterministic) -> assets/sfx/<kind>.wav.

  python3 sfx_synth.py [--out <folder>] [kind ...]
Kinds: click, tick, pop, blip, whoosh, riser, hit, ding, swipe. Without kinds, all are written.
Simple electronic sounds come out well; realistic ones (camera shutter, keyboard, glass) do not:
generate those with ElevenLabs or record them.
"""
from __future__ import annotations

import argparse
import logging
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from common import SKILL_DIR, setup_logging

SR = 48000
log = logging.getLogger("sfx_synth")
rng = np.random.default_rng(7)


def t_axis(sec: float) -> np.ndarray:
    """Time axis of the given length."""
    return np.arange(int(SR * sec)) / SR


def env(n: int, attack: float, decay: float) -> np.ndarray:
    """Linear attack, exponential decay envelope over n samples."""
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def lowpass(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """One-pole low-pass; cutoff may change per sample (Hz)."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    k = 1 - np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    s = 0.0
    for i, v in enumerate(x):
        s += k[i] * (v - s)
        y[i] = s
    return y


def click() -> np.ndarray:
    """Short UI click: two damped high partials."""
    t = t_axis(0.05)
    return (np.sin(2 * np.pi * 3200 * t) + 0.5 * np.sin(2 * np.pi * 5100 * t)) * env(len(t), 0.0005, 0.006)


def tick() -> np.ndarray:
    """Clock-like tick: filtered noise burst."""
    n = int(SR * 0.04)
    x = rng.standard_normal(n)
    return (x - lowpass(x, 2500.0)) * env(n, 0.0003, 0.004)


def pop() -> np.ndarray:
    """Bubble pop: fast downward pitch sweep."""
    t = t_axis(0.12)
    f = 900 * np.exp(-t * 30) + 180
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(t), 0.001, 0.035)


def blip() -> np.ndarray:
    """Notification blip: two short sine notes up a fifth."""
    a, b = t_axis(0.07), t_axis(0.11)
    n1 = np.sin(2 * np.pi * 880 * a) * env(len(a), 0.002, 0.03)
    n2 = np.sin(2 * np.pi * 1320 * b) * env(len(b), 0.002, 0.05)
    return np.concatenate([n1, n2])


def whoosh() -> np.ndarray:
    """Air whoosh: noise through a sweeping low-pass, swelling and fading."""
    n = int(SR * 0.45)
    t = np.arange(n) / SR
    shape = np.sin(np.pi * t / t[-1]) ** 2
    y = lowpass(rng.standard_normal(n), 300 + 4200 * shape)
    return y * shape


def swipe() -> np.ndarray:
    """Quick swipe: short bright whoosh."""
    n = int(SR * 0.2)
    t = np.arange(n) / SR
    shape = np.sin(np.pi * t / t[-1]) ** 3
    x = rng.standard_normal(n)
    return (x - lowpass(x, 1500 + 3000 * shape)) * shape


def riser() -> np.ndarray:
    """Soft riser: rising filtered noise plus a rising tone, cut at the top."""
    n = int(SR * 1.6)
    t = np.arange(n) / SR
    grow = (t / t[-1]) ** 2
    noise = lowpass(rng.standard_normal(n), 200 + 6000 * grow) * grow
    tone = np.sin(2 * np.pi * np.cumsum(220 + 660 * grow) / SR) * grow * 0.3
    return noise + tone


def hit() -> np.ndarray:
    """Sub hit for accents: low sine drop with a noise transient."""
    t = t_axis(0.7)
    f = 120 * np.exp(-t * 6) + 42
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(len(t), 0.002, 0.25)
    n = int(SR * 0.02)
    trans = np.zeros_like(body)
    trans[:n] = lowpass(rng.standard_normal(n), 3000.0) * env(n, 0.0002, 0.005)
    return body + 0.6 * trans


def ding() -> np.ndarray:
    """Bell ding: inharmonic partials with long decay."""
    t = t_axis(1.0)
    parts = [(1.0, 1.0), (2.76, 0.5), (5.4, 0.25), (8.93, 0.12)]
    return sum(a * np.sin(2 * np.pi * 1046 * r * t) * env(len(t), 0.001, 0.35 / r ** 0.5) for r, a in parts)


KINDS: dict[str, Callable[[], np.ndarray]] = {
    "click": click, "tick": tick, "pop": pop, "blip": blip, "whoosh": whoosh,
    "swipe": swipe, "riser": riser, "hit": hit, "ding": ding,
}


def write(path: Path, x: np.ndarray, peak_db: float = -3.0) -> None:
    """Normalise to the peak level, 5 ms fade-out, write 16-bit stereo wav."""
    x = x / (np.max(np.abs(x)) or 1) * 10 ** (peak_db / 20)
    fade = min(len(x), int(SR * 0.005))
    x[-fade:] *= np.linspace(1, 0, fade)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kinds", nargs="*", help=", ".join(KINDS))
    ap.add_argument("--out", type=Path, default=SKILL_DIR / "assets" / "sfx")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    bad = [k for k in a.kinds if k not in KINDS]
    if bad:
        ap.error(f"unknown kinds: {bad}")
    for k in a.kinds or KINDS:
        write(a.out / f"{k}.wav", KINDS[k]())
        log.info("%s.wav", k)


if __name__ == "__main__":
    main()
