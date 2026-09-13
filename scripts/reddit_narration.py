#!/usr/bin/env python3
"""
Turns a raw Reddit post into narration-ready text plus the metadata needed
to post the finished video: a title/hook overlay, a social caption, and
hashtags. The LLM's job here is light cleanup (fixing broken grammar/reddit
shorthand so it reads naturally aloud) -- it must not invent plot details
that aren't in the original post.
"""
import json
import re
import time

import config
from llm_client import call_llm

NARRATION_PROMPT = """You are preparing a real Reddit post to be read aloud in a short-form
narrated video. Below is the original post. Your job:

1. Lightly clean up the text so it reads naturally when spoken aloud: expand
   abbreviations (AITA -> "Am I the jerk", TIFU -> "Today I effed up", etc.),
   fix broken sentences, remove leftover reddit formatting/links, but DO NOT
   invent new plot details, change the story, or add commentary. Preserve the
   original narrator's voice and meaning.
   HARD LIMIT: the narration must be at most {max_words} words. If the post is
   longer than that, condense it -- cut asides, repetition, and background
   detail, keeping the setup, the turn, and the payoff intact. Condensing means
   removing the author's less important words, never inventing replacements.
2. Write an on-screen hook: 2-3 short sentences (roughly 20-35 words total)
   that set up the situation and read like the opening of the post itself --
   not a single short title. This stays visible on screen for the whole
   video, so it needs to work as a self-contained mini-summary of the setup.
3. Write a 1-2 sentence social caption for the post itself.
4. Write 5-8 relevant hashtags.

Subreddit: r/{subreddit}
Original title: {title}

Original post:
{selftext}

Return ONLY valid JSON matching this exact shape, no markdown fences, no commentary:
{{
  "hook": "punchy on-screen title, under 12 words",
  "narration": "the full cleaned-up narration text, ready to be read aloud start to finish",
  "caption": "1-2 sentence social caption",
  "hashtags": ["#tag1", "#tag2", "..."]
}}"""


CONDENSE_PROMPT = """This narration is too long for the video slot. Shorten it to at most
{target} words.

Cut asides, repetition, scene-setting and background detail. Keep the setup,
the turn and the payoff intact, and keep the narrator's voice. Do not invent
replacement wording for what you remove, and do not add commentary.

Dialogue exchanges are expensive here -- each line break becomes a spoken
pause -- so prefer collapsing back-and-forth dialogue into reported speech
over cutting story beats.

Narration:
{narration}

Return ONLY the shortened narration text. No preamble, no quotes, no markdown."""


GRAMMAR_PROMPT = """Proofread this narration for grammar, spelling, and punctuation errors ONLY.

Do not rephrase, condense, improve style, or change wording choices -- fix
only objective mistakes (a misspelled word, subject-verb disagreement, a
missing or wrong punctuation mark, a duplicated word). If a sentence is
already correct, leave it untouched. This runs right before the text is
recorded as final audio, so it needs to be exactly the original text, just
corrected -- not a rewrite.

Narration:
{narration}

Return ONLY valid JSON, no markdown fences, no commentary:
{{
  "corrected": "the full narration, grammar/spelling fixed, otherwise identical to the original",
  "corrections": ["short description of each fix, e.g. 'affect -> effect'; empty list if none needed"]
}}"""


def grammar_check(narration: str, attempts: int = 3) -> dict:
    """Proofreading pass on the final narration text, run right before it's
    recorded -- catches typos/grammar slips left over from generation or
    introduced by condense_narration(). Returns {"text", "corrections",
    "changed"}; falls back to the original narration untouched on any
    failure, since a broken proofread pass corrupting the video is worse than
    skipping it."""
    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * (4 ** (attempt - 1)))
        try:
            raw = call_llm(
                model=config.LLM_MODEL_SCRIPT,
                system="You are a meticulous proofreader. You fix only objective grammar and "
                       "spelling errors and change nothing else. You always return strict JSON.",
                user=GRAMMAR_PROMPT.format(narration=narration),
                max_tokens=4000,
                temperature=0.1,
                json_mode=True,
            )
            data = _extract_json(raw)
            corrected = (data.get("corrected") or "").strip()
            if not corrected:
                raise ValueError("empty corrected text")

            # A proofread shouldn't meaningfully change length -- if it does,
            # the model rewrote rather than corrected, and the rewrite is
            # more likely to introduce a new problem than fix one.
            orig_words, new_words = len(narration.split()), len(corrected.split())
            if abs(new_words - orig_words) > max(10, orig_words * 0.12):
                raise ValueError(f"proofread changed length too much ({orig_words} -> {new_words} "
                                 f"words) -- looks like a rewrite, not a correction")

            return {"text": corrected, "corrections": data.get("corrections") or [],
                    "changed": corrected != narration.strip()}
        except Exception as e:
            last_error = e

    print(f"  grammar check failed ({last_error}); keeping narration as-is")
    return {"text": narration, "corrections": [], "changed": False, "error": str(last_error)}


