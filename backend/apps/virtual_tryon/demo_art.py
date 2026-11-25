"""Procedurally drawn demo garments for the try-on catalogue (``manage.py seed_tryon_demo``).

These are clearly labelled *samples* so the live camera can be tried before sellers upload real
product cut-outs. Each garment is a set of transparent layers with the same anchor contract as
real uploads (see ``assets.ANCHOR_KEYS``): a body layer and optional sleeve layers.

Body layer: 600 x 1300 px. Wearer's right shoulder joint (image left) at (0.365, 0.13), left at
(0.635, 0.13), hip joints at (0.405, 0.37) / (0.595, 0.37). Sleeve layers: 160 x 420 px, the bone runs from
(0.5, 0.06) to (0.5, 0.94), drawn at the body layer's pixel scale.
"""

import io
import math
import random
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 2  # supersampling for smooth edges
BW, BH = 600, 1300
LW, LH = 160, 420
# Anchors sit on the *joints* MediaPipe reports (inside the body outline), so the drawn garment
# reaches ~15–20 % past them on each side — as fabric does past the shoulder and hip joints.
BODY_ANCHORS = {
    "right_shoulder": [0.365, 0.13],
    "left_shoulder": [0.635, 0.13],
    "right_hip": [0.405, 0.37],
    "left_hip": [0.595, 0.37],
}
LIMB_ANCHORS = {"start": [0.5, 0.06], "end": [0.5, 0.94]}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _shade(size, centre_x: float, half: float, depth=0.32, top=1.04, bottom=0.9) -> Image.Image:
    """Cylinder-like light: bright in the middle, darker to the sides and towards the hem."""
    w, h = size
    row = Image.new("L", (w, 1))
    row.putdata([int(255 * max(0.0, 1 - depth * min(1.0, ((x - centre_x) / half) ** 2))) for x in range(w)])
    col = Image.new("L", (1, h))
    col.putdata([int(255 * min(1.0, (top + (bottom - top) * y / h) / top)) for y in range(h)])
    return ImageChops.multiply(row.resize((w, h)), col.resize((w, h)))


