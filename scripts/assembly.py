#!/usr/bin/env python3
"""
Renders the narration as a single "beat" -- looped gameplay footage + Kokoro
voiceover + burned word-by-word captions -- then mixes in background music
for the final vertical 1080x1920 MP4.
"""
import json
import subprocess
from pathlib import Path

import config
from tts import synthesize
from captions import estimate_word_timestamps
from reddit_card import CARD_STATIC_NAME

W, H = 1080, 1920
# Vertical position of the intro card, high enough to clear the captions.
CARD_Y = 380

# Measured against the actual broll/gameplay libraries: 75 of 135 broll clips
# are 1080x1080 (from the compilation), and a handful are 720p. Filling a
# 1080x1920 frame from either means real upscaling -- by 1.78x and up to 1.5x
# respectively -- not just a crop. Plain bicubic `scale` softens that; the
# libplacebo GPU filter's ewa_lanczossharp kernel holds detail much better on
# genuine upscales, so it's used only when the source is actually smaller than
# the output in some dimension. A native-resolution or larger clip (most
# gameplay footage, and the widescreen recordings) gets the cheap path --
# there's nothing to gain and it doesn't need a GPU filter to succeed.
UPSCALE_THRESHOLD = 0.98  # tolerate float noise from odd source dimensions


def probe_resolution(path: Path) -> tuple[int, int] | None:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        stream = json.loads(r.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        return None


def needs_upscale(src_w: int, src_h: int, dst_w: int = W, dst_h: int = H) -> bool:
    """True if filling the output frame (scale-to-cover, same as the crop
    filter below) requires enlarging the source in either dimension."""
    fill_scale = max(dst_w / src_w, dst_h / src_h)
    return fill_scale > (1.0 / UPSCALE_THRESHOLD)


def _fill_frame_filter(visual_path: Path) -> str:
    """Scale-to-cover-and-crop filter for the background clip, sized to
    whichever ffmpeg filter the source actually needs. A native-resolution or
    larger clip uses the cheap `scale` filter -- there's nothing to gain from
    a GPU pass. A clip smaller than the output frame (see needs_upscale) uses
    libplacebo's ewa_lanczossharp kernel instead, which holds real detail on
    a genuine enlargement where plain bicubic scale goes soft; reset_sar is
    required or libplacebo leaves the wrong SAR on the stream and the output
    plays back squashed."""
    res = probe_resolution(visual_path)
    if res and needs_upscale(*res):
        return f"libplacebo=w={W}:h={H}:upscaler=ewa_lanczossharp:fit_mode=cover:reset_sar=true"
    return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"


def _run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\ncmd: {' '.join(cmd)}\nstderr:\n{result.stderr[-3000:]}")
    return result


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,90,&H00FFFFFF,&H00000000,&H00000000,1,0,1,6,0,2,60,60,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(words, out_path: Path):
    lines = [ASS_HEADER]
    for w in words:
        text = w["word"].upper().replace(",", "").replace(".", "")
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(w['start'])},{_ass_time(w['end'])},Caption,,0,0,0,,{text}"
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape a path for use as an ffmpeg filtergraph option value. Needed on
    Windows because the drive letter's ':' is otherwise parsed as a filter
    option separator, corrupting the rest of the path."""
    escaped = path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"'{escaped}'"


def render_beat(
    beat: dict, visual_path: Path, work_dir: Path, index: int, card_frames: tuple = None,
    visual_start: float = 0.0, audio_override: Path = None, tts_info: dict = None,
) -> Path:
    """Renders the narration over looped footage with burned captions.

    Footage is always full-bleed 1080x1920. card_frames, when given, is the
    (dir, frame_count, fps) tuple from reddit_card.generate_card_frames(): the
    card plays its pop-in/Subscribe animation for its own length, then its
    settled still frame (card_static.png, alongside the sequence) is held as
    an overlay for the rest of the video. It does not disappear -- checked
    against two unrelated channels in this niche, both keep the card on
    screen for the whole runtime, concurrent with the captions.

    visual_start seeks into visual_path before looping -- lets a single long
    source clip (e.g. a 10-minute gameplay recording) start from a different
    point each render instead of always playing from frame 0.

    audio_override supplies a ready-made narration track (e.g. exported from
    an external TTS tool) instead of synthesizing one.

    tts_info reuses narration already synthesized by the caller -- the result
    dict from tts.synthesize(). The caller needs the audio before the render
    to check its true length (see run_pipeline._fit_narration), and passing it
    back in avoids both synthesizing twice and losing the exact word timings
    that keep captions locked to the speech."""
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / f"beat_{index:02d}.wav"
    ass_path = work_dir / f"beat_{index:02d}.ass"
    out_path = work_dir / f"beat_{index:02d}.mp4"

    words = None
    if audio_override:
        audio_path = Path(audio_override)
        duration = probe_duration(audio_path)
    elif tts_info:
        audio_path = Path(tts_info["path"])
        duration = tts_info["duration_sec"]
        words = tts_info.get("words")
    else:
        tts_info = synthesize(beat["voiceover"], str(audio_path))
        # Backends pick their own container (Kokoro wav, Edge mp3).
        audio_path = Path(tts_info["path"])
        duration = tts_info["duration_sec"]
        words = tts_info.get("words")

    # Exact timings from the synthesiser keep captions locked to the audio.
    # Estimating from word length is only a fallback (Kokoro, or imported
    # audio) and drifts audibly over a long narration.
    if not words:
        words = estimate_word_timestamps(beat["voiceover"], duration)
    build_ass(words, ass_path)
    ass_arg = _escape_ffmpeg_filter_path(ass_path)

    visual_input_args = (["-ss", f"{visual_start:.3f}"] if visual_start else []) + [
        "-stream_loop", "-1", "-i", str(visual_path),
    ]

    fill_filter = _fill_frame_filter(visual_path)

    if card_frames:
        frames_dir, frame_count, card_fps = card_frames
        card_secs = frame_count / float(card_fps)
        static_card = Path(frames_dir) / CARD_STATIC_NAME
        # Two overlay stages on the same [bg]: the animated sequence plays
        # through card_secs, then its settled still frame takes over for the
        # remainder -- see the render_beat docstring for why the card no
        # longer disappears after the intro.
        filter_complex = (
            f"[0:v]{fill_filter}[bg];"
            f"[bg][1:v]overlay=x=0:y={CARD_Y}:eof_action=pass:enable='lte(t,{card_secs:.3f})'[ov1];"
            f"[ov1][2:v]overlay=x=0:y={CARD_Y}:eof_action=pass:enable='gte(t,{card_secs:.3f})'[ov2];"
            f"[ov2]ass={ass_arg}[v]"
        )
        cmd = [
            "ffmpeg", "-y",
            *visual_input_args,
            "-framerate", str(card_fps), "-i", str(Path(frames_dir) / "frame_%04d.png"),
            "-loop", "1", "-i", str(static_card),
            "-i", str(audio_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "3:a",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    else:
        vf = f"{fill_filter},ass={ass_arg}"
        cmd = [
            "ffmpeg", "-y",
            *visual_input_args,
            "-i", str(audio_path),
            "-filter_complex", f"[0:v]{vf}[v]",
            "-map", "[v]", "-map", "1:a",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    _run(cmd)
    return out_path


def mix_music(video_in: Path, music_path: Path, out_path: Path, music_volume: float = 0.12,
               sfx_cues: list = None, sfx_volume: float = 0.55):
    """sfx_cues (only ever passed for AI-authored fiction -- never for a real
    pulled post, see sfx.py/run_pipeline.py) is a list of {"clip", "start"}:
    each clip is delayed to its cue's timestamp with adelay and mixed in
    alongside the narration and music. normalize=0 on amix is required --
    amix's default behaviour quietens every existing input as more inputs are
    added, which would make the narration progressively fainter as a story
    picks up more cues; each stream's level is set explicitly instead."""
    sfx_cues = sfx_cues or []
    inputs = ["-i", str(video_in), "-stream_loop", "-1", "-i", str(music_path)]
    for cue in sfx_cues:
        inputs += ["-i", str(cue["clip"])]

    parts = [f"[1:a]volume={music_volume}[m]"]
    mix_labels = ["0:a", "m"]
    for i, cue in enumerate(sfx_cues):
        delay_ms = max(int(cue["start"] * 1000), 0)
        label = f"s{i}"
        parts.append(f"[{i + 2}:a]adelay={delay_ms}:all=1,volume={sfx_volume}[{label}]")
        mix_labels.append(label)

    parts.append(
        "".join(f"[{lbl}]" for lbl in mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0:normalize=0[a]"
    )
    filter_complex = ";".join(parts)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    _run(cmd)
    return out_path


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


if __name__ == "__main__":
    # Smoke test with a synthetic test pattern -- no gameplay footage needed.
    work = config.ASSETS_DIR / "assembly_smoke_test"
    work.mkdir(parents=True, exist_ok=True)
    synthetic = work / "synthetic.mp4"
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
        "-t", "20", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(synthetic),
    ])

    beat = {"voiceover": "This is the smoke test narration line for the reddit story pipeline."}
    out_path = render_beat(beat, synthetic, work, 0)
    print("Smoke test output:", out_path, "duration:", probe_duration(out_path))
