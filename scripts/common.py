"""Shared helpers for labops-montage: tool lookup, keys, project layout, ffmpeg runner, words I/O.

Keys are read from the environment first, then from ~/.config/labops-montage/keys.env
(NAME=value lines). Keys are never printed or written anywhere by these scripts.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
KEYS_FILE = Path.home() / ".config" / "labops-montage" / "keys.env"
W, H, FPS = 1080, 1920, 30

log = logging.getLogger("labops-montage")


def setup_logging() -> None:
    """Plain message logging to stderr."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def tool(name: str) -> str:
    """Absolute path of a command-line tool (ffmpeg, ffprobe, node, npx); exit with a hint if missing."""
    env = os.environ.get(f"LABOPS_{name.upper()}")
    if env:
        return env
    local = Path.home() / ".local" / "bin" / name
    found = shutil.which(name) or (str(local) if local.exists() else None)
    if not found:
        sys.exit(f"{name} not found. Install it (see SKILL.md, step 0) or set LABOPS_{name.upper()}.")
    return found


def key(name: str) -> str | None:
    """API key NAME from the environment or keys.env; None if absent."""
    if os.environ.get(name):
        return os.environ[name]
    if KEYS_FILE.exists():
        for line in KEYS_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command, raise with its stderr tail on failure."""
    if quiet and Path(cmd[0]).name in ("ffmpeg", "ffprobe"):
        cmd = [cmd[0], "-hide_banner", "-v", "error", *cmd[1:]]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        tail = "\n".join(res.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"command failed: {Path(cmd[0]).name} ...\n{tail}")
    return res


def probe(path: Path) -> dict:
    """ffprobe JSON (format + streams)."""
    res = run([tool("ffprobe"), "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(res.stdout)


def duration(path: Path) -> float:
    """Media duration in seconds."""
    return float(probe(path)["format"]["duration"])


@dataclass
class Word:
    """One recognised word with its timing in seconds."""
    text: str
    start: float
    end: float


def load_words(path: Path) -> list[Word]:
    """Read words.json."""
    return [Word(**w) for w in json.loads(path.read_text())]


def save_words(path: Path, words: list[Word]) -> None:
    """Write words.json (one word per line, easy to diff and hand-fix)."""
    rows = [json.dumps(asdict(w), ensure_ascii=False) for w in words]
    path.write_text("[\n" + ",\n".join(rows) + "\n]\n")


@dataclass
class Project:
    """Folder layout of one reel project."""
    root: Path

    @property
    def work(self) -> Path:
        """Intermediate files."""
        p = self.root / "work"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def out(self) -> Path:
        """Previews and finals."""
        p = self.root / "out"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def meta_path(self) -> Path:
        """project.json: settings chosen with the user (language, speed, catalogue picks)."""
        return self.root / "project.json"

    def meta(self) -> dict:
        """Read project.json (empty dict if missing)."""
        return json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    def update(self, **kw: object) -> dict:
        """Merge keys into project.json."""
        m = self.meta()
        m.update(kw)
        self.meta_path.write_text(json.dumps(m, ensure_ascii=False, indent=1))
        return m
