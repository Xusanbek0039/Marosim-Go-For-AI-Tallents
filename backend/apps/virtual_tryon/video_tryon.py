"""Real Video Virtual Try-On pipeline.

Primary engine (when ``REPLICATE_API_TOKEN`` is set):
* **Kling v3 Omni Video Editing** (``kwaivgi/kling-v3-omni-video`` via Replicate REST API):
  Takes the user's actual camera video (normalized to ≥720p H.264 MP4, 3–5 s) as the ``base``
  reference video and the selected garment photo as ``reference_images[0]``. Because Kling v3 Omni
  edits the video with temporal consistency, the user's exact face, background, and every single
  real movement stay locked to their original recording while only the garment changes.

fal.ai (``FAL_KEY``) is not handled here: it renders for minutes, so it runs as a background job
(see ``video_jobs.py``) instead of inside one request.

Fallback (when ``REPLICATE_API_TOKEN`` is not set):
* OpenAI ``gpt-image-1.5`` keyframe try-on + ``ffmpeg`` motion interpolation.
"""

import io
import logging
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings
from PIL import Image
from rest_framework.exceptions import ValidationError

from . import openai_tryon

logger = logging.getLogger("apps.virtual_tryon.video")

MAX_VIDEO_BYTES = 25 * 1024 * 1024
KEYFRAME_COUNT = 8
OUTPUT_FPS = 24
MAX_OUTPUT_SIDE = 768
REPLICATE_API = "https://api.replicate.com/v1"


@dataclass(frozen=True)
class VideoTryOnResult:
    video_bytes: bytes
    poster_bytes: bytes
    width: int
    height: int
    frames: int
    model: str
    latency_ms: int


def is_replicate_configured() -> bool:
    return bool(settings.AI_TRYON.get("REPLICATE_API_TOKEN", "").strip())


def _ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise openai_tryon.OpenAITryOnError("provider_unavailable")
    return path


