"""Find official logos -> candidates to look at and pick from.

  python3 logos.py <folder> "Claude" ["Notion" ...] [--n 3]
For every name: up to --n candidates from Wikimedia Commons (official files uploaded as "<name> logo",
rendered to PNG 800 px) -> <folder>/<name>-1.png ...; if Commons has nothing, a one-colour brand icon
from Simple Icons (CC0) -> <folder>/<name>-icon.svg.
Always open the candidates and check that the logo is the current official one before using it.
"""
from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path

import requests

from shared import setup_logging

log = logging.getLogger("logos")
UA = {"User-Agent": "labops-montage/1.0 (reels editing skill)"}
COMMONS = "https://commons.wikimedia.org/w/api.php"


def slug(name: str) -> str:
    """File-safe name."""
    return re.sub(r"[^\w-]+", "-", name.lower()).strip("-")


def commons(name: str, n: int) -> list[str]:
    """PNG renderings of the best Commons matches for '<name> logo'."""
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{name} logo", "gsrlimit": 10, "prop": "imageinfo",
              "iiprop": "url|mime", "iiurlwidth": 800}
    pages = requests.get(COMMONS, params=params, headers=UA, timeout=30).json().get("query", {}).get("pages", {})
    ranked = sorted(pages.values(), key=lambda p: p.get("index", 99))
    out = []
    for p in ranked:
        title = p["title"].lower()
        info = (p.get("imageinfo") or [{}])[0]
        if name.lower().split()[0] in title and "logo" in title and info.get("thumburl"):
            out.append(info["thumburl"])
    return out[:n]


def simple_icon(name: str) -> str | None:
    """Simple Icons SVG (brand colour) if the brand is there."""
    url = f"https://cdn.simpleicons.org/{re.sub(r'[^a-z0-9]', '', name.lower())}"
    r = requests.get(url, headers=UA, timeout=30)
    return r.text if r.status_code == 200 and "<svg" in r.text else None


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("names", nargs="+")
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    a.folder.mkdir(parents=True, exist_ok=True)
    for name in a.names:
        urls = commons(name, a.n)
        saved = 0
        for u in urls:
            time.sleep(1.0)  # Commons answers 429 to quick bursts
            r = requests.get(u, headers=UA, timeout=60)
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
                log.info("%s: skipped %s (HTTP %s)", name, u.rsplit("/", 1)[-1], r.status_code)
                continue
            saved += 1
            dst = a.folder / f"{slug(name)}-{saved}.png"
            dst.write_bytes(r.content)
            log.info("%s -> %s", name, dst)
        if not saved:
            svg = simple_icon(name)
            if svg:
                dst = a.folder / f"{slug(name)}-icon.svg"
                dst.write_text(svg)
                log.info("%s -> %s (Simple Icons, one colour)", name, dst)
            else:
                log.info("%s: nothing found, ask the user for the official file", name)


if __name__ == "__main__":
    main()
