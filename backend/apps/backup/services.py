"""Backup rules. ``sync(user)`` is the single place that moves a user between states; it is
idempotent (the cron cycle, subscription approval and the admin list may all call it) and holds a row
lock so two callers never grant two free periods or send a notification twice.

States shown in the panels (``status_of``):

* ``NO_VIDEO`` — no ceremony video yet, the free period has not started.
* ``TRIAL``    — inside the free period (from the first video, after Premium, or set by an admin).
* ``PREMIUM``  — a personal subscription is running.
* ``BACKUP``   — the period ended without Premium: ceremonies hidden from the couple and their guests.
"""

import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, Min, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Role, User
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.subscriptions.services import add_months

from .models import BackupState, GraceReason, Notification, NotificationKind

NO_VIDEO, TRIAL, PREMIUM, BACKUP = "NO_VIDEO", "TRIAL", "PREMIUM", "BACKUP"


def free_months() -> int:
    return int(getattr(settings, "BACKUP_FREE_MONTHS", 3))


def _fmt(moment: datetime.datetime) -> str:
    return timezone.localtime(moment).strftime("%d.%m.%Y")


# --------------------------------------------------------------- reading
def first_video_at(user) -> datetime.datetime | None:
    from apps.ceremonies.models import CeremonyOwnership, OwnershipStatus
    from apps.media.models import CeremonyMedia, MediaKind, MediaStatus

    owned = CeremonyOwnership.objects.filter(user=user, status=OwnershipStatus.ACCEPTED).values("ceremony_id")
    return CeremonyMedia.objects.filter(
        ceremony_id__in=owned, kind=MediaKind.VIDEO, status=MediaStatus.READY, completed_at__isnull=False
    ).aggregate(first=Min("completed_at"))["first"]


def _personal_subs(user):
    return Subscription.objects.filter(
        user=user, studio__isnull=True, venue__isnull=True, status=SubscriptionStatus.ACTIVE
    )


def running_premium(user, now=None) -> Subscription | None:
    now = now or timezone.now()
    return _personal_subs(user).filter(starts_at__lte=now, ends_at__gt=now).order_by("-ends_at").first()


def premium_until(user, now=None) -> datetime.datetime | None:
    """End of the paid time, including periods queued after the running one."""
    now = now or timezone.now()
    return _personal_subs(user).filter(ends_at__gt=now).order_by("-ends_at").values_list("ends_at", flat=True).first()


