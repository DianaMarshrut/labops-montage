"""Edit plan: draft from the words, check it, apply it to the project.

  python3 plan.py draft <project> [--cta "пиши ПЛАН в комментарии"]
      -> plan.draft.json (never overwrites plan.json) + plan.md (readable passport for the user)
  python3 plan.py check <project>
      checks plan.json; exit 1 on errors (see RULES)
  python3 plan.py apply <project>
      plan.json -> work/sfx.json, work/grey.json, work/zooms.json, work/inserts.json, work/fx.json

plan.json = {"beats": [beat, ...]}; a beat:
  {"a": 0.0, "b": 2.1, "text": "...", "role": "hook|body|list|cta",
   "zoom": 1.0,                       1.0 wide, 1.3 medium, 1.6 close (jump zoom on the face)
   "insert": null | {"kind": "image|logo|meme|screenshot|text", "src": "path or TODO: what to find",
                     "layout": "card|full|split", "text": "for kind=text"},
   "accent": ["слово"],               caption accent words in this beat
   "sfx": null | "whoosh" | {"kind": "pop", "gain": -8, "at": 0.0},
   "grey": false,                      grey moment: true = black-and-white, "spinner" = plus loading icon
   "fx": null | "shake" | {"kind": "flash", "at": 0.0, "len": 0.3}}
                                       video effect: shake, glitch, flash, freeze (effects.py)
Times are on the clean timeline (work/words.json). Draft beats with "TODO" in insert.src must be filled
with a real file before apply.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from common import Project, Word, duration, load_words, setup_logging
from effects import KINDS as FX_KINDS

log = logging.getLogger("plan")
ZOOMS = (1.3, 1.0, 1.6, 1.0)            # jump-zoom cycle on the talking head, starts close on the hook
MIN_BEAT, MAX_BEAT = 0.8, 3.2
NUM = re.compile(r"\d")
BRAND = re.compile(r"^[A-ZА-ЯЁ][\w-]*[A-Za-z]|^[A-Z]{2,}")  # Latin-capitalised or acronym: likely a product name

RULES = """Checks:
  E  beats are sorted, do not overlap, cover the whole clean cut (gaps < 0.15 s)
  E  every beat is 0.4-6 s long
  E  no insert has src with TODO
  E  the first 1.5 s has a visual change (zoom change, insert or a cut)
  E  every effect (fx) is one of: shake, glitch, flash, freeze
  W  no stretch of the same framing longer than 6 s
  W  at least one insert per 10 s
  W  the last beat has role cta
  W  sound effects not denser than one per 1.5 s
  W  video effects not denser than one per 3 s"""


def beats_from_words(words: list[Word]) -> list[list[Word]]:
    """Split words into beats at sentence/clause ends, MIN..MAX seconds long."""
    beats: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        span = cur[-1].end - cur[0].start
        end_clause = w.text.rstrip()[-1:] in ".!?,:;…"
        if (end_clause and span >= MIN_BEAT) or span >= MAX_BEAT:
            beats.append(cur)
            cur = []
    if cur:
        if beats and cur[-1].end - cur[0].start < MIN_BEAT:
            beats[-1] += cur
        else:
            beats.append(cur)
    return beats


def fx_kind(fx: str | dict) -> str:
    """Effect kind of a beat's fx field."""
    return fx if isinstance(fx, str) else fx.get("kind", "")


