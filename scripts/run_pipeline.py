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
from reddit_narration import generate_narration, condense_narration
from tts import synthesize
from gameplay_footage import pick_gameplay_clip
from reddit_card import generate_card_frames
from assembly import render_beat, mix_music, probe_duration
from mood import classify
from music import pick_track, volume_for, credit_for
from qa import run_qa


def _fit_narration(script: dict, work_dir: Path, run_id: str, attempts: int = 2) -> dict:
    """Synthesize the narration and, if it overruns VIDEO_MAX_SEC, condense and
    re-synthesize until it fits.

    Estimating length from a words-per-second constant does not work: measured
    across two real scripts the same voice ran at 2.90 w/s for flowing prose
    and 2.27 w/s for a dialogue-heavy story, because every line break becomes a
    spoken pause. The estimate is still used to budget the first draft, but
    only the synthesized audio settles it -- and checking here, before the
    encode, is what stops an over-length script being discovered by QA after a
    full render has already been paid for."""
    cap = config.VIDEO_MAX_SEC
    info = synthesize(script["narration"], str(work_dir / "narration.mp3"))

    for attempt in range(attempts + 1):
        words = len(script["narration"].split())
        rate = words / info["duration_sec"] if info["duration_sec"] else config.NARRATION_WORDS_PER_SEC
        print(f"[{run_id}] Narration audio: {info['duration_sec']:.1f}s "
              f"({words} words, {rate:.2f} w/s)")
        if info["duration_sec"] <= cap:
            return info
        if attempt == attempts:
            break

        # Target from THIS script's measured rate, with margin for the pauses
        # that re-editing will not remove.
        target = int(cap * rate * 0.90)
        print(f"[{run_id}] Over the {cap:.0f}s cap -- condensing to ~{target} words "
              f"(attempt {attempt + 1}/{attempts})")
        shorter = condense_narration(script["narration"], target)
        if shorter == script["narration"]:
            print(f"[{run_id}] Narration unchanged; giving up on condensing")
            break
        script["narration"] = shorter
        info = synthesize(script["narration"], str(work_dir / f"narration_fit{attempt}.mp3"))

    print(f"[{run_id}] Still {info['duration_sec']:.1f}s, over the {cap:.0f}s cap; "
          f"rendering anyway (QA will flag it)")
    return info


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
        print(f"[{run_id}] Narration ready: {script.get('hook')} ({words} words)")

        # Synthesize before anything expensive: the audio's real length decides
        # whether the script fits, and condensing here costs seconds where
        # discovering it at QA costs the whole encode.
        tts_info = None
        if not audio_override:
            tts_info = _fit_narration(script, work_dir, run_id)
            (work_dir / "script.json").write_text(json.dumps(script, indent=2))

        # Decided before the render so the run log records the mood even if a
        # later stage fails, and so a missing-music error surfaces in seconds
        # rather than after a full encode.
        story_mood = classify(script)
        track = pick_track(story_mood["mood"])
        music_credit = credit_for(track["path"])
        log["mood"] = {**story_mood, "track": track["path"].name,
                       "matched_folder": track["matched"], "music_credit": music_credit}
        note = "" if track["matched"] else "  (fallback -- no tracks in that mood folder)"
        print(f"[{run_id}] Mood: {story_mood['mood']} ({story_mood['source']}) "
              f"-> {track['path'].name}{note}")
        if story_mood.get("why"):
            print(f"[{run_id}]   {story_mood['why']}")

        gameplay_clip, gameplay_start = pick_gameplay_clip()

        # score feeds the card's engagement footer (see reddit_card
        # ._engagement_numbers) so it reflects the post's real upvotes
        # instead of a flat placeholder.
        card_post = {"title": script.get("hook") or post["title"], "score": post.get("score")}
        card_frames = generate_card_frames(card_post, work_dir / "card_frames")

        beat = {"voiceover": script["narration"]}
        beat_video_path = render_beat(
            beat, gameplay_clip, work_dir / "beats", 0, card_frames=card_frames,
            visual_start=gameplay_start, audio_override=audio_override, tts_info=tts_info,
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
                # CC BY obliges this to appear in the upload description.
                f"{('MUSIC CREDIT (must go in the description): ' + music_credit + chr(10) + chr(10)) if music_credit else ''}"
                f"Source: {post.get('permalink')}\n",
                # Explicit UTF-8: Windows would otherwise write this in the
                # system codepage and mangle accented artist names in the
                # credit line -- which then gets pasted into a description.
                encoding="utf-8",
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
