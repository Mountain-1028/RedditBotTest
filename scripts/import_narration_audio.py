#!/usr/bin/env python3
"""
Step 2 of the manual-TTS workflow: take the audio you exported from TikTok's
in-app text-to-speech, stitch the chunks back into one narration track, and
run the rest of the pipeline (footage, card, captions, music, QA).

Expects the export folder made by export_narration_text.py, with your
exported audio saved into its audio/ subfolder, named to match the chunk
numbers (01.*, 02.*, ...). Any common audio/video container works -- the
audio stream is extracted either way.

Usage:
    python3 import_narration_audio.py tts_export_20260912_183000
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import config
from run_pipeline import produce_video

AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".mp4", ".mov", ".webm", ".opus", ".ogg")


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\ncmd: {' '.join(cmd)}\nstderr:\n{result.stderr[-3000:]}")
    return result


def collect_chunk_files(audio_dir: Path) -> list:
    """Return audio files sorted by their leading chunk number, so 10 sorts
    after 9 rather than after 1."""
    files = [p for p in audio_dir.iterdir() if p.suffix.lower() in AUDIO_EXTS]
    numbered = []
    for p in files:
        m = re.match(r"(\d+)", p.stem)
        if m:
            numbered.append((int(m.group(1)), p))
    numbered.sort(key=lambda t: t[0])
    return [p for _, p in numbered]


def concat_audio(files: list, out_path: Path) -> Path:
    """Normalize each chunk to a common format, then concatenate. Chunks come
    from separate exports so sample rates/codecs can differ between them."""
    tmp_dir = out_path.parent / "_chunks"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    normalized = []
    for i, f in enumerate(files):
        norm = tmp_dir / f"{i:03d}.wav"
        _run(["ffmpeg", "-y", "-i", str(f), "-vn", "-ac", "1", "-ar", "24000", str(norm)])
        normalized.append(norm)

    list_file = tmp_dir / "concat_list.txt"
    list_file.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in normalized), encoding="utf-8")

    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)])
    return out_path


def main(export_name: str):
    export_dir = config.OUTPUT_DIR / export_name
    if not export_dir.exists():
        sys.exit(f"No such export folder: {export_dir}")

    manifest_path = export_dir / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"Missing manifest.json in {export_dir} -- was this made by export_narration_text.py?")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    audio_dir = export_dir / "audio"
    if not audio_dir.exists():
        sys.exit(f"No audio/ folder in {export_dir}. Save your exported clips there as 01.*, 02.*, ...")

    files = collect_chunk_files(audio_dir)
    if not files:
        sys.exit(f"No numbered audio files found in {audio_dir}")

    expected = len(manifest.get("chunks", []))
    print(f"Found {len(files)} audio chunks (expected {expected})")
    if expected and len(files) != expected:
        print("WARNING: count mismatch -- the narration will be missing or duplicating text.")

    narration_path = concat_audio(files, export_dir / "narration.wav")
    print(f"Stitched narration: {narration_path}")

    produce_video(
        manifest["post"], manifest["script"],
        run_id=manifest.get("run_id"), audio_override=narration_path,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("export_name", help="folder name under output/, e.g. tts_export_20260912_183000")
    args = parser.parse_args()
    main(args.export_name)
