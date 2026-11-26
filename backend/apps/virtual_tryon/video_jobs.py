"""Background fal.ai video try-on jobs.

A Kling video edit takes several minutes. Waiting for it inside one HTTP request fails on real
hosting (the proxy / Passenger / the browser drops the connection first) while fal still renders
and bills the job — so the user pays and never sees the video. Instead:

1. ``start`` uploads the clip, submits the job and stores its fal ``request_id`` (returns in seconds).
2. ``advance`` does one quick status check; when fal reports ``COMPLETED`` it downloads the MP4 and
   saves a ``SavedLook``. The browser calls it every few seconds; the
   ``finalize_video_jobs`` management command does the same for jobs whose tab was closed.

A submitted job is never resubmitted: a failed download is retried from the stored ``response_url``.

Pipelines (``settings.AI_TRYON["FAL_VIDEO_PIPELINE"]``):

* ``fast`` (default): stage PHOTO — FASHN dresses one frame of the clip (~20 s); that photo is saved
  as the look right away so the user sees themselves in the garment while stage VIDEO — LTX turns
  the photo into a short video (~30 s) — runs. About one minute in total.
* ``kling``: one Kling O3 edit of the user's own clip (keeps their exact motion; 5–12 minutes).
"""

import io
import logging
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from . import drive_sync, fal_tryon, motion_caption, openai_tryon, quota, video_tryon
from .models import AiRenderLog, RenderLogStatus, SavedLook, VideoJobStatus, VideoTryOnJob

logger = logging.getLogger("apps.virtual_tryon.video_jobs")

#: A job stuck in FINALIZING longer than this (a worker died mid-download) may be picked up again.
FINALIZE_LEASE = timedelta(minutes=5)
#: fal keeps queue results for a limited time; give up on jobs older than this.
MAX_JOB_AGE = timedelta(hours=6)


def _frame_jpeg(src: Path, work: Path) -> bytes:
    """A sharp frame from the start of the clip (the user faces the camera before turning)."""
    out = work / "frame.jpg"
    subprocess.run(  # noqa: S603 — fixed argv, paths we created
        [video_tryon._ffmpeg_bin(), "-y", "-ss", "0.4", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(out)],
        capture_output=True,
        timeout=20,
        check=False,
    )
    if not out.is_file():
        from rest_framework.exceptions import ValidationError

        raise ValidationError("Videodan kadr ajratib bo'lmadi. Qayta yozib ko'ring.")
    img = Image.open(out).convert("RGB")
    img.thumbnail((1536, 1536), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def start(*, user, video_upload, garment) -> VideoTryOnJob:
    if video_upload.size > video_tryon.MAX_VIDEO_BYTES:
        from rest_framework.exceptions import ValidationError

        raise ValidationError("Video hajmi 25 MB dan oshmasligi kerak.")
    pipeline = fal_tryon.video_pipeline()
    with tempfile.TemporaryDirectory(prefix="tryon-vid-") as tmp:
        work = Path(tmp)
        suffix = Path(video_upload.name or "clip.webm").suffix or ".webm"
        src = work / f"input{suffix}"
        with open(src, "wb") as fh:
            for chunk in video_upload.chunks():
                fh.write(chunk)
        motion = ""
        if pipeline == "fast":
            # describe the user's real movements while the photo stage is uploaded and submitted
            with ThreadPoolExecutor(max_workers=1) as pool:
                caption = pool.submit(motion_caption.describe, src, work)
                fal_job = fal_tryon.submit_photo_stage(frame_jpeg=_frame_jpeg(src, work), garment=garment)
                motion = caption.result()
            stage = "PHOTO"
        else:
            norm_mp4 = work / "input_720p.mp4"
            video_tryon._normalize_input_mp4(src, norm_mp4)
            fal_job = fal_tryon.submit_video_tryon(norm_mp4=norm_mp4, garment=garment)
            pipeline, stage = "kling", ""

    return VideoTryOnJob.objects.create(
        user=user,
        garment=garment,
        model=fal_job.model_id,
        pipeline=pipeline,
        stage=stage,
        motion_prompt=motion,
        request_id=fal_job.request_id,
        status_url=fal_job.status_url,
        response_url=fal_job.response_url,
    )


def _photo_stage_done(job: VideoTryOnJob) -> VideoTryOnJob:
    """FASHN finished: save the dressed photo as the look (shown at once) and start the video stage."""
    photo_url = fal_tryon.fetch_photo_url(job.response_url)
    img = Image.open(io.BytesIO(fal_tryon.download(photo_url, timeout=60))).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=True)
    motion = fal_tryon.submit_motion_stage(image_url=photo_url, garment=job.garment, motion=job.motion_prompt)

    look = job.look or SavedLook(user=job.user, garment=job.garment)
    look.width, look.height = img.width, img.height
    look.image.save(f"tryon-{job.garment_id or job.pk}.jpg", ContentFile(buf.getvalue()), save=False)
    look.save()
    job.look = look
    job.stage, job.status = "VIDEO", VideoJobStatus.PENDING
    job.model = f"{job.model} + {motion.model_id}"[:200]
    job.status_url, job.response_url = motion.status_url, motion.response_url
    job.save(update_fields=["look", "stage", "status", "model", "status_url", "response_url", "updated_at"])
    logger.info(
        "fal video job %s: photo ready (look %s), motion %s submitted", job.request_id, look.pk, motion.request_id
    )
    return job


