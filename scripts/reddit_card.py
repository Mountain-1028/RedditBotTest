#!/usr/bin/env python3
"""
Renders the story card: a social-style rounded card carrying the channel's
own handle, avatar, the story hook, and an engagement footer. It pops in and
animates briefly, then holds as a static overlay for the rest of the video --
matching the reference genre, where the card stays on screen concurrently
with the captions for the full runtime rather than a short intro that
disappears. Cross-checked against two unrelated 400K+ subscriber channels in
this niche (thumbnails, Sept 2026): both keep the card up throughout, and
both show real-looking engagement numbers plus a share icon rather than a
thumbs-up. Neither showed a Subscribe pill on the card itself (they use a
"..." menu icon) -- that stays here anyway since it was an explicit earlier
request, but it's worth knowing it's not the genre convention.

The handle is the channel's own (CARD_HANDLE in .env) -- this is channel
branding, not an impersonation of the original poster or of any real account.
"""
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

# AI-generated bell icon (nano-banana-2 / gemini-3.1-flash-image, via
# image_gen.py) -- replaces an earlier hand-drawn PIL version that read as a
# helmet. Not checked into git (assets/* is bulk-media-ignored, same as the
# avatar), so this degrades to the old primitive shapes if the file is
# missing rather than crashing a fresh checkout.
BELL_ICON_PATH = config.ASSETS_DIR / "branding" / "bell_icon.png"
_bell_icon_cache = {}


def _load_bell_icon():
    if "img" not in _bell_icon_cache:
        _bell_icon_cache["img"] = (
            Image.open(BELL_ICON_PATH).convert("RGBA") if BELL_ICON_PATH.exists() else None
        )
    return _bell_icon_cache["img"]

FONT_DIR = Path(r"C:\Windows\Fonts")
FONT_BOLD = FONT_DIR / "segoeuib.ttf"
FONT_SEMI = FONT_DIR / "seguisb.ttf"
FONT_REG = FONT_DIR / "segoeui.ttf"
FONT_EMOJI = FONT_DIR / "seguiemj.ttf"

THEMES = {
    "light": {
        "card": (255, 255, 255, 255),
        "title": (15, 15, 15, 255),
        "handle": (15, 15, 15, 255),
        "muted": (120, 124, 128, 255),
        "avatar_bg": (222, 226, 232, 255),
    },
    "dark": {
        "card": (18, 18, 20, 255),
        "title": (255, 255, 255, 255),
        "handle": (255, 255, 255, 255),
        "muted": (168, 172, 178, 255),
        "avatar_bg": (52, 56, 64, 255),
    },
}
VERIFIED_BLUE = (29, 155, 240, 255)


def _font(path: Path, size: int):
    return ImageFont.truetype(str(path), size)


