"""Video Virtual Try-On pipeline for Apple Silicon / CPU servers (ffmpeg + OpenAI gpt-image-1.5).

Flow:
1. Extract 3 evenly-spaced pose keyframes from the user's 3–5 s camera video via ``ffmpeg``.
2. Run ``openai_tryon.render_tryon`` on the keyframes in parallel (preserving facial identity with
   ``input_fidelity="high"``).
3. Assemble the dressed frames into a smooth, looping ~5 s H.264 MP4 showcase via ``ffmpeg``
   ``xfade`` transitions (compatible with Chrome, Safari, iOS and Android).
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
KEYFRAME_COUNT = 3


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
    """Extract ``count`` evenly-spaced PNG frames from ``video_path`` using ffmpeg."""
    ffmpeg = _ffmpeg_bin()
    pattern = out_dir / "frame_%02d.png"
    # Sample at 1 fps (capped to 10 frames) and pick evenly spaced frames so it works on any duration/codec.
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "fps=2,scale='min(1024,iw)':'min(1024,ih)':force_original_aspect_ratio=decrease",
        "-frames:v",
        "12",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    files = sorted(out_dir.glob("frame_*.png"))
    if not files:
        # Fallback: grab at least the very first frame if video is ultra-short
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


def _assemble_mp4(frame_jpegs: list[bytes], work_dir: Path) -> tuple[bytes, int, int]:
    """Normalize frame sizes and stitch them into a smooth H.264 MP4 using ffmpeg xfade."""
    ffmpeg = _ffmpeg_bin()
    imgs = [Image.open(io.BytesIO(raw)).convert("RGB") for raw in frame_jpegs]
    # Use the first frame's aspect ratio, rounded to even dimensions for yuv420p.
    target_w = (imgs[0].width // 2) * 2
    target_h = (imgs[0].height // 2) * 2
    saved: list[Path] = []
    for idx, img in enumerate(imgs):
        if img.size != (target_w, target_h):
            img = img.resize((target_w, target_h), Image.LANCZOS)
        path = work_dir / f"dressed_{idx:02d}.jpg"
        img.save(path, format="JPEG", quality=92)
        saved.append(path)

    out_mp4 = work_dir / "tryon_result.mp4"
    if len(saved) == 1:
        cmd = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-t",
            "3.5",
            "-i",
            str(saved[0]),
            "-vf",
            "fps=25,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
    else:
        # Build smooth crossfade chain across all frames (plus return to frame 0 for seamless loop feel)
        seq = [*saved, saved[0]]
        seg_dur = 1.6
        fade_dur = 0.55
        inputs: list[str] = []
        for p in seq:
            inputs += ["-loop", "1", "-t", str(seg_dur), "-i", str(p)]
        filters: list[str] = []
        prev = "0:v"
        for i in range(1, len(seq)):
            offset = round(i * (seg_dur - fade_dur), 2)
            out_label = f"v{i}"
            filters.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={fade_dur}:offset={offset}[{out_label}]")
            prev = out_label
        filters.append(f"[{prev}]format=yuv420p[outv]")
        cmd = [
            ffmpeg,
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[outv]",
            "-r",
            "25",
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
        logger.warning("ffmpeg assemble failed: %s", proc.stderr.decode(errors="ignore")[-400:])
        raise openai_tryon.OpenAITryOnError("provider_unavailable")
    return out_mp4.read_bytes(), target_w, target_h


def render_video_tryon(*, video_upload, garment) -> VideoTryOnResult:
    """Process uploaded camera video + garment → dressed MP4 video."""
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

        # Render all keyframes in parallel via OpenAI gpt-image-1.5 (input_fidelity="high")
        def _dress(frame_bytes: bytes) -> openai_tryon.TryOnRenderResult:
            return openai_tryon.render_tryon(photo_bytes=frame_bytes, garment=garment)

        with ThreadPoolExecutor(max_workers=len(keyframes)) as pool:
            results = list(pool.map(_dress, keyframes))

        dressed_jpegs = [r.image_bytes for r in results]
        mp4_bytes, width, height = _assemble_mp4(dressed_jpegs, work)

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
