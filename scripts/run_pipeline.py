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
from reddit_source import pick_post, HORROR_SUBREDDITS
from reddit_narration import generate_narration, condense_narration, grammar_check, split_narration_into_parts
from fiction_story import generate_fiction
from tts import synthesize
from gameplay_footage import pick_gameplay_clip
from reddit_card import generate_card_frames
from assembly import render_beat, mix_music, probe_duration
from mood import classify
from music import pick_track, volume_for, credit_for
from qa import run_qa
from sfx import detect_cues


def _fit_narration(script: dict, work_dir: Path, run_id: str, max_sec: float = None, attempts: int = 2) -> dict:
    """Synthesize the narration and, if it overruns VIDEO_MAX_SEC, condense and
    re-synthesize until it fits.

    Estimating length from a words-per-second constant does not work: measured
    across two real scripts the same voice ran at 2.90 w/s for flowing prose
    and 2.27 w/s for a dialogue-heavy story, because every line break becomes a
    spoken pause. The estimate is still used to budget the first draft, but
    only the synthesized audio settles it -- and checking here, before the
    encode, is what stops an over-length script being discovered by QA after a
    full render has already been paid for."""
    cap = max_sec if max_sec is not None else config.VIDEO_MAX_SEC
    info = synthesize(script["narration"], str(work_dir / "narration.mp3"))
    fits = False

    for attempt in range(attempts + 1):
        words = len(script["narration"].split())
        rate = words / info["duration_sec"] if info["duration_sec"] else config.NARRATION_WORDS_PER_SEC
        print(f"[{run_id}] Narration audio: {info['duration_sec']:.1f}s "
              f"({words} words, {rate:.2f} w/s)")
        if info["duration_sec"] <= cap:
            fits = True
            break
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

    if not fits:
        print(f"[{run_id}] Still {info['duration_sec']:.1f}s, over the {cap:.0f}s cap; "
              f"rendering anyway (QA will flag it)")

    # Proofread the text that's actually going to be recorded -- run last,
    # after any condensing, since condensing is its own LLM call and can
    # introduce a grammar slip that the original draft didn't have. Any
    # correction changes the words, so the audio has to be re-recorded or the
    # captions (built from this synthesis's word timings) would show text
    # that doesn't match what's spoken.
    check = grammar_check(script["narration"])
    if check["corrections"]:
        print(f"[{run_id}] Grammar check: {len(check['corrections'])} fix(es) -- "
              + "; ".join(check["corrections"][:4]))
    if check["changed"]:
        script["narration"] = check["text"]
        info = synthesize(script["narration"], str(work_dir / "narration_final.mp3"))
        print(f"[{run_id}] Re-recorded after grammar fixes: {info['duration_sec']:.1f}s")
    info["grammar"] = {"corrections": check["corrections"], "changed": check["changed"]}
    return info


def produce_video(post: dict, script: dict, run_id: str = None, audio_override: Path = None,
                   max_sec: float = None, apply_sfx: bool = False) -> dict:
    """Everything after the narration text exists: footage, card, render, music,
    QA, and the drop into ready_to_post. audio_override uses a ready-made
    narration track instead of synthesizing one (see import_narration_audio.py).
    max_sec overrides config.VIDEO_MAX_SEC (used for the long-form/Halloween
    track and by run_series() when rendering an already-split part).

    apply_sfx layers onomatopoeia sound effects (see sfx.py) into the mix at
    their exact spoken timestamp. Only ever set True for AI-authored fiction
    (source="fiction") -- a real pulled Reddit post is someone else's actual
    account of something that happened to them, and sweetening it with sound
    effects isn't this pipeline's call to make. Silently a no-op if there's
    no audio_override-free tts_info to find word timings in."""
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
            tts_info = _fit_narration(script, work_dir, run_id, max_sec=max_sec)
            log["grammar_check"] = tts_info.get("grammar")
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

        sfx_cues = []
        if apply_sfx and tts_info and tts_info.get("words"):
            sfx_cues = detect_cues(tts_info["words"])
            if sfx_cues:
                print(f"[{run_id}] SFX: {len(sfx_cues)} cue(s) -- "
                      + ", ".join(f"{c['category']}@{c['start']:.1f}s" for c in sfx_cues))
        log["sfx_cues"] = [{"category": c["category"], "word": c["word"], "start": c["start"]} for c in sfx_cues]

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
                  music_volume=volume_for(story_mood["mood"]), sfx_cues=sfx_cues)
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


