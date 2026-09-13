#!/usr/bin/env python3
"""
Picks the background clip (and a random start point within it) that loops
behind the narration.

Two libraries feed this, under MEDIA_ROOT:
    gameplay/  the classic "Subway Surfers / Minecraft parkour" look
    broll/     everything else (satisfying/ASMR-style footage, etc.)

BROLL_MIX in .env sets how often broll wins over gameplay (0.0 = always
gameplay, 1.0 = always broll). Whichever library is empty is skipped, so this
still works with only one populated.

Neither library is fetched automatically -- this is footage you record or
license yourself, same as the music in assets/music/. Long recordings are
fine: a random start point is chosen per render, so one long file supplies
plenty of variety. See prepare_broll.py for cutting a long compilation into
clean clips.
"""
import random
import subprocess
from pathlib import Path

import config

GAMEPLAY_DIR = config.GAMEPLAY_DIR
BROLL_DIR = config.BROLL_DIR
EXTENSIONS = ("*.mp4", "*.mov", "*.mkv", "*.webm")

# Don't start so near the end that the loop wraps almost immediately.
MIN_TAIL_SEC = 60
RANDOM_START_MIN_DURATION = 90


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _clips_in(directory: Path) -> list:
    if not directory.exists():
        return []
    found = []
    for pattern in EXTENSIONS:
        found.extend(directory.glob(pattern))
    return found


def pick_gameplay_clip() -> tuple[Path, float]:
    """Returns (clip_path, start_offset_seconds)."""
    gameplay = _clips_in(GAMEPLAY_DIR)
    broll = _clips_in(BROLL_DIR)

    if not gameplay and not broll:
        raise RuntimeError(
            f"No background footage found in {GAMEPLAY_DIR} or {BROLL_DIR}. "
            "Add clips you have the rights to use, or run prepare_broll.py on a long compilation."
        )

    if gameplay and broll:
        pool = broll if random.random() < config.BROLL_MIX else gameplay
    else:
        pool = broll or gameplay

    clip = random.choice(pool)
    duration = _probe_duration(clip)
    if duration > RANDOM_START_MIN_DURATION:
        start_offset = random.uniform(0, max(0, duration - MIN_TAIL_SEC))
    else:
        start_offset = 0.0
    return clip, start_offset


if __name__ == "__main__":
    print(f"gameplay: {len(_clips_in(GAMEPLAY_DIR))} clips in {GAMEPLAY_DIR}")
    print(f"broll   : {len(_clips_in(BROLL_DIR))} clips in {BROLL_DIR}")
    print(f"mix     : {config.BROLL_MIX:.0%} chance of broll")
    for _ in range(5):
        clip, start = pick_gameplay_clip()
        print(f"  -> {clip.parent.name}/{clip.name} @ {start:.0f}s")
