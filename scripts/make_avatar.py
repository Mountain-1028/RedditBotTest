#!/usr/bin/env python3
"""
Draws a flat-vector mascot avatar for the intro card.

Generated locally rather than fetched from the image gateway so the card never
depends on an external service (and it currently can't -- that project is over
its spend cap). Swap in any square image via CARD_AVATAR in .env.

Usage:
    python3 make_avatar.py                 # default palette
    python3 make_avatar.py --palette mint
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

import config

PALETTES = {
    "coral":  {"bg": (255, 94, 91),  "bg2": (255, 148, 120), "skin": (255, 224, 196), "hair": (58, 42, 64),  "accent": (44, 40, 60)},
    "mint":   {"bg": (46, 204, 168), "bg2": (120, 230, 200), "skin": (255, 226, 200), "hair": (40, 52, 64),  "accent": (30, 44, 52)},
    "violet": {"bg": (138, 92, 246), "bg2": (186, 148, 255), "skin": (255, 222, 194), "hair": (38, 32, 56),  "accent": (32, 26, 48)},
    "sunny":  {"bg": (255, 186, 38), "bg2": (255, 214, 110), "skin": (255, 226, 198), "hair": (62, 44, 34),  "accent": (48, 34, 26)},
}
SS = 4  # supersample factor, for clean edges


def draw_avatar(size: int = 512, palette: str = "coral") -> Image.Image:
    p = PALETTES.get(palette, PALETTES["coral"])
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # background disc with a lighter wedge for depth
    d.ellipse([(0, 0), (S, S)], fill=p["bg"])
    d.pieslice([(0, 0), (S, S)], start=200, end=340, fill=p["bg2"])

    cx = S // 2
    outline = max(2, int(S * 0.012))

    # shoulders
    d.rounded_rectangle([(cx - S * 0.30, S * 0.78), (cx + S * 0.30, S * 1.05)],
                        radius=int(S * 0.14), fill=p["accent"])

    # head
    hw, hh = S * 0.235, S * 0.255
    head = [(cx - hw, S * 0.32), (cx + hw, S * 0.32 + hh * 2)]
    d.ellipse(head, fill=p["skin"], outline=p["accent"], width=outline)

    # hair cap
    d.pieslice([(cx - hw - S * 0.012, S * 0.30), (cx + hw + S * 0.012, S * 0.30 + hh * 2)],
               start=180, end=360, fill=p["hair"])

    # eyes
    ey = S * 0.55
    er = S * 0.043
    for ex in (cx - S * 0.095, cx + S * 0.095):
        d.ellipse([(ex - er, ey - er * 1.15), (ex + er, ey + er * 1.15)], fill=(28, 28, 34))
        d.ellipse([(ex - er * 0.30, ey - er * 0.62), (ex + er * 0.22, ey - er * 0.08)], fill=(255, 255, 255))

    # smile
    d.arc([(cx - S * 0.075, S * 0.60), (cx + S * 0.075, S * 0.70)],
          start=10, end=170, fill=(28, 28, 34), width=outline)

    # headphones: band + cups
    band_r = hw + S * 0.045
    d.arc([(cx - band_r, S * 0.30), (cx + band_r, S * 0.30 + band_r * 2)],
          start=185, end=355, fill=p["accent"], width=int(S * 0.038))
    cup_w, cup_h = S * 0.072, S * 0.105
    for sx in (cx - band_r + S * 0.004, cx + band_r - cup_w - S * 0.004):
        d.rounded_rectangle([(sx, S * 0.50), (sx + cup_w, S * 0.50 + cup_h)],
                            radius=int(S * 0.032), fill=p["accent"])

    # little sparkles, for the "graphic sticker" feel
    for ang, rad, sz in ((35, 0.40, 0.022), (150, 0.42, 0.016), (300, 0.38, 0.013)):
        a = math.radians(ang)
        sx, sy = cx + math.cos(a) * S * rad, cx + math.sin(a) * S * rad
        r = S * sz
        d.polygon([(sx, sy - r), (sx + r * 0.36, sy - r * 0.36), (sx + r, sy),
                   (sx + r * 0.36, sy + r * 0.36), (sx, sy + r),
                   (sx - r * 0.36, sy + r * 0.36), (sx - r, sy),
                   (sx - r * 0.36, sy - r * 0.36)], fill=(255, 255, 255, 235))

    # clip to the circle so nothing spills past the edge
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (S, S)], fill=255)
    img.putalpha(mask)

    return img.resize((size, size), Image.LANCZOS)


def draw_ghost(size: int = 512, palette: str = "violet") -> Image.Image:
    """Alternate mascot: a chunky ghost/blob with a speech tail -- reads more
    like a logo than a face, so it stays legible at small sizes."""
    p = PALETTES.get(palette, PALETTES["violet"])
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.ellipse([(0, 0), (S, S)], fill=p["bg"])
    d.pieslice([(0, 0), (S, S)], start=205, end=335, fill=p["bg2"])

    cx = S // 2
    body = (255, 255, 255, 255)
    ink = p["accent"]

    # rounded body
    top, bot = S * 0.24, S * 0.70
    bw = S * 0.29
    d.ellipse([(cx - bw, top), (cx + bw, top + bw * 2)], fill=body)
    d.rectangle([(cx - bw, top + bw), (cx + bw, bot)], fill=body)

    # scalloped hem
    lobes = 4
    lobe_w = (bw * 2) / lobes
    for i in range(lobes):
        lx = cx - bw + i * lobe_w
        d.ellipse([(lx, bot - lobe_w * 0.52), (lx + lobe_w, bot + lobe_w * 0.52)], fill=body)

    # eyes + smile
    ey = S * 0.45
    er = S * 0.052
    for ex in (cx - S * 0.105, cx + S * 0.105):
        d.ellipse([(ex - er, ey - er * 1.2), (ex + er, ey + er * 1.2)], fill=ink)
        d.ellipse([(ex - er * 0.32, ey - er * 0.68), (ex + er * 0.18, ey - er * 0.12)], fill=(255, 255, 255))
    d.arc([(cx - S * 0.082, S * 0.50), (cx + S * 0.082, S * 0.60)],
          start=15, end=165, fill=ink, width=max(3, int(S * 0.014)))

    # chat tail, to signal "stories"
    tw = S * 0.10
    d.polygon([(cx + bw * 0.55, bot - S * 0.02), (cx + bw * 0.55 + tw, bot + S * 0.06),
               (cx + bw * 0.20, bot + S * 0.01)], fill=body)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (S, S)], fill=255)
    img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


STYLES = {"person": draw_avatar, "ghost": draw_ghost}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--palette", default="coral", choices=sorted(PALETTES))
    ap.add_argument("--style", default="person", choices=sorted(STYLES))
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = Path(args.out) if args.out else config.ASSETS_DIR / f"avatar_{args.style}_{args.palette}.png"
    STYLES[args.style](args.size, args.palette).save(out)
    print("Saved:", out)
