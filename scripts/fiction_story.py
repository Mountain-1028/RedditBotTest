#!/usr/bin/env python3
"""
Generates an original horror short story for the Halloween track, in the
same first-person "this really happened to me" voice as r/nosleep -- but
invented, not narrating a real post. This is the one place in the pipeline
where the LLM is allowed to make up plot details; reddit_narration.py's
prompt explicitly forbids that everywhere else, because everywhere else is
narrating someone's real, attributed post.

Because nothing here traces back to a real Reddit thread, the resulting
video carries no subreddit/permalink -- run_pipeline.py records its
provenance as "Original fiction (AI-generated)" in the ready_to_post
metadata instead, so the description is honest about what it's watching
even though the on-screen card looks like any other video (see
reddit_card.py -- the card is the channel's own branding, not a screenshot
of a real post, so it doesn't need a different look for fiction).

Usage:
    python3 fiction_story.py                  # one story, short-form budget
    python3 fiction_story.py --max-sec 600     # long-form budget
"""
import json
import random
import re
import time
import uuid
from datetime import datetime, timezone

import config
from llm_client import call_llm

HISTORY_PATH = config.LOGS_DIR / "used_fiction_premises.json"

# Inspiration, not an exhaustive menu -- the prompt tells the model to riff on
# or depart from these rather than pick one verbatim, so output doesn't
# collapse into the same handful of stories.
PREMISE_SEEDS = [
    "a night-shift job where something is wrong with one specific rule you're told never to break",
    "a new apartment/house with a neighbor, sound, or feature that's slightly off",
    "a family member's odd, specific request that turns out to have a reason",
    "something followed you home from an ordinary errand or commute",
    "a childhood memory that resurfaces as an adult and turns out to mean something else",
    "a small town with a tradition or rule outsiders aren't told about",
    "a video call, phone line, or recording that shows something it shouldn't",
    "a babysitting or pet-sitting job with an instruction that seems paranoid until it isn't",
    "a hiking/camping trip where the group realizes they are not alone",
    "a workplace (hospital, warehouse, call center) with an unexplained policy",
]

FICTION_PROMPT = """Write an original horror short story in the exact voice and format of a
r/nosleep post: first person, told as if it genuinely happened to the narrator, grounded and
plausible rather than over-the-top gore, with escalating dread and an ambiguous or unsettling
ending (not a tidy resolution, not a jump-scare punchline). This is fiction you are inventing --
own that fully, write a complete original story, don't hedge or add disclaimers inside the story
itself.
{style_directive}

Loose inspiration (use, combine, or depart from freely -- do not just restate it):
{seed}

Avoid re-treading these recent premises:
{avoid}

HARD LIMIT: the story must be at most {max_words} words. Pace it so the length earns the
ending -- don't rush the escalation just to hit a small budget; if the budget is large, use it
for slow-building unease, not padding.

Return ONLY valid JSON matching this exact shape, no markdown fences, no commentary:
{{
  "hook": "punchy on-screen title, under 12 words, written like a nosleep post title",
  "narration": "the full story, first person, ready to be read aloud start to finish",
  "caption": "1-2 sentence social caption that doesn't give away the ending",
  "hashtags": ["#tag1", "#tag2", "..."]
}}"""


def _load_history() -> list[str]:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return []


def _save_history(history: list[str]):
    # Keep it bounded -- only the last ~40 premises are useful context for
    # "don't repeat yourself"; an unbounded file just bloats the prompt.
    HISTORY_PATH.write_text(json.dumps(history[-40:], indent=2), encoding="utf-8")


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def generate_fiction(max_sec: float = None, attempts: int = 4, style: str = None) -> tuple[dict, dict]:
    """Returns (post, script) shaped exactly like reddit_source.pick_post()
    and reddit_narration.generate_narration() would, so it drops straight
    into run_pipeline.produce_video() without that function needing to know
    whether the story is real or invented.

    style is an optional free-text subgenre steer, e.g. "Lovecraftian cosmic
    horror" -- left blank it defaults to plain grounded nosleep-voice horror."""
    max_words = config.narration_word_budget(max_sec=max_sec)
    history = _load_history()
    avoid = "\n".join(f"- {h}" for h in history[-15:]) or "(none yet)"
    seed = random.choice(PREMISE_SEEDS)
    style_directive = f"Subgenre/style to write this in: {style}." if style else ""

    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * (4 ** (attempt - 1)))
        try:
            raw = call_llm(
                model=config.LLM_MODEL_SCRIPT,
                system="You are a skilled horror fiction writer who writes in the authentic "
                       "voice of real r/nosleep posts. You always return strict JSON.",
                user=FICTION_PROMPT.format(seed=seed, avoid=avoid, max_words=max_words,
                                            style_directive=style_directive),
                max_tokens=6000,
                temperature=0.95,
                json_mode=True,
            )
            data = _extract_json(raw)
        except Exception as e:
            last_error = e
            continue

        word_count = len(data.get("narration", "").split())
        if word_count > max_words * 1.15:
            last_error = ValueError(f"story was {word_count} words, budget is {max_words}")
            continue
        if word_count < 60:
            last_error = ValueError(f"story too short ({word_count} words) to be a real story")
            continue

        post_id = f"fiction_{uuid.uuid4().hex[:12]}"
        post = {
            "id": post_id,
            "subreddit": "original_fiction",
            "title": data["hook"],
            "score": None,
            "permalink": "Original fiction (AI-generated) -- not sourced from Reddit",
        }
        data["subreddit"] = post["subreddit"]
        data["post_id"] = post_id
        data["permalink"] = post["permalink"]
        data["original_title"] = data["hook"]

        history.append(f"{data['hook']} -- {seed}")
        _save_history(history)
        return post, data

    raise RuntimeError(f"Fiction generation failed after {attempts} attempts: {last_error}")


if __name__ == "__main__":
    import sys
    max_sec = float(sys.argv[sys.argv.index("--max-sec") + 1]) if "--max-sec" in sys.argv else None
    post, script = generate_fiction(max_sec=max_sec)
    print(json.dumps({"post": post, "script": script}, indent=2))
