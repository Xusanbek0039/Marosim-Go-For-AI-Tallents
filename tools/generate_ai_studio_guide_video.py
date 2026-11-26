#!/usr/bin/env python3
"""Generate the MarosimGo AI Fashion Studio Motion Design Tutorial Video (1280x720, 30fps, H.264 MP4).

Outputs:
  frontend-user/public/videos/ai-studio-guide.mp4
  frontend-user/public/videos/ai-studio-guide-poster.jpg
"""

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "frontend-user" / "public" / "videos"
OUT_MP4 = OUT_DIR / "ai-studio-guide.mp4"
OUT_POSTER = OUT_DIR / "ai-studio-guide-poster.jpg"
LOGO_PATH = ROOT / "frontend-user" / "public" / "brand" / "logo-icon.png"

W, H = 1280, 720
FPS = 30
DURATION = 18.0
TOTAL_FRAMES = int(FPS * DURATION)

FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
]
FONT_REG_CANDIDATES = [
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _pick_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in candidates:
        if Path(p).is_file():
            try:
                return ImageFont.truetype(p, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


FONTS = {
    "h1": _pick_font(FONT_BOLD_CANDIDATES, 52),
    "h2": _pick_font(FONT_BOLD_CANDIDATES, 40),
    "h3": _pick_font(FONT_BOLD_CANDIDATES, 26),
    "body": _pick_font(FONT_REG_CANDIDATES, 22),
    "small": _pick_font(FONT_REG_CANDIDATES, 17),
    "badge": _pick_font(FONT_BOLD_CANDIDATES, 16),
    "tiny": _pick_font(FONT_BOLD_CANDIDATES, 14),
}


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def ease_out(t: float) -> float:
    t = clamp(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = clamp(t)
    return 3 * t * t - 2 * t * t * t


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def make_background() -> Image.Image:
    """Create the dark midnight glass backdrop with soft MarosimGo indigo/violet/rose glows."""
    bg = Image.new("RGBA", (W, H), (10, 11, 20, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([-140, -160, 560, 480], fill=(99, 102, 241, 70))
    d.ellipse([760, -120, 1420, 520], fill=(168, 85, 247, 65))
    d.ellipse([420, 380, 1180, 960], fill=(236, 72, 153, 45))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=95))
    bg = Image.alpha_composite(bg, glow)
    # Subtle grid dots
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for gx in range(40, W, 64):
        for gy in range(40, H, 64):
            gd.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=(255, 255, 255, 14))
    return Image.alpha_composite(bg, grid)


def draw_gradient_pill(img: Image.Image, box: tuple[int, int, int, int], radius: int = 20, alpha: int = 255) -> None:
    x1, y1, x2, y2 = box
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for x in range(w):
        ratio = x / max(1, w - 1)
        r = int(lerp(99, 217, ratio))
        g = int(lerp(102, 70, ratio))
        b = int(lerp(241, 239, ratio))
        gd.line([(x, 0), (x, h)], fill=(r, g, b, alpha))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    img.paste(grad, (x1, y1), mask)


def draw_glass_card(
    img: Image.Image,
    box: tuple[int, int, int, int],
    radius: int = 28,
    fill=(22, 24, 38, 220),
    outline=(255, 255, 255, 36),
    width: int = 2,
) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    img.alpha_composite(layer)


def draw_cursor(img: Image.Image, x: float, y: float, click_p: float = 0.0) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    if 0.0 < click_p < 1.0:
        rad = int(lerp(10, 44, ease_out(click_p)))
        a = int(lerp(220, 0, ease_out(click_p)))
        d.ellipse([x - rad, y - rad, x + rad, y + rad], outline=(168, 85, 247, a), width=4)
    pts = [(x, y), (x, y + 28), (x + 7, y + 22), (x + 13, y + 34), (x + 18, y + 31), (x + 12, y + 19), (x + 21, y + 19)]
    d.polygon(pts, fill=(255, 255, 255, 250), outline=(15, 17, 28, 255))
    img.alpha_composite(layer)


def draw_garment_icon(d: ImageDraw.ImageDraw, cx: int, cy: int, scale: float, color: tuple[int, int, int, int]) -> None:
    s = scale
    pts = [
        (cx - 24 * s, cy - 42 * s),
        (cx - 48 * s, cy - 22 * s),
        (cx - 36 * s, cy - 4 * s),
        (cx - 24 * s, cy - 14 * s),
        (cx - 28 * s, cy + 48 * s),
        (cx + 28 * s, cy + 48 * s),
        (cx + 24 * s, cy - 14 * s),
        (cx + 36 * s, cy - 4 * s),
        (cx + 48 * s, cy - 22 * s),
        (cx + 24 * s, cy - 42 * s),
        (cx + 10 * s, cy - 34 * s),
        (cx - 10 * s, cy - 34 * s),
    ]
    d.polygon(pts, fill=color)


def draw_person_silhouette(
    d: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    sway: float,
    outfit_color: tuple[int, int, int, int],
    accent_color: tuple[int, int, int, int] | None = None,
) -> None:
    # Head
    hx = cx + int(sway * 10)
    d.ellipse([hx - 32, cy - 132, hx + 32, cy - 68], fill=(238, 200, 176, 255))
    # Hair arc
    d.pieslice([hx - 34, cy - 138, hx + 34, cy - 82], start=180, end=360, fill=(38, 30, 34, 255))
    # Neck
    d.rectangle([hx - 11, cy - 72, hx + 11, cy - 52], fill=(226, 185, 160, 255))
    # Shoulders / outfit
    sx = cx + int(sway * 6)
    torso = [
        (sx - 64, cy - 52),
        (sx + 64, cy - 52),
        (sx + 82, cy + 125),
        (sx - 82, cy + 125),
    ]
    d.polygon(torso, fill=outfit_color)
    if accent_color:
        # Decorative embroidery strip down center
        d.rectangle([sx - 10, cy - 52, sx + 10, cy + 125], fill=accent_color)
        d.line([(sx - 64, cy - 52), (sx, cy - 20), (sx + 64, cy - 52)], fill=accent_color, width=5)


def draw_step_header(img: Image.Image, badge_text: str, title: str, subtitle: str, enter_p: float) -> None:
    dy = int(lerp(28, 0, ease_out(enter_p)))
    alpha = int(lerp(0, 255, ease_out(enter_p)))
    x0, y0 = 76, 158 + dy
    draw_gradient_pill(img, (x0, y0, x0 + 132, y0 + 36), radius=18, alpha=alpha)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((x0 + 22, y0 + 9), badge_text, font=FONTS["badge"], fill=(255, 255, 255, alpha))
    # Title (supports multiline)
    ty = y0 + 54
    for line in title.split("\n"):
        d.text((x0, ty), line, font=FONTS["h2"], fill=(255, 255, 255, alpha))
        ty += 50
    sy = ty + 14
    for line in subtitle.split("\n"):
        d.text((x0, sy), line, font=FONTS["body"], fill=(195, 200, 224, alpha))
        sy += 32
    img.alpha_composite(layer)


def draw_timeline(img: Image.Image, t: float) -> None:
    """Bottom timeline showing current step 1..4 and overall progress."""
    bar_y = H - 56
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Top brand watermark
    d.text((76, 36), "MarosimGo AI Fashion Studio", font=FONTS["badge"], fill=(255, 255, 255, 190))
    d.text((W - 220, 36), "Video qo'llanma", font=FONTS["small"], fill=(180, 188, 220, 180))

    steps = [(2.5, "1. Libos"), (6.2, "2. Kamera"), (10.0, "3. Video / Foto"), (14.0, "4. Natija")]
    seg_w = (W - 152 - 36) // 4
    for idx, (start_t, label) in enumerate(steps):
        sx = 76 + idx * (seg_w + 12)
        end_t = steps[idx + 1][0] if idx < 3 else DURATION
        p = clamp((t - start_t) / max(0.1, end_t - start_t))
        d.rounded_rectangle([sx, bar_y, sx + seg_w, bar_y + 8], radius=4, fill=(255, 255, 255, 34))
        if p > 0:
            fw = max(8, int(seg_w * p))
            draw_gradient_pill(img, (sx, bar_y, sx + fw, bar_y + 8), radius=4)
        col = (255, 255, 255, 235) if p > 0 else (150, 158, 188, 140)
        d.text((sx, bar_y + 16), label, font=FONTS["tiny"], fill=col)
    img.alpha_composite(layer)


def render_frame(base_bg: Image.Image, logo: Image.Image | None, frame_idx: int) -> Image.Image:
    t = frame_idx / FPS
    img = base_bg.copy()

    # ------------------------------------------------------------ Scene 1: Intro (0.0 - 2.5s)
    if t < 2.5:
        p = ease_out(t / 0.7)
        fade_out = 1.0 if t < 2.1 else 1.0 - ease_out((t - 2.1) / 0.4)
        alpha = int(255 * p * fade_out)
        if logo is not None:
            size = int(lerp(92, 124, p))
            resized = logo.resize((size, size), Image.LANCZOS)
            r_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            r_layer.paste(resized, ((W - size) // 2, 175 - (size - 110) // 2), resized)
            img.alpha_composite(r_layer)

        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        title = "MarosimGo AI Fashion Studio"
        sub = "4 oddiy qadamda libosni o'zingizda ko'ring"
        tw = d.textlength(title, font=FONTS["h1"])
        sw = d.textlength(sub, font=FONTS["body"])
        dy = int(lerp(24, 0, p))
        d.text(((W - tw) / 2, 330 + dy), title, font=FONTS["h1"], fill=(255, 255, 255, alpha))
        d.text(((W - sw) / 2, 405 + dy), sub, font=FONTS["body"], fill=(196, 202, 232, alpha))
        img.alpha_composite(layer)
        return img.convert("RGB")

    # ------------------------------------------------------------ Scene 2: Step 1 Garment (2.5 - 6.2s)
    if t < 6.2:
        lt = t - 2.5
        draw_step_header(
            img,
            "1-QADAM",
            "Katalogdan\nlibos tanlang",
            "Ayollar, Erkaklar yoki kategoriya\nbo'yicha o'zingizga yoqqanini bosing.",
            lt / 0.55,
        )
        # Right glass stage: 3 garment cards
        draw_glass_card(img, (570, 128, 1204, 595), radius=32)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((606, 158), "AI uchun kiyimlar", font=FONTS["h3"], fill=(255, 255, 255, 235))
        draw_gradient_pill(img, (980, 156, 1085, 190), radius=16)
        d.text((1000, 165), "Barchasi", font=FONTS["tiny"], fill=(255, 255, 255, 255))
        d.rounded_rectangle([1094, 156, 1174, 190], radius=16, fill=(255, 255, 255, 20))
        d.text((1112, 165), "Ayollar", font=FONTS["tiny"], fill=(200, 205, 225, 200))

        selected = lt >= 1.65
        pop = ease_out((lt - 1.65) / 0.35) if selected else 0.0
        cards = [
            ("Atlas ko'ylak", (236, 72, 153, 220)),
            ("Shohona libos", (99, 102, 241, 240)),
            ("Klassik kostyum", (56, 189, 248, 220)),
        ]
        for i, (name, col) in enumerate(cards):
            cx1 = 606 + i * 194
            cy1 = 220 - (int(12 * pop) if i == 1 else 0)
            cx2 = cx1 + 174
            cy2 = cy1 + 315
            outline = (168, 85, 247, 255) if (i == 1 and selected) else (255, 255, 255, 30)
            ow = 4 if (i == 1 and selected) else 2
            fill = (38, 32, 68, 235) if (i == 1 and selected) else (28, 30, 48, 210)
            d.rounded_rectangle([cx1, cy1, cx2, cy2], radius=22, fill=fill, outline=outline, width=ow)
            d.rounded_rectangle([cx1 + 14, cy1 + 14, cx2 - 14, cy1 + 240], radius=16, fill=(245, 246, 252, 255))
            draw_garment_icon(d, (cx1 + cx2) // 2, cy1 + 128, 1.15, col)
            d.text((cx1 + 16, cy1 + 258), name, font=FONTS["small"], fill=(255, 255, 255, 240))
            if i == 1 and selected:
                draw_gradient_pill(img, (cx2 - 96, cy1 + 22, cx2 - 20, cy1 + 48), radius=12)
                d.text((cx2 - 86, cy1 + 28), "Tanlandi", font=FONTS["tiny"], fill=(255, 255, 255, 255))

        img.alpha_composite(layer)
        # Cursor glides from bottom-right to card #2
        cp = ease_in_out((lt - 0.5) / 1.0)
        cur_x = lerp(1120, 888, cp)
        cur_y = lerp(550, 355, cp)
        click_p = (lt - 1.55) / 0.5 if lt >= 1.55 else 0.0
        draw_cursor(img, cur_x, cur_y, click_p)
        draw_timeline(img, t)
        return img.convert("RGB")

    # ------------------------------------------------------------ Scene 3: Step 2 Camera (6.2 - 10.0s)
    if t < 10.0:
        lt = t - 6.2
        draw_step_header(
            img,
            "2-QADAM",
            "Kamerani yoqing\nva to'g'ri turing",
            "Rozilik belgisini qo'ying va\n1–1.5 m uzoqlikda yorug' joyda turing.",
            lt / 0.55,
        )
        draw_glass_card(img, (570, 128, 1204, 595), radius=32)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)

        checked = lt >= 1.05
        cam_on = lt >= 2.25

        if not cam_on:
            # Consent panel
            d.rounded_rectangle([650, 190, 1124, 535], radius=26, fill=(18, 20, 34, 240), outline=(255, 255, 255, 35), width=2)
            d.text((712, 232), "2-qadam: Kamerani yoqing", font=FONTS["h3"], fill=(255, 255, 255, 245))
            d.text((712, 276), "Tik va yorug' joyda turing, yuzingiz aniq ko'rinsin", font=FONTS["small"], fill=(185, 192, 220, 210))
            # Checkbox
            cb_fill = (99, 102, 241, 255) if checked else (255, 255, 255, 20)
            d.rounded_rectangle([712, 340, 742, 370], radius=8, fill=cb_fill, outline=(255, 255, 255, 110), width=2)
            if checked:
                d.line([(719, 356), (725, 363), (735, 348)], fill=(255, 255, 255, 255), width=4)
            d.text((756, 346), "Kamera va AI qayta ishlashga roziman", font=FONTS["small"], fill=(240, 242, 255, 245))
            # Camera button
            if checked:
                draw_gradient_pill(img, (712, 412, 1062, 474), radius=20)
            else:
                d.rounded_rectangle([712, 412, 1062, 474], radius=20, fill=(255, 255, 255, 30))
            d.text((814, 431), "Kamerani yoqish", font=FONTS["body"], fill=(255, 255, 255, 255 if checked else 130))
            img.alpha_composite(layer)

            if lt < 1.3:
                p1 = ease_in_out(lt / 0.95)
                cx, cy = lerp(1040, 728, p1), lerp(510, 356, p1)
                cp = (lt - 0.98) / 0.45 if lt >= 0.98 else 0.0
            else:
                p2 = ease_in_out((lt - 1.3) / 0.85)
                cx, cy = lerp(728, 888, p2), lerp(356, 444, p2)
                cp = (lt - 2.1) / 0.4 if lt >= 2.1 else 0.0
            draw_cursor(img, cx, cy, cp)
        else:
            # Live camera viewfinder preview
            vp = ease_out((lt - 2.25) / 0.45)
            d.rounded_rectangle([600, 158, 1174, 565], radius=24, fill=(14, 18, 30, 255), outline=(56, 189, 248, 140), width=2)
            # Corner brackets
            for bx, by, sx, sy in [(635, 192, 1, 1), (1139, 192, -1, 1), (635, 530, 1, -1), (1139, 530, -1, -1)]:
                d.line([(bx, by), (bx + 28 * sx, by)], fill=(56, 189, 248, 220), width=4)
                d.line([(bx, by), (bx, by + 28 * sy)], fill=(56, 189, 248, 220), width=4)
            draw_person_silhouette(d, 887, 395, math.sin(lt * 2.5) * 0.2, (72, 82, 112, 255))
            # Badges
            d.rounded_rectangle([624, 174, 836, 208], radius=16, fill=(16, 185, 129, int(210 * vp)))
            d.text((642, 182), "Yorug' joy · 1–1.5 m", font=FONTS["tiny"], fill=(255, 255, 255, 255))
            d.rounded_rectangle([960, 174, 1150, 208], radius=16, fill=(0, 0, 0, 165))
            d.text((978, 182), "Kamera tayyor ✓", font=FONTS["tiny"], fill=(56, 189, 248, 255))
            img.alpha_composite(layer)

        draw_timeline(img, t)
        return img.convert("RGB")

    # ------------------------------------------------------------ Scene 4: Step 3 Record + AI Scan (10.0 - 14.0s)
    if t < 14.0:
        lt = t - 10.0
        draw_step_header(
            img,
            "3-QADAM",
            "Video (4s) yoki\nFoto kiyib ko'ring",
            "Video tugmasini bosing va 4 soniya\nsekin chapga va o'ngga buriling.",
            lt / 0.55,
        )
        draw_glass_card(img, (570, 128, 1204, 595), radius=32)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle([600, 158, 1174, 565], radius=24, fill=(14, 18, 30, 255), outline=(255, 255, 255, 35), width=2)

        sway = math.sin(lt * 3.0)
        if lt < 2.2:
            # Recording countdown 4..1
            sec_left = max(1, 4 - int(lt / 0.55))
            draw_person_silhouette(d, 887, 395, sway, (72, 82, 112, 255))
            # Pulsing red badge
            pulse = 180 + int(75 * abs(math.sin(lt * 8)))
            d.rounded_rectangle([770, 176, 1004, 214], radius=19, fill=(225, 29, 72, 235))
            d.ellipse([788, 189, 800, 201], fill=(255, 255, 255, pulse))
            d.text((810, 186), f"Video yozilmoqda · {sec_left}s", font=FONTS["badge"], fill=(255, 255, 255, 255))
            d.rounded_rectangle([724, 514, 1050, 546], radius=16, fill=(0, 0, 0, 170))
            d.text((748, 522), "Sekin chapga va o'ngga buriling", font=FONTS["tiny"], fill=(255, 255, 255, 230))
            img.alpha_composite(layer)
        else:
            # AI Scan sweep transforming outfit into vibrant royal MarosimGo attire!
            scan_p = ease_in_out((lt - 2.2) / 1.55)
            scan_y = int(lerp(215, 535, scan_p))
            # Draw BEFORE on full canvas
            before = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw_person_silhouette(ImageDraw.Draw(before), 887, 395, sway * 0.5, (72, 82, 112, 255))
            # Draw AFTER (dressed in royal indigo/gold embroidered garment)
            after = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw_person_silhouette(
                ImageDraw.Draw(after),
                887,
                395,
                sway * 0.5,
                (99, 102, 241, 255),
                accent_color=(250, 204, 21, 255),
            )
            # Composite after above scan_y, before below scan_y (preserving alpha!)
            img.alpha_composite(layer)
            after_crop = after.crop((600, 158, 1174, max(159, scan_y)))
            before_crop = before.crop((600, min(564, scan_y), 1174, 565))
            img.alpha_composite(after_crop, (600, 158))
            img.alpha_composite(before_crop, (600, min(564, scan_y)))

            # Glowing scan laser line + AI label
            beam = Image.new("RGBA", img.size, (0, 0, 0, 0))
            bd = ImageDraw.Draw(beam)
            bd.rectangle([620, scan_y - 4, 1154, scan_y + 4], fill=(192, 132, 252, 240))
            bd.rectangle([620, scan_y - 16, 1154, scan_y + 16], fill=(168, 85, 247, 75))
            bd.rounded_rectangle([742, 176, 1032, 214], radius=19, fill=(15, 17, 32, 215), outline=(168, 85, 247, 220), width=2)
            bd.text((766, 186), "MarosimGo AI kiydirmoqda...", font=FONTS["badge"], fill=(255, 255, 255, 255))
            img.alpha_composite(beam)

        draw_timeline(img, t)
        return img.convert("RGB")

    # ------------------------------------------------------------ Scene 5: Step 4 Result + Player + Buy (14.0 - 18.0s)
    lt = t - 14.0
    draw_step_header(
        img,
        "4-QADAM",
        "Ko'ring, yuklab oling\nva buyurtma bering",
        "Natija «Saqlangan obrazlarim» da qoladi.\nMarosimGo Player'da 0.5x ko'ring!",
        lt / 0.55,
    )
    draw_glass_card(img, (570, 128, 1204, 595), radius=32)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Result player frame
    d.rounded_rectangle([600, 154, 1174, 490], radius=24, fill=(14, 18, 30, 255), outline=(168, 85, 247, 160), width=2)
    draw_person_silhouette(
        d,
        887,
        360,
        math.sin(lt * 2.4) * 0.45,
        (99, 102, 241, 255),
        accent_color=(250, 204, 21, 255),
    )
    # Top badges inside MarosimGo Player
    draw_gradient_pill(img, (620, 172, 774, 204), radius=16)
    d.text((634, 180), "MarosimGo Player", font=FONTS["tiny"], fill=(255, 255, 255, 255))
    d.rounded_rectangle([1048, 172, 1154, 204], radius=16, fill=(16, 185, 129, 220))
    d.text((1068, 180), "Tayyor ✓", font=FONTS["tiny"], fill=(255, 255, 255, 255))

    # Player progress bar at bottom of video frame
    prog = clamp((lt % 2.8) / 2.8)
    d.rounded_rectangle([622, 456, 1152, 464], radius=4, fill=(255, 255, 255, 55))
    draw_gradient_pill(img, (622, 456, 622 + max(12, int(530 * prog)), 464), radius=4)

    # Action buttons below player
    d.rounded_rectangle([600, 510, 776, 566], radius=20, fill=(255, 255, 255, 22), outline=(255, 255, 255, 50), width=2)
    d.text((630, 528), "0.5x ko'rish", font=FONTS["small"], fill=(255, 255, 255, 240))

    d.rounded_rectangle([792, 510, 984, 566], radius=20, fill=(255, 255, 255, 22), outline=(255, 255, 255, 50), width=2)
    d.text((814, 528), "Yuklab olish MP4", font=FONTS["small"], fill=(255, 255, 255, 240))

    draw_gradient_pill(img, (1000, 510, 1174, 566), radius=20)
    d.text((1036, 528), "Sotib olish", font=FONTS["badge"], fill=(255, 255, 255, 255))

    img.alpha_composite(layer)

    # Cursor glides to "Sotib olish" button and clicks
    cp = ease_in_out((lt - 0.6) / 1.1)
    cx = lerp(740, 1088, cp)
    cy = lerp(420, 538, cp)
    click_p = (lt - 1.75) / 0.55 if lt >= 1.75 else 0.0
    draw_cursor(img, cx, cy, click_p)
    draw_timeline(img, t)
    return img.convert("RGB")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base_bg = make_background()
    logo = Image.open(LOGO_PATH).convert("RGBA") if LOGO_PATH.is_file() else None

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{W}x{H}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(OUT_MP4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for i in range(TOTAL_FRAMES):
            frame = render_frame(base_bg, logo, i)
            if i == int(12.8 * FPS):  # Crisp poster frame during AI transformation sweep
                frame.save(OUT_POSTER, format="JPEG", quality=90, optimize=True)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode(errors="ignore") if proc.stderr else ""
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed ({rc}): {stderr[-400:]}")
    finally:
        if proc.poll() is None:
            proc.kill()

    size_kb = OUT_MP4.stat().st_size / 1024
    print(f"Generated {OUT_MP4} ({size_kb:.1f} KB) and {OUT_POSTER}")


if __name__ == "__main__":
    main()
