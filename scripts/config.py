#!/usr/bin/env python3
"""
Central config loader. Reads a .env file (in the project root) for all
secrets/settings so nothing sensitive lives in code or chat history.

Expected .env keys:
    LLM_BASE_URL          e.g. https://your-gateway.example.com/v1
    LLM_API_KEY           your gateway API key
    LLM_MODEL_SCRIPT      model name for cheap/fast narration cleanup, e.g. "gemini-flash" or a small qwen model
    LLM_MODEL_QA          model name for the QA/content-safety pass, e.g. "claude-sonnet" (whatever your gateway calls it)
    REDDIT_CLIENT_ID      optional -- from a free "script" app at https://www.reddit.com/prefs/apps.
    REDDIT_CLIENT_SECRET  Only needed as a fallback when Downloads/reddit-story-queue/ is empty;
                          see reddit_source.py.
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    pass


def _require(name: str, default=None):
    val = os.environ.get(name, default)
    return val


LLM_BASE_URL = _require("LLM_BASE_URL")
LLM_API_KEY = _require("LLM_API_KEY")
LLM_MODEL_SCRIPT = _require("LLM_MODEL_SCRIPT")
LLM_MODEL_QA = _require("LLM_MODEL_QA")

# Optional gateway-specific extra body params (e.g. disabling Gemini's default
# "thinking" mode, which otherwise eats the completion-token budget), as a JSON object.
_extra_body_raw = _require("LLM_EXTRA_BODY")
LLM_EXTRA_BODY = json.loads(_extra_body_raw) if _extra_body_raw else None

KOKORO_VOICE = _require("KOKORO_VOICE", "af_heart")

# Only used when TTS_BACKEND=elevenlabs (see tts_elevenlabs.py). Paid per
# character -- having a key set here does not switch the active backend.
ELEVENLABS_API_KEY = _require("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _require("ELEVENLABS_VOICE_ID")

# Which TTS backend narrates the video: "kokoro" (local ONNX) or "edge"
# (Microsoft neural voices -- more natural). See tts.py.
TTS_BACKEND = _require("TTS_BACKEND", "kokoro")
EDGE_VOICE = _require("EDGE_VOICE", "en-US-GuyNeural")
# edge-tts speaking-rate adjustment, e.g. "-8%" to slow delivery down.
EDGE_RATE = _require("EDGE_RATE", "+0%")

# Accepted finished-video length. The max is a platform decision, not a fixed
# truth -- YouTube Shorts/Reels cap at 180s, TikTok allows far longer.
VIDEO_MIN_SEC = float(_require("VIDEO_MIN_SEC", "15"))
VIDEO_MAX_SEC = float(_require("VIDEO_MAX_SEC", "180"))

# Long-form cap for content posted outside the Shorts/Reels slot (e.g. the
# Halloween nosleep-style track) -- run_pipeline.py's --length long uses this
# instead of VIDEO_MAX_SEC. A story that still overruns this gets split into
# multiple "Part N" videos (--split) rather than condensed, since condensing
# a long story down to a Short defeats the point of sourcing a long one.
VIDEO_MAX_SEC_LONG = float(_require("VIDEO_MAX_SEC_LONG", "600"))
# Rate used to budget the FIRST narration draft only. Scaled from the
# previous measurements (2.27-2.90 w/s at EDGE_RATE=-5%) by the actual
# measured speedup from moving EDGE_RATE to +50% (1.494x, timed directly --
# a fixed sentence ran 8.50s at +0% vs 5.69s at +50%, not assumed from the
# percentage). Kept at the slow end of that scaled range since dialogue-heavy
# scripts still pause more than flowing prose regardless of rate. The
# authority on length is still the synthesized audio, measured in
# run_pipeline._fit_narration before the render -- this constant only sizes
# the first draft so it doesn't come in reliably too short at the new rate.
NARRATION_WORDS_PER_SEC = float(_require("NARRATION_WORDS_PER_SEC", "3.60"))


def narration_word_budget(safety: float = 0.88, max_sec: float = None) -> int:
    """Max narration words that should fit under the given cap (default
    VIDEO_MAX_SEC), with margin."""
    return int((max_sec if max_sec is not None else VIDEO_MAX_SEC) * NARRATION_WORDS_PER_SEC * safety)

REDDIT_CLIENT_ID = _require("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _require("REDDIT_CLIENT_SECRET")

# Intro title card. The handle is the channel's own branding.
CARD_HANDLE = _require("CARD_HANDLE", "@RedditStories")
CARD_AVATAR = _require("CARD_AVATAR")          # path to an image; blank = flat placeholder
CARD_THEME = _require("CARD_THEME", "light")   # light | dark
CARD_EMOJI = _require("CARD_EMOJI", "")        # optional emoji row under the handle
CARD_SECONDS = float(_require("CARD_SECONDS", "6"))  # how long the card stays on screen

# Optional image-generation gateway for scripts/image_gen.py (thumbnail generation).
IMAGE_GATEWAY_API_KEY = _require("IMAGE_GATEWAY_API_KEY")
IMAGE_GATEWAY_BASE_URL = _require("IMAGE_GATEWAY_BASE_URL")
IMAGE_GATEWAY_MODEL = _require("IMAGE_GATEWAY_MODEL", "nano-banana-lite")

ASSETS_DIR = PROJECT_ROOT / "assets"
OUTPUT_DIR = PROJECT_ROOT / "output"
READY_DIR = PROJECT_ROOT / "output" / "ready_to_post"
LOGS_DIR = PROJECT_ROOT / "logs"
MODELS_DIR = PROJECT_ROOT / "models"

# Background video is bulky (hours of footage), so it can live off the system
# drive. MEDIA_ROOT holds gameplay/ and broll/; defaults to assets/ in-project.
MEDIA_ROOT = Path(_require("MEDIA_ROOT") or ASSETS_DIR)
GAMEPLAY_DIR = MEDIA_ROOT / "gameplay"
BROLL_DIR = MEDIA_ROOT / "broll"
MUSIC_DIR = ASSETS_DIR / "music"

# Background music is chosen to match the story's mood (see mood.py). Each
# mood has its own subfolder under assets/music/; anything left loose in
# assets/music/ is used as a mood-agnostic fallback.
MOODS = ("upbeat", "dramatic", "somber")

# Per-mood music level in the final mix. A somber bed under a quiet delivery
# needs less room than an upbeat one, or it fights the narration. Lowered
# 15% across the board (0.09/0.07/0.05 -> 0.0765/0.0595/0.0425) per request.
_DEFAULT_MUSIC_VOLUMES = {"upbeat": 0.0765, "dramatic": 0.0595, "somber": 0.0425}
_volumes_raw = _require("MUSIC_VOLUMES")
MUSIC_VOLUMES = {**_DEFAULT_MUSIC_VOLUMES, **(json.loads(_volumes_raw) if _volumes_raw else {})}
MUSIC_VOLUME_DEFAULT = float(_require("MUSIC_VOLUME_DEFAULT", "0.051"))  # also -15% (was 0.06)

# How often the broll/ library wins over gameplay/ when both have clips.
# 0.0 = always gameplay, 1.0 = always broll.
BROLL_MIX = float(_require("BROLL_MIX", "0.5"))

# Free key from pexels.com/api -- used by fetch_broll_pexels.py to stock the
# broll library with properly licensed, watermark-free footage.
PEXELS_API_KEY = _require("PEXELS_API_KEY")

for d in (ASSETS_DIR, OUTPUT_DIR, READY_DIR, LOGS_DIR, MODELS_DIR, MUSIC_DIR):
    d.mkdir(parents=True, exist_ok=True)
for _mood in MOODS:
    (MUSIC_DIR / _mood).mkdir(parents=True, exist_ok=True)


def missing_keys():
    """Return a list of required config values that are not yet set."""
    # REDDIT_CLIENT_ID/SECRET are deliberately not required here: the pipeline
    # can run entirely off Downloads/reddit-story-queue/ (see reddit_source.py)
    # and only needs Reddit API credentials as a fallback when that's empty.
    required = {
        "LLM_BASE_URL": LLM_BASE_URL,
        "LLM_API_KEY": LLM_API_KEY,
        "LLM_MODEL_SCRIPT": LLM_MODEL_SCRIPT,
        "LLM_MODEL_QA": LLM_MODEL_QA,
    }
    return [k for k, v in required.items() if not v]


if __name__ == "__main__":
    miss = missing_keys()
    if miss:
        print("Missing config values (set these in .env):", ", ".join(miss))
    else:
        print("All required config values are set.")