def _wrap(draw, text, font, max_width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if lines and len(" ".join(lines).split()) < len(words):
        last = lines[-1]
        while draw.textlength(last + "...", font=font) > max_width and len(last) > 1:
            last = last[:-1].rstrip()
        lines[-1] = last + "..."
    return lines


def _verified_badge(draw, x, y, d):
    draw.ellipse([(x, y), (x + d, y + d)], fill=VERIFIED_BLUE)
    cx, cy, s = x + d / 2, y + d / 2, d * 0.26
    draw.line([(cx - s, cy), (cx - s * 0.15, cy + s * 0.8), (cx + s, cy - s * 0.7)],
              fill=(255, 255, 255, 255), width=max(3, int(d * 0.11)), joint="curve")


def _paste_avatar(card, avatar_path, box, fallback_fill):
    x, y, d = box
    circle = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(circle).ellipse([(0, 0), (d * 4, d * 4)], fill=255)
    mask = circle.resize((d, d), Image.LANCZOS)

    src = None
    if avatar_path:
        p = Path(avatar_path)
        if p.exists():
            try:
                src = Image.open(p).convert("RGBA")
            except Exception:
                src = None
    if src is None:
        src = Image.new("RGBA", (d, d), fallback_fill)
    else:
        side = min(src.size)
        src = src.crop(((src.width - side) // 2, (src.height - side) // 2,
                        (src.width + side) // 2, (src.height + side) // 2)).resize((d, d), Image.LANCZOS)
    card.paste(src, (x, y), mask)


SUB_RED = (230, 33, 23, 255)
SUB_DONE = (99, 99, 99, 255)


def _draw_subscribe(img, box, scale=1.0, subscribed=False):
    """Draw the Subscribe pill. scale pulses it; subscribed flips it to the
    settled grey state."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    w, h = w * scale, h * scale
    x, y = cx - w / 2, cy - h / 2

    d = ImageDraw.Draw(img)
    d.rounded_rectangle([(x, y), (x + w, y + h)], radius=int(h / 2),
                        fill=SUB_DONE if subscribed else SUB_RED)

    label = "Subscribed" if subscribed else "Subscribe"
    f = _font(FONT_BOLD, int(h * 0.46))
    tw = d.textlength(label, font=f)
    # Gap/bell size computed from the actual measured label width, not a
    # constant -- a fixed pad tuned against "Subscribe" overlapped once the
    # label switched to the longer "Subscribed".
    bell_icon = _load_bell_icon() if subscribed else None
    bell_size = h * 0.44
    gap = h * 0.16
    bell_pad = (bell_size + gap) if subscribed else 0
    d.text((cx - (tw + bell_pad) / 2, cy - h * 0.27), label, font=f, fill=(255, 255, 255, 255))

    if subscribed:
        bx = cx - (tw + bell_pad) / 2 + tw + gap
        by = cy - bell_size / 2
        if bell_icon is not None:
            icon = bell_icon.resize((int(bell_size), int(bell_size)), Image.LANCZOS)
            img.paste(icon, (int(bx), int(by)), icon)
        else:  # fallback if the generated asset is missing (fresh checkout)
            r = bell_size * 0.38
            cx2, cy2 = bx + bell_size / 2, by + bell_size / 2
            d.pieslice([(cx2 - r, cy2 - r), (cx2 + r, cy2 + r)], start=180, end=360, fill=(255, 255, 255, 255))
            d.rectangle([(cx2 - r, cy2), (cx2 + r, cy2 + r * 0.5)], fill=(255, 255, 255, 255))
            d.ellipse([(cx2 - r * 0.25, cy2 + r * 0.5), (cx2 + r * 0.25, cy2 + r)], fill=(255, 255, 255, 255))


def _engagement_numbers(post: dict) -> tuple[str, str]:
    """Plausible like/comment counts for the footer. Derived from the post's
    real Reddit score when we have one, so a 40K-upvote post doesn't show the
    same flat placeholder as a 50-upvote one -- the reference cards show
    numbers that look like real post stats, not a fixed "99+" on everything.
    Falls back to a stable pseudo-random pick (hashed on title, not
    time-random) so re-rendering the same post doesn't change its numbers."""
    score = post.get("score")
    if not isinstance(score, (int, float)) or score <= 0:
        seed = int(hashlib.sha1((post.get("title") or "x").encode()).hexdigest(), 16)
        score = 400 + seed % 12000
    likes = int(score)
    comments = max(8, int(likes * (0.06 + (likes % 7) / 100)))

    def _fmt(n: int) -> str:
        if n >= 1000:
            return f"{n/1000:.1f}".rstrip("0").rstrip(".") + "K"
        return str(n)

    return _fmt(likes), _fmt(comments)


def _draw_cursor(img, x, y, size=54):
    d = ImageDraw.Draw(img)
    pts = [(x, y), (x, y + size), (x + size * 0.27, y + size * 0.74),
           (x + size * 0.43, y + size * 1.05), (x + size * 0.58, y + size * 0.98),
           (x + size * 0.42, y + size * 0.68), (x + size * 0.70, y + size * 0.66)]
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))


CARD_STATIC_NAME = "card_static.png"


def generate_card_frames(post: dict, out_dir: Path, seconds: float = None,
                         fps: int = 30, width: int = 1080) -> tuple:
    """Render the card's opening animation as a PNG sequence: it pops in, the
    Subscribe button breathes, then a cursor moves over and clicks it. The
    settled last frame is also saved as out_dir/card_static.png -- the
    reference genre keeps the card on screen for the whole video, not just
    the opening seconds, so the caller (assembly.render_beat) uses this still
    image to extend the overlay past the animated window without needing a
    frame file per second of runtime.

    Returns (out_dir, frame_count, fps)."""
    seconds = seconds if seconds is not None else config.CARD_SECONDS
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("frame_*.png"):
        stale.unlink()

    base = _build_card(post, width)
    cw, ch = base.size

    # Subscribe pill sits on the footer row, right-aligned inside the card
    btn_w, btn_h = 250, 74
    btn_x = width - 30 - 44 - btn_w
    btn_y = ch - 44 - btn_h - 4
    box = (btn_x, btn_y, btn_w, btn_h)

    n = max(1, int(seconds * fps))
    click_t = seconds * 0.62
    for i in range(n):
        t = i / fps
        frame = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

        # pop-in: ease-out scale + fade over the first 0.45s
        p = min(1.0, t / 0.45)
        ease = 1 - (1 - p) ** 3
        s = 0.92 + 0.08 * ease
        layer = base if s >= 0.999 else base.resize((int(cw * s), int(ch * s)), Image.LANCZOS)
        lx, ly = (cw - layer.width) // 2, (ch - layer.height) // 2
        if ease < 1.0:
            layer = layer.copy()
            layer.putalpha(layer.getchannel("A").point(lambda a: int(a * ease)))
        frame.paste(layer, (lx, ly), layer)

        subscribed = t >= click_t
        if subscribed:
            # brief squash on the click, then settle
            k = min(1.0, (t - click_t) / 0.18)
            pulse = 0.90 + 0.10 * k
        else:
            pulse = 1.0 + 0.035 * math.sin(t * 3.4)
        _draw_subscribe(frame, box, scale=pulse, subscribed=subscribed)

        # cursor glides in, clicks, then leaves
        approach_start = click_t - 0.85
        if approach_start <= t <= click_t + 0.75:
            a = min(1.0, max(0.0, (t - approach_start) / 0.85))
            ce = 1 - (1 - a) ** 2
            sx, sy = btn_x + btn_w + 190, btn_y + btn_h + 150
            tx, ty = btn_x + btn_w * 0.62, btn_y + btn_h * 0.55
            _draw_cursor(frame, sx + (tx - sx) * ce, sy + (ty - sy) * ce)

        frame.save(out_dir / f"frame_{i:04d}.png")
        if i == n - 1:
            frame.save(out_dir / CARD_STATIC_NAME)

    return out_dir, n, fps


def _build_card(post: dict, width: int = 1080) -> Image.Image:
    """The static card, without the Subscribe pill (that's drawn per frame so
    it can animate). Returns an RGBA image sized to its content."""
    theme = THEMES.get((config.CARD_THEME or "light").lower(), THEMES["light"])
    handle = config.CARD_HANDLE
    pad = 44
    card_w = width - 2 * 30

    f_handle = _font(FONT_BOLD, 46)
    f_title = _font(FONT_SEMI, 56)
    f_meta = _font(FONT_SEMI, 30)

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    # 6 lines: reference cards run 2-3 full sentences of setup (~20-35 words),
    # not a single short title -- this needs headroom for that, with the
    # existing ellipsis fallback in _wrap still catching genuine overflow.
    title_lines = _wrap(probe, post.get("title", ""), f_title, card_w - 2 * pad, max_lines=6)
    line_h = f_title.getbbox("Ag")[3] + 16

    # Emoji row's vertical gap below the handle is measured from the
    # handle's actual ink extent (descenders included) rather than a fixed
    # pixel offset -- a fixed "+52" only happened to clear the old handle
    # ("@RedditStories" has no descenders); "@DailyStoriesCentral" has a "y"
    # in "Daily" that dipped straight into the emoji row below it.
    # textbbox((0,0), ...) returns ink extents relative to the drawn origin
    # (hy below), NOT relative to each other -- bbox[3] alone (not
    # bbox[3]-bbox[1]) is the distance from hy down to the bottom of the ink.
    handle_bbox = probe.textbbox((0, 0), handle, font=f_handle)
    emoji_gap = 14
    emoji_h = 40 if config.CARD_EMOJI else 0
    hy_offset = 6  # matches the ax/ay-relative "hy = ay + 6" below
    header_content_h = hy_offset + handle_bbox[3] + (emoji_gap + emoji_h if config.CARD_EMOJI else 0)

    avatar_d = 104
    header_h = max(avatar_d, header_content_h, 100)
    card_h = pad + header_h + 26 + len(title_lines) * line_h + 30 + 44 + pad

    img = Image.new("RGBA", (width, card_h + 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(30, 8), (30 + card_w, 8 + card_h)], radius=38, fill=theme["card"])

    ax, ay = 30 + pad, 8 + pad
    _paste_avatar(img, config.CARD_AVATAR, (ax, ay, avatar_d), theme["avatar_bg"])

    hx = ax + avatar_d + 22
    hy = ay + hy_offset
    draw.text((hx, hy), handle, font=f_handle, fill=theme["handle"])
    badge_x = hx + draw.textlength(handle, font=f_handle) + 12
    _verified_badge(draw, badge_x, hy + 8, 34)

    if config.CARD_EMOJI:
        try:
            f_emoji = ImageFont.truetype(str(FONT_EMOJI), 34)
            emoji_y = hy + handle_bbox[3] + emoji_gap
            draw.text((hx, emoji_y), config.CARD_EMOJI, font=f_emoji, embedded_color=True)
        except Exception:
            pass

    y = ay + header_h + 26
    for line in title_lines:
        draw.text((30 + pad, y), line, font=f_title, fill=theme["title"])
        y += line_h

    # Engagement row: heart + comment counts derived from the post's real
    # score where available, plus a share icon+label -- both reference
    # channels use this exact trio (never a thumbs-up, which the earlier
    # version had).
    likes, comments = _engagement_numbers(post)
    fy = y + 22
    fx = 30 + pad
    for label in (f"\u2665 {likes}", f"\U0001F4AC {comments}", "\u2197 Share"):
        try:
            draw.text((fx, fy), label, font=_font(FONT_EMOJI, 30), fill=theme["muted"], embedded_color=True)
        except Exception:
            draw.text((fx, fy), label.split()[-1], font=f_meta, fill=theme["muted"])
        fx += 150

    return img


def generate_card_image(post: dict, out_path: Path, width: int = 1080) -> Path:
    """Static single-frame card (used for stills/previews)."""
    img = _build_card(post, width)
    btn_w, btn_h = 250, 74
    _draw_subscribe(img, (width - 30 - 44 - btn_w, img.height - 44 - btn_h - 4, btn_w, btn_h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    demo = {"title": "My landlord and I did the deed in the laundry room and now we do it regularly."}
    out = generate_card_image(demo, Path("../assets/card_preview.png"))
    print("Saved:", out)