def user_in_backup(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or user.role != Role.USER:
        return False
    return BackupState.objects.filter(user=user, in_backup=True).exists()


def backed_up_ceremonies_q() -> Q:
    """Ceremonies whose every accepted owner is in Backup (their guests lose access too)."""
    from apps.ceremonies.models import CeremonyOwnership, OwnershipStatus

    accepted = CeremonyOwnership.objects.filter(ceremony=OuterRef("pk"), status=OwnershipStatus.ACCEPTED)
    active_owner = accepted.exclude(user__backup_state__in_backup=True)
    return Q(Exists(accepted)) & ~Q(Exists(active_owner))


def status_of(state: BackupState | None, user, now=None) -> str:
    now = now or timezone.now()
    if state and state.in_backup:
        return BACKUP
    if running_premium(user, now):
        return PREMIUM
    if state is None or state.grace_ends_at is None:
        return NO_VIDEO
    return TRIAL


# ---------------------------------------------------------- notifications
def notify(user, kind: str, title: str, body: str = "", link: str = "", key: str = "") -> Notification | None:
    if key and Notification.objects.filter(user=user, key=key).exists():
        return None
    return Notification.objects.create(user=user, kind=kind, title=title, body=body, link=link, key=key)


def _notify_backup(user, state: BackupState) -> None:
    notify(
        user,
        NotificationKind.TRIAL_ENDED,
        "Sinov muddati tugadi — akkauntingiz Backup rejimida",
        "3 oylik bepul muddat tugadi. Video va rasmlaringiz o'chirilmagan, ular xavfsiz Backupda saqlanmoqda, "
        "lekin hozir ularni siz ham, siz ulashgan odamlar ham ko'ra olmaysiz. Premium obuna sotib olsangiz, "
        "hammasi darhol qaytadi.",
        "/obuna",
        key=f"backup:{state.grace_ends_at.isoformat() if state.grace_ends_at else 'manual'}",
    )


def _notify_released(user, reason: str) -> None:
    notify(
        user,
        NotificationKind.BACKUP_RELEASED,
        "Akkauntingiz Backup rejimidan chiqarildi",
        reason,
        "/",
        key=f"released:{timezone.now().isoformat()}",
    )


# ------------------------------------------------------------------- sync
def _lock(user) -> BackupState:
    state, _ = BackupState.objects.get_or_create(user=user)
    return BackupState.objects.select_for_update().get(pk=state.pk)


def sync(user, now=None) -> BackupState | None:
    """Bring one couple's state up to date. Returns ``None`` for non-USER accounts."""
    if user.role != Role.USER:
        return None
    now = now or timezone.now()
    with transaction.atomic():
        state = _lock(user)
        months = free_months()
        changed = ["synced_at", "updated_at"]

        # 1. the first free period starts on the day the first ceremony video was uploaded
        if state.first_video_at is None:
            state.first_video_at = first_video_at(user)
            changed.append("first_video_at")
        if state.grace_ends_at is None and state.first_video_at:
            state.grace_started_at = state.first_video_at
            state.grace_ends_at = add_months(state.first_video_at, months)
            state.grace_reason = GraceReason.FIRST_VIDEO
            changed += ["grace_started_at", "grace_ends_at", "grace_reason"]

        # 2. while Premium runs the account is never in Backup
        if running_premium(user, now):
            if state.in_backup:
                state.in_backup, state.backup_since = False, None
                changed += ["in_backup", "backup_since"]
                _notify_released(user, "Premium obunangiz faol — barcha marosimlaringiz yana ochiq.")
            state.synced_at = now
            state.save(update_fields=sorted(set(changed)))
            return state

        # 3. Premium ended: notify once and give one new free period from its end (replacing, not stacking)
        last_end = (
            _personal_subs(user).filter(ends_at__lte=now).order_by("-ends_at").values_list("ends_at", flat=True).first()
        )
        if last_end and (state.premium_end_handled_at is None or last_end > state.premium_end_handled_at):
            new_end = add_months(last_end, months)
            if state.grace_ends_at is None or new_end > state.grace_ends_at:
                state.grace_started_at, state.grace_ends_at = last_end, new_end
                state.grace_reason = GraceReason.PREMIUM_ENDED
                changed += ["grace_started_at", "grace_ends_at", "grace_reason"]
            state.premium_end_handled_at = last_end
            changed.append("premium_end_handled_at")
            if new_end > now:
                notify(
                    user,
                    NotificationKind.PREMIUM_ENDED,
                    "Premium obunangiz tugadi",
                    f"Marosimlaringiz {_fmt(new_end)} gacha ochiq qoladi. Shu kungacha Premiumni yangilamasangiz, "
                    "akkauntingiz Backup rejimiga o'tadi va video-rasmlarni faqat Premium bilan qayta ko'rasiz.",
                    "/obuna",
                    key=f"premium_ended:{last_end.isoformat()}",
                )

        # 4. the free period is over and there is no Premium → Backup
        if not state.in_backup and state.grace_ends_at and now >= state.grace_ends_at:
            state.in_backup, state.backup_since = True, now
            changed += ["in_backup", "backup_since"]
            _notify_backup(user, state)

        state.synced_at = now
        state.save(update_fields=sorted(set(changed)))
        return state


def candidates():
    """Couples that own a ceremony with a ready video, plus everyone who already has a state."""
    from apps.ceremonies.models import CeremonyOwnership, OwnershipStatus
    from apps.media.models import CeremonyMedia, MediaKind, MediaStatus

    with_video = CeremonyMedia.objects.filter(kind=MediaKind.VIDEO, status=MediaStatus.READY).values("ceremony_id")
    owners = CeremonyOwnership.objects.filter(status=OwnershipStatus.ACCEPTED, ceremony_id__in=with_video).values(
        "user_id"
    )
    return User.objects.filter(role=Role.USER).filter(Q(pk__in=owners) | Q(backup_state__isnull=False)).distinct()


def sync_all(now=None) -> dict[str, int]:
    now = now or timezone.now()
    counts = {NO_VIDEO: 0, TRIAL: 0, PREMIUM: 0, BACKUP: 0}
    for user in candidates().iterator():
        state = sync(user, now)
        counts[status_of(state, user, now)] += 1
    return counts


# ----------------------------------------------------------- admin actions
def put_in_backup(user, by, note: str = "") -> BackupState:
    with transaction.atomic():
        if running_premium(user):
            raise ValidationError({"detail": "Premium obunasi faol foydalanuvchini Backupga o'tkazib bo'lmaydi."})
        state = _lock(user)
        now = timezone.now()
        state.in_backup, state.backup_since = True, now
        state.grace_ends_at = min(state.grace_ends_at or now, now)
        state.grace_reason = state.grace_reason or GraceReason.ADMIN
        state.save()
    notify(
        user,
        NotificationKind.BACKUP_ADMIN,
        "Akkauntingiz Backup rejimiga o'tkazildi",
        (note + " " if note else "")
        + "Video va rasmlaringiz o'chirilmagan. Ularni qayta ko'rish uchun Premium obuna sotib oling.",
        "/obuna",
        key=f"admin_backup:{now.isoformat()}",
    )
    return state


def release(user, by, until: datetime.datetime, note: str = "") -> BackupState:
    """Take a user out of Backup and keep them out until ``until`` (a new free period set by an admin)."""
    if until <= timezone.now():
        raise ValidationError({"until": ["Sana kelajakda bo'lishi kerak."]})
    with transaction.atomic():
        state = _lock(user)
        was_in_backup = state.in_backup
        state.in_backup, state.backup_since = False, None
        state.grace_started_at, state.grace_ends_at, state.grace_reason = timezone.now(), until, GraceReason.ADMIN
        state.save()
    if was_in_backup:
        _notify_released(user, (note + " " if note else "") + f"Marosimlaringiz {_fmt(until)} gacha ochiq.")
    return state


def extend_premium(user, until: datetime.datetime) -> Subscription:
    """Move the end of the user's last Premium period (running or queued) to ``until``."""
    now = timezone.now()
    sub = _personal_subs(user).filter(ends_at__gt=now).order_by("-ends_at").first()
    if sub is None:
        raise ValidationError(
            {"detail": "Faol Premium yo'q. Avval 'Obunalar' bo'limida obuna bering, keyin uzaytiring."}
        )
    if until <= sub.starts_at:
        raise ValidationError({"until": ["Yangi sana obuna boshlanishidan keyin bo'lishi kerak."]})
    sub.ends_at = until
    sub.save(update_fields=["ends_at", "updated_at"])
    sync(user)
    return sub
