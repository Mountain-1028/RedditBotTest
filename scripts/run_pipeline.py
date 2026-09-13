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
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import config
from reddit_source import pick_post
from reddit_narration import generate_narration
from gameplay_footage import pick_gameplay_clip
from reddit_card import generate_card_frames
from assembly import render_beat, mix_music, probe_duration
from mood import classify
from music import pick_track, volume_for
from qa import run_qa


def produce_video(post: dict, script: dict, run_id: str = None, audio_override: Path = None) -> dict:
    """Everything after the narration text exists: footage, card, render, music,
    QA, and the drop into ready_to_post. audio_override uses a ready-made
    narration track instead of synthesizing one (see import_narration_audio.py)."""
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    work_dir = config.OUTPUT_DIR / f"work_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    log = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat()}
    log["reddit_post"] = {"id": post["id"], "subreddit": post["subreddit"], "title": post["title"]}

    try:
        (work_dir / "script.json").write_text(json.dumps(script, indent=2))
        words = len(script["narration"].split())
        est_sec = words / config.NARRATION_WORDS_PER_SEC
        print(f"[{run_id}] Narration ready: {script.get('hook')} ({words} words, ~{est_sec:.0f}s)")
        if est_sec > config.VIDEO_MAX_SEC:
            print(f"[{run_id}] WARNING: ~{est_sec:.0f}s exceeds VIDEO_MAX_SEC={config.VIDEO_MAX_SEC:.0f}s; "
                  "this will fail QA on duration.")

        # Decided before the render so the run log records the mood even if a
        # later stage fails, and so a missing-music error surfaces in seconds
        # rather than after a full encode.
        story_mood = classify(script)
        track = pick_track(story_mood["mood"])
        log["mood"] = {**story_mood, "track": track["path"].name, "matched_folder": track["matched"]}
        note = "" if track["matched"] else "  (fallback -- no tracks in that mood folder)"
        print(f"[{run_id}] Mood: {story_mood['mood']} ({story_mood['source']}) "
              f"-> {track['path'].name}{note}")
        if story_mood.get("why"):
            print(f"[{run_id}]   {story_mood['why']}")

        gameplay_clip, gameplay_start = pick_gameplay_clip()

        card_post = {"title": script.get("hook") or post["title"]}
        card_frames = generate_card_frames(card_post, work_dir / "card_frames")

        beat = {"voiceover": script["narration"]}
        beat_video_path = render_beat(
            beat, gameplay_clip, work_dir / "beats", 0, card_frames=card_frames,
            visual_start=gameplay_start, audio_override=audio_override,
        )
        print(f"[{run_id}] Rendered")

        final_path = work_dir / "final.mp4"
        mix_music(beat_video_path, track["path"], final_path,
                  music_volume=volume_for(story_mood["mood"]))
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
                f"Mood: {story_mood['mood']} ({story_mood['source']}) - music: {track['path'].name}\n\n"
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


def run_once() -> dict:
    """Fully automatic: pick a post, generate narration, synthesize with Kokoro."""
    post = pick_post()
    print(f"r/{post['subreddit']}: {post['title']}")
    script = generate_narration(post)
    return produce_video(post, script)


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
