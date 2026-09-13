#!/usr/bin/env python3
"""
ElevenLabs TTS backend -- what the voice survey (see analyze_voice.py) found
most competing Reddit-story channels actually use. Paid per character (the
account behind ELEVENLABS_API_KEY is on the free tier: 10,000 chars/month,
no payment method attached -- roughly 3-4 short-form videos' worth); this
backend is NOT the active one (see TTS_BACKEND in .env) until that's a
deliberate choice.

Usage:
    python3 tts_elevenlabs.py "Text to narrate" output.mp3 [voice_id]
"""
import sys
from pathlib import Path

import requests

import config

API_BASE = "https://api.elevenlabs.io/v1"
# "Roger" -- a premade ElevenLabs voice (Laid-Back, Casual, Resonant,
# American, male): a reasonable narration default matching the General
# American accent the voice survey found dominant in this niche. Only used
# when ELEVENLABS_VOICE_ID isn't set in .env.
DEFAULT_VOICE_ID = "CwhRBWXzGAHq8TQ4Fs17"
MODEL_ID = "eleven_multilingual_v2"


def _headers():
    if not config.ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set in .env")
    return {"xi-api-key": config.ELEVENLABS_API_KEY, "Content-Type": "application/json"}


def synthesize(text: str, out_path: str, voice_id: str = None) -> dict:
    """Matches tts_edge.synthesize()'s contract (path, duration_sec,
    sample_rate, voice, words) so backends stay swappable via tts.py.

    Uses the with-timestamps endpoint (character-level alignment) rather
    than plain /text-to-speech, and aggregates characters into words --
    captions.py and sfx.py both need real per-word timing, the same reason
    tts_edge.py captures WordBoundary events instead of estimating."""
    voice_id = voice_id or config.ELEVENLABS_VOICE_ID or DEFAULT_VOICE_ID
    out_path = Path(out_path).with_suffix(".mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    r = requests.post(
        f"{API_BASE}/text-to-speech/{voice_id}/with-timestamps",
        headers=_headers(),
        json={"text": text, "model_id": MODEL_ID},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs request failed ({r.status_code}): {r.text[:400]}")
    data = r.json()

    import base64
    out_path.write_bytes(base64.b64decode(data["audio_base64"]))

    words = _chars_to_words(data.get("alignment") or {}, text)

    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_path)],
        capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip())

    return {
        "path": str(out_path),
        "duration_sec": round(duration, 2),
        "sample_rate": 44100,
        "voice": voice_id,
        "words": words,
    }


def _chars_to_words(alignment: dict, original_text: str) -> list[dict]:
    """ElevenLabs reports per-character start/end times; group consecutive
    non-whitespace characters into words the same way tts_edge's
    WordBoundary events already arrive shaped, so captions.py/sfx.py don't
    need to know which backend produced the audio."""
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not (chars and len(chars) == len(starts) == len(ends)):
        return []

    words, buf_chars, buf_start = [], [], None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if buf_chars:
                words.append({"word": "".join(buf_chars), "start": round(buf_start, 3), "end": round(prev_end, 3)})
                buf_chars, buf_start = [], None
            continue
        if buf_start is None:
            buf_start = s
        buf_chars.append(ch)
        prev_end = e
    if buf_chars:
        words.append({"word": "".join(buf_chars), "start": round(buf_start, 3), "end": round(prev_end, 3)})
    return words


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 tts_elevenlabs.py \"text\" output.mp3 [voice_id]")
        sys.exit(1)
    result = synthesize(sys.argv[1], sys.argv[2], voice_id=sys.argv[3] if len(sys.argv) > 3 else None)
    print(f"OK: wrote {result['path']} ({result['duration_sec']}s, voice={result['voice']}, "
          f"{len(result['words'])} words timed)")