def condense_narration(narration: str, target_words: int, attempts: int = 3) -> str:
    """Shorten narration to fit the video slot. Used when synthesized audio
    comes back over the cap -- measured length, not an estimate.

    The result is sanity-checked before being returned: this output goes
    straight into the voiceover, so a mangled response becomes the video. A
    gateway error page once did exactly that, and a shortening that lands far
    under target means the story was gutted rather than trimmed. Either way,
    keeping the original over-length narration is the better failure."""
    floor = max(int(target_words * 0.55), 40)
    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * (4 ** (attempt - 1)))
        try:
            raw = call_llm(
                model=config.LLM_MODEL_SCRIPT,
                system="You are a careful editor. You shorten text by removing the author's "
                       "less important words, never by inventing new ones.",
                user=CONDENSE_PROMPT.format(target=target_words, narration=narration),
                max_tokens=4000,
                temperature=0.3,
            )
        except Exception as e:
            last_error = e
            continue

        text = re.sub(r"^```(\w+)?|```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
        count = len(text.split())
        if count < floor:
            last_error = ValueError(f"condensed to {count} words, below the {floor}-word floor")
            continue
        if count >= len(narration.split()):
            last_error = ValueError(f"condensing returned {count} words, no shorter than the original")
            continue
        return text

    print(f"  condensing failed ({last_error}); keeping the original narration")
    return narration


def split_narration_into_parts(narration: str, max_words_per_part: int) -> list[str]:
    """Split a long narration into consecutive parts that each fit
    max_words_per_part, breaking at paragraph boundaries (falling back to
    sentence boundaries for a single oversized paragraph) so no sentence is
    ever cut mid-thought. Used for --split long-form stories into a "Part
    1/2/3" series instead of condensing them down to fit one slot, which
    would defeat the point of picking a long story in the first place.

    Deliberately not an LLM call: the exact wording has to match what
    _fit_narration synthesizes and what captions are built from, so this only
    ever removes/moves whitespace-delimited text, never rewrites it."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", narration.strip()) if p.strip()]
    if not paragraphs:
        return [narration.strip()] if narration.strip() else []

    chunks = []
    for para in paragraphs:
        if len(para.split()) <= max_words_per_part:
            chunks.append(para)
            continue
        # A single paragraph longer than one whole part -- break it at
        # sentence boundaries instead of dropping it in one oversized chunk.
        sentences = re.split(r"(?<=[.!?])\s+", para)
        buf = []
        for sent in sentences:
            if buf and len(" ".join(buf + [sent]).split()) > max_words_per_part:
                chunks.append(" ".join(buf))
                buf = [sent]
            else:
                buf.append(sent)
        if buf:
            chunks.append(" ".join(buf))

    parts, current = [], []
    current_words = 0
    for chunk in chunks:
        words = len(chunk.split())
        if current and current_words + words > max_words_per_part:
            parts.append("\n\n".join(current))
            current, current_words = [], 0
        current.append(chunk)
        current_words += words
    if current:
        parts.append("\n\n".join(current))
    return parts


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def generate_narration(post: dict, attempts: int = 4, max_sec: float = None) -> dict:
    """Attempts are spaced (2s, 8s, 32s). The gateway returns a 503 "model is
    overloaded" page often enough that three back-to-back retries all land in
    the same outage window and the post gets burned for nothing.

    max_sec overrides the default (short-form) word budget -- pass
    config.VIDEO_MAX_SEC_LONG for the long-form/Halloween track, otherwise a
    long real post gets condensed down to Shorts length here, before
    run_pipeline's long-form/--split handling ever sees the full story."""
    last_error = None
    max_words = config.narration_word_budget(max_sec=max_sec)
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * (4 ** (attempt - 1)))
        try:
            raw = call_llm(
                model=config.LLM_MODEL_SCRIPT,
                system="You are a careful editor preparing real user-submitted stories for narration. You always return strict JSON.",
                user=NARRATION_PROMPT.format(
                    subreddit=post["subreddit"], title=post["title"], selftext=post["selftext"],
                    max_words=max_words,
                ),
                max_tokens=4000,
                temperature=0.4,
                json_mode=True,
            )
            data = _extract_json(raw)
        except Exception as e:  # unparseable JSON, or the gateway being down
            last_error = e
            continue

        word_count = len(data.get("narration", "").split())
        if word_count > max_words * 1.15:
            last_error = ValueError(f"narration was {word_count} words, budget is {max_words}")
            continue
        data["subreddit"] = post["subreddit"]
        data["post_id"] = post["id"]
        data["permalink"] = post["permalink"]
        data["original_title"] = post["title"]
        return data
    raise RuntimeError(f"Narration generation failed after {attempts} attempts: {last_error}")


if __name__ == "__main__":
    from reddit_source import pick_post
    post = pick_post()
    script = generate_narration(post)
    print(json.dumps(script, indent=2))
