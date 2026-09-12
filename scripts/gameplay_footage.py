#!/usr/bin/env python3
"""
Picks a random gameplay clip from assets/gameplay/ to loop behind the
narration -- the classic "Subway Surfers / Minecraft parkour" background.

These clips aren't fetched automatically: gameplay footage like this is
normally your own recorded/licensed clips, not something to auto-download
from YouTube (copyright/ToS risk), so you supply them here the same way you
supply background music in assets/music/.
"""
import random
from pathlib import Path

import config

GAMEPLAY_DIR = config.ASSETS_DIR / "gameplay"


def pick_gameplay_clip() -> Path:
    GAMEPLAY_DIR.mkdir(parents=True, exist_ok=True)
    clips = (
        list(GAMEPLAY_DIR.glob("*.mp4"))
        + list(GAMEPLAY_DIR.glob("*.mov"))
        + list(GAMEPLAY_DIR.glob("*.mkv"))
    )
    if not clips:
        raise RuntimeError(
            f"No gameplay footage found in {GAMEPLAY_DIR}. Drop a few gameplay clips there "
            "first (e.g. Subway Surfers / Minecraft parkour recordings you have the rights to use)."
        )
    return random.choice(clips)


if __name__ == "__main__":
    print(pick_gameplay_clip())
