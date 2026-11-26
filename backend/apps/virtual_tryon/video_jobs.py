"""Background fal.ai video try-on jobs.

A Kling video edit takes several minutes. Waiting for it inside one HTTP request fails on real
hosting (the proxy / Passenger / the browser drops the connection first) while fal still renders
and bills the job — so the user pays and never sees the video. Instead:

1. ``start`` uploads the clip, submits the job and stores its fal ``request_id`` (returns in seconds).
2. ``advance`` does one quick status check; when fal reports ``COMPLETED`` it downloads the MP4 and
   saves a ``SavedLook``. The browser calls it every few seconds; the
   ``finalize_video_jobs`` management command does the same for jobs whose tab was closed.

A submitted job is never resubmitted: a failed download is retried from the stored ``response_url``.
"""

import logging
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from . import drive_sync, fal_tryon, openai_tryon, video_tryon
from .models import SavedLook, VideoJobStatus, VideoTryOnJob

logger = logging.getLogger("apps.virtual_tryon.video_jobs")

#: A job stuck in FINALIZING longer than this (a worker died mid-download) may be picked up again.
FINALIZE_LEASE = timedelta(minutes=5)
#: fal keeps queue results for a limited time; give up on jobs older than this.
MAX_JOB_AGE = timedelta(hours=6)


def start(*, user, video_upload, garment) -> VideoTryOnJob:
    if video_upload.size > video_tryon.MAX_VIDEO_BYTES:
        from rest_framework.exceptions import ValidationError

        raise ValidationError("Video hajmi 25 MB dan oshmasligi kerak.")
    with tempfile.TemporaryDirectory(prefix="tryon-vid-") as tmp:
        work = Path(tmp)
        suffix = Path(video_upload.name or "clip.webm").suffix or ".webm"
        src = work / f"input{suffix}"
        with open(src, "wb") as fh:
            for chunk in video_upload.chunks():
                fh.write(chunk)
        norm_mp4 = work / "input_720p.mp4"
        video_tryon._normalize_input_mp4(src, norm_mp4)
        fal_job = fal_tryon.submit_video_tryon(norm_mp4=norm_mp4, garment=garment)

    return VideoTryOnJob.objects.create(
        user=user,
        garment=garment,
        model=fal_job.model_id,
        request_id=fal_job.request_id,
        status_url=fal_job.status_url,
        response_url=fal_job.response_url,
    )


def _fail(job: VideoTryOnJob, code: str) -> None:
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

    look = SavedLook(user=job.user, garment=job.garment, width=width, height=height)
    tag = job.garment_id or job.pk
    look.image.save(f"tryon-{tag}.jpg", ContentFile(poster_bytes), save=False)
    look.video.save(f"tryon-{tag}.mp4", ContentFile(mp4_bytes), save=False)
    look.save()
    try:
        drive_sync.upload_look_to_drive(look)
    except Exception:  # noqa: BLE001 — Drive backup must never lose the paid video
        logger.exception("drive upload of look %s failed", look.pk)

    job.look = look
    job.status = VideoJobStatus.DONE
    job.finished_at = timezone.now()
    job.save(update_fields=["look", "status", "finished_at", "updated_at"])
    logger.info("fal video job %s saved as look %s", job.request_id, look.pk)
    return job
