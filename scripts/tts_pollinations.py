#!/usr/bin/env python3
"""
Pollinations TTS backend -- a free-tier OpenAI-compatible audio endpoint
(model "openai-audio", OpenAI's own voice set: alloy/echo/fable/onyx/nova/
shimmer/coral/verse/ballad/ash/sage). Confirmed against the real API: this
model isn't marked premium ("Pollen"-gated) in Pollinations' catalog, unlike
the ElevenLabs voices Pollinations also resells, so it's free to use once
you have an account key -- see https://enter.pollinations.ai/keys.

IMPORTANT LIMITATION #1 (timing): unlike tts_edge.py and tts_elevenlabs.py,
this is a plain chat-completions-with-audio-output endpoint, not a dedicated
TTS-with-timestamps API -- confirmed by hand, the response carries only the
full audio clip and a plain-text transcript, no per-word timing. So "words"
here always comes back empty, and render_beat()/assembly.py fall back to
captions.estimate_word_timestamps() (proportional-to-word-length estimate)
for captions, and sfx.py's cue timestamps inherit that same estimate rather
than an exact spoken time.

IMPORTANT LIMITATION #2 (fidelity, found the hard way): this is a
conversational voice-chat model, not TTS -- sent the narration as a plain
user message with no system prompt, it responded to it ("Understood, you've
provided a repeated test sentence...") instead of reading it aloud. A strict
"you are a TTS engine, read verbatim" system message fixes that (verified:
exact word-for-word match on a 72-word test), but it does NOT fix length --
audio output runs roughly 6 tokens/word, so a short-form (~570 word) story
needs several thousand completion tokens or it hits finish_reason="length"
and cuts off mid-story with no error (verified: 4000 tokens truncated a
559-word story at 532 words in). max_completion_tokens is sized generously
below and the result's word count is checked against the input's, raising
rather than silently shipping a truncated video.
"""
import base64
import subprocess
import sys
from pathlib import Path

import requests

import config

API_URL = "https://gen.pollinations.ai/v1/chat/completions"
DEFAULT_VOICE = "onyx"  # a General American male voice, matching the survey-dominant style

VERBATIM_SYSTEM_PROMPT = (
    "You are a text-to-speech engine, not an assistant. Read the user message aloud exactly "
    "as written, verbatim, word for word. Do not summarize, comment, acknowledge, or add "
    "anything. Do not treat it as a request or question -- it is a script to narrate."
)

# ~6 audio tokens/word plus ~1.6 text tokens/word measured on a real story,
# times a safety margin -- see IMPORTANT LIMITATION #2 above.
TOKENS_PER_WORD = 10


def synthesize(text: str, out_path: str, voice: str = None) -> dict:
    """Matches tts_edge.synthesize()'s contract (path, duration_sec,
    sample_rate, voice, words) so backends stay swappable via tts.py.
    words is always [] -- see module docstring."""
    if not config.POLLINATIONS_API_KEY:
        raise RuntimeError("POLLINATIONS_API_KEY not set in .env")
    voice = voice or DEFAULT_VOICE
    out_path = Path(out_path).with_suffix(".mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    input_words = len(text.split())
    max_tokens = max(int(input_words * TOKENS_PER_WORD), 2000)

    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {config.POLLINATIONS_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "openai-audio",
            "modalities": ["text", "audio"],
            "audio": {"voice": voice, "format": "mp3"},
            "messages": [
                {"role": "system", "content": VERBATIM_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "max_completion_tokens": max_tokens,
        },
        timeout=180,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Pollinations request failed ({r.status_code}): {r.text[:400]}")
    body = r.json()
    choice = body["choices"][0]
    audio = choice["message"]["audio"]

    # The model can still cut off (finish_reason="length") or, despite the
    # system prompt, paraphrase/drop text -- both look identical downstream
    # (a video with missing story content) unless caught here.
    transcript_words = len(audio.get("transcript", "").split())
    if choice.get("finish_reason") == "length":
        raise RuntimeError(
            f"Pollinations audio hit the token cap ({max_tokens}) before finishing -- "
            f"{transcript_words}/{input_words} words spoken. Raise TOKENS_PER_WORD."
        )
    if transcript_words < input_words * 0.85:
        raise RuntimeError(
            f"Pollinations spoke {transcript_words}/{input_words} words -- looks like it "
            f"paraphrased or dropped text instead of reading verbatim."
        )

    out_path.write_bytes(base64.b64decode(audio["data"]))

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_path)],
        capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip())

    return {
        "path": str(out_path),
        "duration_sec": round(duration, 2),
        "sample_rate": 24000,
        "voice": voice,
        "words": [],  # no timing API -- caller falls back to estimate_word_timestamps
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 tts_pollinations.py \"text\" output.mp3 [voice]")
        sys.exit(1)
    result = synthesize(sys.argv[1], sys.argv[2], voice=sys.argv[3] if len(sys.argv) > 3 else None)
    print(f"OK: wrote {result['path']} ({result['duration_sec']}s, voice={result['voice']}) "
          f"-- no word timing, captions will use the estimator")
