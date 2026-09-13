#!/usr/bin/env python3
"""
Renders a generic "Reddit post card" graphic (subreddit name, title, a plain
placeholder avatar, and simple upvote/comment icons) as a static PNG for the
top portion of the video. Deliberately generic UI shapes only -- no Reddit
logo/mascot -- since this is an original layout evoking the post-card format,
not a reproduction of Reddit's actual branding.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(r"C:\Windows\Fonts")
FONT_BOLD = FONT_DIR / "segoeuib.ttf"
FONT_SEMIBOLD = FONT_DIR / "seguisb.ttf"
FONT_REGULAR = FONT_DIR / "segoeui.ttf"

BG = (255, 255, 255)
TEXT_DARK = (26, 26, 27)
TEXT_GRAY = (120, 124, 126)
AVATAR_COLOR = (90, 100, 120)
ICON_GRAY = (135, 138, 140)
BORDER = (237, 239, 241)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) == max_lines - 1:
            break
    if current:
        lines.append(current)

    if len(lines) == max_lines and words:
        consumed = len(" ".join(lines).split())
        if consumed < len(words):
            last = lines[-1]
            while draw.textlength(last + "...", font=font) > max_width and len(last) > 1:
                last = last[:-1].rstrip()
            lines[-1] = last + "..."
    return lines


def generate_card_image(post: dict, out_path: Path, width: int = 1080, height: int = 480) -> Path:
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    pad = 56
    draw.line([(0, height - 1), (width, height - 1)], fill=BORDER, width=2)

    # Avatar: plain generic circle, no logo/mascot.
    avatar_d = 72
    avatar_xy = (pad, pad)
    draw.ellipse([avatar_xy, (avatar_xy[0] + avatar_d, avatar_xy[1] + avatar_d)], fill=AVATAR_COLOR)

    sub_font = _font(FONT_BOLD, 38)
    meta_font = _font(FONT_REGULAR, 30)
    text_x = avatar_xy[0] + avatar_d + 24
    draw.text((text_x, pad + 4), f"r/{post.get('subreddit', 'stories')}", font=sub_font, fill=TEXT_DARK)
    draw.text((text_x, pad + 4 + 44), "Posted by u/original-poster", font=meta_font, fill=TEXT_GRAY)

    # Title, wrapped and vertically centered in the space below the header row.
    title_font = _font(FONT_SEMIBOLD, 52)
    title_top = pad + avatar_d + 30
    title_area_h = height - title_top - 100
    lines = _wrap_text(draw, post.get("title", ""), title_font, width - 2 * pad, max_lines=3)
    line_h = title_font.getbbox("Ag")[3] + 14
    block_h = line_h * len(lines)
    y = title_top + max(0, (title_area_h - block_h) // 2)
    for line in lines:
        draw.text((pad, y), line, font=title_font, fill=TEXT_DARK)
        y += line_h

    # Footer row: simple upvote arrow + score, generic comment bubble.
    icon_font = _font(FONT_SEMIBOLD, 32)
    footer_y = height - 70
    ax, ay = pad, footer_y
    draw.polygon([(ax + 14, ay), (ax, ay + 20), (ax + 28, ay + 20)], fill=ICON_GRAY)
    score = post.get("score")
    score_text = _format_score(score) if score else "Vote"
    draw.text((ax + 40, ay - 6), score_text, font=icon_font, fill=ICON_GRAY)

    cx = ax + 40 + int(draw.textlength(score_text, font=icon_font)) + 48
    draw.rounded_rectangle([(cx, ay - 4), (cx + 34, ay + 22)], radius=8, outline=ICON_GRAY, width=3)
    draw.polygon([(cx + 6, ay + 22), (cx + 6, ay + 30), (cx + 14, ay + 22)], fill=BG, outline=ICON_GRAY)
    draw.text((cx + 46, ay - 6), "Comments", font=icon_font, fill=ICON_GRAY)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _format_score(score) -> str:
    if score is None:
        return "Vote"
    if score >= 1000:
        return f"{score / 1000:.1f}k"
    return str(score)


if __name__ == "__main__":
    demo_post = {
        "subreddit": "AmItheAsshole",
        "title": "AITA for not wanting to go a childfree wedding my husband already RSVP'd us to",
        "score": 4200,
    }
    out = generate_card_image(demo_post, Path("../assets/card_test.png"))
    print("Saved:", out)
