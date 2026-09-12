#!/usr/bin/env python3
"""
End-to-end orchestrator for Reddit-story videos: real Reddit post -> cleaned
narration -> Kokoro voiceover + looped gameplay footage + burned captions ->
music -> QA -> drop into output/ready_to_post/.

Usage:
    python3 run_pipeline.py            # one video, pipeline picks the post
    python3 run_pipeline.py --batch 5  # 5 videos in a row
"""
import argparse
import json
import random
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import config
from reddit_source import pick_post
from reddit_narration import generate_narration
from gameplay_footage import pick_gameplay_clip
from assembly import render_beat, mix_music, probe_duration
from qa import run_qa

MUSIC_DIR = config.ASSETS_DIR / "music"


def pick_music_track() -> Path:
    tracks = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.aac")) + list(MUSIC_DIR.glob("*.wav"))
    if not tracks:
        raise RuntimeError(
            f"No background music found in {MUSIC_DIR}. Drop a few royalty-free tracks there first."
        )
    return random.choice(tracks)


def run_once() -> dict:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    work_dir = config.OUTPUT_DIR / f"work_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    log = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat()}

    try:
        post = pick_post()
        log["reddit_post"] = {"id": post["id"], "subreddit": post["subreddit"], "title": post["title"]}
        print(f"[{run_id}] r/{post['subreddit']}: {post['title']}")

        script = generate_narration(post)
        (work_dir / "script.json").write_text(json.dumps(script, indent=2))
        print(f"[{run_id}] Narration ready: {script.get('hook')}")

        gameplay_clip = pick_gameplay_clip()

        beat = {"voiceover": script["narration"]}
        beat_video_path = render_beat(beat, gameplay_clip, work_dir / "beats", 0)
        print(f"[{run_id}] Rendered")

        music_path = pick_music_track()
        final_path = work_dir / "final.mp4"
        mix_music(beat_video_path, music_path, final_path, music_volume=0.06)
        print(f"[{run_id}] Assembled: {final_path} ({probe_duration(final_path):.1f}s)")

        qa_result = run_qa(script, final_path)
        log["qa"] = qa_result
        print(f"[{run_id}] QA pass: {qa_result['pass']}")

        if qa_result["pass"]:
            safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in script.get("hook", post["title"]))[:60].strip()
            dest_video = config.READY_DIR / f"{run_id}_{safe_title}.mp4"
            dest_meta = config.READY_DIR / f"{run_id}_{safe_title}.txt"
            shutil.copy(final_path, dest_video)
            dest_meta.write_text(
                f"Hook: {script.get('hook')}\n\n"
                f"Caption: {script.get('caption')}\n\n"
                f"Hashtags: {' '.join(script.get('hashtags', []))}\n\n"
                f"Source: {post.get('permalink')}\n"
            )
            log["status"] = "ready"
            log["output"] = str(dest_video)
            print(f"[{run_id}] READY: {dest_video}")
        else:
            log["status"] = "failed_qa"
            print(f"[{run_id}] FAILED QA: {qa_result}")

    except Exception as e:
        log["status"] = "error"
        log["error"] = str(e)
        log["traceback"] = traceback.format_exc()
        print(f"[{run_id}] ERROR: {e}", file=sys.stderr)

    log["finished_at"] = datetime.now(timezone.utc).isoformat()
    log_path = config.LOGS_DIR / f"run_{run_id}.json"
    log_path.write_text(json.dumps(log, indent=2))
    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1)
    args = parser.parse_args()

    missing = config.missing_keys()
    if missing:
        print("Missing required config in .env:", ", ".join(missing))
        sys.exit(1)

    for _ in range(args.batch):
        run_once()
