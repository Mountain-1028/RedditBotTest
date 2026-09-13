#!/usr/bin/env python3
"""
Picks a random gameplay clip (and a random start point within it) from
assets/gameplay/ to loop behind the narration -- the classic "Subway
Surfers / Minecraft parkour" background.

These clips aren't fetched automatically: gameplay footage like this is
normally your own recorded/licensed clips, not something to auto-download
from YouTube (copyright/ToS risk), so you supply them here the same way you
supply background music in assets/music/.
"""
import random
import subprocess
from pathlib import Path

import config

GAMEPLAY_DIR = config.GAMEPLAY_DIR
BROLL_DIR = config.BROLL_DIR
EXTENSIONS = ("*.mp4", "*.mov", "*.mkv", "*.webm")


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def pick_gameplay_clip() -> tuple[Path, float]:
    """Returns (clip_path, start_offset_seconds). For clips longer than a
    couple minutes, start_offset is randomized so long source videos (e.g. a
    10-minute gameplay recording) don't always play from the same point --
    that's the "variety" a large source clip needs without physically
    splitting it into many duplicate files."""
    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)
    clips = []
    for pattern in EXTENSIONS:
        clips.extend(GAMEPLAY_DIR.glob(pattern))
    if not clips:
        raise RuntimeError(
            f"No gameplay footage found in {GAMEPLAY_DIR}. Drop a few gameplay clips there "
            "first (e.g. Subway Surfers / Minecraft parkour recordings you have the rights to use)."
        )
    clip = random.choice(clips)
    duration = _probe_duration(clip)
    start_offset = random.uniform(0, max(0, duration - 60)) if duration > 90 else 0.0
    return clip, start_offset


if __name__ == "__main__":
    print(pick_gameplay_clip())
