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
# Measured narration rate (Edge en-US-GuyNeural at -5%: 2.67 w/s). Used to
# budget narration length so long posts get condensed instead of failing QA
# after a full render.
NARRATION_WORDS_PER_SEC = float(_require("NARRATION_WORDS_PER_SEC", "2.65"))


def narration_word_budget(safety: float = 0.88) -> int:
    """Max narration words that should fit under VIDEO_MAX_SEC, with margin."""
    return int(VIDEO_MAX_SEC * NARRATION_WORDS_PER_SEC * safety)

REDDIT_CLIENT_ID = _require("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _require("REDDIT_CLIENT_SECRET")

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

for d in (ASSETS_DIR, OUTPUT_DIR, READY_DIR, LOGS_DIR, MODELS_DIR, MUSIC_DIR):
    d.mkdir(parents=True, exist_ok=True)


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
