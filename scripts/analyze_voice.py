#!/usr/bin/env python3
"""
Download a batch of TikTok (or other yt-dlp-supported) video URLs, extract
audio, and ask Gemini to actually listen to each clip and characterize the
narration voice -- gender, accent, tone, and whether it's a human recording
or a TTS engine (with a best-guess at which one). Used to survey what voices
competing Reddit-story channels are using.

The gateway's OpenAI-compatible chat/completions route rejects audio input
("Content type 'input_audio' is supported only by the direct OpenAI
service") -- verified by hand. Google's own native generateContent endpoint
(same gateway, same key, /v1beta instead of /v1) accepts inline_data audio
directly and does support it, so this calls that instead.

Usage:
    python3 analyze_voice.py "https://www.tiktok.com/@user/video/123" "https://..." ...
    python3 analyze_voice.py --file urls.txt
    python3 analyze_voice.py --file urls.txt --out voice_report.json
"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

import config

# LLM_BASE_URL is the OpenAI-compatible route (".../proxy/google-ai/v1");
# the native Gemini API lives one level up at v1beta and is what actually
# accepts audio.
GENERATE_BASE = config.LLM_BASE_URL.rsplit("/v1", 1)[0] + "/v1beta"
MODEL = "gemini-2.5-flash"

PROMPT = """Listen to this narration clip from a short-form video and analyze ONLY the voice \
(ignore the words/story content). Respond with strict JSON, no markdown fences, matching this \
shape exactly:

{
  "gender": "male|female|unclear",
  "age_range": "e.g. 20s-30s",
  "accent": "e.g. General American, British, Australian",
  "tone": "short phrase, e.g. calm narrative, energetic, deadpan",
  "is_tts": true or false,
  "likely_engine": "your best guess if is_tts is true, e.g. ElevenLabs, Google Cloud TTS, Amazon Polly, \
Microsoft Edge/Azure Neural, TikTok built-in TTS, CapCut TTS, or 'human' if is_tts is false",
  "confidence": "low|medium|high",
  "notes": "one sentence on what gave it away"
}"""


def download_audio(url: str, dest_dir: Path) -> Path | None:
    out_tmpl = str(dest_dir / "%(id)s.%(ext)s")
    try:
        subprocess.run(
            ["yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "mp3",
             "-o", out_tmpl, "--quiet", "--no-warnings", url],
            check=True, timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  download failed: {e}")
        return None
    matches = list(dest_dir.glob("*.mp3"))
    return matches[-1] if matches else None


def analyze_audio(path: Path) -> dict:
    # A minute of narration is plenty to characterize a voice, and the gateway
    # 413s on the full-length audio of longer "full story" compilation videos
    # (some run 30+ minutes) -- trim before base64-inflating it into the request.
    clip = path.with_name(path.stem + "_clip.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-t", "90", "-vn", "-acodec", "libmp3lame",
         "-ar", "22050", "-ab", "64k", str(clip)],
        check=True, capture_output=True, timeout=60,
    )
    b64 = base64.b64encode(clip.read_bytes()).decode()
    clip.unlink(missing_ok=True)
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": "audio/mp3", "data": b64}},
            ],
        }],
        "generationConfig": {"temperature": 0},
    }
    r = requests.post(
        f"{GENERATE_BASE}/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": config.LLM_API_KEY, "Content-Type": "application/json"},
        json=body, timeout=90,
    )
    r.raise_for_status()
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*", help="video URLs (TikTok, etc.)")
    ap.add_argument("--file", help="text file, one URL per line, appended to urls")
    ap.add_argument("--out", default=None, help="write JSON report here")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        urls += [ln.strip() for ln in Path(args.file).read_text().splitlines() if ln.strip()]
    if not urls:
        print("No URLs given.")
        sys.exit(1)

    results = []
    with tempfile.TemporaryDirectory(prefix="voice_analyze_") as tmp:
        tmp_dir = Path(tmp)
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            audio_path = download_audio(url, tmp_dir)
            if not audio_path:
                results.append({"url": url, "error": "download failed"})
                continue
            try:
                analysis = analyze_audio(audio_path)
                analysis["url"] = url
                results.append(analysis)
                print(f"  {analysis['gender']:<8} {analysis['accent']:<20} "
                      f"tts={analysis['is_tts']!s:<5} engine={analysis['likely_engine']}")
            except Exception as e:
                print(f"  analysis failed: {e}")
                results.append({"url": url, "error": str(e)})
            finally:
                audio_path.unlink(missing_ok=True)

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")

    tts = [r for r in results if r.get("is_tts") is True]
    human = [r for r in results if r.get("is_tts") is False]
    errors = [r for r in results if "error" in r]
    print(f"\n{len(results)} analyzed: {len(tts)} TTS, {len(human)} human-sounding, {len(errors)} failed")
    if tts:
        from collections import Counter
        engines = Counter(r["likely_engine"] for r in tts)
        print("Engine guesses:", dict(engines))


if __name__ == "__main__":
    main()
