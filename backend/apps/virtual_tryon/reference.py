"""Validate and normalise the garment reference image used by the AI try-on (Decart lucy-vton).

Decart's documented requirements (docs.platform.decart.ai, "Reference images" / "Virtual try-on"):
JPEG, PNG or WebP; at least 512×512 recommended; a clean garment photo with no person, on a white
or plain background; keep it under 5 MB and under 2048 px on the longest side.

What is checked here (deterministic, no ML):
* real image of an allowed format (fully decoded, decompression-bomb guarded), ≤ 10 MB upload;
* shorter side ≥ 512 px; aspect ratio between 1:3 and 3:1;
* plain background: the outer border is near-white / transparent, or one uniform colour;
* output: EXIF stripped, transparency flattened onto white, longest side ≤ 2048, JPEG q90 (< 5 MB).

Not checked (needs a vision model): that no person is wearing the garment. Staff confirm that
before approving; the admin API says so.
"""

import io
import statistics
import warnings

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
MIN_SIDE = 512
MAX_SIDE = 2048
MAX_ASPECT = 3.0
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
#: Border pixels: ≥ this share must be near-white (all channels ≥ LIGHT) ...
LIGHT, LIGHT_SHARE = 225, 0.80
#: ... or the border must be one plain colour (luminance spread ≤ PLAIN_STDEV).
PLAIN_STDEV = 12.0
BORDER = 0.03  # 3% strip on each edge


def _open(upload) -> Image.Image:
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"Rasm hajmi {MAX_UPLOAD_BYTES // (1024 * 1024)} MB dan oshmasligi kerak.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            upload.seek(0)
            probe = Image.open(upload)
            if probe.format not in ALLOWED_FORMATS:
                raise ValidationError("Faqat JPG, PNG yoki WEBP rasm qabul qilinadi.")
            if probe.width * probe.height > MAX_PIXELS:
                raise ValidationError("Rasm o'lchami juda katta.")
            probe.verify()
            upload.seek(0)
            image = Image.open(upload)
            image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, SyntaxError):
        raise ValidationError("Fayl yaroqli rasm emas.") from None
    return ImageOps.exif_transpose(image)


def _flatten(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, rgba).convert("RGB")


def _border_pixels(rgb: Image.Image) -> list[tuple[int, int, int]]:
    # NEAREST keeps the background's texture: an averaging filter would make a busy room look plain.
    scale = min(1.0, 256 / max(rgb.size))
    small = rgb.resize((max(1, int(rgb.width * scale)), max(1, int(rgb.height * scale))), Image.NEAREST)
    w, h = small.size
    bx, by = max(1, int(w * BORDER)), max(1, int(h * BORDER))
    px = small.load()
    out = []
    for y in range(h):
        for x in range(w):
            if x < bx or x >= w - bx or y < by or y >= h - by:
                out.append(px[x, y])
    return out


def has_plain_background(rgb: Image.Image) -> bool:
    pixels = _border_pixels(rgb)
    light = sum(1 for r, g, b in pixels if r >= LIGHT and g >= LIGHT and b >= LIGHT) / len(pixels)
    if light >= LIGHT_SHARE:
        return True
    luminance = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
    return statistics.pstdev(luminance) <= PLAIN_STDEV


def process_reference(upload) -> tuple[ContentFile, int, int]:
    image = _open(upload)
    w, h = image.size
    if min(w, h) < MIN_SIDE:
        raise ValidationError(f"Rasm kamida {MIN_SIDE}×{MIN_SIDE} piksel bo'lishi kerak (hozir {w}×{h}).")
    if max(w, h) / min(w, h) > MAX_ASPECT:
        raise ValidationError("Rasm juda cho'zinchoq: tomonlar nisbati 1:3 dan 3:1 gacha bo'lishi kerak.")
    rgb = _flatten(image)
    if not has_plain_background(rgb):
        raise ValidationError(
            "Fon oddiy bo'lishi kerak: kiyim oq yoki bir xil rangli fonda, odamsiz, butun ko'rinib tursin."
        )
    rgb.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=90, optimize=True)
    return ContentFile(buf.getvalue(), name="reference.jpg"), rgb.width, rgb.height
