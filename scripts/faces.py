"""Face track of the clean cut (OpenCV, any OS) -> work/faces.json, plus jump-zoom framing -> work/framed.mp4.

  python3 faces.py track <project>      largest face every 0.25 s: [[t, cx, cy, w, h] | [t]] in 0..1
  python3 faces.py frame <project> [--face-y 0.40]
      applies work/zooms.json (from plan.py apply): every beat cropped around the face with its zoom
      (1.0 wide, 1.3 medium, 1.6 close), face centre at --face-y of the height -> work/framed.mp4
  python3 faces.py frame <project> --smooth 0.5 [--drift 0.03]
      soft zooms instead of jumps: every change of zoom and face centre eases in over --smooth seconds,
      and each beat slowly pushes in by --drift (0.03 = 3 %); looks calmer on close-ups

Detector: OpenCV YuNet (model downloaded once to ~/.cache/labops-montage, about 0.3 MB); if the download
is impossible, the Haar cascade bundled with OpenCV. Run `track` again after every re-cut.
"""
from __future__ import annotations

import argparse
import json
import logging
import urllib.request
from pathlib import Path
from statistics import median

from shared import FPS, H, W, Project, run, setup_logging, tool

log = logging.getLogger("faces")
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
YUNET = Path.home() / ".cache" / "labops-montage" / "face_detection_yunet_2023mar.onnx"
STEP = 0.25


def detector():
    """Callable frame -> list of (x, y, w, h) boxes."""
    import cv2

    try:
        if not YUNET.exists():
            YUNET.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(YUNET_URL, YUNET)
        net = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.6)

        def yunet(fr):
            net.setInputSize((fr.shape[1], fr.shape[0]))
            _, faces = net.detect(fr)
            return [] if faces is None else [tuple(f[:4]) for f in faces]
        return yunet
    except Exception as e:  # offline or old OpenCV: fall back to the bundled cascade
        log.info("YuNet unavailable (%s), using Haar cascade", e)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def haar(fr):
            gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            return [tuple(b) for b in cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))]
        return haar


