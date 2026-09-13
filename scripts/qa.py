#!/usr/bin/env python3
"""
Two-part QA gate a finished video has to pass before it's dropped into
ready_to_post/:

1. llm_check_script  -- an LLM checks the narration text for hate speech/
   slurs/graphic content that would violate platform guidelines, and for
   text that reads as broken/incoherent.
2. spec_check        -- programmatic check of resolution/duration/audio
   levels on the rendered file.
"""
import json
import subprocess
import time
from pathlib import Path

import config
from llm_client import call_llm

QA_PROMPT = """Review this narration text, which will be read aloud over video and posted
publicly on social media (TikTok/YouTube Shorts). Check for:
- Hate speech, slurs, or content targeting a protected group
- Extremely graphic violence, sexual content, or anything that would violate
  typical short-form platform community guidelines
- Text that reads as broken or incoherent (garbled, cut off mid-sentence, etc.)

Narration:
{narration}

Respond in exactly this plain-text format, nothing else:

VERDICT: PASS

or, if there are problems:

VERDICT: FAIL
ISSUE: <one problem, on one line>
ISSUE: <another problem, on one line>"""


def _parse_verdict(raw: str) -> dict:
    """Parse the plain-text verdict format. Deliberately not JSON: this
    gateway reliably drops the first several characters of a response, which
    leaves JSON unparseable but leaves line-based text readable (a mangled
    "VERDICT: PASS" still arrives as "PASS"). Hence the bare-token fallback."""
    verdict = None
    issues = []
    for line in raw.splitlines():
        line = line.strip().lstrip("*-# ").strip().rstrip("*")
        upper = line.upper()
        if upper.startswith("VERDICT:"):
            value = upper.split(":", 1)[1].strip()
            if value.startswith("PASS"):
                verdict = True
            elif value.startswith("FAIL"):
                verdict = False
        elif upper.startswith("ISSUE:"):
            issue = line.split(":", 1)[1].strip()
            if issue:
                issues.append(issue)
        elif verdict is None and upper.strip(".!") in ("PASS", "FAIL"):
            verdict = upper.strip(".!") == "PASS"

    if verdict is None:
        raise ValueError(f"no verdict found in response: {raw[:200]!r}")
    return {"pass": verdict, "issues": issues}


def llm_check_script(script: dict, attempts: int = 4) -> dict:
    """QA runs after a full render, so losing it to a momentary gateway blip
    throws away several minutes of encoding. Attempts are spaced out (2s, 8s,
    32s) rather than fired back-to-back, which would just land all of them
    inside the same outage window -- the failure mode this backoff was added
    for was three instant retries against one 503."""
    last_error = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * (4 ** (attempt - 1)))
        try:
            raw = call_llm(
                model=config.LLM_MODEL_QA,
                system="You are a meticulous content moderator preparing videos for public posting.",
                user=QA_PROMPT.format(narration=script["narration"]),
                max_tokens=1500,
                temperature=0.2,
            )
            return _parse_verdict(raw)
        except Exception as e:  # unparseable verdict, or the gateway being down
            last_error = e
    raise RuntimeError(f"QA model gave no parseable verdict after {attempts} attempts: {last_error}")


def spec_check(video_path: Path, min_sec=None, max_sec=None) -> dict:
    min_sec = config.VIDEO_MIN_SEC if min_sec is None else min_sec
    max_sec = config.VIDEO_MAX_SEC if max_sec is None else max_sec
    issues = []

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries", "format=duration",
         "-of", "json", str(video_path)],
        capture_output=True, text=True,
    )
    info = json.loads(probe.stdout)
    stream = info.get("streams", [{}])[0]
    duration = float(info.get("format", {}).get("duration", 0))
    width, height = stream.get("width"), stream.get("height")

    if not (width == 1080 and height == 1920):
        issues.append(f"resolution is {width}x{height}, expected 1080x1920")
    if not (min_sec <= duration <= max_sec):
        issues.append(f"duration is {duration:.1f}s, expected {min_sec}-{max_sec}s")

    # loudness sanity check -- catch a silent or clipped render
    vol = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    mean_line = [l for l in vol.stderr.splitlines() if "mean_volume" in l]
    if mean_line:
        mean_db = float(mean_line[0].split(":")[1].strip().replace(" dB", ""))
        if mean_db < -35:
            issues.append(f"audio mean volume is {mean_db} dB, sounds too quiet/silent")

    return {"pass": len(issues) == 0, "issues": issues, "duration": duration, "resolution": f"{width}x{height}"}


def run_qa(script: dict, video_path: Path) -> dict:
    script_result = llm_check_script(script)
    spec_result = spec_check(video_path)
    overall_pass = script_result.get("pass", False) and spec_result["pass"]
    return {
        "pass": overall_pass,
        "script_check": script_result,
        "spec_check": spec_result,
    }


if __name__ == "__main__":
    import sys
    video = Path(sys.argv[1])
    print(json.dumps(spec_check(video), indent=2))
