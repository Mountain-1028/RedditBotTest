#!/usr/bin/env python3
"""
Picks the background track for a video from the mood folder that matches the
story (see mood.py), and reports what the library is missing.

Layout:
    assets/music/upbeat/      funny, wholesome, triumphant
    assets/music/dramatic/    tense, confrontational, high-stakes
    assets/music/somber/      sad, grieving, heavy
    assets/music/*.mp3        loose files = mood-agnostic fallback

Usage:
    python3 music.py                 # library report
    python3 music.py --pick somber   # show what a somber story would get
"""
import argparse
import random
from pathlib import Path

import config

EXTENSIONS = ("*.mp3", "*.m4a", "*.aac", "*.wav", "*.ogg", "*.flac")


def _tracks_in(directory: Path) -> list:
    if not directory.exists():
        return []
    found = []
    for pattern in EXTENSIONS:
        found.extend(p for p in directory.glob(pattern) if p.is_file())
    return sorted(found)


def tracks_for(mood: str) -> list:
    return _tracks_in(config.MUSIC_DIR / mood)


def fallback_tracks() -> list:
    """Loose files directly in assets/music/ -- used when a mood folder is empty."""
    return _tracks_in(config.MUSIC_DIR)


def volume_for(mood: str) -> float:
    return float(config.MUSIC_VOLUMES.get(mood, config.MUSIC_VOLUME_DEFAULT))


def pick_track(mood: str) -> dict:
    """Return {"path", "mood", "matched"} for the chosen track. matched is False
    when the mood folder was empty and a loose fallback track was used, so the
    caller can say so in the run log rather than silently shipping the wrong
    feel."""
    candidates = tracks_for(mood)
    if candidates:
        return {"path": random.choice(candidates), "mood": mood, "matched": True}

    loose = fallback_tracks()
    if loose:
        return {"path": random.choice(loose), "mood": mood, "matched": False}

    raise RuntimeError(
        f"No music for mood {mood!r}: {config.MUSIC_DIR / mood} is empty and there are no "
        f"fallback tracks loose in {config.MUSIC_DIR}. Add royalty-free tracks to the mood "
        f"folders ({', '.join(config.MOODS)})."
    )


def report() -> dict:
    counts = {m: len(tracks_for(m)) for m in config.MOODS}
    loose = fallback_tracks()
    print(f"music library: {config.MUSIC_DIR}")
    for mood in config.MOODS:
        names = tracks_for(mood)
        state = "EMPTY -- will fall back" if not names else f"{len(names)} track(s)"
        print(f"  {mood:<9} vol={volume_for(mood):.2f}  {state}")
        for n in names:
            print(f"      {n.name}")
    print(f"  fallback  vol={config.MUSIC_VOLUME_DEFAULT:.2f}  {len(loose)} loose file(s)")
    for n in loose:
        print(f"      {n.name}")
    return {"counts": counts, "fallback": len(loose)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pick", choices=list(config.MOODS), help="show the track a mood would get")
    args = ap.parse_args()
    if args.pick:
        chosen = pick_track(args.pick)
        tag = "" if chosen["matched"] else "  (fallback -- mood folder empty)"
        print(f"{args.pick}: {chosen['path'].name}  vol={volume_for(args.pick):.2f}{tag}")
    else:
        report()
