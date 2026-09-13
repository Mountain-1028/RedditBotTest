#!/usr/bin/env python3
"""
Quarantine background clips that carry someone else's watermark, logo, handle
or burned-in text overlay.

Aggregated compilations are usually other creators' clips with their branding
still on them. Those markings sit anywhere in the frame -- often dead centre --
so cropping can't remove them; the clip has to be dropped. A vision model does
the judging, since the markings vary in language, position and style.

Flagged clips move to <library>/rejected/ rather than being deleted.

Usage:
    python3 filter_watermarked.py                       # the broll library
    python3 filter_watermarked.py --dir F:/.../gameplay
    python3 filter_watermarked.py --sample 30           # spot-check only
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import requests

import config
from image_to_text import _as_data_url, _headers

PROMPT = (
    "Does this video frame contain any watermark, platform logo, username/handle, "
    "or burned-in text overlay? Ignore ordinary objects and packaging. "
    "Answer with exactly one word: YES or NO."
)
FRAME_AT = 25  # seconds into the clip; past any lead-in


def _frame(clip: Path, out: Path) -> bool:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(FRAME_AT), "-i", str(clip), "-frames:v", "1",
         "-vf", "scale=420:-1", str(out)],
        capture_output=True,
    )
    if not out.exists() or out.stat().st_size == 0:
        # clip may be shorter than FRAME_AT -- fall back to its first frame
        subprocess.run(["ffmpeg", "-y", "-i", str(clip), "-frames:v", "1",
                        "-vf", "scale=420:-1", str(out)], capture_output=True)
    return out.exists() and out.stat().st_size > 0


def has_marking(img: Path, timeout: int = 90) -> bool:
    payload = {
        "model": config.LLM_MODEL_SCRIPT,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": _as_data_url(img.read_bytes(), "image/jpeg")}},
        ]}],
        "max_tokens": 200,
    }
    if config.LLM_EXTRA_BODY:
        payload.update(config.LLM_EXTRA_BODY)
    r = requests.post(f"{config.LLM_BASE_URL}/chat/completions",
                      headers=_headers(), json=payload, timeout=timeout)
    r.raise_for_status()
    text = (r.json()["choices"][0]["message"].get("content") or "").strip().upper()
    # Unparseable answers are treated as clean: better to keep a questionable
    # clip than to bin the library on a flaky response.
    return "YES" in text and "NO" not in text.replace("NOT", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None, help="library to scan (default <MEDIA_ROOT>/broll)")
    ap.add_argument("--sample", type=int, default=0, help="only check N evenly-spaced clips")
    ap.add_argument("--dry-run", action="store_true", help="report without moving anything")
    args = ap.parse_args()

    library = Path(args.dir) if args.dir else config.BROLL_DIR
    if not library.exists():
        sys.exit(f"No such library: {library}")
    reject = library / "rejected"
    tmp = config.OUTPUT_DIR / "_wm_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    clips = sorted(library.glob("*.mp4"))
    if args.sample and args.sample < len(clips):
        clips = clips[:: max(1, len(clips) // args.sample)][: args.sample]

    print(f"checking {len(clips)} clips in {library}")
    flagged, clean, errors = 0, 0, 0
    f = tmp / "frame.jpg"

    for i, clip in enumerate(clips, 1):
        if not _frame(clip, f):
            errors += 1
            continue
        try:
            marked = has_marking(f)
        except Exception as e:
            print(f"  {clip.name}: check failed ({e})")
            errors += 1
            continue

        if marked:
            flagged += 1
            if not args.dry_run:
                reject.mkdir(parents=True, exist_ok=True)
                shutil.move(str(clip), str(reject / clip.name))
        else:
            clean += 1

        if i % 25 == 0:
            print(f"  {i}/{len(clips)}  flagged={flagged} clean={clean}")

    shutil.rmtree(tmp, ignore_errors=True)
    verb = "would quarantine" if args.dry_run else "quarantined"
    print()
    print(f"checked   : {len(clips)}")
    print(f"{verb:<10}: {flagged}")
    print(f"clean     : {clean}")
    if errors:
        print(f"errors    : {errors} (left in place)")
    print(f"remaining : {len(list(library.glob('*.mp4')))} clips in {library}")


if __name__ == "__main__":
    main()