def track(proj: Project) -> None:
    """Sample the clean cut and store the largest face per sample."""
    import cv2

    detect = detector()
    cap = cv2.VideoCapture(str(proj.work / "clean.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    step = max(1, round(fps * STEP))
    rows, n = [], 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if n % step == 0:
            small = cv2.resize(fr, (540, 960))
            boxes = detect(small)
            t = round(n / fps, 3)
            if boxes:
                x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
                rows.append([t] + [round(float(v), 4) for v in ((x + w / 2) / 540, (y + h / 2) / 960, w / 540, h / 960)])
            else:
                rows.append([t])
        n += 1
    (proj.work / "faces.json").write_text(json.dumps(rows))
    log.info("faces: %d samples, face found in %d", len(rows), sum(len(r) > 1 for r in rows))


def centre(rows: list[list[float]], a: float, b: float) -> tuple[float, float]:
    """Median face centre over [a, b]; frame centre if no face was seen."""
    hits = [r for r in rows if a - 0.3 <= r[0] <= b + 0.3 and len(r) > 1]
    if not hits:
        return 0.5, 0.4
    return median(r[1] for r in hits), median(r[2] for r in hits)


def frame(proj: Project, face_y: float) -> None:
    """Crop every beat around the face with its zoom; audio stays untouched."""
    rows = json.loads((proj.work / "faces.json").read_text())
    beats = json.loads((proj.work / "zooms.json").read_text())
    parts, labels = [], []
    for i, z in enumerate(beats):
        cw, ch = round(W / z["zoom"] / 2) * 2, round(H / z["zoom"] / 2) * 2
        fx, fy = centre(rows, z["a"], z["b"])
        x = int(min(max(fx * W - cw / 2, 0), W - cw))
        y = int(min(max(fy * H - ch * face_y, 0), H - ch))
        parts.append(f"[0:v]trim={z['a']:.3f}:{z['b']:.3f},setpts=PTS-STARTPTS,crop={cw}:{ch}:{x}:{y},"
                     f"scale={W}:{H}:flags=lanczos,setsar=1[v{i}];")
        labels.append(f"[v{i}]")
    graph = "".join(parts) + "".join(labels) + f"concat=n={len(beats)}:v=1:a=0,fps={FPS}[v]"
    script = proj.work / "frame.filter"
    script.write_text(graph)
    run([tool("ffmpeg"), "-y", "-i", str(proj.work / "clean.mp4"), "-/filter_complex", str(script),
         "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-c:a", "copy",
         str(proj.work / "framed.mp4")])
    log.info("framed: %d beats -> %s", len(beats), proj.work / "framed.mp4")


def smooth_frame(proj: Project, face_y: float, ease: float, drift: float) -> None:
    """Like frame(), but zoom and face centre glide between beats (smoothstep) instead of jumping."""
    import subprocess

    import cv2
    import numpy as np

    rows = json.loads((proj.work / "faces.json").read_text())
    beats = json.loads((proj.work / "zooms.json").read_text())
    targets = [(z["zoom"], *centre(rows, z["a"], z["b"])) for z in beats]
    src = proj.work / "clean.mp4"
    out = proj.work / "framed.mp4"
    reader = subprocess.Popen([tool("ffmpeg"), "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "bgr24",
                               "-vf", f"scale={W}:{H},fps={FPS}", "-"], stdout=subprocess.PIPE)
    writer = subprocess.Popen([tool("ffmpeg"), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(src), "-map", "0:v",
                               "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                               "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", str(out)], stdin=subprocess.PIPE)
    state = targets[0]  # (zoom, fx, fy) at the end of the previous beat
    i, start, n = 0, targets[0], 0
    while True:
        buf = reader.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        t = n / FPS
        while i + 1 < len(beats) and t >= beats[i + 1]["a"]:
            i += 1
            start = state
        a, b = beats[i]["a"], beats[i]["b"]
        k = min(1.0, (t - a) / ease) if i else 1.0
        k = k * k * (3 - 2 * k)
        tz, tx, ty = targets[i]
        tz *= 1 + drift * min(1.0, (t - a) / max(b - a, 0.1))
        z, fx, fy = (s0 + (s1 - s0) * k for s0, s1 in zip(start, (tz, tx, ty)))
        state = (z, fx, fy)
        cw, ch = W / z, H / z
        x = min(max(fx * W - cw / 2, 0), W - cw)
        y = min(max(fy * H - ch * face_y, 0), H - ch)
        img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        m = np.float32([[z, 0, -x * z], [0, z, -y * z]])
        writer.stdin.write(cv2.warpAffine(img, m, (W, H), flags=cv2.INTER_CUBIC,
                                          borderMode=cv2.BORDER_REPLICATE).tobytes())
        n += 1
    writer.stdin.close()
    reader.wait()
    if writer.wait():
        raise SystemExit("ffmpeg failed while writing framed.mp4")
    log.info("framed (smooth %.2f s, drift %.0f %%): %d beats -> %s", ease, drift * 100, len(beats), out)


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("track").add_argument("project", type=Path)
    f = sub.add_parser("frame")
    f.add_argument("project", type=Path)
    f.add_argument("--face-y", type=float, default=0.40)
    f.add_argument("--smooth", type=float, default=0.0, help="ease zoom changes over this many seconds")
    f.add_argument("--drift", type=float, default=0.03, help="slow push-in per beat with --smooth")
    a = ap.parse_args()
    if a.cmd == "track":
        track(Project(a.project))
    elif a.smooth > 0:
        smooth_frame(Project(a.project), a.face_y, a.smooth, a.drift)
    else:
        frame(Project(a.project), a.face_y)


if __name__ == "__main__":
    main()
