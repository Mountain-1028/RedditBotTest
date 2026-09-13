#!/usr/bin/env python3
"""
Picks the TTS backend based on TTS_BACKEND in .env:

    kokoro      -- local ONNX model, no network, flatter delivery (default)
    edge        -- Microsoft neural voices via edge-tts, more natural
    elevenlabs  -- paid per character; see tts_elevenlabs.py for why it's not
                   the default despite being what most competing channels use

All backends return the same dict shape, so callers don't care which ran:
    {"path", "duration_sec", "sample_rate", "voice", "words"}
"""
import config


def synthesize(text: str, out_path: str) -> dict:
    backend = (config.TTS_BACKEND or "kokoro").lower()
    if backend == "edge":
        from tts_edge import synthesize as _edge
        return _edge(text, out_path)
    if backend == "elevenlabs":
        from tts_elevenlabs import synthesize as _elevenlabs
        return _elevenlabs(text, out_path)
    if backend == "kokoro":
        from tts_kokoro import synthesize as _kokoro
        result = _kokoro(text, out_path)
        result.setdefault("path", out_path)
        return result
    raise ValueError(f"Unknown TTS_BACKEND {backend!r} -- expected 'kokoro', 'edge', or 'elevenlabs'")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 tts.py \"text\" output_path")
        sys.exit(1)
    info = synthesize(sys.argv[1], sys.argv[2])
    print(f"OK ({config.TTS_BACKEND}): {info['path']} ({info['duration_sec']}s, voice={info['voice']})")
