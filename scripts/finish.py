"""Final assembly: clean cut + overlay tracks + grey moments + clean voice + sound effects -> out/.

  python3 finish.py <project> [--final] [--target -15] [--no-denoise] [--name slug]
      --final   1080x1920 high quality (out/<name>.mp4); default is a 720p preview (out/preview.mp4)

Reads from the project:
  work/clean.mp4              picture and voice after prep.py cut
  work/framed.mp4             the same with jump zooms from faces.py frame (used instead when present)
  work/subs.mov               caption track from subtitles.py (optional)
  work/overlays/*.mov         other transparent tracks (graphics), applied in name order (optional)
  work/sfx.json               [{"t": 3.2, "kind": "whoosh", "gain": -6}, ...]  kinds = assets/sfx/<kind>.wav
                              or "file": "/path/sound.wav" for any other sound (optional)
  work/grey.json              [{"a": 5.0, "b": 6.4}, ...] grey moments: black-and-white picture (optional)

Sound rules: no music (it is added in Instagram at publishing); gentle denoise (high-pass 70 Hz + light FFT
denoise) and one static gain to the target loudness. No loudness compressor: it lifts room noise in every pause.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from common import FPS, SKILL_DIR, Project, duration, run, setup_logging, tool

log = logging.getLogger("finish")
DENOISE = "highpass=f=70,afftdn=nr=6:nf=-55"


def loudness(src: Path, chain: str) -> float:
    """Integrated loudness (LUFS) of the audio after the given filter chain."""
    res = run([tool("ffmpeg"), "-nostats", "-i", str(src), "-vn", "-af", f"{chain},ebur128=framelog=quiet",
               "-f", "null", "-"], quiet=False)
    found = re.findall(r"I:\s+(-?[\d.]+) LUFS", res.stderr)
    if not found:
        raise RuntimeError("could not measure loudness")
    return float(found[-1])


def sfx_inputs(proj: Project) -> list[tuple[Path, float, float]]:
    """(file, time, gain dB) of every placed sound effect."""
    path = proj.work / "sfx.json"
    if not path.exists():
        return []
    out = []
    for e in json.loads(path.read_text()):
        f = Path(e["file"]) if e.get("file") else SKILL_DIR / "assets" / "sfx" / f"{e['kind']}.wav"
        if not f.exists():
            raise SystemExit(f"sound not found: {f}")
        out.append((f, float(e["t"]), float(e.get("gain", -8))))
    return out


def finish(proj: Project, final: bool, target: float, denoise: bool, name: str) -> Path:
    """Build the preview or the final file."""
    clean = proj.work / "clean.mp4"
    if not clean.exists():
        raise SystemExit("run prep.py cut first")
    total = duration(clean)
    voice_chain = DENOISE if denoise else "anull"
    gain = target - loudness(clean, voice_chain)
    # graphics first, captions last so they stay on top
    tracks = sorted((proj.work / "overlays").glob("*.mov")) if (proj.work / "overlays").exists() else []
    tracks += [proj.work / "subs.mov"] if (proj.work / "subs.mov").exists() else []
    sfx = sfx_inputs(proj)
    grey = json.loads((proj.work / "grey.json").read_text()) if (proj.work / "grey.json").exists() else []

    picture = proj.work / "framed.mp4" if (proj.work / "framed.mp4").exists() else clean
    ins = ["-i", str(picture)]
    for t in tracks:
        ins += ["-i", str(t)]
    for f, _, _ in sfx:
        ins += ["-i", str(f)]

    v = "[0:v]"
    graph = []
    if grey:
        cond = "+".join(f"between(t,{g['a']},{g['b']})" for g in grey)
        graph.append(f"{v}hue=s=0:enable='{cond}'[vg]")
        v = "[vg]"
    for i in range(len(tracks)):
        graph.append(f"{v}[{i + 1}:v]overlay=0:0:format=auto:eof_action=pass[vo{i}]")
        v = f"[vo{i}]"
    size = "1080:1920" if final else "720:1280"
    graph.append(f"{v}scale={size}:flags=lanczos,fps={FPS},format=yuv420p[v]")

    graph.append(f"[0:a]{voice_chain},volume={gain:.2f}dB,aresample=48000[voice]")
    mix = ["[voice]"]
    base = 1 + len(tracks)
    for k, (_, t, g) in enumerate(sfx):
        ms = int(t * 1000)
        graph.append(f"[{base + k}:a]aresample=48000,aformat=channel_layouts=stereo,"
                     f"adelay={ms}|{ms},volume={g}dB[s{k}]")
        mix.append(f"[s{k}]")
    graph.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,"
                 "alimiter=limit=0.79:level=false[a]")

    out = proj.out / (f"{name}.mp4" if final else "preview.mp4")
    script = proj.work / "finish.filter"
    script.write_text(";".join(graph))
    venc = ["-c:v", "libx264", "-preset", "slow", "-crf", "17"] if final else \
        ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    run([tool("ffmpeg"), "-y", *ins, "-/filter_complex", str(script), "-map", "[v]", "-map", "[a]", *venc,
         "-c:a", "aac", "-b:a", "256k" if final else "128k", "-t", f"{total:.3f}",
         "-movflags", "+faststart", str(out)])
    log.info("%s: %.1f s, voice gain %+.1f dB, %d tracks, %d sounds, %d grey moments",
             out, total, gain, len(tracks), len(sfx), len(grey))
    return out


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--target", type=float, default=-15.0, help="loudness of the voice, LUFS")
    ap.add_argument("--no-denoise", action="store_true")
    ap.add_argument("--name", default="final")
    a = ap.parse_args()
    finish(Project(a.project), a.final, a.target, not a.no_denoise, a.name)


if __name__ == "__main__":
    main()
