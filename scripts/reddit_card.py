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

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

# Room reserved around the visible card for the drop shadow to blur into --
# without this the blur clips hard at the canvas edge and looks like a stripe
# instead of a soft glow. Shadow spec (offset/blur/opacity) came from a
# second design opinion (GPT-4o-mini, asked to critique a render of this
# exact card) then tuned by eye at this canvas's actual scale -- its first
# pass gave web-card-scale numbers (e.g. 16px fonts) that didn't match a
# 1080px-wide card using 46-56px fonts, so treat it as a starting point
# rather than gospel.
SHADOW_MARGIN = 50
SHADOW_BLUR = 24
SHADOW_OFFSET = (0, 10)
SHADOW_ALPHA = 70  # 0-255

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
    # Bell sized and gapped from measured text width, not a guessed padding
    # constant -- the earlier fixed 0.55h pad was tuned against "Subscribe"
    # and overlapped once the label switched to the longer "Subscribed".
    bell_size = h * 0.42
    gap = h * 0.18
    bell_pad = (bell_size + gap) if subscribed else 0
    d.text((cx - (tw + bell_pad) / 2, cy - h * 0.27), label, font=f, fill=(255, 255, 255, 255))

    if subscribed:
        bx = cx - (tw + bell_pad) / 2 + tw + gap
        by = cy - bell_size * 0.55
        _draw_bell_icon(d, (bx, by, bell_size), (255, 255, 255, 255))


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


# Footer icons, drawn as matched vector shapes rather than emoji glyphs.
# The earlier version mixed Unicode symbols (heart/speech-bubble/arrow)
# rendered through Windows' Segoe emoji font, which draws each one in a
# completely different visual style with no control over it: a solid-fill
# heart, an outline speech bubble, and an arrow-in-a-blue-box for "share" --
# three unrelated icon languages in one row. Drawing them all here fixes the
# stroke width, proportions, and color treatment to actually match.
ICON_STROKE = 0.10  # stroke width as a fraction of icon size, shared by all three


def _draw_heart_icon(draw, box, color):
    x, y, s = *box[:2], box[2]
    lobe_r = s * 0.28
    cx1, cx2, cy = x + lobe_r, x + s - lobe_r, y + lobe_r * 0.95
    draw.ellipse([(cx1 - lobe_r, cy - lobe_r), (cx1 + lobe_r, cy + lobe_r)], fill=color)
    draw.ellipse([(cx2 - lobe_r, cy - lobe_r), (cx2 + lobe_r, cy + lobe_r)], fill=color)
    draw.polygon([(x, cy), (x + s / 2, y + s * 0.98), (x + s, cy),
                 (x + s * 0.86, cy - lobe_r * 0.3), (x + s * 0.14, cy - lobe_r * 0.3)], fill=color)


def _draw_comment_icon(draw, box, color):
    x, y, s = *box[:2], box[2]
    w = max(2, int(s * ICON_STROKE))
    body_h = s * 0.78
    draw.rounded_rectangle([(x, y), (x + s, y + body_h)], radius=body_h * 0.32, outline=color, width=w)
    tail_x = x + s * 0.28
    draw.polygon([(tail_x, y + body_h - w * 0.5), (tail_x, y + s), (tail_x + s * 0.24, y + body_h - w * 0.5)],
                fill=color)


def _draw_share_icon(draw, box, color):
    """Diagonal arrow breaking out of an open corner bracket -- the same
    "share/open externally" glyph as Twitter/X and iOS, at the same stroke
    weight as the other two icons instead of a colored emoji box."""
    x, y, s = *box[:2], box[2]
    w = max(2, int(s * ICON_STROKE))
    draw.line([(x + s * 0.32, y + s), (x + s * 0.32, y + s * 0.68), (x + s * 0.64, y + s * 0.68)],
             fill=color, width=w, joint="curve")
    ax, ay = x + s * 0.30, y + s * 0.70
    bx, by = x + s * 0.92, y + s * 0.08
    draw.line([(ax, ay), (bx, by)], fill=color, width=w)
    head = s * 0.30
    draw.line([(bx - head, by), (bx, by), (bx, by + head)], fill=color, width=w, joint="curve")


