"""Memes from a public Telegram channel (default @membeztexta: memes without captions, mostly short videos).

  python3 memes.py fetch <folder> [--channel membeztexta] [--count 40]
      reads the channel's public web page (t.me/s/<channel>, no login, no key), saves the newest posts with
      media: preview pictures + folder/index.json (post number, caption text, media links)
  python3 memes.py sheet <folder> <out.png>
      numbered preview sheet with each post's caption: show it to the user or pick by meaning yourself
  python3 memes.py get <folder> <N> [<N> ...]
      downloads the full video/picture of sheet numbers N into folder/ and prints the paths;
      put a path into plan.json: "insert": {"kind": "meme", "src": "<path>", "layout": "full"}
Media links on the page expire after a while: "get" reads the post again, so it works later too.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
from pathlib import Path

import requests

from shared import setup_logging

log = logging.getLogger("memes")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
POST = re.compile(r'<div class="tgme_widget_message_wrap.*?data-post="[^/"]+/(\d+)"(.*?)(?=<div class="tgme_widget_message_wrap|\Z)',
                  re.S)
VIDEO = re.compile(r'<video[^>]*src="([^"]+)"')
PHOTO = re.compile(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)")
THUMB = re.compile(r"tgme_widget_message_video_thumb[^>]*background-image:url\('([^']+)'\)")
TEXT = re.compile(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', re.S)


def parse(page: str) -> dict[int, dict]:
    """Posts with media on one channel page: {id: {"videos", "photos", "thumbs", "text"}}."""
    posts = {}
    for pid, body in POST.findall(page):
        videos, photos = VIDEO.findall(body), PHOTO.findall(body)
        if not videos and not photos:
            continue
        text = TEXT.search(body)
        clean = html.unescape(re.sub(r"<[^>]+>", " ", text.group(1))).strip() if text else ""
        posts[int(pid)] = {"videos": videos, "photos": photos, "thumbs": THUMB.findall(body) or photos[:1],
                           "text": re.sub(r"\s+", " ", clean)[:120]}
    return posts


def get_page(channel: str, before: int | None = None, post: int | None = None) -> str:
    """HTML of the public channel page (newest posts, or posts before an id)."""
    url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
    if post:
        url = f"https://t.me/s/{channel}?before={post + 1}"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.text


def download(url: str, path: Path) -> Path:
    """Save one media file."""
    r = requests.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def fetch(folder: Path, channel: str, count: int) -> None:
    """Newest posts with media -> previews + index.json."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "thumbs").mkdir(exist_ok=True)
    posts: dict[int, dict] = {}
    before = None
    while len(posts) < count:
        found = parse(get_page(channel, before))
        if not found:
            break
        posts.update(found)
        before = min(found)
        time.sleep(1)
    chosen = sorted(posts, reverse=True)[:count]
    index = []
    for pid in chosen:
        p = posts[pid]
        thumb = folder / "thumbs" / f"{pid}.jpg"
        if p["thumbs"] and not thumb.exists():
            download(p["thumbs"][0], thumb)
        index.append({"post": pid, "kind": "video" if p["videos"] else "photo", "text": p["text"],
                      "thumb": str(thumb) if thumb.exists() else ""})
    (folder / "index.json").write_text(json.dumps({"channel": channel, "items": index}, ensure_ascii=False,
                                                  indent=1))
    log.info("%d memes from @%s -> %s", len(index), channel, folder / "index.json")


def sheet(folder: Path, out: Path) -> None:
    """Numbered preview grid, 6 per row."""
    import base64

    from playwright.sync_api import sync_playwright

    items = json.loads((folder / "index.json").read_text())["items"]
    cells = []
    for i, it in enumerate(items, 1):
        img = (f"data:image/jpeg;base64,{base64.b64encode(Path(it['thumb']).read_bytes()).decode()}"
               if it["thumb"] else "")
        mark = "▶ " if it["kind"] == "video" else ""
        cells.append(f"<div class='c'><div class='i' style=\"background-image:url('{img}')\"></div>"
                     f"<b>{i}</b><p>{mark}{html.escape(it['text'][:60])}</p></div>")
    doc = ("<html><head><meta charset='utf-8'><style>body{margin:0;padding:8px;background:#111;display:grid;"
           "grid-template-columns:repeat(6,220px);gap:8px;font-family:sans-serif}.c{position:relative;"
           "background:#222;border-radius:8px;overflow:hidden}.i{height:220px;background:center/cover #000}"
           "b{position:absolute;left:6px;top:6px;background:#000c;color:#fff;font-size:22px;padding:2px 8px;"
           "border-radius:6px}p{margin:6px;color:#ddd;font-size:13px;height:32px;overflow:hidden}</style>"
           f"</head><body>{''.join(cells)}</body></html>")
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        rows = -(-len(items) // 6)
        pg = b.new_page(viewport={"width": 6 * 228 + 8, "height": rows * 274 + 16})
        pg.set_content(doc)
        pg.screenshot(path=str(out), full_page=True)
        b.close()
    log.info("-> %s", out)


def get(folder: Path, numbers: list[int]) -> list[Path]:
    """Full media of the chosen sheet numbers (re-reads each post, links expire)."""
    data = json.loads((folder / "index.json").read_text())
    out = []
    for n in numbers:
        it = data["items"][n - 1]
        post = parse(get_page(data["channel"], post=it["post"])).get(it["post"])
        if not post:
            raise SystemExit(f"post {it['post']} not found on the channel page any more")
        url, ext = (post["videos"][0], ".mp4") if post["videos"] else (post["photos"][0], ".jpg")
        path = download(url, folder / f"meme-{it['post']}{ext}")
        print(path)
        out.append(path)
        time.sleep(1)
    return out


def main() -> None:
    """CLI entry."""
    setup_logging()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("folder", type=Path)
    f.add_argument("--channel", default="membeztexta")
    f.add_argument("--count", type=int, default=40)
    s = sub.add_parser("sheet")
    s.add_argument("folder", type=Path)
    s.add_argument("out", type=Path)
    g = sub.add_parser("get")
    g.add_argument("folder", type=Path)
    g.add_argument("numbers", type=int, nargs="+")
    a = ap.parse_args()
    if a.cmd == "fetch":
        fetch(a.folder, a.channel, a.count)
    elif a.cmd == "sheet":
        sheet(a.folder, a.out)
    else:
        get(a.folder, a.numbers)


if __name__ == "__main__":
    main()
