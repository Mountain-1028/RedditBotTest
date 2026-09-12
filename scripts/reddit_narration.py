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

import config
from llm_client import call_llm

NARRATION_PROMPT = """You are preparing a real Reddit post to be read aloud in a short-form
narrated video. Below is the original post. Your job:

1. Lightly clean up the text so it reads naturally when spoken aloud: expand
   abbreviations (AITA -> "Am I the jerk", TIFU -> "Today I effed up", etc.),
   fix broken sentences, remove leftover reddit formatting/links, but DO NOT
   invent new plot details, change the story, or add commentary. Preserve the
   original narrator's voice and meaning.
2. Write a short, punchy on-screen title/hook (under 12 words) to open the video.
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


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def generate_narration(post: dict, attempts: int = 3) -> dict:
    last_error = None
    for _ in range(attempts):
        raw = call_llm(
            model=config.LLM_MODEL_SCRIPT,
            system="You are a careful editor preparing real user-submitted stories for narration. You always return strict JSON.",
            user=NARRATION_PROMPT.format(
                subreddit=post["subreddit"], title=post["title"], selftext=post["selftext"]
            ),
            max_tokens=4000,
            temperature=0.4,
            json_mode=True,
        )
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        data["subreddit"] = post["subreddit"]
        data["post_id"] = post["id"]
        data["permalink"] = post["permalink"]
        data["original_title"] = post["title"]
        return data
    raise RuntimeError(f"Model returned malformed/truncated JSON after {attempts} attempts: {last_error}")


if __name__ == "__main__":
    from reddit_source import pick_post
    post = pick_post()
    script = generate_narration(post)
    print(json.dumps(script, indent=2))
