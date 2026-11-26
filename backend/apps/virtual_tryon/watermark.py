"""Premium check and MarosimGo logo watermarking for try-on image downloads.

* Premium users (active paid user subscription) download the clean, unwatermarked image.
* Non-premium users can also download the image, with the MarosimGo logo pill placed neatly
  in the bottom-right corner.
"""

import io
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from apps.subscriptions.models import Subscription, SubscriptionStatus


def is_premium_user(user) -> bool:
    """True when ``user`` has an active personal paid subscription."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    now = timezone.now()
    return Subscription.objects.filter(
        user=user,
        studio__isnull=True,
        venue__isnull=True,
        status=SubscriptionStatus.ACTIVE,
        starts_at__lte=now,
        ends_at__gt=now,
    ).exists()


def _brand_file(name: str) -> Path | None:
    for root in (settings.BASE_DIR / "panel" / "brand", settings.BASE_DIR / "panel-user" / "brand"):
        path = root / name
        if path.is_file():
            return path
    return None


def apply_marosimgo_watermark(image_bytes: bytes) -> bytes:
    """Overlay the MarosimGo logo pill on the bottom-right corner of the image and return JPEG bytes."""
    base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = base.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    pad = max(14, int(min(w, h) * 0.025))
    icon_h = max(24, int(min(w, h) * 0.055))
    word_h = max(18, int(icon_h * 0.68))

    icon_path = _brand_file("logo-icon.png")
    word_path = _brand_file("wordmark-light.png")

    icon_img = None
    word_img = None
    if icon_path is not None:
        raw_icon = Image.open(icon_path).convert("RGBA")
        iw = max(1, int(raw_icon.width * (icon_h / raw_icon.height)))
        icon_img = raw_icon.resize((iw, icon_h), Image.LANCZOS)
    if word_path is not None:
        raw_word = Image.open(word_path).convert("RGBA")
        ww = max(1, int(raw_word.width * (word_h / raw_word.height)))
        word_img = raw_word.resize((ww, word_h), Image.LANCZOS)

    inner_px = max(12, icon_h // 3)
    inner_py = max(8, icon_h // 4)
    gap = max(8, icon_h // 4)

    if icon_img is not None and word_img is not None:
        pill_w = inner_px * 2 + icon_img.width + gap + word_img.width
        pill_h = inner_py * 2 + icon_img.height
        x0 = max(pad, w - pill_w - pad)
        y0 = max(pad, h - pill_h - pad)
        draw.rounded_rectangle(
            [x0, y0, x0 + pill_w, y0 + pill_h],
            radius=pill_h // 2,
            fill=(10, 15, 30, 185),
            outline=(255, 255, 255, 70),
            width=1,
        )
        overlay.alpha_composite(icon_img, (x0 + inner_px, y0 + inner_py))
        wy = y0 + (pill_h - word_img.height) // 2
        overlay.alpha_composite(word_img, (x0 + inner_px + icon_img.width + gap, wy))
    else:
        font = ImageFont.load_default()
        label = "MarosimGo"
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pill_w = tw + inner_px * 2
        pill_h = th + inner_py * 2
        x0 = max(pad, w - pill_w - pad)
        y0 = max(pad, h - pill_h - pad)
        draw.rounded_rectangle(
            [x0, y0, x0 + pill_w, y0 + pill_h],
            radius=pill_h // 2,
            fill=(10, 15, 30, 195),
            outline=(255, 255, 255, 80),
            width=1,
        )
        draw.text((x0 + inner_px, y0 + inner_py), label, fill=(255, 255, 255, 240), font=font)

    combined = Image.alpha_composite(base, overlay).convert("RGB")
    out = io.BytesIO()
    combined.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()
