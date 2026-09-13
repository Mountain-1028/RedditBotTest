#!/usr/bin/env python3
"""
Stock the b-roll library with properly licensed, watermark-free footage from
Pexels (free for commercial use, no attribution required).

The alternative -- compilations scraped off video platforms -- arrives covered
in other creators' watermarks and handles, which can't be cropped out when
they sit mid-frame. This fetches originals instead.

Usage:
    python3 fetch_broll_pexels.py                   # default query set
    python3 fetch_broll_pexels.py --limit 40
    python3 fetch_broll_pexels.py --queries "slime,glitter" --dry-run
"""
import argparse
import sys
from pathlib import Path

import requests

import config

SEARCH_URL = "https://api.pexels.com/videos/search"
DEFAULT_QUERIES = [
    "slime", "kinetic sand", "paint mixing", "soap cutting", "resin art",
    "glitter", "satisfying texture", "hydraulic press", "candle making",
    "clay sculpting",
]
MIN_DURATION = 8
MAX_DURATION = 120


def _pick_file(video: dict):
    """Prefer a portrait rendition around 1080 wide -- big enough for a
    1080x1920 frame without dragging down a needless 4K file."""
    files = video.get("video_files", [])
    portrait = [f for f in files if (f.get("height") or 0) > (f.get("width") or 0)]
    pool = portrait or files
    if not pool:
        return None
    sized = [f for f in pool if 900 <= (f.get("width") or 0) <= 1200]
    return (sized or sorted(pool, key=lambda f: -(f.get("width") or 0)))[0]


def search(query: str, per_page: int = 30) -> list:
    r = requests.get(SEARCH_URL, headers={"Authorization": config.PEXELS_API_KEY},
                     params={"query": query, "orientation": "portrait", "per_page": per_page},
                     timeout=30)
    r.raise_for_status()
    return r.json().get("videos", [])


def download(url: str, dest: Path) -> int:
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)
            total += len(chunk)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60, help="max clips to download")
    ap.add_argument("--queries", default=None, help="comma-separated search terms")
    ap.add_argument("--out", default=None, help="destination (default <MEDIA_ROOT>/broll)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not config.PEXELS_API_KEY:
        sys.exit("PEXELS_API_KEY not set in .env (free key from pexels.com/api)")

    out_dir = Path(args.out) if args.out else config.BROLL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = [q.strip() for q in args.queries.split(",")] if args.queries else DEFAULT_QUERIES

    existing = {p.stem for p in out_dir.glob("pexels_*.mp4")}
    picked, seen = [], set()

    for q in queries:
        try:
            videos = search(q)
        except requests.RequestException as e:
            print(f"  search failed for {q!r}: {e}")
            continue
        for v in videos:
            vid = v.get("id")
            dur = v.get("duration", 0)
            if not vid or vid in seen or not (MIN_DURATION <= dur <= MAX_DURATION):
                continue
            if f"pexels_{vid}" in existing:
                continue
            f = _pick_file(v)
            if not f:
                continue
            seen.add(vid)
            picked.append({"id": vid, "query": q, "duration": dur,
                           "url": f["link"], "w": f.get("width"), "h": f.get("height")})

    picked = picked[: args.limit]
    print(f"{len(picked)} clips to fetch into {out_dir}")
    if args.dry_run:
        for p in picked[:15]:
            print(f"  [{p['query']:<18}] id={p['id']} {p['w']}x{p['h']} {p['duration']}s")
        return

    total_bytes = 0
    for i, p in enumerate(picked, 1):
        dest = out_dir / f"pexels_{p['id']}.mp4"
        try:
            total_bytes += download(p["url"], dest)
        except requests.RequestException as e:
            print(f"  {p['id']}: download failed ({e})")
            dest.unlink(missing_ok=True)
            continue
        if i % 10 == 0:
            print(f"  {i}/{len(picked)}  ({total_bytes/1e6:.0f} MB so far)")

    print(f"done: {len(list(out_dir.glob('pexels_*.mp4')))} pexels clips, {total_bytes/1e6:.0f} MB downloaded")


if __name__ == "__main__":
    main()
