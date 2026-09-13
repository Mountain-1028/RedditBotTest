#!/usr/bin/env python3
"""
Finds onomatopoeia/sound-cue words in a narration's word-level TTS timings
and matches each to a sound-effect clip fetched by fetch_sfx.py, so a word
like "thud" or "creak" gets an actual sound layered under the narration at
the exact moment it's spoken -- not just the TTS voice saying the word.

Cue words are matched, not narrated meaning -- "the door creaked open" cues
a creak, same as an asterisked "*creak*". That's deliberate: both are the
author marking an audible moment, just with different punctuation.
"""
import random
import re
from pathlib import Path

import config

SFX_DIR = config.ASSETS_DIR / "sfx"

# category -> trigger words/stems. Keys must match fetch_sfx.py's QUERIES
# categories. Matched against a lowercased, punctuation-stripped word with a
# simple stem check (see _normalize) so "creaking"/"creaked"/"creaks" all hit
# "creak" without listing every inflection.
SFX_KEYWORDS = {
    "thud": ["thud", "thump"],
    "knock": ["knock"],
    "bang": ["bang", "slam"],
    "creak": ["creak"],
    "scrape": ["scrape", "scratch"],
    "click": ["click"],
    "hiss": ["hiss"],
    "growl": ["growl", "snarl"],
    "crack": ["crack", "snap"],
    "footsteps": ["footstep"],
    "scream": ["scream", "shriek", "screech"],
    "glass_break": ["shatter"],
    "drip": ["drip"],
    "rustle": ["rustle"],
    "gasp": ["gasp"],
    "static": ["static"],
    "heartbeat": ["heartbeat"],
    "wind": ["howl"],
    "whisper": ["whisper"],
}

# Longest stem first, so "screech" (a scream-category stem) doesn't get
# shadowed by a shorter unrelated prefix match.
_STEM_TO_CATEGORY = sorted(
    ((stem, cat) for cat, stems in SFX_KEYWORDS.items() for stem in stems),
    key=lambda p: -len(p[0]),
)

# A word wrapped in asterisks or written with a drawn-out/repeated letter
# ("*creak*", "scraaaape") is the clearest possible authorial cue -- give it
# priority and collapse the letter-stretching before matching.
_STRETCH_RE = re.compile(r"(.)\1{2,}")


def _normalize(word: str) -> str:
    w = re.sub(r"[^a-zA-Z]", "", word).lower()
    # Collapse a 3+ run down to a single letter, not two -- "scraaaape" needs
    # to become "scrape" (one 'a') to match the "scrape" stem via startswith.
    # A word with a genuine short double letter ("hiss") has a run of only 2
    # and is untouched by the {2,} (3-total) threshold below.
    return _STRETCH_RE.sub(r"\1", w)


def _match_category(word: str) -> str | None:
    norm = _normalize(word)
    if len(norm) < 3:
        return None
    for stem, cat in _STEM_TO_CATEGORY:
        if norm.startswith(stem):
            return cat
    return None


def available_categories() -> set[str]:
    if not SFX_DIR.exists():
        return set()
    return {d.name for d in SFX_DIR.iterdir() if d.is_dir() and any(d.glob("*.mp3"))}


def pick_clip(category: str) -> Path | None:
    clips = list((SFX_DIR / category).glob("*.mp3"))
    return random.choice(clips) if clips else None


def detect_cues(words: list[dict], max_cues: int = 10, min_gap_sec: float = 0.6) -> list[dict]:
    """words is tts_info["words"] (see tts_edge.synthesize): [{"word","start","end"}, ...].
    Returns cues sorted by time: [{"category", "word", "start", "clip"}, ...],
    each with a real clip already picked, skipping categories the library has
    no clips for. min_gap_sec avoids stacking two cues close enough to mush
    together into noise; max_cues caps how busy the mix gets on a long story."""
    have = available_categories()
    if not have:
        return []

    cues = []
    last_time_by_cat = {}
    for w in words:
        cat = _match_category(w.get("word", ""))
        if not cat or cat not in have:
            continue
        start = w["start"]
        if start - last_time_by_cat.get(cat, -999) < min_gap_sec:
            continue
        clip = pick_clip(cat)
        if not clip:
            continue
        cues.append({"category": cat, "word": w["word"], "start": start, "clip": clip})
        last_time_by_cat[cat] = start
        if len(cues) >= max_cues:
            break
    return cues


if __name__ == "__main__":
    import json
    import sys
    text = " ".join(sys.argv[1:]) or sys.stdin.read()
    fake_words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.3} for i, w in enumerate(text.split())]
    cues = detect_cues(fake_words)
    print(json.dumps([{**c, "clip": str(c["clip"])} for c in cues], indent=2))
