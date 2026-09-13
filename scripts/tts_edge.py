#!/usr/bin/env python3
"""
Edge TTS backend -- Microsoft's neural voices via the edge-tts library.
Noticeably more natural/expressive than Kokoro, and unlike TikTok's in-app
voices this is a documented, openly-used interface rather than a private
endpoint.

Usage:
    python3 tts_edge.py "Text to narrate" output.mp3 [voice]

Default voice comes from EDGE_VOICE in .env (see config.py).
"""
import asyncio
import subprocess
import sys
from pathlib import Path

import edge_tts

import config


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


# 100-nanosecond ticks per second, the unit edge-tts reports offsets in
TICKS_PER_SEC = 10_000_000


def synthesize(text: str, out_path: str, voice: str = None, rate: str = None) -> dict:
    """Matches tts_kokoro.synthesize()'s contract so the two are swappable.
    rate is an edge-tts percentage string like "-8%" to slow delivery down.

    Also returns "words": exact per-word timings reported by the synthesiser.
    Captions built from these stay locked to the audio, where timings estimated
    from word length drift badly over a long narration."""
    voice = voice or config.EDGE_VOICE
    rate = rate or config.EDGE_RATE

    # edge-tts emits mp3; don't let a .wav-named file hold mp3 bytes.
    out_path = Path(out_path).with_suffix(".mp3")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        words = []
        with open(out_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / TICKS_PER_SEC
                    words.append({
                        "word": chunk["text"],
                        "start": round(start, 3),
                        "end": round(start + chunk["duration"] / TICKS_PER_SEC, 3),
                    })
        return words

    words = asyncio.run(_run())

    duration = _probe_duration(out_path)
    return {
        "path": str(out_path),
        "duration_sec": round(duration, 2),
        "sample_rate": 24000,
        "voice": voice,
        "words": words,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 tts_edge.py \"text\" output.mp3 [voice]")
        sys.exit(1)
    result = synthesize(sys.argv[1], sys.argv[2], voice=sys.argv[3] if len(sys.argv) > 3 else None)
    print(f"OK: wrote {result['path']} ({result['duration_sec']}s, voice={result['voice']})")