def _noise(size, sigma: float, scale: int = 1) -> Image.Image:
    """Grey (128-centred) noise; ``scale`` > 1 gives softer, larger blotches."""
    w, h = size
    small = Image.effect_noise((max(1, w // scale), max(1, h // scale)), sigma)
    return small.resize(size, Image.BICUBIC) if scale > 1 else small


def _texture(size, kind: str) -> Image.Image | None:
    """Fabric surface as a grey overlay map (128 = no change)."""
    w, h = size
    if kind == "satin":  # smooth, with slow uneven sheen
        return ImageChops.add(_noise(size, 7, 60), _noise(size, 4), scale=2, offset=0)
    if kind == "wool":  # fine twill: diagonal ribs + fibre noise
        tex = Image.new("L", size, 128)
        d = ImageDraw.Draw(tex)
        for x in range(-h, w, 5 * SS):
            d.line((x, 0, x + h, h), fill=118, width=SS)
        return ImageChops.add(tex, _noise(size, 10), scale=2, offset=0)
    if kind == "cotton":  # plain weave
        tex = Image.new("L", size, 128)
        d = ImageDraw.Draw(tex)
        for y in range(0, h, 3 * SS):
            d.line((0, y, w, y), fill=122)
        for x in range(0, w, 3 * SS):
            d.line((x, 0, x, h), fill=124)
        return ImageChops.add(tex, _noise(size, 8), scale=2, offset=0)
    if kind == "silk":  # long horizontal streaks of light
        streak = Image.effect_noise((max(1, w // 60), h // 2), 30).resize(size, Image.BICUBIC)
        return ImageChops.add(streak, _noise(size, 6), scale=2, offset=0)
    return None


class Canvas:
    """Draw in final-pixel coordinates; stored supersampled."""

    def __init__(self, w: int, h: int, texture: str | None = None):
        self.w, self.h = w, h
        self.texture = texture
        self.img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))

    def mask(self, polygons=(), ellipses=()) -> Image.Image:
        m = Image.new("L", self.img.size, 0)
        d = ImageDraw.Draw(m)
        for poly in polygons:
            d.polygon([(x * SS, y * SS) for x, y in poly], fill=255)
        for x0, y0, x1, y1 in ellipses:
            d.ellipse((x0 * SS, y0 * SS, x1 * SS, y1 * SS), fill=255)
        return m

    def fill(
        self, mask: Image.Image, color: str, centre_x=None, half=None, pattern: Image.Image | None = None, depth=0.32
    ):
        base = pattern.copy() if pattern is not None else Image.new("RGB", self.img.size, _rgb(color))
        shade = _shade(self.img.size, (centre_x or self.w / 2) * SS, (half or self.w / 2) * SS, depth)
        lit = ImageChops.multiply(base.convert("RGB"), Image.merge("RGB", (shade, shade, shade)))
        layer = lit.convert("RGBA")
        layer.putalpha(mask)
        self.img.alpha_composite(layer)

    def _overlay(self, paint):
        """Draw on a clear layer and blend it in — drawing straight on RGBA would overwrite alpha."""
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        paint(ImageDraw.Draw(layer))
        # Never paint outside the garment: keep only where the garment already is.
        alpha = ImageChops.multiply(layer.getchannel("A"), self.img.getchannel("A").point(lambda v: 255 if v else 0))
        layer.putalpha(alpha)
        self.img.alpha_composite(layer)

    def line(self, pts, color, width):
        scaled = [(x * SS, y * SS) for x, y in pts]
        self._overlay(lambda d: d.line(scaled, fill=color, width=int(width * SS), joint="curve"))

    def dot(self, x, y, r, color):
        box = ((x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS)
        self._overlay(lambda d: d.ellipse(box, fill=color))

    def folds(self, top: float, bottom: float, cx: float, spread_top: float, spread_bottom: float, n: int = 9):
        """Soft fabric folds: alternating light / shadow streaks fanning from ``top`` to ``bottom``."""
        streaks = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(streaks)
        for i in range(n):
            t = (i + 0.5) / n * 2 - 1  # -1..1 across
            x0, x1 = cx + t * spread_top, cx + t * spread_bottom
            light = i % 2 == 0
            color = (255, 255, 255, 62) if light else (10, 14, 30, 84)
            width = (spread_bottom / n) * (0.55 if light else 0.4)
            d.polygon(
                [
                    ((x0 - width * 0.15) * SS, top * SS),
                    ((x0 + width * 0.15) * SS, top * SS),
                    ((x1 + width / 2) * SS, bottom * SS),
                    ((x1 - width / 2) * SS, bottom * SS),
                ],
                fill=color,
            )
        streaks = streaks.filter(ImageFilter.GaussianBlur(9 * SS))
        self._clip_composite(streaks)

    def sheen(self, x: float, top: float, bottom: float, width: float, strength: int = 60):
        """A long satin highlight."""
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse(
            ((x - width) * SS, top * SS, (x + width) * SS, bottom * SS), fill=(255, 255, 255, strength)
        )
        self._clip_composite(layer.filter(ImageFilter.GaussianBlur(width * 0.8 * SS)))

    def lace(self, box: tuple[float, float, float, float], color: str, step: float = 13):
        """Tiny floral dots (lace / embroidery) inside ``box``."""
        x0, y0, x1, y1 = box
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        rgb = _rgb(color)
        row = 0
        y = y0
        while y < y1:
            x = x0 + (step / 2 if row % 2 else 0)
            while x < x1:
                r = 2.2 * SS
                for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                    cx, cy = x * SS + dx * r * 1.2, y * SS + dy * r * 1.2
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*rgb, 150))
                x += step
            y += step
            row += 1
        self._clip_composite(layer)

    def _clip_composite(self, layer: Image.Image):
        alpha = ImageChops.multiply(layer.getchannel("A"), self.img.getchannel("A"))
        layer.putalpha(alpha)
        self.img.alpha_composite(layer)

    def result(self, volume: bool = True) -> Image.Image:
        tex = _texture(self.img.size, self.texture) if self.texture else None
        if tex is not None:
            rgb = self.img.convert("RGB")
            textured = ImageChops.overlay(rgb, Image.merge("RGB", (tex, tex, tex)))
            mixed = Image.blend(rgb, textured, 0.55).convert("RGBA")
            mixed.putalpha(self.img.getchannel("A"))
            self.img = mixed
        if volume:
            # Darker towards the silhouette's edges: reads as a rounded, filled garment.
            alpha = self.img.getchannel("A")
            inner = alpha.filter(ImageFilter.GaussianBlur(14 * SS))
            edge = ImageChops.subtract(alpha, inner).point(lambda v: min(255, int(v * 1.1)))
            shadow = Image.new("RGBA", self.img.size, (8, 12, 28, 0))
            shadow.putalpha(edge)
            self._clip_composite(shadow)
        return self.img.resize((self.w, self.h), Image.LANCZOS)


def _curve(p0, p1, p2, n=24):
    """Quadratic Bézier points."""
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1],
        )
        for t in (i / n for i in range(n + 1))
    ]