def draft(proj: Project, cta: str) -> Path:
    """Draft plan: hook, jump zooms, insert candidates on names and numbers, CTA."""
    words = load_words(proj.work / "words.json")
    total = duration(proj.work / "clean.mp4")
    groups = beats_from_words(words)
    if len(groups[0]) > 2 and groups[0][-1].end - groups[0][0].start > 1.5:
        # hook: a visual change within the first 1.5 s, so split the first beat at a word near 1.1 s
        k = min(range(1, len(groups[0])), key=lambda j: abs(groups[0][j].start - groups[0][0].start - 1.1))
        groups[:1] = [groups[0][:k], groups[0][k:]]
    beats = []
    for i, g in enumerate(groups):
        a = 0.0 if i == 0 else round((groups[i - 1][-1].end + g[0].start) / 2, 3)
        b = total if i == len(groups) - 1 else round((g[-1].end + groups[i + 1][0].start) / 2, 3)
        text = " ".join(w.text for w in g)
        names = [w.text.strip(".,!?:;«»\"") for w in g[1:] if BRAND.match(w.text)]
        nums = [w.text.strip(".,!?:;") for w in g if NUM.search(w.text)]
        insert = None
        if names:
            insert = {"kind": "logo", "src": f"TODO: official logo of {names[0]}", "layout": "card"}
        elif nums:
            insert = {"kind": "text", "src": "", "layout": "card", "text": nums[0]}
        role = "hook" if g[0].start - groups[0][0].start < 1.5 else "cta" if i == len(groups) - 1 else "body"
        beats.append({"a": a, "b": b, "text": text, "role": role, "zoom": ZOOMS[i % len(ZOOMS)],
                      "insert": insert, "accent": (names or nums)[:1],
                      "sfx": "whoosh" if insert else ("pop" if i == 0 else None), "grey": False, "fx": None})
    if cta:
        beats[-1]["insert"] = {"kind": "text", "src": "", "layout": "card", "text": cta}
    out = proj.root / "plan.draft.json"
    out.write_text(json.dumps({"beats": beats}, ensure_ascii=False, indent=1))
    passport(beats, total, proj.root / "plan.md")
    log.info("draft: %d beats -> %s and plan.md; review, copy to plan.json, fill TODO", len(beats), out)
    return out


def passport(beats: list[dict], total: float, path: Path) -> None:
    """Readable plan for the user (the passport)."""
    rows = [f"Длина: {total:.1f} с, кусков: {len(beats)}", ""]
    for i, b in enumerate(beats, 1):
        ins = b["insert"]
        what = f" | вставка: {ins['kind']} {ins.get('text') or ins.get('src')}" if ins else ""
        extra = (" | звук: " + (b["sfx"] if isinstance(b["sfx"], str) else b["sfx"]["kind"])) if b["sfx"] else ""
        grey = " | серый момент" if b["grey"] else ""
        fx = (" | эффект: " + FX_KINDS[fx_kind(b["fx"])][0].lower()) if b.get("fx") else ""
        rows.append(f"{i:>2}. {b['a']:5.1f}-{b['b']:5.1f}  [{b['role']}, наезд x{b['zoom']}]{what}{extra}{grey}{fx}"
                    f"\n    {b['text']}")
    path.write_text("\n".join(rows) + "\n")