def _get_post_and_script(source: str, max_sec: float) -> tuple[dict, dict]:
    if source == "fiction":
        return generate_fiction(max_sec=max_sec)
    subs = HORROR_SUBREDDITS if source == "horror" else None
    # The manual queue is for posts the user hand-picked for the default
    # track -- a --source horror run shouldn't silently consume it.
    post = pick_post(subreddits=subs, check_queue=(source == "reddit"))
    print(f"r/{post['subreddit']}: {post['title']}")
    script = generate_narration(post, max_sec=max_sec)
    return post, script


def run_series(source: str = "reddit", length: str = "short", split: bool = False) -> list[dict]:
    """One story -> one or more rendered videos.

    length="long" raises the cap to config.VIDEO_MAX_SEC_LONG. If the story
    still doesn't fit that cap: split=True breaks it into a "Part N/M" series
    (each part its own produce_video() call, same cap, sharing a run_id
    prefix) instead of condensing, since condensing a long story down to fit
    defeats the reason to have picked a long one. split=False falls back to
    the normal condense-to-fit behavior in _fit_narration.
    """
    max_sec = config.VIDEO_MAX_SEC_LONG if length == "long" else config.VIDEO_MAX_SEC
    # generate_narration/generate_fiction condense/cap to whatever budget
    # they're given -- if split is on, generate against a generous ceiling
    # instead of max_sec, so a naturally long story survives intact for the
    # split below to divide. Without this, generation would condense the
    # story down to one part's worth of words before split ever saw it.
    gen_max_sec = max(max_sec * 6, 3600) if split else max_sec
    post, script = _get_post_and_script(source, gen_max_sec)
    # SFX only ever touch stories this pipeline itself authored -- see
    # produce_video's apply_sfx docstring.
    apply_sfx = (source == "fiction")

    if not split:
        return [produce_video(post, script, max_sec=max_sec, apply_sfx=apply_sfx)]

    budget = config.narration_word_budget(max_sec=max_sec)
    if len(script["narration"].split()) <= budget:
        return [produce_video(post, script, max_sec=max_sec, apply_sfx=apply_sfx)]

    parts = split_narration_into_parts(script["narration"], budget)
    print(f"Story runs {len(script['narration'].split())} words, over the {budget}-word "
          f"({max_sec:.0f}s) cap -- splitting into {len(parts)} parts")

    base_run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = []
    for i, part_text in enumerate(parts, 1):
        part_script = {
            **script,
            "narration": part_text,
            "hook": f"{script['hook']} (Part {i}/{len(parts)})",
            "caption": f"{script['caption']} (Part {i} of {len(parts)}{' -- follow for the rest' if i < len(parts) else ''})",
        }
        results.append(produce_video(post, part_script, run_id=f"{base_run_id}_part{i}",
                                      max_sec=max_sec, apply_sfx=apply_sfx))
    return results


def run_once() -> dict:
    """Fully automatic: pick a post, generate narration, synthesize with Kokoro.
    Kept for backward compatibility -- equivalent to run_series()[0]."""
    return run_series()[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--source", choices=["reddit", "horror", "fiction"], default="reddit",
                         help="reddit = default subreddit pool; horror = real nosleep-style "
                              "subreddits (Halloween); fiction = AI-original horror story")
    parser.add_argument("--length", choices=["short", "long"], default="short",
                         help="short = VIDEO_MAX_SEC (Shorts/Reels); long = VIDEO_MAX_SEC_LONG")
    parser.add_argument("--split", action="store_true",
                         help="if the story overruns the length cap, split into a Part N/M "
                              "series instead of condensing it down to fit")
    args = parser.parse_args()

    missing = config.missing_keys()
    if missing:
        print("Missing required config in .env:", ", ".join(missing))
        sys.exit(1)

    for _ in range(args.batch):
        run_series(source=args.source, length=args.length, split=args.split)