def _drive_backup_later(look_id) -> None:
    """Copy the finished video to Google Drive in the background.

    Uploading a video can take minutes; doing it inside the status poll held the request open until
    the proxy gave up ("server temporarily unavailable") although the video was already saved.
    """

    def run():
        from django.db import connection

        try:
            drive_sync.upload_look_to_drive(SavedLook.objects.get(pk=look_id))
        except Exception:  # noqa: BLE001 — Drive backup must never affect the user's video
            logger.exception("drive upload of look %s failed", look_id)
        finally:
            connection.close()

    if getattr(settings, "TRYON_DRIVE_BACKUP_SYNC", False):  # tests: run inline
        run()
        return
    threading.Thread(target=run, name=f"drive-backup-{look_id}", daemon=True).start()


def _render_log(job: VideoTryOnJob) -> AiRenderLog | None:
    return AiRenderLog.objects.filter(ref=job.request_id, status=RenderLogStatus.RESERVED).first()


def _fail(job: VideoTryOnJob, code: str) -> None:
    log = _render_log(job)
    if log:
        quota.refund(log)  # a failed render does not use up the user's monthly video
    VideoTryOnJob.objects.filter(pk=job.pk).update(
        status=VideoJobStatus.FAILED, error_code=code, finished_at=timezone.now(), updated_at=timezone.now()
    )
    job.refresh_from_db()


def advance(job: VideoTryOnJob) -> VideoTryOnJob:
    """Move a job forward by at most one step. Never blocks for the render itself."""
    if job.status in (VideoJobStatus.DONE, VideoJobStatus.FAILED):
        return job
    now = timezone.now()
    if job.status == VideoJobStatus.FINALIZING and now - job.updated_at < FINALIZE_LEASE:
        return job  # another request is downloading it right now

    if now - job.created_at > MAX_JOB_AGE:
        _fail(job, "provider_timeout")
        return job

    try:
        fal_status, response_url = fal_tryon.check_video_job(job.status_url)
    except openai_tryon.OpenAITryOnError as exc:
        logger.warning("fal status check for %s failed (%s); will retry", job.request_id, exc.code)
        return job  # transient: keep PENDING, the next poll retries

    if fal_status in ("FAILED", "CANCELLED", "ERROR"):
        logger.warning("fal video job %s ended with %s", job.request_id, fal_status)
        _fail(job, "provider_rejected_request")
        return job
    if fal_status != "COMPLETED":
        return job

    # Claim the download so two polls do not both save a look.
    claimed = VideoTryOnJob.objects.filter(pk=job.pk, status=job.status, updated_at=job.updated_at).update(
        status=VideoJobStatus.FINALIZING, response_url=response_url or job.response_url, updated_at=now
    )
    job.refresh_from_db()
    if not claimed:
        return job

    if job.stage == "PHOTO":
        try:
            return _photo_stage_done(job)
        except openai_tryon.OpenAITryOnError as exc:
            logger.warning("fal photo stage of %s failed (%s); will retry", job.request_id, exc.code)
            VideoTryOnJob.objects.filter(pk=job.pk).update(status=VideoJobStatus.PENDING, updated_at=timezone.now())
            job.refresh_from_db()
            return job

    try:
        mp4_bytes = fal_tryon.fetch_video_result(job.response_url)
        with tempfile.TemporaryDirectory(prefix="tryon-out-") as tmp:
            out_mp4 = Path(tmp) / "fal_output.mp4"
            out_mp4.write_bytes(mp4_bytes)
            poster_bytes, width, height = video_tryon._extract_poster(out_mp4, Path(tmp) / "poster.jpg")
    except openai_tryon.OpenAITryOnError as exc:
        # The render is paid for and still on fal: go back to PENDING and download it on the next poll.
        logger.warning("fal video %s download failed (%s); will retry", job.request_id, exc.code)
        VideoTryOnJob.objects.filter(pk=job.pk).update(status=VideoJobStatus.PENDING, updated_at=timezone.now())
        job.refresh_from_db()
        return job

    tag = job.garment_id or job.pk
    look = job.look
    if look is None:  # kling pipeline: the first frame of the video is the poster
        look = SavedLook(user=job.user, garment=job.garment, width=width, height=height)
        look.image.save(f"tryon-{tag}.jpg", ContentFile(poster_bytes), save=False)
    look.video.save(f"tryon-{tag}.mp4", ContentFile(mp4_bytes), save=False)
    look.save()
    _drive_backup_later(look.pk)

    job.look = look
    job.status = VideoJobStatus.DONE
    job.finished_at = timezone.now()
    job.save(update_fields=["look", "status", "finished_at", "updated_at"])
    log = _render_log(job)
    if log:
        quota.done(log, job.model)
    logger.info("fal video job %s saved as look %s", job.request_id, look.pk)
    return job
