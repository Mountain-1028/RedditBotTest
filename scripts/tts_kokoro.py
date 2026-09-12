#!/usr/bin/env python3
"""
Kokoro TTS wrapper for the faceless recipe-video pipeline.

Usage:
    python3 tts_kokoro.py "Text to narrate" output.wav [voice]

Default voice: af_heart (American English, female) -- swap via the
KOKORO_VOICE env var or the third CLI arg. Run list_voices() to see options.
"""
import sys
import os

MODEL_PATH = os.environ.get(
    "KOKORO_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "kokoro-v1.0.onnx"),
)
VOICES_PATH = os.environ.get(
    "KOKORO_VOICES_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "voices-v1.0.bin"),
)
DEFAULT_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
DEFAULT_SPEED = float(os.environ.get("KOKORO_SPEED", "1.0"))


def get_kokoro():
    from kokoro_onnx import Kokoro
    return Kokoro(MODEL_PATH, VOICES_PATH)


def synthesize(text: str, out_path: str, voice: str = DEFAULT_VOICE, speed: float = DEFAULT_SPEED):
    import soundfile as sf
    kokoro = get_kokoro()
    samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    sf.write(out_path, samples, sample_rate)
    duration = len(samples) / sample_rate
    return {"path": out_path, "duration_sec": round(duration, 2), "sample_rate": sample_rate, "voice": voice}


def list_voices():
    kokoro = get_kokoro()
    return sorted(kokoro.voices.keys()) if hasattr(kokoro, "voices") else []


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 tts_kokoro.py \"text\" output.wav [voice]")
        sys.exit(1)
    text = sys.argv[1]
    out_path = sys.argv[2]
    voice = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VOICE
    result = synthesize(text, out_path, voice=voice)
    print(f"OK: wrote {result['path']} ({result['duration_sec']}s, {result['sample_rate']}Hz, voice={result['voice']})")
