#!/usr/bin/env python3
"""
Stock assets/sfx/<category>/ with short, properly licensed sound effect clips
from the Openverse API -- same source and licensing pattern as fetch_music.py.

Unlike music, Openverse actually has usable CC0 (public domain, no
attribution needed) results for sound-effect search terms -- verified by
hand ("door creak", "thud impact", "glass break" etc. all return real CC0
Freesound clips). CC0 is preferred for exactly that reason: a single video
can trigger several different SFX cues, and requiring an attribution line
per cue would make the description unmanageable. Falls back to CC BY (with
credit recorded, same as fetch_music.py) only if a category comes up short
on CC0 results.

Usage:
    python3 fetch_sfx.py                        # ~4 clips per category
    python3 fetch_sfx.py --category creak --per-category 8
    python3 fetch_sfx.py --dry-run
"""
import argparse
import html
import json
from pathlib import Path

import requests

import config

API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "faceless-videos/1.0 (+royalty-free sfx fetch)"}
SFX_DIR = config.ASSETS_DIR / "sfx"
CREDITS_PATH = SFX_DIR / "credits.json"
ATTRIBUTION_PATH = SFX_DIR / "ATTRIBUTION.txt"

# A cue needs to read as a discrete hit, not a scene -- long ambience/found
# recordings under the same search terms would otherwise get picked and play
# as an off-topic music bed instead of a sound effect.
MIN_SEC, MAX_SEC = 0.2, 8.0

# category -> search queries. Matched against narration text by sfx.py using
# the SAME category keys (see sfx.py's SFX_KEYWORDS) -- if you add a category
# here, add its trigger words there too, and vice versa.
QUERIES = {
    "thud": ["thud impact", "body fall thump", "heavy footstep thud"],
    "knock": ["door knock", "knocking on wood"],
    "bang": ["door slam", "loud bang"],
    "creak": ["door creak", "wooden creak", "floorboard creak"],
    "scrape": ["scraping metal", "scratching sound", "dragging scrape"],
    "click": ["click sound effect", "switch click"],
    "hiss": ["snake hiss", "steam hiss", "gas leak hiss"],
    "growl": ["monster growl", "demon growl", "low menacing growl", "snarl"],
    "crack": ["wood crack snap", "branch snap", "bone crack"],
    "footsteps": ["footsteps wood floor", "footsteps gravel", "running footsteps"],
    "scream": ["human scream", "scream horror", "shriek"],
    "glass_break": ["glass breaking", "glass shatter"],
    "drip": ["water drip", "dripping sound"],
    "rustle": ["leaves rustle", "fabric rustle"],
    "gasp": ["gasp sound", "sharp inhale gasp"],
    "static": ["radio static", "tv static buzz"],
    "heartbeat": ["heartbeat sound effect", "pulse thud"],
    "wind": ["wind gust", "wind howl"],
    "whisper": ["whisper sound effect", "creepy whisper"],
}

CATEGORIES = list(QUERIES)


def search(query: str, license_filter: str, page_size: int = 20) -> list:
    r = requests.get(API, headers=UA, timeout=30, params={
        "q": query, "license": license_filter, "page_size": page_size,
    })
    r.raise_for_status()
    return r.json().get("results", [])


def load_credits() -> dict:
    if CREDITS_PATH.exists():
        return json.loads(CREDITS_PATH.read_text(encoding="utf-8"))
    return {}


def write_credits(credits: dict):
    CREDITS_PATH.write_text(json.dumps(credits, indent=2), encoding="utf-8")
    by_needed = {k: v for k, v in credits.items() if v.get("license", "").startswith("by")}
    if not by_needed:
        ATTRIBUTION_PATH.write_text(
            "All fetched sound effects are CC0 (public domain) -- no attribution required.\n",
            encoding="utf-8",
        )
        return
    lines = ["SFX credits -- CC BY clips require these wherever they're used.", ""]
    for cat in CATEGORIES:
        entries = {k: v for k, v in by_needed.items() if v.get("category") == cat}
        if not entries:
            continue
        lines.append(f"[{cat}]")
        for name, meta in sorted(entries.items()):
            lines.append(f"  {name}\n    {meta['attribution']}\n    source: {meta['source_url']}")
        lines.append("")
    ATTRIBUTION_PATH.write_text("\n".join(lines), encoding="utf-8")


def download(url: str, dest: Path) -> int:
    r = requests.get(url, headers=UA, stream=True, timeout=60)
    r.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)
            total += len(chunk)
    return total


def _attribution(rec: dict) -> str:
    given = html.unescape(rec.get("attribution") or "").strip()
    if given:
        return " ".join(given.split())
    lic = f"CC {rec.get('license', '').upper()} {rec.get('license_version', '')}".strip()
    title, creator = html.unescape(rec.get("title") or ""), html.unescape(rec.get("creator") or "")
    return f'"{title}" by {creator} is licensed under {lic}. {rec.get("license_url", "")}'.strip()


def collect(category: str, want: int, credits: dict) -> list:
    picked, seen = [], set()
    existing_ids = {meta.get("openverse_id") for meta in credits.values() if meta.get("category") == category}

    for license_filter in ("cc0", "by"):  # CC0 first -- see module docstring
        if len(picked) >= want:
            break
        for query in QUERIES[category]:
            if len(picked) >= want:
                break
            try:
                results = search(query, license_filter)
            except requests.RequestException as e:
                print(f"  search failed for {query!r} ({license_filter}): {e}")
                continue
            for rec in results:
                rid = rec.get("id")
                dur = (rec.get("duration") or 0) / 1000.0
                if not rid or rid in seen or rid in existing_ids or not (MIN_SEC <= dur <= MAX_SEC):
                    continue
                seen.add(rid)
                picked.append({
                    "name": f"{category}_{rid[:8]}.mp3", "url": rec.get("url"), "duration": dur,
                    "meta": {
                        "category": category, "openverse_id": rid,
                        "title": html.unescape(rec.get("title") or ""),
                        "creator": html.unescape(rec.get("creator") or ""),
                        "license": f"{rec.get('license')}-{rec.get('license_version')}",
                        "license_url": rec.get("license_url"),
                        "source_url": rec.get("foreign_landing_url"),
                        "attribution": _attribution(rec),
                    },
                })
                if len(picked) >= want:
                    break
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=CATEGORIES, help="just one category (default: all)")
    ap.add_argument("--per-category", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    categories = [args.category] if args.category else CATEGORIES
    credits = load_credits()
    grand_total = 0

    for category in categories:
        dest_dir = SFX_DIR / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        picked = collect(category, args.per_category, credits)
        print(f"\n{category}: {len(picked)} new clip(s)")

        for p in picked:
            if args.dry_run:
                print(f"  {p['duration']:5.1f}s  {p['meta']['license']:8s} {p['meta']['title'][:45]}")
                continue
            dest = dest_dir / p["name"]
            try:
                size = download(p["url"], dest)
            except requests.RequestException as e:
                print(f"  {p['meta']['title'][:40]}: download failed ({e})")
                dest.unlink(missing_ok=True)
                continue
            grand_total += size
            credits[p["name"]] = p["meta"]
            print(f"  {p['duration']:5.1f}s  {size/1e3:5.0f} KB  {p['meta']['license']:8s} {p['meta']['title'][:40]}")

    if args.dry_run:
        return
    write_credits(credits)
    print(f"\ndownloaded {grand_total/1e6:.1f} MB")
    print(f"credits    -> {CREDITS_PATH}")


if __name__ == "__main__":
    main()
