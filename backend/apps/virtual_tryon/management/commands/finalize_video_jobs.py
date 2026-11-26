"""Save finished fal.ai video try-ons whose browser tab was closed. Run from cron every minute or two."""

from django.core.management.base import BaseCommand

from apps.virtual_tryon import video_jobs
from apps.virtual_tryon.models import VideoJobStatus, VideoTryOnJob


class Command(BaseCommand):
    help = "Check pending fal.ai video try-on jobs and save the finished ones as looks."

    def handle(self, *args, **options):
        pending = VideoTryOnJob.objects.filter(status__in=[VideoJobStatus.PENDING, VideoJobStatus.FINALIZING])
        counts = {}
        for job in pending.order_by("created_at")[:50]:
            job = video_jobs.advance(job)
            counts[job.status] = counts.get(job.status, 0) + 1
        self.stdout.write(", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no pending jobs")
