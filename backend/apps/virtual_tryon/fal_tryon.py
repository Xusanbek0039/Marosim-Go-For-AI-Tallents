"""fal.ai Virtual Try-On client (Photo + Video).

* **Photo Try-On**: ``fal-ai/fashn/tryon/v1.6`` — dedicated virtual try-on model that preserves the
  user's face, hair, body proportions, and background while transferring the exact garment fabric
  and pattern.
* **Video Try-On**: ``fal-ai/kling-video/o3/standard/video-to-video/edit`` — temporal video-to-video
  editing that preserves the user's real camera motion while replacing only their outfit with
  ``@Image1``.

Uses fal.ai's REST Storage + Queue API directly via ``requests`` (no extra SDK dependency), so the
permanent ``FAL_KEY`` stays strictly on the server.
"""

import io
import logging
import time
from pathlib import Path

import requests
from django.conf import settings
from PIL import Image

from . import openai_tryon

logger = logging.getLogger("apps.virtual_tryon.fal")

FAL_REST_BASE = "https://rest.fal.ai"
FAL_QUEUE_BASE = "https://queue.fal.run"


def is_configured() -> bool:
    return bool(settings.AI_TRYON.get("FAL_KEY", "").strip())


def _api_key() -> str:
    return settings.AI_TRYON.get("FAL_KEY", "").strip()


def _photo_model() -> str:
    return settings.AI_TRYON.get("FAL_PHOTO_MODEL", "fal-ai/fashn/tryon/v1.6").strip()


def _video_model() -> str:
    return settings.AI_TRYON.get("FAL_VIDEO_MODEL", "fal-ai/kling-video/o3/standard/video-to-video/edit").strip()


def _timeout() -> int:
    return int(settings.AI_TRYON.get("FAL_TIMEOUT_SECONDS", 240))


def _map_http_error(status_code: int) -> str:
    return {
        401: "provider_auth_failed",
        403: "provider_auth_failed",
        402: "provider_insufficient_credits",
        400: "provider_rejected_request",
        422: "provider_rejected_request",
        429: "provider_rate_limited",
    }.get(status_code, "provider_unavailable")


def _upload_bytes(key: str, data: bytes, filename: str, content_type: str) -> str:
    """Upload binary bytes to fal CDN storage and return the hosted ``file_url``."""
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    try:
        init_res = requests.post(
            f"{FAL_REST_BASE}/storage/upload/initiate",
            headers=headers,
            json={"file_name": filename, "content_type": content_type},
            timeout=30,
        )
    except requests.Timeout:
        logger.warning("fal storage initiate timed out")
        raise openai_tryon.OpenAITryOnError("provider_timeout") from None
    except requests.RequestException as exc:
        logger.warning("fal storage initiate failed: %s", type(exc).__name__)
        raise openai_tryon.OpenAITryOnError("provider_unavailable") from None

    if init_res.status_code not in (200, 201):
        code = _map_http_error(init_res.status_code)
        logger.warning("fal storage initiate rejected: HTTP %s (%s)", init_res.status_code, init_res.text[:200])
        raise openai_tryon.OpenAITryOnError(code, init_res.status_code)

    try:
        payload = init_res.json()
        upload_url = payload["upload_url"]
        file_url = payload["file_url"]
    except (ValueError, KeyError, TypeError):
        raise openai_tryon.OpenAITryOnError("provider_bad_response", init_res.status_code) from None

    try:
        put_res = requests.put(
            upload_url,
            data=data,
            headers={"Content-Type": content_type},
            timeout=120,
        )
    except requests.Timeout:
        logger.warning("fal storage PUT timed out (%s, %d bytes)", filename, len(data))
        raise openai_tryon.OpenAITryOnError("provider_timeout") from None
    except requests.RequestException as exc:
        logger.warning("fal storage PUT failed: %s", type(exc).__name__)
        raise openai_tryon.OpenAITryOnError("provider_unavailable") from None

    if put_res.status_code not in (200, 201, 204):
        code = _map_http_error(put_res.status_code)
        logger.warning("fal storage PUT rejected: HTTP %s", put_res.status_code)
        raise openai_tryon.OpenAITryOnError(code, put_res.status_code)

    return str(file_url)


