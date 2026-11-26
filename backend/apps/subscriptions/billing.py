"""Mandatory monthly fee of businesses (user decision 2026-11-26).

A venue pays 300 000 and a studio 150 000 so'm a month; a running payment *is* their Premium
(galichka). When it ends the business keeps panel access, sees a "payment needed" banner, and after
``GRACE_DAYS`` disappears from the public catalog (``visible_q``) until it pays again.

A business never paid is treated as if its last period ended when it was created — or on the
launch day (``START``) for businesses that existed before the fee — so everyone gets the same grace.
"""

import datetime
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from .models import Subscription, SubscriptionStatus

OK, GRACE, OVERDUE = "OK", "GRACE", "OVERDUE"


def _cfg() -> dict:
    return settings.BUSINESS_BILLING


def enforced() -> bool:
    return bool(_cfg()["ENFORCE"])


def grace() -> datetime.timedelta:
    return datetime.timedelta(days=_cfg()["GRACE_DAYS"])


def launch() -> datetime.datetime:
    day = datetime.date.fromisoformat(_cfg()["START"])
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))


def monthly_fee(kind: str) -> int:
    return _cfg()["VENUE_MONTHLY_FEE"] if kind == "venue" else _cfg()["STUDIO_MONTHLY_FEE"]


@dataclass(frozen=True)
class Standing:
    state: str  # OK / GRACE / OVERDUE
    paid_until: datetime.datetime | None
    grace_until: datetime.datetime
    monthly_fee: int

    @property
    def visible(self) -> bool:
        return self.state != OVERDUE or not enforced()


def _paid_until(kind: str, business) -> datetime.datetime | None:
    return (
        Subscription.objects.filter(**{kind: business}, status=SubscriptionStatus.ACTIVE, starts_at__lte=timezone.now())
        .order_by("-ends_at")
        .values_list("ends_at", flat=True)
        .first()
    )


def standing(*, studio=None, venue=None) -> Standing:
    kind, business = ("studio", studio) if studio is not None else ("venue", venue)
    now = timezone.now()
    paid_until = _paid_until(kind, business)
    period_end = paid_until or max(business.created_at, launch())
    grace_until = period_end + grace()
    if paid_until and paid_until > now:
        state = OK
    elif now < grace_until:
        state = GRACE
    else:
        state = OVERDUE
    return Standing(state, paid_until, grace_until, monthly_fee(kind))


def visible_q(kind: str) -> Q:
    """Filter for the public catalog of ``kind`` ("studio" / "venue"): paid, or still within grace."""
    if not enforced():
        return Q()
    now = timezone.now()
    cutoff = now - grace()  # a period that ended after this is still in grace
    if launch() > cutoff:
        return Q()  # everyone is still inside the launch grace
    paid_recently = Subscription.objects.filter(
        **{kind: OuterRef("pk")}, status=SubscriptionStatus.ACTIVE, starts_at__lte=now, ends_at__gt=cutoff
    )
    return Q(Exists(paid_recently)) | Q(created_at__gt=cutoff)
