"""OpenAI Image Edit virtual try-on (``gpt-image-1`` / ``gpt-image-1-mini`` via REST API).

Used as the AI try-on engine when ``DECART_API_KEY`` is not configured (or when snapshot mode is
chosen) and ``OPENAI_API_KEY`` is present. The user captures a camera photo, selects a garment with
an ``ai_reference_image``, and the server calls OpenAI ``POST /v1/images/edits`` with both images
and returns the photorealistic result (WebP/JPEG).
"""

import base64
import io
import logging
import time
from dataclasses import dataclass

import requests
from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

logger = logging.getLogger("apps.virtual_tryon.openai")

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1024
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")


class OpenAITryOnError(Exception):
    def __init__(self, code: str, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class TryOnRenderResult:
    image_bytes: bytes
    content_type: str
    width: int
    height: int
    model: str
    latency_ms: int


def is_configured() -> bool:
    return bool(settings.AI_PLANNER.get("OPENAI_API_KEY", "").strip())


def _api_key() -> str:
    return settings.AI_PLANNER.get("OPENAI_API_KEY", "").strip()


def _base_url() -> str:
    return settings.AI_PLANNER.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _model() -> str:
    return settings.AI_TRYON.get("OPENAI_MODEL", "gpt-image-1")


def prepare_user_photo(upload) -> bytes:
    """Validate and normalize the uploaded camera snapshot to a clean RGB PNG (≤ 1024 px)."""
    if upload.size > MAX_PHOTO_BYTES:
        raise ValidationError("Rasm hajmi 10 MB dan oshmasligi kerak.")
    try:
        upload.seek(0)
        img = Image.open(upload)
        if img.format not in ALLOWED_FORMATS:
            raise ValidationError("Faqat JPG, PNG yoki WEBP rasm qabul qilinadi.")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValidationError("Fayl yaroqli rasm emas.") from None
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _garment_png(garment) -> bytes:
    with garment.ai_reference_image.open("rb") as fh:
        img = Image.open(fh).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _build_prompt(garment) -> str:
    custom = (garment.ai_prompt or "").strip()
    garment_desc = custom or f"the garment shown in the second image ({garment.name})"
    return (
        "Photorealistic virtual try-on. Keep the person from the first image completely unchanged: "
        "preserve their exact face, facial expression, hairstyle, skin tone, body proportions, pose, "
        "hands, lighting, and background. Replace only their current clothing with "
        f"{garment_desc}, matching the exact color, fabric texture, pattern, cut, and details from "
        "the second image so it fits naturally on their body with realistic folds and shadows."
    )


def render_tryon(*, photo_bytes: bytes, garment) -> TryOnRenderResult:
    """Call OpenAI ``/v1/images/edits`` with the person photo + garment reference image."""
    if not is_configured():
        raise OpenAITryOnError("ai_tryon_not_configured")

    garment_bytes = _garment_png(garment)
    model = _model()
    url = f"{_base_url()}/images/edits"
    headers = {"Authorization": f"Bearer {_api_key()}"}
    files = [
        ("image[]", ("person.png", photo_bytes, "image/png")),
        ("image[]", ("garment.png", garment_bytes, "image/png")),
    ]
    data = {
        "model": model,
        "prompt": _build_prompt(garment),
        "size": "1024x1024",
        "quality": settings.AI_TRYON.get("OPENAI_QUALITY", "medium"),
    }

    started = time.monotonic()
    try:
        res = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=float(settings.AI_TRYON.get("OPENAI_TIMEOUT_SECONDS", 90)),
        )
    except requests.Timeout:
        logger.warning("openai try-on request timed out")
        raise OpenAITryOnError("provider_timeout") from None
    except requests.RequestException as exc:
        logger.warning("openai try-on request failed: %s", type(exc).__name__)
        raise OpenAITryOnError("provider_unavailable") from None
    latency_ms = int((time.monotonic() - started) * 1000)

    if res.status_code != 200:
        code = {
            401: "provider_auth_failed",
            403: "provider_auth_failed",
            402: "provider_insufficient_credits",
            400: "provider_rejected_request",
            422: "provider_rejected_request",
            429: "provider_rate_limited",
        }.get(res.status_code, "provider_unavailable")
        logger.warning("openai try-on failed: %s (HTTP %s)", code, res.status_code)
        raise OpenAITryOnError(code, res.status_code)

    try:
        payload = res.json()
        item = (payload.get("data") or [])[0]
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            img_res = requests.get(item["url"], timeout=30)
            img_res.raise_for_status()
            raw = img_res.content
        else:
            raise ValueError("missing image data")
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=90, optimize=True)
        return TryOnRenderResult(
            image_bytes=out_buf.getvalue(),
            content_type="image/jpeg",
            width=img.width,
            height=img.height,
            model=model,
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("openai try-on bad response: %s", type(exc).__name__)
        raise OpenAITryOnError("provider_bad_response", 200) from None
