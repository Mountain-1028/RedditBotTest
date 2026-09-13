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
# Queued posts that fail validate_post() land here instead of used/, with a
# sidecar explaining why -- used/ means "became a video"; a silently-broken
# post disappearing into the same folder would look identical to a success.
QUEUE_REJECTED_DIR = QUEUE_DIR / "rejected"

SUBREDDITS = [
    "AskReddit", "tifu", "AmItheAsshole", "TrueOffMyChest",
    "relationship_advice", "confession", "MaliciousCompliance",
    "pettyrevenge", "EntitledPeople",
]

# Real, permalink-attributed horror/creepypasta posts -- the Halloween track's
# default source. These are genuine user-submitted posts (same validation and
# used-post history as SUBREDDITS), just from subs where the genre is horror
# rather than drama/confession.
HORROR_SUBREDDITS = [
    "nosleep", "LetsNotMeet", "shortscarystories", "Thetruthishorrifying",
    "libraryofshadows", "DarkTales", "creepyencounters",
]

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
    # Markdown that survives to here reads literally aloud (a TTS voice will
    # say "pound" for a leftover "#", or "dash" for a bullet) -- strip the
    # rest of what Reddit's editor produces: headers, blockquotes, bullets,
    # code spans/fences, and horizontal rules.
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return text


# Below this length there usually isn't enough of an actual story to narrate
# -- matches the API path's existing MIN_CHARS bar, applied here so the
# manual queue gets the same floor.
MIN_STORY_CHARS = 300


def validate_post(post: dict) -> list[str]:
    """Pre-narration sanity check on a candidate post. Returns a list of
    problems (empty means it's fine to narrate). Catches what generation
    won't reliably catch on its own: a removed/link/question post narrates
    into something thin or empty, garbled encoding narrates into nonsense,
    and non-English text narrates in mispronounced English -- all of these
    are cheaper to catch here than after a wasted render.

    This runs on the RAW (pre-clean) selftext for the encoding/language
    checks, since _clean_selftext can't distinguish "genuinely broken" from
    "just needs stripping." Length is checked after cleaning, since markup
    removal is exactly what can take a post from a real length down to
    nothing (e.g. a post that's 90% blockquoted "context" a bot appended)."""
    issues = []
    title = (post.get("title") or "").strip()
    raw = post.get("selftext") or ""
    cleaned = _clean_selftext(raw).strip()

    if not title:
        issues.append("missing title")

    if not cleaned:
        issues.append("no narratable story text (empty, link post, or fully removed/deleted)")
        return issues  # nothing further to check against empty text

    if len(cleaned) < MIN_STORY_CHARS:
        issues.append(f"too short to narrate as a story ({len(cleaned)} chars, need {MIN_STORY_CHARS}+)")

    if "�" in raw:
        issues.append("garbled text (unicode replacement characters present -- likely a bad decode)")

    letters = [c for c in raw if c.isalpha()]
    if letters:
        non_ascii_ratio = sum(1 for c in letters if ord(c) > 127) / len(letters)
        if non_ascii_ratio > 0.3:
            issues.append(f"mostly non-English text ({non_ascii_ratio:.0%} non-ASCII letters); "
                          f"narration voice is English")

    words = cleaned.split()
    if cleaned.endswith("?") and len(words) < 40:
        issues.append("reads like a discussion prompt/question, not a personal story to narrate")

    return issues


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


def _reject_queued(f: Path, reasons: list[str]):
    """Move a bad queue file to rejected/ with a sidecar explaining why,
    instead of letting it silently look identical to a used-successfully
    file in used/."""
    QUEUE_REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    dest = QUEUE_REJECTED_DIR / f.name
    f.rename(dest)
    (dest.with_suffix(".reason.txt")).write_text(
        "Rejected before narration:\n" + "\n".join(f"- {r}" for r in reasons), encoding="utf-8"
    )
    for r in reasons:
        print(f"  rejected {f.name}: {r}")


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
        except (json.JSONDecodeError, OSError) as e:
            _reject_queued(f, [f"unreadable JSON: {e}"])
            continue

        post_id = data.get("id") or f.stem
        if post_id in used_ids:
            f.rename(QUEUE_USED_DIR / f.name)
            continue

        selftext = data.get("selftext", "")
        image_urls = data.get("image_urls") or []

        # Image posts (screenshots of texts/notes) carry their story in the
        # picture; read it out before anything downstream needs the text.
        if not _clean_selftext(selftext).strip() and image_urls:
            from image_to_text import transcribe_images
            print(f"  transcribing {len(image_urls)} image(s) from the post...")
            selftext = transcribe_images(image_urls)
            if not selftext.strip():
                _reject_queued(f, ["no readable text in the attached images"])
                continue

        post = {
            "id": post_id,
            "subreddit": data.get("subreddit") or "unknown",
            "title": (data.get("title") or "").strip(),
            "selftext": selftext,
            "score": data.get("score"),
            "permalink": data.get("permalink") or "",
        }

        # Same quality bar the API path already enforced (length, has-a-real-
        # story) -- the queue path had none of this, so anything queued via
        # the extension (a removed post, a one-line question, garbled OCR)
        # would otherwise go straight to narration untested.
        issues = validate_post(post)
        if issues:
            _reject_queued(f, issues)
            continue

        post["selftext"] = _clean_selftext(selftext)
        history.append({
            "id": post_id, "subreddit": post["subreddit"], "title": post["title"],
            "used_at": datetime.now(timezone.utc).isoformat(), "source": "manual_queue",
        })
        save_history(history)
        f.rename(QUEUE_USED_DIR / f.name)
        return post

    return None


def pick_post(subreddits: list[str] = None, check_queue: bool = True) -> dict:
    """subreddits defaults to SUBREDDITS; pass HORROR_SUBREDDITS for the
    Halloween track. check_queue=False skips the manual queue (used when a
    caller wants a post from a specific pool -- the queue's contents were
    hand-picked by the user for the default track, not this one)."""
    if check_queue:
        queued = pick_queued_post()
        if queued:
            return queued

    history = load_history()
    used_ids = {h["id"] for h in history}
    subs = (subreddits or SUBREDDITS)[:]
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
            if (
                not post_id or post_id in used_ids
                or d.get("over_18") or d.get("stickied")
                or d.get("score", 0) < MIN_SCORE
            ):
                continue
            candidate = {
                "id": post_id,
                "subreddit": sub,
                "title": d.get("title", "").strip(),
                "selftext": d.get("selftext", ""),
                "score": d.get("score", 0),
                "permalink": f"https://reddit.com{d.get('permalink', '')}",
            }
            issues = validate_post(candidate)
            if issues:
                continue
            post = {**candidate, "selftext": _clean_selftext(candidate["selftext"])}
            history.append({
                "id": post_id, "subreddit": sub, "title": post["title"],
                "used_at": datetime.now(timezone.utc).isoformat(),
            })
            save_history(history)
            return post

    raise RuntimeError(
        f"No suitable unused Reddit post found today across {subs} "
        f"(need {MIN_STORY_CHARS}+ chars of real story, score >= {MIN_SCORE}, not NSFW/stickied/already-used)."
    )


if __name__ == "__main__":
    p = pick_post()
    print(json.dumps(p, indent=2))
