"""Word-level speech recognition (Whisper) -> words.json.

  python3 transcribe.py <audio_or_video> <out_words.json> [--lang ru] [--engine auto|local|groq|openai]
                        [--prompt "Claude, HyperFrames, labopsai"]

Engines:
  local   faster-whisper on this computer, free (pip install faster-whisper; first run downloads the model)
  groq    Groq Whisper large-v3 (GROQ_API_KEY), free tier with limits
  openai  OpenAI whisper-1 (OPENAI_API_KEY), paid per minute of audio
  auto    groq if its key is set, else openai if its key is set, else local
--prompt lists names and terms that should be spelled exactly (product names, people).
"""
from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from common import Word, key, run, save_words, setup_logging, tool

log = logging.getLogger("transcribe")

API = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3", "GROQ_API_KEY"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "whisper-1", "OPENAI_API_KEY"),
}


def to_mp3(src: Path, dst: Path) -> None:
    """Mono 16 kHz 64 kbps mp3: about 0.5 MB per minute, fits the 25 MB API upload limit."""
    run([tool("ffmpeg"), "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(dst)])


def via_api(engine: str, audio: Path, lang: str, prompt: str) -> list[Word]:
    """Whisper over an OpenAI-compatible HTTP API with word timestamps."""
    import requests

    url, model, key_name = API[engine]
    secret = key(key_name)
    if not secret:
        raise SystemExit(f"{key_name} is not set (environment or ~/.config/labops-montage/keys.env)")
    data = {"model": model, "language": lang, "response_format": "verbose_json",
            "timestamp_granularities[]": "word", "temperature": "0"}
    if prompt:
        data["prompt"] = prompt
    with audio.open("rb") as fh:
        r = requests.post(url, headers={"Authorization": f"Bearer {secret}"}, data=data,
                          files={"file": (audio.name, fh, "audio/mpeg")}, timeout=600)
    if r.status_code != 200:
        raise SystemExit(f"{engine} transcription failed: HTTP {r.status_code} {r.text[:300]}")
    return [Word(w["word"].strip(), float(w["start"]), float(w["end"]))
            for w in r.json().get("words", []) if w["word"].strip()]


def via_local(audio: Path, lang: str, prompt: str) -> list[Word]:
    """faster-whisper on this computer (CPU int8 by default, GPU if available)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SystemExit("faster-whisper is not installed: pip install faster-whisper") from e
    model = WhisperModel("large-v3", device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(audio), language=lang, word_timestamps=True,
                                   initial_prompt=prompt or None, vad_filter=False)
    return [Word(w.word.strip(), float(w.start), float(w.end))
            for s in segments for w in (s.words or []) if w.word.strip()]


def pick(engine: str) -> str:
    """Resolve 'auto' to a concrete engine."""
    if engine != "auto":
        return engine
    if key("GROQ_API_KEY"):
        return "groq"
    if key("OPENAI_API_KEY"):
        return "openai"
    return "local"


def transcribe(src: Path, lang: str = "ru", engine: str = "auto", prompt: str = "") -> list[Word]:
    """Recognise speech of any audio/video file, return words sorted and with monotonic timing."""
    engine = pick(engine)
    log.info("transcribe: %s via %s", src.name, engine)
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = Path(tmp) / "speech.mp3"
        to_mp3(src, mp3)
        words = via_local(mp3, lang, prompt) if engine == "local" else via_api(engine, mp3, lang, prompt)
    words.sort(key=lambda w: w.start)
    for a, b in zip(words, words[1:]):
        b.start = max(b.start, a.start + 0.02)
        b.end = max(b.end, b.start + 0.05)
    return words


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--engine", default="auto", choices=["auto", "local", "groq", "openai"])
    ap.add_argument("--prompt", default="")
    a = ap.parse_args()
    words = transcribe(a.src, a.lang, a.engine, a.prompt)
    save_words(a.out, words)
    log.info("%d words -> %s", len(words), a.out)


if __name__ == "__main__":
    main()