def _draw_bell_icon(draw, box, color):
    """A real bell silhouette, built from separate primitives rather than one
    hand-rolled polygon (the first rewrite got the taper direction backwards
    -- the "flare" was narrower than the dome's shoulders, so it pinched
    inward like a cone instead of widening like a bell): a rounded dome, a
    trapezoid body that widens going down, a wide flat base rim, and a
    clapper hanging just clear of it. Coordinates are fractions of the
    (x, y, size) bounding box."""
    x, y, s = box
    cx = x + s * 0.5

    dome_r = s * 0.26
    dome_cy = y + s * 0.30           # dome's own center -- its shoulders sit here
    body_bottom = y + s * 0.66
    flare_half = dome_r * 1.35        # base is wider than the dome's shoulders

    draw.pieslice([(cx - dome_r, dome_cy - dome_r), (cx + dome_r, dome_cy + dome_r)],
                 start=180, end=360, fill=color)
    draw.polygon([(cx - dome_r, dome_cy), (cx + dome_r, dome_cy),
                 (cx + flare_half, body_bottom), (cx - flare_half, body_bottom)], fill=color)
    rim_h = s * 0.09
    draw.ellipse([(cx - flare_half * 1.08, body_bottom - rim_h / 2),
                 (cx + flare_half * 1.08, body_bottom + rim_h / 2)], fill=color)

    # Small mounting loop at the very top and the clapper hanging below the
    # rim -- both of these, more than the body shape, are what read as
    # "bell" rather than "dome/badge".
    draw.ellipse([(cx - s * 0.035, dome_cy - dome_r - s * 0.06),
                 (cx + s * 0.035, dome_cy - dome_r + s * 0.02)], fill=color)
    clap_r = s * 0.055
    clap_cy = body_bottom + rim_h / 2 + clap_r * 1.3
    draw.ellipse([(cx - clap_r, clap_cy - clap_r), (cx + clap_r, clap_cy + clap_r)], fill=color)


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

    # Subscribe pill sits on the footer row, right-aligned inside the card.
    # Positioned off the visible card's bottom edge, not the canvas height --
    # the canvas extends SHADOW_MARGIN (+ the shadow's vertical offset)
    # past the card itself so the drop shadow has room to blur into.
    visible_bottom = ch - SHADOW_MARGIN - SHADOW_OFFSET[1]
    btn_w, btn_h = 250, 74
    btn_x = width - 30 - 44 - btn_w
    btn_y = visible_bottom - 44 - btn_h - 4
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


def _vcenter_box(anchor_top, anchor_bottom, size):
    """Top-left y for a `size`-tall box whose vertical center matches the
    center of an (anchor_top, anchor_bottom) ink span -- used to align an
    icon against a text glyph's actual visual center rather than a guessed
    pixel offset."""
    return (anchor_top + anchor_bottom) / 2 - size / 2


