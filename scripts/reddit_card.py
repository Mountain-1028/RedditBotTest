#!/usr/bin/env python3
"""
Renders the intro title card: a social-style rounded card carrying the
channel's own handle, avatar, the story hook, and a decorative engagement
footer. Overlaid on the footage for the opening seconds, then removed so the
captions carry the rest of the video.

The handle is the channel's own (CARD_HANDLE in .env) -- this is channel
branding, not an impersonation of the original poster or of any real account.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

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
    bell_pad = h * 0.55 if subscribed else 0
    d.text((cx - (tw + bell_pad) / 2, cy - h * 0.27), label, font=f, fill=(255, 255, 255, 255))

    if subscribed:  # little bell after the label
        bx = cx - (tw + bell_pad) / 2 + tw + h * 0.16
        by = cy - h * 0.20
        r = h * 0.17
        d.pieslice([(bx - r, by - r), (bx + r, by + r)], start=180, end=360, fill=(255, 255, 255, 255))
        d.rectangle([(bx - r, by), (bx + r, by + r * 0.5)], fill=(255, 255, 255, 255))
        d.ellipse([(bx - r * 0.25, by + r * 0.5), (bx + r * 0.25, by + r)], fill=(255, 255, 255, 255))


def _draw_cursor(img, x, y, size=54):
    d = ImageDraw.Draw(img)
    pts = [(x, y), (x, y + size), (x + size * 0.27, y + size * 0.74),
           (x + size * 0.43, y + size * 1.05), (x + size * 0.58, y + size * 0.98),
           (x + size * 0.42, y + size * 0.68), (x + size * 0.70, y + size * 0.66)]
    d.polygon(pts, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))


def generate_card_frames(post: dict, out_dir: Path, seconds: float = None,
                         fps: int = 30, width: int = 1080) -> tuple:
    """Render the intro card as an animated PNG sequence: the card pops in, the
    Subscribe button breathes, then a cursor moves over and clicks it.

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
    title_lines = _wrap(probe, post.get("title", ""), f_title, card_w - 2 * pad, max_lines=4)
    line_h = f_title.getbbox("Ag")[3] + 16

    avatar_d = 104
    header_h = max(avatar_d, 100)
    card_h = pad + header_h + 26 + len(title_lines) * line_h + 30 + 44 + pad

    img = Image.new("RGBA", (width, card_h + 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(30, 8), (30 + card_w, 8 + card_h)], radius=38, fill=theme["card"])

    ax, ay = 30 + pad, 8 + pad
    _paste_avatar(img, config.CARD_AVATAR, (ax, ay, avatar_d), theme["avatar_bg"])

    hx = ax + avatar_d + 22
    hy = ay + 6
    draw.text((hx, hy), handle, font=f_handle, fill=theme["handle"])
    badge_x = hx + draw.textlength(handle, font=f_handle) + 12
    _verified_badge(draw, badge_x, hy + 8, 34)

    if config.CARD_EMOJI:
        try:
            f_emoji = ImageFont.truetype(str(FONT_EMOJI), 34)
            draw.text((hx, hy + 52), config.CARD_EMOJI, font=f_emoji, embedded_color=True)
        except Exception:
            pass

    y = ay + header_h + 26
    for line in title_lines:
        draw.text((30 + pad, y), line, font=f_title, fill=theme["title"])
        y += line_h

    # decorative engagement row -- placeholder counts, same as the genre uses
    fy = y + 22
    fx = 30 + pad
    for label in ("\u2665 99+", "\U0001F4AC 99+", "\U0001F44D 99+"):
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
