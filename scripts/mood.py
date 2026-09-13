#!/usr/bin/env python3
"""
Reads the finished narration and decides which of three moods the story sits
in, so the background bed matches what's being told instead of being picked at
random:

    upbeat    -- funny, wholesome, triumphant, light
    dramatic  -- tense, confrontational, shocking, high-stakes
    somber    -- sad, grieving, regretful, heavy

An LLM does the judging (tone is not a keyword problem -- "my dad finally
called" and "my dad finally called the police" score identically on word
lists). The keyword heuristic is only a fallback for when the gateway is down,
so a classifier outage degrades the music choice instead of killing the run.

Usage:
    python3 mood.py "some narration text"
    python3 mood.py --file path/to/script.json
"""
import json
import re
import sys

import config
from llm_client import call_llm

MOODS = config.MOODS
DEFAULT_MOOD = "dramatic"  # the centre of gravity for r/AITA-style storytelling

MOOD_PROMPT = """You are choosing background music for a narrated short-form video of a
real Reddit story. Read the narration and pick the single mood the music
should match.

The three choices, and what each is for:
- UPBEAT: funny, wholesome, satisfying, triumphant, light-hearted. The
  listener should finish it smiling.
- DRAMATIC: tense, confrontational, shocking, high-stakes, a betrayal or a
  blow-up. The listener should feel the tension build.
- SOMBER: sad, grieving, lonely, regretful, heavy. The listener should feel
  the weight of it.

Judge the story's overall emotional arc and where it lands at the end, not
individual words. A story with a tense middle and a happy resolution is
UPBEAT. A revenge story that lands satisfyingly is UPBEAT, not DRAMATIC.
If it genuinely sits between two, pick DRAMATIC.

Narration:
{narration}

Respond in exactly this plain-text format, nothing else:

MOOD: DRAMATIC
WHY: <one short line explaining the choice>"""

# Fallback only. Weighted toward terms that rarely appear in the other two
# registers -- generic emotional words are useless here.
_KEYWORDS = {
    "somber": (
        "died", "death", "passed away", "funeral", "grief", "grieving", "cancer",
        "hospice", "terminal", "miscarriage", "suicide", "cried", "crying",
        "lonely", "regret", "never got to", "miss him", "miss her", "goodbye",
        "divorce", "estranged", "abandoned",
    ),
    "upbeat": (
        "hilarious", "laughed", "laughing", "wholesome", "adorable", "proud",
        "surprise party", "wedding", "engaged", "celebrat", "best day",
        "thank you all", "happy ending", "worked out", "made my day", "wince",
        "karma", "instant justice", "got what they deserved",
    ),
    "dramatic": (
        "screamed", "yelled", "confronted", "cheated", "affair", "betray",
        "police", "cops", "lawyer", "restraining order", "threatened", "fight",
        "caught him", "caught her", "lied", "stole", "kicked out", "no contact",
    ),
}


def _parse_mood(raw: str) -> dict:
    """Parse the plain-text answer. Plain text rather than JSON for the same
    reason as qa.py: this gateway drops the first characters of a response
    often enough that JSON comes back unparseable, while a line-based format
    survives ("MOOD: SOMBER" mangled down to "SOMBER" is still readable)."""
    mood = None
    why = ""
    for line in raw.splitlines():
        line = line.strip().lstrip("*-# ").strip().rstrip("*")
        upper = line.upper()
        if upper.startswith("MOOD:"):
            value = upper.split(":", 1)[1].strip().strip(".!").lower()
            if value in MOODS:
                mood = value
        elif upper.startswith("WHY:"):
            why = line.split(":", 1)[1].strip()
        elif mood is None and upper.strip(".!").lower() in MOODS:
            mood = upper.strip(".!").lower()

    if mood is None:
        raise ValueError(f"no mood found in response: {raw[:200]!r}")
    return {"mood": mood, "why": why}


def heuristic_mood(text: str) -> dict:
    """Keyword scoring. Crude by design -- it exists so an LLM outage picks a
    plausible bed rather than aborting the video."""
    low = text.lower()
    scores = {m: sum(len(re.findall(re.escape(k), low)) for k in words)
              for m, words in _KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return {"mood": DEFAULT_MOOD, "why": "no signal in text; defaulted", "scores": scores}
    return {"mood": best, "why": f"keyword score {scores}", "scores": scores}


def classify(script, attempts: int = 2) -> dict:
    """Return {"mood", "why", "source"} for a script dict or raw narration."""
    narration = script["narration"] if isinstance(script, dict) else str(script)
    title = script.get("hook") or script.get("original_title", "") if isinstance(script, dict) else ""
    text = f"{title}\n\n{narration}".strip()

    last_error = None
    for _ in range(attempts):
        try:
            raw = call_llm(
                model=config.LLM_MODEL_SCRIPT,
                system="You are a music supervisor choosing a score to match a story's tone.",
                user=MOOD_PROMPT.format(narration=text),
                max_tokens=1200,
                temperature=0.2,
            )
            result = _parse_mood(raw)
            result["source"] = "llm"
            return result
        except Exception as e:  # network, gateway, or unparseable answer
            last_error = e

    result = heuristic_mood(text)
    result["source"] = "heuristic"
    result["llm_error"] = str(last_error)
    print(f"  mood: LLM classification failed ({last_error}); fell back to keywords")
    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--file":
        data = json.loads(open(args[1], encoding="utf-8").read())
        payload = data if isinstance(data, dict) and "narration" in data else {"narration": str(data)}
    elif args:
        payload = {"narration": " ".join(args)}
    else:
        payload = {"narration": sys.stdin.read()}
    print(json.dumps(classify(payload), indent=2))
