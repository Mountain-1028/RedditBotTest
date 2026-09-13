#!/usr/bin/env python3
"""
Turn a long compilation into a library of clean background clips.

Compilations often come framed inside branded borders and padded with dead
black stretches, both of which look broken once the pipeline crops to vertical
and seeks to a random point. This:

  1. finds the real content window by temporal variance (the branded frame is
     static, the footage moves)
  2. crops to it and cuts the file into fixed-length segments
  3. deletes segments that are mostly black

Segments keep the content window's native resolution -- the render step does
the final scale/crop, so nothing is upscaled twice.

Usage:
    python3 prepare_broll.py "F:/path/compilation.webm"
    python3 prepare_broll.py src.webm --seconds 45 --out F:/.../media/broll
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageStat

import config

SAMPLE_COUNT = 11
DARK_THRESHOLD = 22.0


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_duration(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", str(path)]).stdout.strip()
    return float(out)


def grab_frame(src: Path, t: float, out: Path, vf: str = None) -> bool:
    cmd = ["ffmpeg", "-y", "-ss", str(t), "-i", str(src), "-frames:v", "1"]
    if vf:
        cmd += ["-vf", vf]
    cmd += [str(out)]
    _run(cmd)
    return out.exists() and out.stat().st_size > 0


def find_content_window(src: Path, duration: float, tmp: Path):
    """Bounding box of whatever changes over time -- i.e. the real footage,
    excluding any static branded border."""
    frames = []
    for i in range(SAMPLE_COUNT):
        t = duration * (i + 0.5) / SAMPLE_COUNT
        f = tmp / f"win{i}.png"
        if grab_frame(src, t, f):
            frames.append(np.asarray(Image.open(f).convert("L"), dtype=np.float32))
            f.unlink(missing_ok=True)
    if len(frames) < 3:
        raise RuntimeError("could not sample enough frames to locate the content window")

    var = np.stack(frames).std(axis=0)
    h, w = var.shape
    col, row = var.mean(axis=0), var.mean(axis=1)
    cols = np.where(col > col.max() * 0.25)[0]
    rows = np.where(row > row.max() * 0.25)[0]
    x0, x1 = int(cols.min()), int(cols.max())
    y0, y1 = int(rows.min()), int(rows.max())

    # even dimensions keep libx264 happy
    cw = (x1 - x0 + 1) // 2 * 2
    ch = (y1 - y0 + 1) // 2 * 2
    return x0, y0, cw, ch, w, h


def segment(src: Path, out_dir: Path, crop: str, seconds: int, prefix: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{prefix}_%04d.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", crop,
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", "120",
        "-f", "segment", "-segment_time", str(seconds), "-reset_timestamps", "1",
        pattern,
    ]
    print("segmenting (this is the slow part)...")
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg segmenting failed:\n{result.stderr[-3000:]}")
    return sorted(out_dir.glob(f"{prefix}_*.mp4"))


def mean_luma(clip: Path, tmp: Path) -> float:
    f = tmp / "luma.png"
    dur = probe_duration(clip)
    if not grab_frame(clip, dur / 2, f, "scale=96:-1"):
        return 0.0
    value = ImageStat.Stat(Image.open(f).convert("L")).mean[0]
    f.unlink(missing_ok=True)
    return value


def border_intrusion(clip: Path, tmp: Path, threshold: float = 0.30) -> bool:
    """True if the branded frame still shows at this clip's edges.

    The content window is found once for the whole source, but compilations
    splice clips of differing widths, so on some segments the border creeps
    back in. Those are cheaper to discard than to crop for -- cropping every
    clip to suit the worst one would zoom the majority needlessly."""
    f = tmp / "border.png"
    dur = probe_duration(clip)
    if not grab_frame(clip, dur / 2, f, "scale=200:200"):
        return False
    arr = np.asarray(Image.open(f).convert("RGB"))
    f.unlink(missing_ok=True)

    edge = max(6, int(arr.shape[1] * 0.06))
    r = arr[..., 0].astype(int); g = arr[..., 1].astype(int); b = arr[..., 2].astype(int)
    saturated_yellow = (r > 170) & (g > 130) & (b < 130) & ((r - b) > 70)
    return max(saturated_yellow[:, :edge].mean(), saturated_yellow[:, -edge:].mean()) > threshold


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="the long compilation to cut up")
    parser.add_argument("--seconds", type=int, default=60, help="segment length (default 60)")
    parser.add_argument("--out", default=None, help="output dir (default <MEDIA_ROOT>/broll)")
    parser.add_argument("--prefix", default=None, help="segment filename prefix")
    args = parser.parse_args()

    src = Path(args.source)
    if not src.exists():
        sys.exit(f"No such file: {src}")

    out_dir = Path(args.out) if args.out else config.BROLL_DIR
    prefix = args.prefix or src.stem[:24].replace(" ", "_")
    tmp = config.OUTPUT_DIR / "_broll_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    try:
        duration = probe_duration(src)
        print(f"source   : {src.name}  ({duration/3600:.2f}h)")

        x, y, cw, ch, w, h = find_content_window(src, duration, tmp)
        crop = f"crop={cw}:{ch}:{x}:{y}"
        if (cw, ch) == (w, h):
            print(f"frame    : {w}x{h}, no border detected -- using full frame")
        else:
            print(f"frame    : {w}x{h} -> content window {cw}x{ch} at ({x},{y}); border cropped away")

        clips = segment(src, out_dir, crop, args.seconds, prefix)
        print(f"produced : {len(clips)} segments")

        dark = bordered = 0
        for clip in clips:
            if mean_luma(clip, tmp) < DARK_THRESHOLD:
                clip.unlink()
                dark += 1
            elif border_intrusion(clip, tmp):
                clip.unlink()
                bordered += 1
        kept = len(clips) - dark - bordered
        print(f"dropped  : {dark} dead/black, {bordered} with the branded border still showing")
        print(f"kept     : {kept} usable clips in {out_dir}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
