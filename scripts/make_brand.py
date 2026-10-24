"""Render brand images for the LIFX Switch Backlight integration.

Usage (macOS, needs the Avenir Next system font):
    uv run --with pillow python scripts/make_brand.py custom_components/lifx_switch_backlight/brand
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

S = 2048  # working canvas for the icon (supersampled)

THEMES = {
    "": {  # light UI: grey rim and drop shadow so the white plate reads on white
        "plate": (248, 248, 246, 255),
        "rim": (196, 199, 204, 255),
        "face": (239, 239, 236, 255),
        "face_shade": (222, 222, 219, 255),
        "shadow": 60,
        "text": (43, 47, 54, 255),
        "sub": (110, 116, 126, 255),
    },
    "dark_": {  # dark UI: the white plate already stands out
        "plate": (240, 240, 238, 255),
        "rim": (255, 255, 255, 255),
        "face": (230, 230, 227, 255),
        "face_shade": (212, 212, 209, 255),
        "shadow": 0,
        "text": (240, 242, 245, 255),
        "sub": (170, 176, 186, 255),
    },
}

ON = (52, 110, 255)  # blueprint default ON hue 240
OFF = (255, 84, 56)  # blueprint default OFF hue 0, warmed slightly
HAPTIC = (122, 167, 255)


def _stadium(d: ImageDraw.ImageDraw, cx: float, cy: float, w: float, h: float, fill) -> None:
    d.rounded_rectangle(
        (round(cx - w / 2), round(cy - h / 2), round(cx + w / 2), round(cy + h / 2)),
        radius=round(h / 2),
        fill=fill,
    )


def _glow(img: Image.Image, draw, blur: float) -> None:
    """Composite a blurred layer drawn by `draw(ImageDraw)` under the next shapes."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw(ImageDraw.Draw(layer))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def draw_button(img: Image.Image, u: float, cx: float, cy: float, color, theme: dict) -> None:
    """A pill-shaped button ringed by a backlight, with a center locator dot."""
    w, h, ring = 330 * u, 196 * u, 22 * u
    bright = tuple(min(255, c + 90) for c in color)
    _glow(img, lambda d: _stadium(d, cx, cy, w + ring * 2, h + ring * 2, color + (190,)), 30 * u)
    d = ImageDraw.Draw(img)
    _stadium(d, cx, cy, w, h, color + (255,))
    _stadium(d, cx, cy, w - ring * 0.9, h - ring * 0.9, bright + (255,))
    # recessed face: darker top edge reads as an inset
    _stadium(d, cx, cy, w - ring * 2, h - ring * 2, theme["face_shade"])
    _stadium(d, cx, cy + 6 * u, w - ring * 2, h - ring * 2 - 6 * u, theme["face"])
    _glow(img, lambda d: d.ellipse(_circle(cx, cy, 26 * u), fill=color + (200,)), 10 * u)
    d = ImageDraw.Draw(img)
    d.ellipse(_circle(cx, cy, 15 * u), fill=color + (255,))
    d.ellipse(_circle(cx, cy, 7 * u), fill=bright + (255,))


def _circle(cx: float, cy: float, radius: float):
    return (round(cx - radius), round(cy - radius), round(cx + radius), round(cy + radius))


def draw_icon(theme: dict) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    u = S / 1024  # design units

    def r(*v):
        return tuple(round(x * u) for x in v)

    plate = (282, 40, 742, 984)
    if theme["shadow"]:
        x0, y0, x1, y1 = plate
        _glow(
            img,
            lambda d: d.rounded_rectangle(r(x0, y0 + 14, x1, y1 + 14), radius=round(60 * u), fill=(0, 0, 0, theme["shadow"])),
            18 * u,
        )
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(r(*plate), radius=round(60 * u), fill=theme["rim"])
    x0, y0, x1, y1 = plate
    d.rounded_rectangle(r(x0 + 8, y0 + 8, x1 - 8, y1 - 8), radius=round(53 * u), fill=theme["plate"])

    cx = (x0 + x1) / 2 * u
    draw_button(img, u, cx, (y0 + (y1 - y0) * 0.27) * u, ON, theme)
    draw_button(img, u, cx, (y0 + (y1 - y0) * 0.73) * u, OFF, theme)

    # Haptic arcs on both sides, centered on the plate
    d = ImageDraw.Draw(img)
    cy = (y0 + y1) / 2
    for radius, alpha in ((70, 255), (130, 190), (190, 120)):
        for (ax, start, end) in ((x1, -38, 38), (x0, 142, 218)):
            d.arc(
                r(ax - radius, cy - radius, ax + radius, cy + radius),
                start=start,
                end=end,
                fill=HAPTIC + (alpha,),
                width=round(30 * u),
            )
    return img


def trim_square(img: Image.Image, margin: float = 0.02) -> Image.Image:
    img = img.crop(img.getbbox())
    side = round(max(img.size) * (1 + 2 * margin))
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.alpha_composite(img, ((side - img.width) // 2, (side - img.height) // 2))
    return out


def font(size: int, weight: str) -> ImageFont.FreeTypeFont:
    path = "/System/Library/Fonts/Avenir Next.ttc"
    for index in range(16):
        try:
            f = ImageFont.truetype(path, size, index=index)
        except OSError:
            break
        if f.getname()[1] == weight:
            return f
    raise SystemExit(f"Avenir Next {weight} not found")


def draw_logo(icon: Image.Image, theme: dict, height: int) -> Image.Image:
    """Icon plus a two-line wordmark, trimmed, at the given height."""
    h = 1024
    mark = icon.crop(icon.getbbox())
    mark = mark.resize((round(mark.width * h / mark.height), h), Image.LANCZOS)
    title = font(round(h * 0.40), "Demi Bold")
    sub = font(round(h * 0.21), "Medium")
    gap = round(h * 0.16)
    t_box = title.getbbox("Switch Backlight")
    s_box = sub.getbbox("for LIFX Switch")
    width = mark.width + gap + max(t_box[2], s_box[2]) + 8
    img = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    img.alpha_composite(mark, (0, 0))
    d = ImageDraw.Draw(img)
    x = mark.width + gap
    d.text((x, round(h * 0.16) - t_box[1]), "Switch Backlight", font=title, fill=theme["text"])
    d.text((x, round(h * 0.66) - s_box[1]), "for LIFX Switch", font=sub, fill=theme["sub"])
    img = img.crop(img.getbbox())
    return img.resize((round(img.width * height / img.height), height), Image.LANCZOS)


for prefix, theme in THEMES.items():
    icon = draw_icon(theme)
    square = trim_square(icon)
    square.resize((256, 256), Image.LANCZOS).save(OUT / f"{prefix}icon.png", optimize=True)
    square.resize((512, 512), Image.LANCZOS).save(OUT / f"{prefix}icon@2x.png", optimize=True)
    draw_logo(icon, theme, 128).save(OUT / f"{prefix}logo.png", optimize=True)
    draw_logo(icon, theme, 256).save(OUT / f"{prefix}logo@2x.png", optimize=True)

for p in sorted(OUT.glob("*.png")):
    with Image.open(p) as im:
        print(f"{p.name:22} {im.size[0]}x{im.size[1]} {im.mode} {p.stat().st_size // 1024} KB")
