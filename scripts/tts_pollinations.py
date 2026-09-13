#!/usr/bin/env python3
"""
Pollinations TTS backend -- a free-tier OpenAI-compatible audio endpoint
(model "openai-audio", OpenAI's own voice set: alloy/echo/fable/onyx/nova/
shimmer/coral/verse/ballad/ash/sage). Confirmed against the real API: this
model isn't marked premium ("Pollen"-gated) in Pollinations' catalog, unlike
the ElevenLabs voices Pollinations also resells, so it's free to use once
you have an account key -- see https://enter.pollinations.ai/keys.

IMPORTANT LIMITATION: unlike tts_edge.py and tts_elevenlabs.py, this is a
plain chat-completions-with-audio-output endpoint, not a dedicated
TTS-with-timestamps API -- confirmed by hand, the response carries only the
full audio clip and a plain-text transcript, no per-word timing. So "words"
here always comes back empty, and render_beat()/assembly.py fall back to
captions.estimate_word_timestamps() (proportional-to-word-length estimate)
for captions, and sfx.py's cue timestamps inherit that same estimate rather
than an exact spoken time. Good enough for captions; SFX cues placed against
an estimate will drift more than with a timestamp-native backend.
"""
import base64
import subprocess
import sys
from pathlib import Path

import requests

import config

API_URL = "https://gen.pollinations.ai/v1/chat/completions"
DEFAULT_VOICE = "onyx"  # a General American male voice, matching the survey-dominant style


def synthesize(text: str, out_path: str, voice: str = None) -> dict:
    """Matches tts_edge.synthesize()'s contract (path, duration_sec,
    sample_rate, voice, words) so backends stay swappable via tts.py.
    words is always [] -- see module docstring."""
    if not config.POLLINATIONS_API_KEY:
        raise RuntimeError("POLLINATIONS_API_KEY not set in .env")
    voice = voice or DEFAULT_VOICE
    out_path = Path(out_path).with_suffix(".mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {config.POLLINATIONS_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "openai-audio",
            "modalities": ["text", "audio"],
            "audio": {"voice": voice, "format": "mp3"},
            "messages": [{"role": "user", "content": text}],
        },
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Pollinations request failed ({r.status_code}): {r.text[:400]}")
    audio = r.json()["choices"][0]["message"]["audio"]
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
