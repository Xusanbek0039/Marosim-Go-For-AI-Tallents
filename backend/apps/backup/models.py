"""Backup mode of couples' accounts (user decisions 2026-11-27).

* A couple (USER) gets a free 3-month period counted from the day the first video of a ceremony they
  own was uploaded. A Premium subscription keeps them out of Backup while it runs; when it ends they
  are notified and get a new 3-month period (one period at a time, never stacked).
* When the period ends without Premium the account moves to Backup automatically: the couple and the
  people they shared with no longer see the ceremonies; only Admin / Super Admin can view and manage
  that media. Buying Premium brings the account back at once.
* Nothing is deleted by Backup itself.
"""

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class GraceReason(models.TextChoices):
    FIRST_VIDEO = "FIRST_VIDEO", "Birinchi video joylangan kundan"
    PREMIUM_ENDED = "PREMIUM_ENDED", "Premium tugagan kundan"
    ADMIN = "ADMIN", "Admin belgilagan"


class BackupState(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_state")
    #: The one running free period (never more than one per user).
    grace_started_at = models.DateTimeField(null=True, blank=True)
    grace_ends_at = models.DateTimeField(null=True, blank=True, db_index=True)
    grace_reason = models.CharField(max_length=16, choices=GraceReason.choices, blank=True)
    in_backup = models.BooleanField(default=False, db_index=True)
    backup_since = models.DateTimeField(null=True, blank=True)
    first_video_at = models.DateTimeField(null=True, blank=True)
    #: End of the last Premium period already turned into a new free period (so it happens once).
    premium_end_handled_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.user} · {'BACKUP' if self.in_backup else 'faol'}"


class NotificationKind(models.TextChoices):
    TRIAL_ENDED = "TRIAL_ENDED", "Sinov muddati tugadi — Backup"
    PREMIUM_ENDED = "PREMIUM_ENDED", "Premium tugadi"
    BACKUP_RELEASED = "BACKUP_RELEASED", "Backupdan chiqarildi"
    BACKUP_ADMIN = "BACKUP_ADMIN", "Admin Backupga o'tkazdi"
    INFO = "INFO", "Xabar"


class Notification(BaseModel):
    """In-app notification shown in the user panel (the project has no SMS / e-mail channel yet)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=NotificationKind.choices, default=NotificationKind.INFO)
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=600, blank=True)
    link = models.CharField(max_length=200, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    #: De-duplicates automatic notifications (the cycle may run many times for one event).
    key = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"], condition=~models.Q(key=""), name="backup_notification_unique_key"
            )
        ]