def _build_card(post: dict, width: int = 1080) -> Image.Image:
    """The static card, without the Subscribe pill (that's drawn per frame so
    it can animate). Returns an RGBA image sized to its content, with a soft
    drop shadow baked in -- SHADOW_MARGIN of transparent canvas surrounds the
    visible card on top/bottom so the blur has room to fall off instead of
    clipping at the image edge."""
    theme = THEMES.get((config.CARD_THEME or "light").lower(), THEMES["light"])
    handle = config.CARD_HANDLE
    pad = 44
    card_w = width - 2 * 30

    f_handle = _font(FONT_BOLD, 46)
    f_title = _font(FONT_SEMI, 56)
    f_meta = _font(FONT_SEMI, 32)

    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    # 6 lines: reference cards run 2-3 full sentences of setup (~20-35 words),
    # not a single short title -- this needs headroom for that, with the
    # existing ellipsis fallback in _wrap still catching genuine overflow.
    title_lines = _wrap(probe, post.get("title", ""), f_title, card_w - 2 * pad, max_lines=6)
    line_h = f_title.getbbox("Ag")[3] + 16

    avatar_d = 104
    handle_bbox = probe.textbbox((0, 0), handle, font=f_handle)
    handle_h = handle_bbox[3] - handle_bbox[1]
    emoji_h = 40 if config.CARD_EMOJI else 0
    header_content_h = handle_h + (14 + emoji_h if emoji_h else 0)
    header_h = max(avatar_d, header_content_h)
    card_h = pad + header_h + 30 + len(title_lines) * line_h + 30 + 44 + pad

    top = SHADOW_MARGIN
    total_w, total_h = width, top + card_h + SHADOW_MARGIN + SHADOW_OFFSET[1]
    card_box = [(30, top), (30 + card_w, top + card_h)]

    # Shadow: a blurred, offset copy of the card's own silhouette, composited
    # first so the crisp card draws on top of it.
    shadow = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sx, sy = SHADOW_OFFSET
    sdraw.rounded_rectangle([(card_box[0][0] + sx, card_box[0][1] + sy),
                            (card_box[1][0] + sx, card_box[1][1] + sy)],
                           radius=38, fill=(0, 0, 0, SHADOW_ALPHA))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))

    img = shadow
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(card_box, radius=38, fill=theme["card"])

    # Header: avatar centered against the handle(+emoji-row) text block as a
    # whole, rather than pinned to the same y as the handle's top -- with an
    # emoji row the old fixed offsets left the avatar visibly high.
    ax = 30 + pad
    hx = ax + avatar_d + 22
    block_top = top + pad
    block_h = header_content_h
    ay = int(_vcenter_box(block_top, block_top + header_h, avatar_d)) if header_h > avatar_d else block_top
    hy = int(_vcenter_box(block_top, block_top + header_h, block_h)) if header_h > block_h else block_top

    _paste_avatar(img, config.CARD_AVATAR, (ax, ay, avatar_d), theme["avatar_bg"])

    draw.text((hx, hy - handle_bbox[1]), handle, font=f_handle, fill=theme["handle"])
    badge_d = 34
    badge_x = hx + draw.textlength(handle, font=f_handle) + 12
    badge_y = _vcenter_box(hy, hy + handle_h, badge_d)
    _verified_badge(draw, badge_x, badge_y, badge_d)

    if config.CARD_EMOJI:
        try:
            f_emoji = ImageFont.truetype(str(FONT_EMOJI), 34)
            draw.text((hx, hy + handle_h + 14), config.CARD_EMOJI, font=f_emoji, embedded_color=True)
        except Exception:
            pass

    y = block_top + header_h + 30
    for line in title_lines:
        draw.text((30 + pad, y), line, font=f_title, fill=theme["title"])
        y += line_h

    # Engagement row: heart + comment counts derived from the post's real
    # score where available, plus a share icon -- both reference channels use
    # exactly this trio (never a thumbs-up, which the earlier version had).
    # All three icons are hand-drawn vector shapes at one shared stroke
    # weight (see _draw_*_icon above) rather than emoji glyphs -- Windows
    # renders those three symbols in three unrelated visual styles with no
    # way to control it, which is what made the footer look inconsistent.
    likes, comments = _engagement_numbers(post)
    icon_s = 40
    fy = y + 22
    fx = 30 + pad
    text_bbox = probe.textbbox((0, 0), "0", font=f_meta)
    text_h = text_bbox[3] - text_bbox[1]
    icon_y = _vcenter_box(fy, fy + text_h, icon_s)
    text_y = fy - text_bbox[1]

    _draw_heart_icon(draw, (fx, icon_y, icon_s), (237, 73, 86, 255))
    tx = fx + icon_s + 14
    draw.text((tx, text_y), likes, font=f_meta, fill=theme["muted"])
    fx = tx + draw.textlength(likes, font=f_meta) + 46

    _draw_comment_icon(draw, (fx, icon_y, icon_s), theme["muted"])
    tx = fx + icon_s + 14
    draw.text((tx, text_y), comments, font=f_meta, fill=theme["muted"])
    fx = tx + draw.textlength(comments, font=f_meta) + 46

    _draw_share_icon(draw, (fx, icon_y, icon_s), theme["muted"])
    tx = fx + icon_s + 14
    draw.text((tx, text_y), "Share", font=f_meta, fill=theme["muted"])

    return img


def generate_card_image(post: dict, out_path: Path, width: int = 1080) -> Path:
    """Static single-frame card (used for stills/previews)."""
    img = _build_card(post, width)
    visible_bottom = img.height - SHADOW_MARGIN - SHADOW_OFFSET[1]
    btn_w, btn_h = 250, 74
    _draw_subscribe(img, (width - 30 - 44 - btn_w, visible_bottom - 44 - btn_h - 4, btn_w, btn_h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    demo = {"title": "My landlord and I did the deed in the laundry room and now we do it regularly."}
    out = generate_card_image(demo, Path("../assets/card_preview.png"))
    print("Saved:", out)
