#!/usr/bin/env python3
"""
Step 1 of the manual-TTS workflow: turn the next queued Reddit post into
narration text, split into app-sized chunks for pasting into TikTok's
built-in text-to-speech one at a time.

Writes output/tts_export_<run_id>/:
    01.txt, 02.txt, ...   chunks to paste, in order
    manifest.json         post + narration metadata for the import step

Usage:
    python3 export_narration_text.py                 # next queued post
    python3 export_narration_text.py --chars 180     # smaller chunks
"""
import argparse
import json
import re
from datetime import datetime, timezone

import config
from reddit_source import pick_post
from reddit_narration import generate_narration

DEFAULT_MAX_CHARS = 200


def split_for_tts(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list:
    """Split narration on sentence boundaries into chunks no longer than
    max_chars, so each chunk is a natural-sounding standalone utterance."""
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " ").strip())
    chunks = []
    current = ""
    for sentence in sentences:
        # A single sentence longer than the limit has to be broken on commas.
        while len(sentence) > max_chars:
            cut = sentence.rfind(",", 0, max_chars)
            cut = cut if cut > max_chars // 2 else sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            piece, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece)
        if not sentence:
            continue
        trial = f"{current} {sentence}".strip()
        if len(trial) <= max_chars:
            current = trial
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def main(max_chars: int):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    post = pick_post()
    print(f"r/{post['subreddit']}: {post['title']}")

    script = generate_narration(post)
    chunks = split_for_tts(script["narration"], max_chars)

    export_dir = config.OUTPUT_DIR / f"tts_export_{run_id}"
    export_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks, start=1):
        (export_dir / f"{i:02d}.txt").write_text(chunk, encoding="utf-8")

    (export_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "post": post, "script": script, "chunks": chunks}, indent=2),
        encoding="utf-8",
    )

    print(f"\n{len(chunks)} chunks written to {export_dir}")
    print("\nPaste each into TikTok's text-to-speech in order, export the audio,")
    print(f"and save the files as 01/02/03... into {export_dir / 'audio'}")
    print(f"Then run:  python3 import_narration_audio.py {export_dir.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chars", type=int, default=DEFAULT_MAX_CHARS,
                        help=f"max characters per chunk (default {DEFAULT_MAX_CHARS})")
    args = parser.parse_args()
    main(args.chars)
