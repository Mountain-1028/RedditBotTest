#!/usr/bin/env python3
"""
Stock assets/music/<mood>/ with properly licensed music from the Openverse
API (no key required; it aggregates Jamendo, ccMixter, Wikimedia and others).

Licensing, which is the whole point of using this source:

  * Only license=by (CC BY) is requested. Searching Openverse for actual
    music rather than sound-effect samples returns essentially nothing under
    CC0 -- verified: category=music&license=cc0 gives 0 results -- so
    ATTRIBUTION IS MANDATORY for every track this fetches.
  * BY-SA is deliberately excluded. ShareAlike can be read as requiring the
    finished video to be released under the same licence, which is not a
    fight worth having on a monetised channel.
  * NC (non-commercial) and ND (no-derivatives) are excluded by omission. ND
    would also forbid the trimming/looping the mix does.

Every track's required credit is recorded in assets/music/credits.json, and
run_pipeline.py copies the credit for the track it used into that video's
ready_to_post/*.txt so it can be pasted into the upload description.

Usage:
    python3 fetch_music.py                      # ~6 tracks per mood
    python3 fetch_music.py --mood somber --per-mood 10
    python3 fetch_music.py --dry-run
"""
import argparse
import html
import json
from pathlib import Path

import requests

import config

API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "faceless-videos/1.0 (+royalty-free music fetch)"}
CREDITS_PATH = config.MUSIC_DIR / "credits.json"
ATTRIBUTION_PATH = config.MUSIC_DIR / "ATTRIBUTION.txt"

# A bed shorter than the narration loops audibly; anything under a minute also
# tends to be a sample fragment rather than a composed track.
MIN_SEC, MAX_SEC = 60, 400

QUERIES = {
    "upbeat": ["upbeat acoustic", "happy ukulele", "feel good instrumental",
               "uplifting corporate", "cheerful folk", "playful whistle"],
    "dramatic": ["tense cinematic", "dark suspense", "dramatic strings",
                 "epic tension", "ominous underscore", "thriller instrumental",
                 "suspense", "dark orchestral", "heartbeat tension", "menacing",
                 "dark ambient", "industrial tension", "brooding", "unsettling",
                 "confrontation", "anxious pulse", "noir", "dark electronic"],
    "somber": ["sad piano", "melancholy instrumental", "emotional piano",
               "reflective ambient", "sorrowful strings", "lonely guitar"],
}


def search(query: str, page_size: int = 20) -> list:
    r = requests.get(API, headers=UA, timeout=30, params={
        "q": query,
        "license": "by",        # see module docstring -- not by-sa, nc or nd
        "category": "music",    # excludes Freesound sample fragments
        "page_size": page_size,
    })
    r.raise_for_status()
    return r.json().get("results", [])


def load_credits() -> dict:
    if CREDITS_PATH.exists():
        return json.loads(CREDITS_PATH.read_text(encoding="utf-8"))
    return {}


def write_credits(credits: dict):
    CREDITS_PATH.write_text(json.dumps(credits, indent=2), encoding="utf-8")
    lines = ["Music credits -- CC BY requires these to appear wherever the track is used.",
             "run_pipeline.py copies the relevant line into each video's ready_to_post/*.txt.",
             ""]
    for mood in config.MOODS:
        entries = {k: v for k, v in credits.items() if v.get("mood") == mood}
        if not entries:
            continue
        lines.append(f"[{mood}]")
        for name, meta in sorted(entries.items()):
            lines.append(f"  {name}")
            lines.append(f"    {meta['attribution']}")
            lines.append(f"    source: {meta['source_url']}")
        lines.append("")
    ATTRIBUTION_PATH.write_text("\n".join(lines), encoding="utf-8")


def download(url: str, dest: Path) -> int:
    r = requests.get(url, headers=UA, stream=True, timeout=120)
    r.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 16):
            f.write(chunk)
            total += len(chunk)
    return total


def _attribution(rec: dict) -> str:
    """Openverse supplies a ready-made credit string; fall back to building one.
    Titles arrive HTML-escaped ("Kida &amp; Eddie"), which would otherwise be
    pasted verbatim into a video description."""
    given = html.unescape(rec.get("attribution") or "").strip()
    if given:
        return " ".join(given.split())
    lic = f"CC {rec.get('license', '').upper()} {rec.get('license_version', '')}".strip()
    title, creator = html.unescape(rec.get("title") or ""), html.unescape(rec.get("creator") or "")
    return f'"{title}" by {creator} is licensed under {lic}. {rec.get("license_url", "")}'.strip()


# One artist's back catalogue -- or worse, several stems of the same piece --
# will otherwise fill a mood folder and make every video of that mood sound
# identical. Counted against what is already on disk, not just this run.
MAX_PER_ARTIST = 3


def collect(mood: str, want: int, credits: dict) -> list:
    picked, seen = [], set()
    by_artist = {}
    for meta in credits.values():
        if meta.get("mood") == mood:
            key = (meta.get("creator") or "").lower()
            by_artist[key] = by_artist.get(key, 0) + 1

    for query in QUERIES[mood]:
        if len(picked) >= want:
            break
        try:
            results = search(query)
        except requests.RequestException as e:
            print(f"  search failed for {query!r}: {e}")
            continue
        for rec in results:
            rid = rec.get("id")
            dur = (rec.get("duration") or 0) / 1000.0
            if not rid or rid in seen or not (MIN_SEC <= dur <= MAX_SEC):
                continue
            name = f"ov_{rid[:8]}.mp3"
            if name in credits:      # already in the library
                continue
            artist = html.unescape(rec.get("creator") or "").lower()
            if by_artist.get(artist, 0) >= MAX_PER_ARTIST:
                continue
            by_artist[artist] = by_artist.get(artist, 0) + 1
            seen.add(rid)
            picked.append({
                "name": name, "url": rec.get("url"), "duration": dur, "query": query,
                "meta": {
                    "mood": mood,
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
    ap.add_argument("--mood", choices=list(config.MOODS), help="just one mood (default: all)")
    ap.add_argument("--per-mood", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    moods = [args.mood] if args.mood else list(config.MOODS)
    credits = load_credits()
    grand_total = 0

    for mood in moods:
        dest_dir = config.MUSIC_DIR / mood
        dest_dir.mkdir(parents=True, exist_ok=True)
        picked = collect(mood, args.per_mood, credits)
        print(f"\n{mood}: {len(picked)} new track(s)")

        for p in picked:
            if args.dry_run:
                print(f"  [{p['query']:<22}] {p['duration']:5.0f}s  {p['meta']['title'][:45]}")
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
            print(f"  {p['duration']:5.0f}s  {size/1e6:4.1f} MB  {p['meta']['title'][:45]} "
                  f"-- {p['meta']['creator']}")

    if args.dry_run:
        return

    write_credits(credits)
    print(f"\ndownloaded {grand_total/1e6:.0f} MB")
    print(f"credits    -> {CREDITS_PATH}")
    print(f"attribution-> {ATTRIBUTION_PATH}")
    print("\nEvery track above is CC BY: the credit line MUST appear in the video "
          "description wherever it is used.")


if __name__ == "__main__":
    main()