def _normalize_input_mp4(src: Path, dst: Path) -> None:
    """Transcode browser WebM/MP4 into a clean ≥720p H.264 MP4 (3–5 s) accepted by Kling v3 Omni."""
    ffmpeg = _ffmpeg_bin()
    # Kling v3 Omni requires: .mp4, duration 3-10s, shorter side >= 720px and <= 2160px.
    # Scale so min(w,h) >= 720 while preserving aspect ratio and even dimensions; pad to at least 3.1s if slightly short.
    vf = (
        "scale='if(lt(iw,ih),max(720,iw),-2)':'if(lt(iw,ih),-2,max(720,ih))',"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        "tpad=stop_mode=clone:stop_duration=0.5,"
        "fps=24,format=yuv420p"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(src),
        "-t",
        "4.0",
        "-an",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-maxrate",
        "2500k",
        "-bufsize",
        "5000k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
    if proc.returncode != 0 or not dst.is_file():
        logger.warning("ffmpeg normalize_input_mp4 failed: %s", proc.stderr.decode(errors="ignore")[-400:])
        raise ValidationError("Videoni qayta ishlab bo'lmadi. Qayta yozib ko'ring.")


def _extract_poster(mp4_path: Path, poster_path: Path) -> tuple[bytes, int, int]:
    ffmpeg = _ffmpeg_bin()
    subprocess.run(
        [ffmpeg, "-y", "-i", str(mp4_path), "-frames:v", "1", "-q:v", "2", str(poster_path)],
        capture_output=True,
        timeout=20,
        check=False,
    )
    if not poster_path.is_file():
        raise openai_tryon.OpenAITryOnError("provider_bad_response")
    img = Image.open(poster_path).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue(), img.width, img.height


def _replicate_upload(token: str, path: Path, mime_type: str) -> str:
    """Upload a local file to Replicate's Files API and return its short-lived GET URL."""
    headers = {"Authorization": f"Bearer {token}"}
    with open(path, "rb") as fh:
        res = requests.post(
            f"{REPLICATE_API}/files",
            headers=headers,
            files={"content": (path.name, fh, mime_type)},
            timeout=60,
        )
    if res.status_code not in (200, 201):
        code = {
            401: "provider_auth_failed",
            403: "provider_auth_failed",
            402: "provider_insufficient_credits",
            429: "provider_rate_limited",
        }.get(res.status_code, "provider_unavailable")
        logger.warning("replicate file upload failed: HTTP %s (%s)", res.status_code, res.text[:200])
        raise openai_tryon.OpenAITryOnError(code, res.status_code)
    url = (res.json().get("urls") or {}).get("get")
    if not url:
        raise openai_tryon.OpenAITryOnError("provider_bad_response")
    return str(url)


def _render_via_replicate(*, src: Path, work: Path, garment) -> VideoTryOnResult:
    token = settings.AI_TRYON["REPLICATE_API_TOKEN"].strip()
    model_slug = settings.AI_TRYON.get("REPLICATE_VIDEO_MODEL", "kwaivgi/kling-v3-omni-video")
    mode = settings.AI_TRYON.get("REPLICATE_VIDEO_MODE", "standard")
    max_wait = int(settings.AI_TRYON.get("REPLICATE_TIMEOUT_SECONDS", 240))

    started = time.monotonic()
    norm_mp4 = work / "input_720p.mp4"
    _normalize_input_mp4(src, norm_mp4)

    garment_jpg = work / "garment.jpg"
    garment_jpg.write_bytes(openai_tryon._garment_png(garment))

    video_url = _replicate_upload(token, norm_mp4, "video/mp4")
    garment_url = _replicate_upload(token, garment_jpg, "image/png")

    garment_desc = (garment.ai_prompt or "").strip() or garment.name
    prompt = (
        "Strict virtual try-on video edit of <<<video_1>>>. Keep the exact same person from <<<video_1>>>: "
        "preserve their exact face, facial expression, hairstyle, skin tone, hands, body, exact movements, "
        "camera angle, and background unchanged in every frame. Replace ONLY their current outfit with the "
        f"exact garment shown in <<<image_1>>> ({garment_desc}), matching its exact color, fabric, pattern, "
        "and cut so it moves naturally with their body."
    )

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    create_res = requests.post(
        f"{REPLICATE_API}/models/{model_slug}/predictions",
        headers=headers,
        json={
            "input": {
                "mode": mode,
                "video_reference_type": "base",
                "reference_video": video_url,
                "reference_images": [garment_url],
                "keep_original_sound": False,
                "prompt": prompt,
            }
        },
        timeout=30,
    )
    if create_res.status_code not in (200, 201):
        code = {
            401: "provider_auth_failed",
            403: "provider_auth_failed",
            402: "provider_insufficient_credits",
            400: "provider_rejected_request",
            422: "provider_rejected_request",
            429: "provider_rate_limited",
        }.get(create_res.status_code, "provider_unavailable")
        logger.warning("replicate prediction create failed: HTTP %s (%s)", create_res.status_code, create_res.text[:300])
        raise openai_tryon.OpenAITryOnError(code, create_res.status_code)

    pred = create_res.json()
    poll_url = (pred.get("urls") or {}).get("get") or f"{REPLICATE_API}/predictions/{pred['id']}"

    deadline = time.monotonic() + max_wait
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.monotonic() > deadline:
            raise openai_tryon.OpenAITryOnError("provider_timeout")
        time.sleep(2.5)
        poll_res = requests.get(poll_url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if poll_res.status_code != 200:
            raise openai_tryon.OpenAITryOnError("provider_unavailable", poll_res.status_code)
        pred = poll_res.json()

    if pred.get("status") != "succeeded":
        logger.warning("replicate prediction %s ended with %s: %s", pred.get("id"), pred.get("status"), pred.get("error"))
        raise openai_tryon.OpenAITryOnError("provider_rejected_request")

    output = pred.get("output")
    out_url = output[0] if isinstance(output, list) and output else output
    if not isinstance(out_url, str) or not out_url.startswith("http"):
        raise openai_tryon.OpenAITryOnError("provider_bad_response")

    dl = requests.get(out_url, timeout=60)
    if dl.status_code != 200 or not dl.content:
        raise openai_tryon.OpenAITryOnError("provider_unavailable", dl.status_code)

    out_mp4 = work / "output.mp4"
    out_mp4.write_bytes(dl.content)
    poster_bytes, width, height = _extract_poster(out_mp4, work / "poster.jpg")
    latency_ms = int((time.monotonic() - started) * 1000)

    return VideoTryOnResult(
        video_bytes=dl.content,
        poster_bytes=poster_bytes,
        width=width,
        height=height,
        frames=0,
        model=model_slug,
        latency_ms=latency_ms,
    )


# ------------------------------------------------------------ fallback (OpenAI keyframes)
def _extract_keyframes(video_path: Path, out_dir: Path, count: int = KEYFRAME_COUNT) -> list[bytes]:
    ffmpeg = _ffmpeg_bin()
    pattern = out_dir / "frame_%03d.png"
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "fps=4,scale='min(1024,iw)':'min(1024,ih)':force_original_aspect_ratio=decrease",
        "-frames:v",
        "24",
        str(pattern),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    files = sorted(out_dir.glob("frame_*.png"))
    if not files:
        raise ValidationError("Videodan kadr ajratib bo'lmadi. Qayta yozib ko'ring.")
    picked = files if len(files) <= count else [files[round(i * (len(files) - 1) / (count - 1))] for i in range(count)]
    out: list[bytes] = []
    for p in picked:
        img = Image.open(p).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def _assemble_motion_mp4(frame_jpegs: list[bytes], work_dir: Path) -> tuple[bytes, int, int]:
    ffmpeg = _ffmpeg_bin()
    imgs = [Image.open(io.BytesIO(raw)).convert("RGB") for raw in frame_jpegs]
    first = imgs[0].copy()
    first.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE), Image.LANCZOS)
    target_w = max(2, (first.width // 2) * 2)
    target_h = max(2, (first.height // 2) * 2)
    for idx, img in enumerate(imgs, start=1):
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.LANCZOS)
        img.save(work_dir / f"dressed_{idx:03d}.jpg", format="JPEG", quality=92)
    out_mp4 = work_dir / "tryon_motion.mp4"
    input_fps = max(1.0, len(imgs) / 4.0)
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        f"{input_fps:.2f}",
        "-i",
        str(work_dir / "dressed_%03d.jpg"),
        "-vf",
        f"minterpolate=fps={OUTPUT_FPS}:mi_mode=blend,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0 or not out_mp4.is_file():
        raise openai_tryon.OpenAITryOnError("provider_unavailable")
    return out_mp4.read_bytes(), target_w, target_h


def render_video_tryon(*, video_upload, garment) -> VideoTryOnResult:
    """Process uploaded camera video + garment → real motion-preserving MP4 video."""
    if video_upload.size > MAX_VIDEO_BYTES:
        raise ValidationError("Video hajmi 25 MB dan oshmasligi kerak.")

    with tempfile.TemporaryDirectory(prefix="tryon-vid-") as tmp:
        work = Path(tmp)
        suffix = Path(video_upload.name or "clip.webm").suffix or ".webm"
        src = work / f"input{suffix}"
        with open(src, "wb") as fh:
            for chunk in video_upload.chunks():
                fh.write(chunk)

        if is_replicate_configured():
            try:
                return _render_via_replicate(src=src, work=work, garment=garment)
            except openai_tryon.OpenAITryOnError as exc:
                if (
                    exc.code
                    in (
                        "provider_insufficient_credits",
                        "provider_auth_failed",
                        "provider_rate_limited",
                        "provider_unavailable",
                    )
                    and openai_tryon.is_configured()
                ):
                    logger.warning(
                        "replicate video try-on unavailable (%s); falling back to OpenAI keyframes",
                        exc.code,
                    )
                else:
                    raise

        if not openai_tryon.is_configured():
            raise openai_tryon.OpenAITryOnError("ai_tryon_not_configured")

        started = time.monotonic()
        keyframes = _extract_keyframes(src, work, count=KEYFRAME_COUNT)
        garment_bytes = openai_tryon._garment_png(garment)

        def _dress(frame_bytes: bytes) -> openai_tryon.TryOnRenderResult:
            return openai_tryon.render_tryon(
                photo_bytes=frame_bytes,
                garment=garment,
                garment_bytes=garment_bytes,
                quality="low",
            )

        with ThreadPoolExecutor(max_workers=len(keyframes)) as pool:
            results = list(pool.map(_dress, keyframes))
        dressed_jpegs = [r.image_bytes for r in results]
        mp4_bytes, width, height = _assemble_motion_mp4(dressed_jpegs, work)

    latency_ms = int((time.monotonic() - started) * 1000)
    return VideoTryOnResult(
        video_bytes=mp4_bytes,
        poster_bytes=dressed_jpegs[0],
        width=width,
        height=height,
        frames=len(dressed_jpegs),
        model=results[0].model,
        latency_ms=latency_ms,
    )
