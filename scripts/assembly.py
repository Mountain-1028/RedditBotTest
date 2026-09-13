#!/usr/bin/env python3
"""
Renders the narration as a single "beat" -- looped gameplay footage + Kokoro
voiceover + burned word-by-word captions -- then mixes in background music
for the final vertical 1080x1920 MP4.
"""
import subprocess
from pathlib import Path

import config
from tts import synthesize
from captions import estimate_word_timestamps

W, H = 1080, 1920


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
    beat: dict, visual_path: Path, work_dir: Path, index: int, card_path: Path = None,
    visual_start: float = 0.0, audio_override: Path = None,
) -> Path:
    """Renders the narration over looped gameplay footage with burned captions.

    If card_path is given, the frame is split: the card image fills the top
    quarter (1080x480) and the gameplay footage is cropped to fill the
    remaining bottom three-quarters (1080x1440), stacked into the full
    1080x1920 frame. Without it, gameplay footage fills the whole frame.

    visual_start seeks into visual_path before looping -- lets a single long
    source clip (e.g. a 10-minute gameplay recording) start from a different
    point each render instead of always playing from frame 0.

    audio_override supplies a ready-made narration track (e.g. exported from
    an external TTS tool) instead of synthesizing one with Kokoro."""
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / f"beat_{index:02d}.wav"
    ass_path = work_dir / f"beat_{index:02d}.ass"
    out_path = work_dir / f"beat_{index:02d}.mp4"

    if audio_override:
        audio_path = Path(audio_override)
        duration = probe_duration(audio_path)
    else:
        tts_info = synthesize(beat["voiceover"], str(audio_path))
        # Backends pick their own container (Kokoro wav, Edge mp3).
        audio_path = Path(tts_info["path"])
        duration = tts_info["duration_sec"]

    words = estimate_word_timestamps(beat["voiceover"], duration)
    build_ass(words, ass_path)
    ass_arg = _escape_ffmpeg_filter_path(ass_path)

    visual_input_args = (["-ss", f"{visual_start:.3f}"] if visual_start else []) + [
        "-stream_loop", "-1", "-i", str(visual_path),
    ]

    if card_path:
        card_h = H // 4
        gp_h = H - card_h
        filter_complex = (
            f"[0:v]scale={W}:{gp_h}:force_original_aspect_ratio=increase,crop={W}:{gp_h},setsar=1[gp];"
            f"[1:v]scale={W}:{card_h},setsar=1[card];"
            f"[card][gp]vstack=inputs=2[stacked];"
            f"[stacked]ass={ass_arg}[v]"
        )
        cmd = [
            "ffmpeg", "-y",
            *visual_input_args,
            "-loop", "1", "-i", str(card_path),
            "-i", str(audio_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "2:a",
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-pix_fmt", "yuv420p",
            str(out_path),
        ]
    else:
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,"
            f"ass={ass_arg}"
        )
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


def mix_music(video_in: Path, music_path: Path, out_path: Path, music_volume: float = 0.12):
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_in),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={music_volume}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
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
