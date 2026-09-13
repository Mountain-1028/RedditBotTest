#!/usr/bin/env python3
"""
Picks the next Reddit post to narrate.

Checks Downloads/reddit-story-queue/ first -- posts saved there by
browser-extension/ when the user manually clicked to queue a post they were
personally viewing. Falls back to Reddit's official OAuth API (app-only
client-credentials grant) if the queue is empty, which requires a free
Reddit "script" app: create one at https://www.reddit.com/prefs/apps
("create app" -> type "script"), then put its client ID and secret in .env
as REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET. Note that Reddit's Responsible
Builder Policy requires explicit approval for API access used for anything
resembling commercial/republished use -- the manual queue exists precisely
to have a path that doesn't depend on that approval.
"""
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

HISTORY_PATH = config.LOGS_DIR / "used_reddit_posts.json"

# Posts saved by browser-extension/ land here (the user manually clicked to
# queue a post they were viewing -- not an automated scrape). Checked first,
# before ever calling the Reddit API.
QUEUE_DIR = Path.home() / "Downloads" / "reddit-story-queue"
QUEUE_USED_DIR = QUEUE_DIR / "used"

SUBREDDITS = [
    "AskReddit", "tifu", "AmItheAsshole", "TrueOffMyChest",
    "relationship_advice", "confession", "MaliciousCompliance",
    "pettyrevenge", "EntitledPeople",
]

MIN_CHARS = 300
MAX_CHARS = 1800
MIN_SCORE = 50

USER_AGENT = "python:faceless-reddit-story-pipeline:v1.0 (by /u/faceless_pipeline_bot)"

_token_cache = {"token": None, "expires_at": 0}


def load_history():
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text())
    return []


def save_history(history):
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


def _clean_selftext(text: str) -> str:
    """Strip reddit-specific markup/boilerplate that reads badly aloud."""
    text = re.sub(r"^\s*edit\s*\d*\s*:.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\[removed\]|\[deleted\]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\*\*|\*|~~|\^", "", text)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return text


def _get_access_token() -> str:
    if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
        raise RuntimeError(
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set in .env. Create a free "
            "'script' app at https://www.reddit.com/prefs/apps and put its client ID "
            "and secret there."
        )
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
    return _token_cache["token"]


def fetch_candidates(subreddit: str, limit: int = 25):
    token = _get_access_token()
    r = requests.get(
        f"https://oauth.reddit.com/r/{subreddit}/top",
        params={"limit": limit, "t": "day"},
        headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("data", {}).get("children", [])


def pick_queued_post() -> dict | None:
    """Check for a post the user manually queued via browser-extension/
    before falling back to the API. Returns None if the queue is empty."""
    if not QUEUE_DIR.exists():
        return None
    files = sorted(QUEUE_DIR.glob("*.json"))
    if not files:
        return None

    history = load_history()
    used_ids = {h["id"] for h in history}
    QUEUE_USED_DIR.mkdir(parents=True, exist_ok=True)

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            f.rename(QUEUE_USED_DIR / f.name)
            continue

        post_id = data.get("id") or f.stem
        selftext = _clean_selftext(data.get("selftext", ""))
        image_urls = data.get("image_urls") or []

        if post_id in used_ids or not (selftext or image_urls):
            f.rename(QUEUE_USED_DIR / f.name)
            continue

        # Image posts (screenshots of texts/notes) carry their story in the
        # picture; read it out before anything downstream needs the text.
        if not selftext and image_urls:
            from image_to_text import transcribe_images
            print(f"  transcribing {len(image_urls)} image(s) from the post...")
            selftext = _clean_selftext(transcribe_images(image_urls))
            if not selftext:
                print("  no readable text in the images; skipping this one")
                f.rename(QUEUE_USED_DIR / f.name)
                continue

        post = {
            "id": post_id,
            "subreddit": data.get("subreddit") or "unknown",
            "title": (data.get("title") or "").strip(),
            "selftext": selftext,
            "score": data.get("score"),
            "permalink": data.get("permalink") or "",
        }
        history.append({
            "id": post_id, "subreddit": post["subreddit"], "title": post["title"],
            "used_at": datetime.now(timezone.utc).isoformat(), "source": "manual_queue",
        })
        save_history(history)
        f.rename(QUEUE_USED_DIR / f.name)
        return post

    return None


def pick_post() -> dict:
    queued = pick_queued_post()
    if queued:
        return queued

    history = load_history()
    used_ids = {h["id"] for h in history}
    subs = SUBREDDITS[:]
    random.shuffle(subs)

    for sub in subs:
        try:
            posts = fetch_candidates(sub)
        except requests.RequestException:
            continue
        random.shuffle(posts)
        for entry in posts:
            d = entry.get("data", {})
            post_id = d.get("id")
            selftext = d.get("selftext", "")
            if (
                not post_id or post_id in used_ids
                or d.get("over_18") or d.get("stickied")
                or d.get("score", 0) < MIN_SCORE
                or not (MIN_CHARS <= len(selftext) <= MAX_CHARS)
            ):
                continue
            post = {
                "id": post_id,
                "subreddit": sub,
                "title": d.get("title", "").strip(),
                "selftext": _clean_selftext(selftext),
                "score": d.get("score", 0),
                "permalink": f"https://reddit.com{d.get('permalink', '')}",
            }
            history.append({
                "id": post_id, "subreddit": sub, "title": post["title"],
                "used_at": datetime.now(timezone.utc).isoformat(),
            })
            save_history(history)
            return post

    raise RuntimeError(
        f"No suitable unused Reddit post found today across {SUBREDDITS} "
        f"(need {MIN_CHARS}-{MAX_CHARS} chars, score >= {MIN_SCORE}, not NSFW/stickied/already-used)."
    )


if __name__ == "__main__":
    p = pick_post()
    print(json.dumps(p, indent=2))
