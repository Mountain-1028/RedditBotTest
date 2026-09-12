#!/usr/bin/env python3
"""
Word-level timing for burned captions.

Originally used faster-whisper for forced alignment, but this environment's
network policy blocks huggingface.co (where its models are hosted), and more
importantly: a pip-installed alignment model is one more thing that can fail
on whatever machine actually runs this pipeline long-term. Since we already
know the exact text fed to Kokoro and its total duration, we estimate
per-word timing by distributing the duration proportionally to word length
(with a small minimum per word) -- this tracks TTS pacing closely enough for
short punchy captions and has zero external dependencies.
"""
import re
import sys


def estimate_word_timestamps(text: str, duration_sec: float, min_word_sec: float = 0.12):
    """Return [{"word": str, "start": float, "end": float}, ...] spanning 0..duration_sec."""
    words = re.findall(r"\S+", text)
    if not words:
        return []

    weights = [max(len(w), 3) for w in words]  # floor so short words still get a fair slice
    total_weight = sum(weights)

    # first pass: proportional durations, floored at min_word_sec
    raw_durations = [max(min_word_sec, duration_sec * w / total_weight) for w in weights]
    scale = duration_sec / sum(raw_durations)  # renormalize so it still sums to duration_sec
    durations = [d * scale for d in raw_durations]

    out = []
    t = 0.0
    for word, d in zip(words, durations):
        out.append({"word": word, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "This is a short test sentence for timing."
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    for w in estimate_word_timestamps(text, dur):
        print(f"{w['start']:.2f}-{w['end']:.2f}  {w['word']}")
