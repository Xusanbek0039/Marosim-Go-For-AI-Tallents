"""Monthly AI try-on quotas (user decision 2026-11-26).

* Premium: the running subscription's ``ai_video_per_month`` / ``ai_photo_per_month``.
* Without Premium: ``AI_FREE_PHOTOS_PER_MONTH`` photos and no video.

Months are calendar months in the server time zone (Asia/Tashkent). A render is reserved before the
provider is called and refunded if it fails, so a failed render never uses up the quota.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.subscriptions.services import active_subscription

from .models import AiRenderLog, RenderKind, RenderLogStatus

UNIT_COST_USD = {
    RenderKind.PHOTO: lambda: Decimal(str(settings.PLATFORM_COSTS["AI_PHOTO_USD"])),
    RenderKind.VIDEO: lambda: Decimal(str(settings.PLATFORM_COSTS["AI_VIDEO_USD"])),
}


@dataclass(frozen=True)
class Quota:
    is_premium: bool
    video_limit: int
    photo_limit: int
    video_used: int
    photo_used: int

    @property
    def video_left(self) -> int:
        return max(0, self.video_limit - self.video_used)

    @property
    def photo_left(self) -> int:
        return max(0, self.photo_limit - self.photo_used)


def month_start():
    return timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _used(user, kind: str) -> int:
    return (
        AiRenderLog.objects.filter(user=user, kind=kind, created_at__gte=month_start())
        .exclude(status=RenderLogStatus.REFUNDED)
        .count()
    )


def quota(user) -> Quota:
    sub = active_subscription(user)
    if sub:
        video_limit, photo_limit = sub.ai_video_per_month, sub.ai_photo_per_month
    else:
        video_limit, photo_limit = 0, settings.AI_FREE_PHOTOS_PER_MONTH
    return Quota(
        is_premium=sub is not None,
        video_limit=video_limit,
        photo_limit=photo_limit,
        video_used=_used(user, RenderKind.VIDEO),
        photo_used=_used(user, RenderKind.PHOTO),
    )


def reserve(user, kind: str) -> AiRenderLog:
    """Take one render from this month's quota or raise ``AiTryOnError`` (403)."""
    from apps.accounts.models import User

    from .ai import AiTryOnError

    with transaction.atomic():
        User.objects.select_for_update().filter(pk=user.pk).first()  # serialise one user's reservations
        q = quota(user)
        if kind == RenderKind.VIDEO and not q.is_premium:
            raise AiTryOnError(
                "ai_premium_required",
                "AI video faqat Premium obunada. Obuna bo'limida Premium sotib oling.",
                status.HTTP_403_FORBIDDEN,
            )
        left = q.video_left if kind == RenderKind.VIDEO else q.photo_left
        if left <= 0:
            what = "AI video" if kind == RenderKind.VIDEO else "AI foto"
            hint = "" if q.is_premium else " Premium obunada limit ko'proq."
            raise AiTryOnError(
                "ai_quota_exhausted",
                f"Bu oy uchun {what} limiti tugadi.{hint}",
                status.HTTP_403_FORBIDDEN,
            )
        return AiRenderLog.objects.create(user=user, kind=kind)


def done(log: AiRenderLog, model: str) -> None:
    log.status, log.model, log.cost_usd = RenderLogStatus.DONE, model[:200], UNIT_COST_USD[log.kind]()
    log.save(update_fields=["status", "model", "cost_usd", "updated_at"])


def refund(log: AiRenderLog) -> None:
    log.status, log.cost_usd = RenderLogStatus.REFUNDED, 0
    log.save(update_fields=["status", "cost_usd", "updated_at"])
