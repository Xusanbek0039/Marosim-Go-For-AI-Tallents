"""Motion-preserving Video Virtual Try-On pipeline (ffmpeg optical-flow + OpenAI gpt-image-1.5).

Flow:
1. Extract 8 evenly-spaced motion frames across the user's 4-second camera recording (2 fps) so
   every real movement (turning, raising arms, smiling, shifting posture) is captured in order.
2. Dress all 8 frames in parallel via OpenAI ``gpt-image-1.5`` (``input_fidelity="high"``) while
   strictly preserving the user's exact face, hands, body pose and room background in each frame.
3. Reconstruct fluid 24 fps motion from the user's exact sequence using ``ffmpeg`` optical-flow
   motion-compensated interpolation (``minterpolate``), outputting a fast-start H.264 MP4.
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

from PIL import Image
from rest_framework.exceptions import ValidationError

from . import openai_tryon

logger = logging.getLogger("apps.virtual_tryon.video")

MAX_VIDEO_BYTES = 25 * 1024 * 1024
KEYFRAME_COUNT = 8
SOURCE_FPS = 2.0
OUTPUT_FPS = 24
MAX_OUTPUT_SIDE = 768


@dataclass(frozen=True)
class VideoTryOnResult:
    video_bytes: bytes
    poster_bytes: bytes
    width: int
    height: int
    frames: int
    model: str
    latency_ms: int


def _ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise openai_tryon.OpenAITryOnError("provider_unavailable")
    return path


def _extract_keyframes(video_path: Path, out_dir: Path, count: int = KEYFRAME_COUNT) -> list[bytes]:
    """Extract ``count`` evenly-spaced PNG motion frames in exact chronological order."""
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
    proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    files = sorted(out_dir.glob("frame_*.png"))
    if not files:
        fallback = out_dir / "single.png"
        subprocess.run(
            [ffmpeg, "-y", "-i", str(video_path), "-frames:v", "1", str(fallback)],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if fallback.is_file():
            files = [fallback]
    if not files:
        logger.warning("ffmpeg extracted 0 frames: %s", proc.stderr.decode(errors="ignore")[-300:])
        raise ValidationError("Videodan kadr ajratib bo'lmadi. Qayta yozib ko'ring.")

    if len(files) <= count:
        picked = files
    else:
        step = (len(files) - 1) / (count - 1)
        picked = [files[round(i * step)] for i in range(count)]

    out: list[bytes] = []
    for p in picked:
        img = Image.open(p).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out.append(buf.getvalue())
    return out


def _assemble_motion_mp4(frame_jpegs: list[bytes], work_dir: Path) -> tuple[bytes, int, int]:
    """Assemble dressed user motion frames into a fluid 24 fps MP4 using optical-flow interpolation."""
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

    if len(imgs) == 1:
        vf = f"fps={OUTPUT_FPS},format=yuv420p"
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            "3.0",
            "-i",
            str(work_dir / "dressed_001.jpg"),
            "-vf",
            vf,
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
    else:
        # Optical-flow motion-compensated interpolation preserves the user's exact recorded movements
        # between consecutive dressed frames without artificial camera panning or slideshow cuts.
        vf = (
            f"minterpolate=fps={OUTPUT_FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
            "format=yuv420p"
        )
        cmd = [
            ffmpeg,
            "-y",
            "-framerate",
            f"{input_fps:.2f}",
            "-i",
            str(work_dir / "dressed_%03d.jpg"),
            "-vf",
            vf,
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

    proc = subprocess.run(cmd, capture_output=True, timeout=90, check=False)
    if proc.returncode != 0 or not out_mp4.is_file():
        logger.warning("ffmpeg minterpolate failed, falling back to blend: %s", proc.stderr.decode(errors="ignore")[-300:])
        fallback_cmd = [
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
        proc2 = subprocess.run(fallback_cmd, capture_output=True, timeout=60, check=False)
        if proc2.returncode != 0 or not out_mp4.is_file():
            logger.warning("ffmpeg fallback failed: %s", proc2.stderr.decode(errors="ignore")[-300:])
            raise openai_tryon.OpenAITryOnError("provider_unavailable")
    return out_mp4.read_bytes(), target_w, target_h


def render_video_tryon(*, video_upload, garment) -> VideoTryOnResult:
    """Process uploaded camera video + garment → motion-preserving 24 fps MP4 video."""
    if not openai_tryon.is_configured():
        raise openai_tryon.OpenAITryOnError("ai_tryon_not_configured")
    if video_upload.size > MAX_VIDEO_BYTES:
        raise ValidationError("Video hajmi 25 MB dan oshmasligi kerak.")

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="tryon-vid-") as tmp:
        work = Path(tmp)
        suffix = Path(video_upload.name or "clip.webm").suffix or ".webm"
        src = work / f"input{suffix}"
        with open(src, "wb") as fh:
            for chunk in video_upload.chunks():
                fh.write(chunk)

        keyframes = _extract_keyframes(src, work, count=KEYFRAME_COUNT)
        # Pre-read the garment image ONCE on the main thread (Django's FieldFile is not thread-safe).
        garment_bytes = openai_tryon._garment_png(garment)

        # Render all 8 motion frames in parallel via OpenAI gpt-image-1.5 (input_fidelity="high")
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