def _ikat(size, colors) -> Image.Image:
    """Atlas-like vertical bands with zig-zag edges."""
    w, h = size
    img = Image.new("RGB", size, _rgb(colors[0]))
    d = ImageDraw.Draw(img)
    band = 34 * SS
    for i, x in enumerate(range(-band, w + band, band)):
        color = _rgb(colors[i % len(colors)])
        pts = []
        for y in range(0, h + 40 * SS, 20 * SS):
            off = (10 * SS) if (y // (20 * SS)) % 2 else -(10 * SS)
            pts.append((x + off, y))
        right = [(px + band * 0.6, py) for px, py in reversed(pts)]
        d.polygon(pts + right, fill=color)
    # Abr: threads dyed before weaving, so every few rows the pattern shifts and the edges feather.
    rng = random.Random(7)  # noqa: S311 — art, not security
    out = Image.new("RGB", size)
    strip = 5 * SS
    for y in range(0, h, strip):
        out.paste(img.crop((0, y, w, y + strip)), (rng.randint(-5, 5) * SS, y))
    feather = out.resize((max(1, w // 5), h), Image.BILINEAR).resize(size, Image.BICUBIC)
    return Image.blend(out, feather, 0.6)


def _stripes(size, colors, width=18) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, _rgb(colors[0]))
    d = ImageDraw.Draw(img)
    for i, x in enumerate(range(0, w, width * SS)):
        d.rectangle((x, 0, x + width * SS * 0.5, h), fill=_rgb(colors[i % len(colors)]))
    return img


@dataclass
class Design:
    slug: str
    category: str
    name: str
    description: str
    price: int
    color: str
    accent: str
    top: str  # gown | strapless | jacket | shirt | robe | atlas
    bottom: str  # ballgown | mermaid | aline | midi | trousers | robe | none
    sleeves: str = "none"  # none | short | long
    sleeve_color: str | None = None
    bottom_color: str | None = None  # trousers under a shirt
    lace: bool = False  # lace / embroidery on the bodice
    texture: str = "satin"  # satin | wool | cotton | silk
    pattern: str | None = None  # ikat | stripes
    pattern_colors: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)
    colors: list[dict] = field(default_factory=list)

    @property
    def legs(self) -> str:
        return "joined"  # trousers live in their own LOWER_BODY layer


def _pattern(design: Design, size):
    if design.pattern == "ikat":
        return _ikat(size, design.pattern_colors)
    if design.pattern == "stripes":
        return _stripes(size, design.pattern_colors)
    return None


TROUSERS = [
    (212, 440),
    (388, 440),
    (392, 560),
    (378, 1245),
    (318, 1245),
    (306, 640),
    (294, 640),
    (282, 1245),
    (222, 1245),
    (208, 560),
]
# Trouser layer anchors: hip joints as on the body layer, knees two thirds down to the hem (ankle).
LOWER_ANCHORS = {
    "right_hip": [0.405, 0.37],
    "left_hip": [0.595, 0.37],
    "right_knee": [0.41, 0.665],
    "left_knee": [0.59, 0.665],
    "legs": "split",
}


def draw_lower(design: Design) -> Image.Image | None:
    """Trousers as their own layer (each leg then follows its own hip → knee → ankle)."""
    if design.bottom != "trousers":
        return None
    c = Canvas(BW, BH, texture=design.texture)
    c.fill(c.mask([TROUSERS]), design.bottom_color or design.color, half=230)
    for x in (250, 350):  # pressed creases
        c.sheen(x, 600, 1240, 9, 45)
    c.line([(300, 640), (300, 450)], "#00000045", 3)  # fly
    c.line([(214, 452), (386, 452)], "#00000030", 2)  # waistband
    return c.result()


def draw_body(design: Design) -> Image.Image:
    c = Canvas(BW, BH, texture=design.texture)
    pat = _pattern(design, c.img.size)
    col, acc = design.color, design.accent
    lower, shapes = [], []

    # ---- lower part
    b = design.bottom
    if b == "ballgown":
        lower.append(
            [
                (238, 405),
                (362, 405),
                *_curve((372, 470), (560, 900), (575, 1240)),
                *_curve((575, 1240), (300, 1290), (25, 1240)),
                *_curve((25, 1240), (40, 900), (228, 470)),
            ]
        )
    elif b == "mermaid":
        lower.append(
            [
                (232, 405),
                (368, 405),
                (388, 520),
                (376, 860),
                *_curve((376, 860), (420, 1080), (490, 1250)),
                (110, 1250),
                *_curve((110, 1250), (180, 1080), (224, 860)),
                (212, 520),
            ]
        )
    elif b == "aline":
        lower.append(
            [
                (236, 405),
                (364, 405),
                (390, 520),
                (470, 1230),
                *_curve((470, 1230), (300, 1260), (130, 1230)),
                (210, 520),
            ]
        )
    elif b == "midi":
        lower.append(
            [(236, 405), (364, 405), (392, 520), (450, 860), *_curve((450, 860), (300, 885), (150, 860)), (208, 520)]
        )
    elif b == "trousers":
        pass  # own layer: draw_lower()
    elif b == "robe":
        lower.append([(196, 300), (404, 300), (440, 700), (468, 1150), (132, 1150), (160, 700)])

    # ---- upper part
    t = design.top
    if t in ("gown", "atlas"):
        neck = _curve((262, 150), (300, 250), (338, 150))
        shapes.append([(196, 150), (262, 150), *neck, (404, 150), (398, 240), (366, 410), (234, 410), (202, 240)])
    elif t == "strapless":
        top_line = _curve((206, 238), (250, 205), (300, 236)) + _curve((300, 236), (350, 205), (394, 238))
        shapes.append([*top_line, (368, 410), (232, 410)])
    elif t == "jacket":
        shapes.append(
            [(188, 148), (262, 140), (300, 330), (338, 140), (412, 148), (408, 300), (396, 600), (204, 600), (192, 300)]
        )
    elif t == "shirt":
        shapes.append(
            [(190, 150), (268, 136), (300, 175), (332, 136), (410, 150), (404, 300), (390, 580), (210, 580), (196, 300)]
        )
    elif t == "robe":
        shapes.append([(186, 150), (266, 140), (300, 260), (334, 140), (414, 150), (418, 320), (182, 320)])

    c.fill(c.mask(lower + shapes), col, half=230, pattern=pat)

    # ---- fabric: folds, satin sheen, lace
    fold = {
        "ballgown": (420, 1250, 300, 70, 270, 13),
        "mermaid": (870, 1250, 300, 70, 180, 9),
        "aline": (420, 1235, 300, 60, 165, 9),
        "midi": (420, 870, 300, 60, 145, 7),
        "robe": (620, 1150, 300, 130, 165, 9),
    }.get(b)
    if fold:
        c.folds(*fold)
    if design.pattern is None and t in ("gown", "strapless"):
        c.sheen(268, 230, 1150 if b != "midi" else 860, 26, 55)
    if design.lace:
        c.lace((214, 238 if t == "strapless" else 170, 386, 400), design.accent)

    # ---- construction: seams, shadow under the bust, tulle
    if t in ("gown", "strapless", "atlas"):
        for side in (-1, 1):  # princess seams
            c.line(_curve((300 + side * 52, 236), (300 + side * 40, 330), (300 + side * 46, 408)), "#0000002a", 2.2)
        shadow = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse((220 * SS, 300 * SS, 380 * SS, 336 * SS), fill=(10, 12, 25, 55))
        c._clip_composite(shadow.filter(ImageFilter.GaussianBlur(10 * SS)))
    if b == "ballgown":
        # Outer tulle: a translucent, slightly wider layer — the body shows through its edge.
        rng = random.Random(design.slug)  # noqa: S311 — art, not security
        tulle = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
        poly = [
            (230, 420),
            (370, 420),
            *_curve((380, 480), (585, 900), (596, 1262)),
            *_curve((596, 1262), (300, 1300), (4, 1262)),
            *_curve((4, 1262), (15, 900), (220, 480)),
        ]
        ImageDraw.Draw(tulle).polygon([(x * SS, y * SS) for x, y in poly], fill=(255, 255, 255, 70))
        tulle = tulle.filter(ImageFilter.GaussianBlur(2 * SS))
        d = ImageDraw.Draw(tulle)
        for _ in range(420):  # sequins
            x, y = rng.uniform(60, 540), rng.uniform(440, 1230)
            rr = rng.uniform(0.8, 2.0) * SS
            d.ellipse((x * SS - rr, y * SS - rr, x * SS + rr, y * SS + rr), fill=(255, 255, 255, rng.randint(120, 230)))
        mask = c.mask([poly])
        tulle.putalpha(ImageChops.multiply(tulle.getchannel("A"), mask))
        c.img.alpha_composite(tulle)

    # ---- details
    if t == "strapless":
        c.line(_curve((206, 238), (250, 205), (300, 236)) + _curve((300, 236), (350, 205), (394, 238)), acc, 5)
        for x in range(214, 390, 14):
            c.dot(x, 410, 3.2, acc)
    if t in ("gown", "atlas"):
        c.line(_curve((262, 150), (300, 250), (338, 150)), acc, 5)
        c.line([(234, 410), (366, 410)], acc, 7)
    if b in ("ballgown", "mermaid", "aline") and design.pattern is None:
        hem_y = {"ballgown": 1240, "mermaid": 1248, "aline": 1228}[b]
        span = {"ballgown": (40, 560), "mermaid": (120, 480), "aline": (140, 460)}[b]
        for x in range(span[0], span[1], 16):
            c.dot(x, hem_y - 8 + 6 * math.sin(x / 9), 4, acc)
    if t == "jacket":
        # shirt + tie in the V, lapels, buttons
        c.fill(c.mask([[(264, 142), (336, 142), (300, 328)]]), "#F8FAFC", depth=0.1)
        c.fill(c.mask([[(292, 170), (308, 170), (312, 300), (300, 322), (288, 300)]]), acc, depth=0.1)
        c.line([(262, 140), (282, 250), (300, 330)], "#00000055", 4)
        c.line([(338, 140), (318, 250), (300, 330)], "#00000055", 4)
        for y in (420, 500):
            c.dot(300, y, 6, "#0B1220")
        # pocket flaps, breast pocket with a square, lapel highlight, stitching
        for x0 in (222, 318):
            c.fill(c.mask([[(x0, 540), (x0 + 62, 540), (x0 + 62, 556), (x0, 556)]]), design.color, depth=0.05)
            c.line([(x0, 540), (x0 + 62, 540)], "#ffffff22", 1.5)
            c.line([(x0, 557), (x0 + 62, 557)], "#00000060", 2)
        c.line([(332, 250), (372, 246)], "#00000060", 2)
        c.fill(
            c.mask([[(338, 238), (346, 230), (356, 236), (366, 232), (368, 246), (336, 248)]]), "#F1F5F9", depth=0.05
        )
        c.sheen(276, 150, 320, 7, 70)
        c.sheen(324, 150, 320, 7, 45)
        c.line([(300, 330), (300, 600)], "#00000040", 3)
    if t == "shirt":
        c.fill(
            c.mask([[(268, 136), (300, 175), (286, 200)], [(332, 136), (300, 175), (314, 200)]]), "#E2E8F0", depth=0.1
        )
        for y in range(215, 580, 55):
            c.dot(300, y, 4, "#94A3B8")
        shadow = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).polygon(
            [(270 * SS, 140 * SS), (300 * SS, 182 * SS), (330 * SS, 140 * SS), (300 * SS, 215 * SS)],
            fill=(15, 23, 42, 70),
        )
        c._clip_composite(shadow.filter(ImageFilter.GaussianBlur(5 * SS)))
        c.line([(330, 250), (372, 250), (370, 300), (351, 308), (332, 300), (330, 250)], "#0000003a", 2)
        c.line([(300, 175), (300, 580)], "#94A3B880", 2)
    if t == "robe":
        c.line([(266, 140), (300, 300), (300, 1150)], acc, 10)
        c.line([(334, 140), (300, 300)], acc, 10)
        c.line([(140, 1140), (460, 1140)], acc, 12)
        c.fill(c.mask([[(222, 560), (378, 560), (378, 600), (222, 600)]]), acc, depth=0.15)  # belt
    return c.result()


def draw_sleeve(design: Design, part: str) -> Image.Image | None:
    """``part``: upper | fore. None when the design has no sleeve for that bone."""
    if design.sleeves == "none" or (design.sleeves == "short" and part == "fore"):
        return None
    c = Canvas(LW, LH, texture=design.texture)
    pat = _pattern(design, c.img.size)
    sx, sy, ey = LW / 2, LH * 0.06, LH * 0.94
    color = design.sleeve_color or design.color
    if part == "upper":
        w0, w1 = 48, 40
        end = ey if design.sleeves == "long" else sy + (ey - sy) * 0.55
        poly = [(sx - w0, sy), (sx + w0, sy), (sx + w1, end + 6), (sx - w1, end + 6)]
        ell = [(sx - w0, sy - 34, sx + w0, sy + 34)]  # rounded shoulder cap
        c.fill(c.mask([poly], ell), color, centre_x=sx, half=w0, pattern=pat, depth=0.45)
        if design.sleeves == "short":
            c.line([(sx - w1, end), (sx + w1, end)], design.accent, 5)
    else:
        w0, w1 = 41, 33
        poly = [(sx - w0, sy - 18), (sx + w0, sy - 18), (sx + w1, ey), (sx - w1, ey)]
        c.fill(
            c.mask([poly], [(sx - w0, sy - 40, sx + w0, sy + 4)]), color, centre_x=sx, half=w0, pattern=pat, depth=0.45
        )
        c.line([(sx - w1, ey - 10), (sx + w1, ey - 10)], design.accent, 7)  # cuff
    c.sheen(sx - 12, LH * 0.02, LH, 12, 50)
    if design.lace:
        c.lace((sx - 40, 10, sx + 40, LH - 20), design.accent, step=15)
    return c.result()


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _place_limb(canvas: Image.Image, limb: Image.Image, frm, to, across: float = 1.0):
    """Affine-paste a sleeve layer along a bone (same rule as the browser renderer)."""
    s = (LIMB_ANCHORS["start"][0] * limb.width, LIMB_ANCHORS["start"][1] * limb.height)
    e = (LIMB_ANCHORS["end"][0] * limb.width, LIMB_ANCHORS["end"][1] * limb.height)
    img_len = math.dist(s, e)
    bone = (to[0] - frm[0], to[1] - frm[1])
    blen = math.hypot(*bone)
    dx, dy = bone[0] / blen, bone[1] / blen  # along
    px, py = -dy, dx  # across
    along = blen / img_len
    # output p = frm + dir*(u*along) + perp*(v*across), with image (x,y): u = y - s.y, v = -(x - s.x)
    # (image "down" is the bone, image perp of (0,1) is (-1,0)) → invert to x, y.
    a, b, c_ = -px * across, dx * along, frm[0] - (-px * across) * s[0] - dx * along * s[1]
    d, e2, f = -py * across, dy * along, frm[1] - (-py * across) * s[0] - dy * along * s[1]
    det = a * e2 - b * d
    inv = (e2 / det, -b / det, (b * f - e2 * c_) / det, -d / det, a / det, (d * c_ - a * f) / det)
    warped = limb.transform(canvas.size, Image.AFFINE, inv, resample=Image.BICUBIC)
    canvas.alpha_composite(warped)


def draw_cover(
    design: Design,
    body: Image.Image,
    upper: Image.Image | None,
    fore: Image.Image | None,
    lower: Image.Image | None = None,
) -> Image.Image:
    """Catalogue thumbnail: the garment alone on a transparent background, arms relaxed.

    The page puts it on its own (light / dark) backdrop, so it suits both themes.
    """
    W, H = 600, 1300
    bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sleeves = Image.new("RGBA", (W, H))
    rs, ls = (198, 156), (402, 156)
    re, le = (176, 400), (424, 400)
    rw, lw = (180, 610), (420, 610)
    if upper is not None:
        for s, e in ((rs, re), (ls, le)):
            _place_limb(sleeves, upper, s, e)
    if fore is not None:
        for s, e in ((re, rw), (le, lw)):
            _place_limb(sleeves, fore, s, e)
    if lower is not None:
        bg.alpha_composite(lower)
    bg.alpha_composite(body)
    bg.alpha_composite(sleeves)
    left, top, right, bottom = bg.getbbox()
    pad = 24
    cover = bg.crop((max(0, left - pad), max(0, top - pad), min(W, right + pad), min(H, bottom + pad)))
    cover.thumbnail((600, 1000))
    return cover


DESIGNS: list[Design] = [
    Design(
        "demo-oq-malika",
        "kelinlik-liboslari",
        "Oq malika libosi",
        "Keng etakli, yurak shaklidagi yoqali kelinlik libosi.",
        12_500_000,
        "#FBFAF7",
        "#D6C7A1",
        "strapless",
        "ballgown",
        lace=True,
        sizes=["XS", "S", "M", "L"],
        colors=[{"name": "Oq", "hex": "#FBFAF7"}],
    ),
    Design(
        "demo-atlas-romantika",
        "kelinlik-liboslari",
        "Romantika (uzun yengli)",
        "Pastga qarab kengayadigan, uzun to'r yengli libos.",
        15_900_000,
        "#F5EFE6",
        "#C9B48A",
        "gown",
        "mermaid",
        sleeves="long",
        sleeve_color="#EFE6D8",
        lace=True,
        sizes=["S", "M", "L"],
        colors=[{"name": "Fil suyagi", "hex": "#F5EFE6"}],
    ),
    Design(
        "demo-qora-smoking",
        "kuyovlik-kostyumlari",
        "Klassik qora smoking",
        "Atlas yoqali qora smoking, oq ko'ylak va kapalak bog'ich bilan.",
        6_800_000,
        "#151A24",
        "#111827",
        "jacket",
        "trousers",
        sleeves="long",
        texture="wool",
        sizes=["46", "48", "50", "52"],
        colors=[{"name": "Qora", "hex": "#151A24"}],
    ),
    Design(
        "demo-kok-kostyum",
        "kuyovlik-kostyumlari",
        "To'q ko'k kostyum",
        "Ikki tugmali to'q ko'k kostyum, qizg'ish galstuk bilan.",
        5_400_000,
        "#1E3A8A",
        "#9F1239",
        "jacket",
        "trousers",
        sleeves="long",
        texture="wool",
        sizes=["46", "48", "50"],
        colors=[{"name": "To'q ko'k", "hex": "#1E3A8A"}],
    ),
    Design(
        "demo-atlas-koylak",
        "milliy-toy-liboslari",
        "Atlas ko'ylak",
        "An'anaviy atlas naqshli milliy ko'ylak.",
        2_300_000,
        "#7C3AED",
        "#FBBF24",
        "atlas",
        "aline",
        sleeves="long",
        pattern="ikat",
        pattern_colors=["#7C3AED", "#F43F5E", "#FBBF24", "#06B6D4"],
        texture="silk",
        sizes=["S", "M", "L", "XL"],
        colors=[{"name": "Rang-barang"}],
    ),
    Design(
        "demo-zarli-chopon",
        "milliy-toy-liboslari",
        "Zarli chopon",
        "Kuyov uchun yo'l-yo'l, zarli hoshiyali chopon.",
        3_900_000,
        "#1D4ED8",
        "#EAB308",
        "robe",
        "robe",
        sleeves="long",
        pattern="stripes",
        pattern_colors=["#1D4ED8", "#16A34A", "#DC2626"],
        texture="silk",
        sizes=["M", "L", "XL"],
        colors=[{"name": "Ko'k-yashil"}],
    ),
    Design(
        "demo-oq-koylak",
        "erkaklar-kiyimlari",
        "Klassik oq ko'ylak",
        "Paxta oq ko'ylak va kulrang klassik shim.",
        690_000,
        "#F8FAFC",
        "#64748B",
        "shirt",
        "trousers",
        sleeves="long",
        bottom_color="#475569",
        texture="cotton",
        sizes=["S", "M", "L", "XL"],
        colors=[{"name": "Oq", "hex": "#F8FAFC"}],
    ),
    Design(
        "demo-qisqa-yeng",
        "erkaklar-kiyimlari",
        "Yozgi ko'ylak",
        "Qisqa yengli moviy ko'ylak, to'q shim bilan.",
        420_000,
        "#38BDF8",
        "#0369A1",
        "shirt",
        "trousers",
        sleeves="short",
        bottom_color="#1E293B",
        texture="cotton",
        sizes=["M", "L", "XL"],
        colors=[{"name": "Moviy", "hex": "#38BDF8"}],
    ),
    Design(
        "demo-qizil-kechki",
        "ayollar-kiyimlari",
        "Qizil kechki libos",
        "Uzun, oqimli qizil kechki libos.",
        1_850_000,
        "#BE123C",
        "#FDA4AF",
        "gown",
        "aline",
        sizes=["XS", "S", "M", "L"],
        colors=[{"name": "Qizil", "hex": "#BE123C"}],
    ),
    Design(
        "demo-moviy-midi",
        "ayollar-kiyimlari",
        "Moviy midi ko'ylak",
        "Qisqa yengli, tizzagacha moviy ko'ylak.",
        980_000,
        "#2563EB",
        "#93C5FD",
        "gown",
        "midi",
        sleeves="short",
        sizes=["S", "M", "L"],
        colors=[{"name": "Moviy", "hex": "#2563EB"}],
    ),
]