def _run_queue(key: str, model_id: str, payload: dict, timeout_seconds: int) -> dict:
    """Submit a job to ``queue.fal.run`` and poll until ``COMPLETED``."""
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    try:
        submit_res = requests.post(
            f"{FAL_QUEUE_BASE}/{model_id}",
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.Timeout:
        logger.warning("fal queue submit timed out for %s", model_id)
        raise openai_tryon.OpenAITryOnError("provider_timeout") from None
    except requests.RequestException as exc:
        logger.warning("fal queue submit failed for %s: %s", model_id, type(exc).__name__)
        raise openai_tryon.OpenAITryOnError("provider_unavailable") from None

    if submit_res.status_code not in (200, 201):
        code = _map_http_error(submit_res.status_code)
        logger.warning("fal queue submit rejected (%s): HTTP %s (%s)", model_id, submit_res.status_code, submit_res.text[:300])
        raise openai_tryon.OpenAITryOnError(code, submit_res.status_code)

    try:
        job = submit_res.json()
        req_id = job["request_id"]
    except (ValueError, KeyError, TypeError):
        raise openai_tryon.OpenAITryOnError("provider_bad_response", submit_res.status_code) from None

    status_url = job.get("status_url") or f"{FAL_QUEUE_BASE}/{model_id}/requests/{req_id}/status"
    response_url = job.get("response_url") or f"{FAL_QUEUE_BASE}/{model_id}/requests/{req_id}"

    auth_header = {"Authorization": f"Key {key}"}
    deadline = time.monotonic() + timeout_seconds
    status_val = job.get("status", "IN_QUEUE")
    logger.info("fal job %s submitted to %s (status=%s)", req_id, model_id, status_val)

    while status_val not in ("COMPLETED", "FAILED", "CANCELLED"):
        if time.monotonic() > deadline:
            logger.warning("fal job %s (%s) timed out after %ss (last_status=%s)", req_id, model_id, timeout_seconds, status_val)
            raise openai_tryon.OpenAITryOnError("provider_timeout")
        time.sleep(2.5)
        try:
            poll_res = requests.get(status_url, headers=auth_header, timeout=30)
        except requests.Timeout:
            continue
        except requests.RequestException as exc:
            logger.warning("fal poll failed for %s: %s", req_id, type(exc).__name__)
            raise openai_tryon.OpenAITryOnError("provider_unavailable") from None
        if poll_res.status_code not in (200, 202):
            code = _map_http_error(poll_res.status_code)
            raise openai_tryon.OpenAITryOnError(code, poll_res.status_code)
        try:
            poll_data = poll_res.json()
        except ValueError:
            raise openai_tryon.OpenAITryOnError("provider_bad_response", poll_res.status_code) from None
        new_status = poll_data.get("status", "")
        if new_status != status_val:
            logger.info("fal job %s status: %s -> %s", req_id, status_val, new_status)
        status_val = new_status
        if poll_data.get("response_url"):
            response_url = poll_data["response_url"]

    if status_val != "COMPLETED":
        logger.warning("fal job %s (%s) ended with status=%s", req_id, model_id, status_val)
        raise openai_tryon.OpenAITryOnError("provider_rejected_request")

    try:
        final_res = requests.get(response_url, headers=auth_header, timeout=60)
    except requests.Timeout:
        raise openai_tryon.OpenAITryOnError("provider_timeout") from None
    except requests.RequestException:
        raise openai_tryon.OpenAITryOnError("provider_unavailable") from None

    if final_res.status_code != 200:
        code = _map_http_error(final_res.status_code)
        logger.warning("fal result fetch failed (%s): HTTP %s (%s)", req_id, final_res.status_code, final_res.text[:300])
        raise openai_tryon.OpenAITryOnError(code, final_res.status_code)

    try:
        return final_res.json()
    except ValueError:
        raise openai_tryon.OpenAITryOnError("provider_bad_response", 200) from None


def render_photo_tryon(
    *,
    photo_bytes: bytes,
    garment,
    garment_bytes: bytes | None = None,
) -> openai_tryon.TryOnRenderResult:
    """Run virtual try-on on a user photo + garment reference via fal.ai FASHN v1.6."""
    if not is_configured():
        raise openai_tryon.OpenAITryOnError("ai_tryon_not_configured")

    key = _api_key()
    model_id = _photo_model()
    garment_bytes = garment_bytes if garment_bytes is not None else openai_tryon._garment_png(garment)

    started = time.monotonic()
    person_url = _upload_bytes(key, photo_bytes, "person.png", "image/png")
    garment_url = _upload_bytes(key, garment_bytes, "garment.png", "image/png")

    result = _run_queue(
        key,
        model_id,
        {
            "model_image": person_url,
            "garment_image": garment_url,
            "garment_photo_type": "auto",
            "category": "auto",
            "mode": "balanced",
        },
        timeout_seconds=min(_timeout(), 120),
    )

    out_url = None
    images = result.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        out_url = images[0].get("url")
    elif isinstance(result.get("image"), dict):
        out_url = result["image"].get("url")

    if not isinstance(out_url, str) or not out_url.startswith("http"):
        logger.warning("fal photo try-on missing output url: %s", list(result.keys()))
        raise openai_tryon.OpenAITryOnError("provider_bad_response", 200)

    try:
        img_res = requests.get(out_url, timeout=30)
        img_res.raise_for_status()
        img = Image.open(io.BytesIO(img_res.content)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fal photo download/decode failed: %s", type(exc).__name__)
        raise openai_tryon.OpenAITryOnError("provider_bad_response", 200) from None

    latency_ms = int((time.monotonic() - started) * 1000)
    return openai_tryon.TryOnRenderResult(
        image_bytes=buf.getvalue(),
        content_type="image/jpeg",
        width=img.width,
        height=img.height,
        model=model_id,
        latency_ms=latency_ms,
    )


def render_video_tryon(*, norm_mp4: Path, garment) -> tuple[bytes, str, int]:
    """Run video virtual try-on on a normalized ≥720p MP4 + garment via fal.ai Kling O3 Edit.

    Returns ``(mp4_bytes, model_id, latency_ms)``.
    """
    if not is_configured():
        raise openai_tryon.OpenAITryOnError("ai_tryon_not_configured")

    key = _api_key()
    model_id = _video_model()
    started = time.monotonic()

    garment_bytes = openai_tryon._garment_png(garment)
    video_url = _upload_bytes(key, norm_mp4.read_bytes(), "input_720p.mp4", "video/mp4")
    garment_url = _upload_bytes(key, garment_bytes, "garment.png", "image/png")

    garment_desc = (garment.ai_prompt or "").strip() or garment.name
    prompt = (
        "Strict virtual try-on video edit. Keep the exact same person from the video: "
        "preserve their exact face, facial expression, hairstyle, skin tone, hands, body, "
        "exact movements, camera angle, and background unchanged in every frame. "
        f"Replace ONLY their current outfit with the exact garment shown in @Image1 ({garment_desc}), "
        "matching its exact color, fabric, embroidery, pattern, and cut so it drapes and moves "
        "naturally with their body."
    )

    result = _run_queue(
        key,
        model_id,
        {
            "prompt": prompt,
            "video_url": video_url,
            "image_urls": [garment_url],
            "keep_audio": False,
        },
        timeout_seconds=_timeout(),
    )

    video_obj = result.get("video")
    out_url = video_obj.get("url") if isinstance(video_obj, dict) else None
    if not isinstance(out_url, str) or not out_url.startswith("http"):
        logger.warning("fal video try-on missing output url: %s", list(result.keys()))
        raise openai_tryon.OpenAITryOnError("provider_bad_response", 200)

    try:
        dl = requests.get(out_url, timeout=120)
    except requests.Timeout:
        raise openai_tryon.OpenAITryOnError("provider_timeout") from None
    except requests.RequestException:
        raise openai_tryon.OpenAITryOnError("provider_unavailable") from None

    if dl.status_code != 200 or not dl.content:
        raise openai_tryon.OpenAITryOnError("provider_unavailable", dl.status_code)

    latency_ms = int((time.monotonic() - started) * 1000)
    return dl.content, model_id, latency_ms