def check(proj: Project) -> int:
    """Lint plan.json; print problems; return the number of errors."""
    plan = json.loads((proj.root / "plan.json").read_text())
    beats = plan["beats"]
    total = duration(proj.work / "clean.mp4")
    err, warn = [], []
    for i, b in enumerate(beats):
        d = b["b"] - b["a"]
        if not 0.4 <= d <= 6:
            err.append(f"beat {i + 1}: length {d:.2f} s outside 0.4-6 s")
        if b.get("fx") and fx_kind(b["fx"]) not in FX_KINDS:
            err.append(f"beat {i + 1}: unknown effect {fx_kind(b['fx'])} (known: {', '.join(FX_KINDS)})")
        if b.get("insert") and "TODO" in str(b["insert"].get("src", "")):
            err.append(f"beat {i + 1}: insert still TODO ({b['insert']['src']})")
        if i and b["a"] < beats[i - 1]["b"] - 0.01:
            err.append(f"beat {i + 1}: overlaps the previous one")
        if i and b["a"] - beats[i - 1]["b"] > 0.15:
            err.append(f"beat {i + 1}: gap of {b['a'] - beats[i - 1]['b']:.2f} s before it")
    if beats and (beats[0]["a"] > 0.15 or total - beats[-1]["b"] > 0.15):
        err.append("beats do not cover the whole cut")
    first = [b for b in beats if b["a"] < 1.5]
    if len({b["zoom"] for b in first}) < 2 and not any(b.get("insert") for b in first):
        err.append("no visual change in the first 1.5 s (hook): change zoom or add an insert")
    run_start, run_zoom = 0.0, None
    for b in beats:
        if b.get("insert") or b["zoom"] != run_zoom:
            run_start, run_zoom = b["a"], b["zoom"]
        if b["b"] - run_start > 6:
            warn.append(f"same framing for {b['b'] - run_start:.1f} s up to {b['b']:.1f} s")
            run_start = b["b"]
    inserts = sum(1 for b in beats if b.get("insert"))
    if inserts < total / 10:
        warn.append(f"{inserts} inserts for {total:.0f} s: aim for at least one per 10 s")
    if beats and beats[-1].get("role") != "cta":
        warn.append("last beat is not a CTA")
    times = sorted(b["a"] for b in beats if b.get("sfx"))
    dense = [t for t, n in zip(times, times[1:]) if n - t < 1.5]
    if dense:
        warn.append(f"sound effects closer than 1.5 s at {', '.join(f'{t:.1f}' for t in dense)}")
    times = sorted(b["a"] for b in beats if b.get("fx"))
    dense = [t for t, n in zip(times, times[1:]) if n - t < 3]
    if dense:
        warn.append(f"video effects closer than 3 s at {', '.join(f'{t:.1f}' for t in dense)}")
    for e in err:
        print(f"ERROR  {e}")
    for w in warn:
        print(f"WARN   {w}")
    print(f"{len(err)} errors, {len(warn)} warnings")
    return len(err)


def apply(proj: Project) -> None:
    """plan.json -> files read by frame.py, inserts.py and finish.py."""
    if check(proj):
        sys.exit("fix the errors in plan.json first")
    beats = json.loads((proj.root / "plan.json").read_text())["beats"]
    sfx, grey, zooms, inserts, fx = [], [], [], [], []
    for b in beats:
        if b.get("sfx"):
            s = {"kind": b["sfx"]} if isinstance(b["sfx"], str) else dict(b["sfx"])
            sfx.append({"t": round(b["a"] + s.pop("at", 0.0), 3), "kind": s["kind"], "gain": s.get("gain", -8)})
        if b.get("grey"):
            grey.append({"a": b["a"], "b": b["b"], "spinner": b["grey"] == "spinner"})
        zooms.append({"a": b["a"], "b": b["b"], "zoom": b["zoom"]})
        if b.get("insert"):
            inserts.append({"a": b["a"], "b": b["b"], **b["insert"]})
        if b.get("fx"):
            e = {"kind": b["fx"]} if isinstance(b["fx"], str) else b["fx"]
            a = round(b["a"] + e.get("at", 0.0), 3)
            fx.append({"a": a, "b": round(min(b["b"], a + e.get("len", FX_KINDS[e["kind"]][1])), 3),
                       "kind": e["kind"]})
    for name, data in (("sfx", sfx), ("grey", grey), ("zooms", zooms), ("inserts", inserts), ("fx", fx)):
        (proj.work / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    log.info("applied: %d sounds, %d grey, %d beats, %d inserts, %d effects",
             len(sfx), len(grey), len(zooms), len(inserts), len(fx))


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__ + "\n" + RULES, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("project", type=Path)
    d.add_argument("--cta", default="")
    for name in ("check", "apply"):
        sub.add_parser(name).add_argument("project", type=Path)
    a = ap.parse_args()
    proj = Project(a.project)
    if a.cmd == "draft":
        draft(proj, a.cta)
    elif a.cmd == "check":
        sys.exit(1 if check(proj) else 0)
    else:
        apply(proj)


if __name__ == "__main__":
    main()
