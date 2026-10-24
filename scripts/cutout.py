"""Person cut out from the background (MediaPipe, free, on this computer) -> work/overlays/06-person.mov.

  python3 cutout.py <project> [--engine auto|mediapipe|hyperframes]
Run after inserts.py when plan.json has text behind the head (insert layout "behind"): the text track
05-behind goes under this track, so the person stands in front of the text. Only the "behind" beats are
processed. Two engines, both free, on this computer, on macOS, Windows and Linux:
  mediapipe    Google MediaPipe (pip install mediapipe; model ~16 MB downloaded on the first run), fast
  hyperframes  `npx hyperframes remove-background` (local u2net model; needs Node.js 22+), slower
  auto         mediapipe if installed, else hyperframes
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import urllib.request
from pathlib import Path

import graphics
from shared import FPS, H, W, Project, duration, run, setup_logging, tool

log = logging.getLogger("cutout")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/"
             "float32/latest/selfie_multiclass_256x256.tflite")
MODEL = Path.home() / ".cache" / "labops-montage" / "selfie_multiclass_256x256.tflite"
SMOOTH = 0.6  # share of the new mask per frame: less flicker on the edges


def segmenter():
    """MediaPipe person segmenter (multiclass model: background is class 0)."""
    try:
        from mediapipe.tasks.python import BaseOptions, vision
    except ImportError as e:
        raise SystemExit("mediapipe is not installed: pip install mediapipe") from e
    if not MODEL.exists():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        log.info("downloading the segmentation model -> %s", MODEL)
        urllib.request.urlretrieve(MODEL_URL, MODEL)
    return vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), output_confidence_masks=True))


def cut_window(picture: Path, a: float, b: float, out: Path, seg) -> None:
    """Frames a..b of the picture -> RGBA video of the person only (transparent elsewhere)."""
    import cv2
    import mediapipe as mp
    import numpy as np

    dec = subprocess.Popen([tool("ffmpeg"), "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i",
                            str(picture), "-vf", f"scale={W}:{H},fps={FPS}", "-f", "rawvideo", "-pix_fmt",
                            "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([tool("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s",
                            f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "png", str(out)], stdin=subprocess.PIPE)
    prev = None
    size = W * H * 3
    while True:
        buf = dec.stdout.read(size)
        if len(buf) < size:
            break
        rgb = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        small = np.ascontiguousarray(cv2.resize(rgb, (W // 2, H // 2), interpolation=cv2.INTER_AREA))
        res = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=small))
        person = 1.0 - res.confidence_masks[0].numpy_view().squeeze()
        prev = person if prev is None else SMOOTH * person + (1 - SMOOTH) * prev
        alpha = np.clip((cv2.resize(prev, (W, H)) - 0.35) / 0.3, 0, 1)
        alpha = cv2.GaussianBlur(alpha, (0, 0), 2)
        enc.stdin.write(np.dstack([rgb, (alpha * 255).astype(np.uint8)]).tobytes())
    enc.stdin.close()
    if dec.wait() or enc.wait():
        raise RuntimeError("cutout: ffmpeg failed")


def cut_window_hf(picture: Path, a: float, b: float, out: Path) -> None:
    """Same as cut_window, through HyperFrames remove-background."""
    clip = out.with_suffix(".src.mp4")
    run([tool("ffmpeg"), "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(picture), "-an", "-vf",
         f"scale={W}:{H},fps={FPS}", "-c:v", "libx264", "-crf", "14", str(clip)])
    run([graphics.npx(), "--yes", "hyperframes", "remove-background", str(clip), "-o", str(out)])
    clip.unlink(missing_ok=True)


def pick_engine(engine: str) -> str:
    """Resolve auto to an installed engine."""
    if engine != "auto":
        return engine
    try:
        import mediapipe  # noqa: F401
        return "mediapipe"
    except ImportError:
        return "hyperframes"


def cutout(proj: Project, engine: str = "auto") -> Path | None:
    """Person track for every insert with layout "behind"."""
    items = [x for x in json.loads((proj.work / "inserts.json").read_text()) if x.get("layout") == "behind"]
    out = proj.work / "overlays" / "06-person.mov"
    out.unlink(missing_ok=True)
    if not items:
        log.info("no text behind the head in inserts.json: nothing to cut out")
        return None
    picture = proj.work / "framed.mp4" if (proj.work / "framed.mp4").exists() else proj.work / "clean.mp4"
    total = duration(proj.work / "clean.mp4")
    folder = proj.work / "cutout"
    folder.mkdir(exist_ok=True)
    engine = pick_engine(engine)
    log.info("cutout engine: %s", engine)
    seg = segmenter() if engine == "mediapipe" else None
    ins = ["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x{H}:r={FPS}:d={total:.3f},format=rgba"]
    graph, v = [], "[0:v]"
    for i, it in enumerate(items):
        part = folder / f"{i:02d}.mov"
        if seg:
            cut_window(picture, it["a"], it["b"], part, seg)
        else:
            cut_window_hf(picture, it["a"], it["b"], part)
        ins += ["-i", str(part)]
        graph += [f"[{i + 1}:v]setpts=PTS-STARTPTS+{it['a']:.3f}/TB,format=rgba[c{i}]",
                  f"{v}[c{i}]overlay=0:0:eof_action=pass[v{i}]"]
        v = f"[v{i}]"
    if seg:
        seg.close()
    script = proj.work / "cutout.filter"
    script.write_text(";".join(graph))
    run([tool("ffmpeg"), "-y", *ins, "-/filter_complex", str(script), "-map", v, "-c:v", "png",
         "-t", f"{total:.3f}", str(out)])
    log.info("%d cut-out beats -> %s", len(items), out)
    return out


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--engine", default="auto", choices=["auto", "mediapipe", "hyperframes"])
    a = ap.parse_args()
    cutout(Project(a.project), a.engine)


if __name__ == "__main__":
    main()
