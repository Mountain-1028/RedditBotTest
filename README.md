# Faceless Reddit Story Video Pipeline

Fully automated: real Reddit post -> cleaned-up narration -> Kokoro voiceover -> looped gameplay footage -> burned captions -> music -> QA -> a finished vertical MP4 dropped in `output/ready_to_post/`, ready for you to upload manually.

## Status

Working end-to-end on real content (Reddit fetch, LLM narration cleanup, Kokoro TTS, ffmpeg assembly, captions, music mixing, QA all confirmed working against real Reddit posts and the configured LLM gateway).

This was pivoted from an earlier recipe-video version of the same pipeline -- the LLM/TTS/assembly/QA plumbing carried over, but the content source, script shape, and background visuals are Reddit-story-specific now.

## One-time setup

1. `pip install -r requirements.txt`
2. Install `espeak-ng` at the OS level (Kokoro depends on it for phonemization):
   - Ubuntu/Debian: `sudo apt-get install espeak-ng`
   - Windows: install from https://github.com/espeak-ng/espeak-ng/releases and make sure it's on PATH
3. Model files go in `models/` (kokoro-v1.0.onnx, voices-v1.0.bin) -- ~340MB total, not synced to every machine automatically since they're large; download from https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0 if setting up elsewhere.
4. Copy `.env.example` to `.env` and fill in:
   - `LLM_BASE_URL` / `LLM_API_KEY` -- your model gateway
   - `LLM_MODEL_SCRIPT` -- a fast/cheap model name from your gateway (used once per video, for narration cleanup)
   - `LLM_MODEL_QA` -- used once per video, for the content-safety/coherence check
   - `LLM_EXTRA_BODY` -- optional JSON of gateway-specific extra params (e.g. disabling a model's default "thinking" mode, which otherwise eats the completion-token budget before producing visible output)
5. Drop a handful of **gameplay clips** (mp4/mov/mkv -- e.g. Subway Surfers / Minecraft parkour recordings you have the rights to use) into `assets/gameplay/`. Not fetched automatically: this is footage you record or license yourself, same reasoning as the music below.
6. Drop a handful of royalty-free background music tracks (mp3/wav/aac) into `assets/music/` -- the pipeline picks one at random per video. Make sure you have rights to use whatever you put there (YouTube Audio Library, Pixabay Music, etc. are safe free sources).

Reddit posts are fetched from the public, unauthenticated `old.reddit.com/*.json` endpoints -- no API key needed (`www.reddit.com`'s equivalent endpoint returned a Cloudflare 403 in testing; `old.reddit.com` didn't). Reddit can rate-limit or change this at its discretion; if fetching starts failing consistently, register a real app at reddit.com/prefs/apps and switch `reddit_source.py` to OAuth.

## Running it

```
python3 scripts/run_pipeline.py            # one video, pipeline picks the post
python3 scripts/run_pipeline.py --batch 5  # 5 videos in a row
```

Each run writes a log to `logs/run_<id>.json`. Anything that passes QA lands in `output/ready_to_post/` as `<id>_<hook>.mp4` plus a matching `.txt` with the hook/caption/hashtags and a link back to the source Reddit post (keep this for attribution). Anything that fails QA stays in `output/work_<id>/` for you to inspect rather than silently disappearing.

`logs/used_reddit_posts.json` tracks every post that's been used so the pipeline never repeats itself.

## Content source & subreddits

`scripts/reddit_source.py` pulls today's top posts from a rotating list of story-friendly subreddits (`AskReddit`, `tifu`, `AmItheAsshole`, `TrueOffMyChest`, `relationship_advice`, `confession`, `MaliciousCompliance`, `pettyrevenge`, `EntitledPeople` -- edit the `SUBREDDITS` list to change these), filtering out NSFW/stickied/too-short/too-long/low-score/already-used posts. `scripts/reddit_narration.py` then has the LLM lightly clean the text for spoken narration (expanding abbreviations like AITA/TIFU, fixing broken sentences) without inventing new plot content, plus generate the on-screen hook, social caption, and hashtags.

## Folder layout

```
scripts/           all pipeline code
models/            Kokoro model files
assets/gameplay/   your background gameplay clips (add these yourself)
assets/music/      your background tracks (add these yourself)
assets/            scratch space for intermediate audio/video during a run
output/ready_to_post/   finished videos + caption text, ready to upload
logs/              per-run logs + the used-posts history
```

## Thumbnail generation

`scripts/image_gen.py` calls an image-generation gateway (OpenAI-compatible `/generations` endpoint) to generate a custom thumbnail per video instead of just grabbing a stock frame. Add `IMAGE_GATEWAY_API_KEY` and `IMAGE_GATEWAY_BASE_URL` to `.env` to use it; `IMAGE_GATEWAY_MODEL` defaults to `nano-banana-lite` (cheap/fast) -- bump to `nano-banana-pro`, `gpt-image-2.5-sunburst`, `seedream-4.5` etc. for higher quality when it's worth the cost. Not yet wired into `run_pipeline.py` automatically -- test it standalone first (`python3 scripts/image_gen.py "your prompt"`), then say the word and I'll hook it into the orchestrator so every video gets one automatically.

## What's next

- Add gameplay clips and music tracks, then run one video and check the output quality.
- Once that looks right: schedule `run_pipeline.py --batch N` to run automatically (cron / Task Scheduler) instead of running it by hand.
