"""Backup mode (user decisions 2026-11-27).

3 free months from the first ceremony video; without Premium the couple's ceremonies go to Backup,
visible only to Admin / Super Admin; Premium brings them back; when Premium ends the couple is
notified and gets one new 3-month period.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import Role
from apps.backup import services
from apps.backup.models import BackupState, Notification, NotificationKind
from apps.media.models import CeremonyMedia
from apps.subscriptions.models import Subscription, SubscriptionPlan, SubscriptionStatus

from .conftest import subscribe
from .test_ceremony_invitations import MY, wedding, world  # noqa: F401
from .test_media_sharing import drive, gallery, media_url, share_with_guest  # noqa: F401

ADMIN = "/api/v1/admin/backup/"


def video_uploaded(g, days_ago: int):
    CeremonyMedia.objects.filter(pk=g["video"].pk).update(completed_at=timezone.now() - timedelta(days=days_ago))
    CeremonyMedia.objects.filter(pk=g["photo"].pk).update(completed_at=timezone.now() - timedelta(days=days_ago))


def past_premium(user, ended_days_ago: int):
    plan = SubscriptionPlan.objects.get(code="M1")
    end = timezone.now() - timedelta(days=ended_days_ago)
    return Subscription.objects.create(
        user=user, plan=plan, status=SubscriptionStatus.ACTIVE, price=plan.price, duration_months=1,
        max_viewers=plan.max_viewers, starts_at=end - timedelta(days=30), ends_at=end, paid_amount=plan.price,
    )  # fmt: skip


def staff(make_user, client_for, *codes):
    return client_for(make_user(Role.ADMIN, admin_permissions=list(codes)))


@pytest.mark.django_db
def test_free_period_starts_from_the_first_video_and_ends_in_backup(gallery):
    bride, c = gallery["users"]["bride"], gallery["ceremony"]
    share_with_guest(gallery)
    video_uploaded(gallery, days_ago=30)

    state = services.sync(bride)
    assert services.status_of(state, bride) == services.TRIAL
    assert state.grace_started_at == CeremonyMedia.objects.get(pk=gallery["video"].pk).completed_at
    assert (state.grace_ends_at - state.grace_started_at).days in (89, 90, 91, 92)  # 3 calendar months
    assert gallery["c"]["bride"].get(media_url(c)).status_code == 200

    video_uploaded(gallery, days_ago=100)
    BackupState.objects.filter(user=bride).update(grace_ends_at=None, first_video_at=None)
    state = services.sync(bride)
    assert state.in_backup and services.status_of(state, bride) == services.BACKUP
    # the couple and the people they shared with lose access; nothing is deleted
    assert gallery["c"]["bride"].get(media_url(c)).status_code == 404
    mine = gallery["c"]["bride"].get(MY).data
    assert (mine["results"] if isinstance(mine, dict) else mine) == []
    assert gallery["c"]["guest"].get(media_url(c)).status_code == 404
    assert CeremonyMedia.objects.filter(ceremony=c, status="READY").count() == 2

    note = Notification.objects.get(user=bride)
    assert note.kind == NotificationKind.TRIAL_ENDED and note.link == "/obuna"
    services.sync(bride)
    assert Notification.objects.filter(user=bride).count() == 1  # the cycle never repeats a notification
    assert gallery["c"]["bride"].get("/api/v1/me/notifications/").data[0]["title"].startswith("Sinov muddati tugadi")
    assert gallery["c"]["bride"].get("/api/v1/me/backup/").data["status"] == "BACKUP"


@pytest.mark.django_db
def test_buying_premium_leaves_backup_and_premium_end_gives_one_new_period(gallery, make_user, client_for):
    bride, c = gallery["users"]["bride"], gallery["ceremony"]
    video_uploaded(gallery, days_ago=200)
    assert services.sync(bride).in_backup

    seller = staff(make_user, client_for, "subscriptions.view", "subscriptions.create")
    plan = SubscriptionPlan.objects.get(code="M1")
    res = seller.post("/api/v1/admin/subscriptions/", {"user_id": str(bride.pk), "plan": str(plan.pk)})
    assert res.status_code == 201
    services.sync(bride)  # on_commit hook does this in production; tests run inside one transaction
    assert not BackupState.objects.get(user=bride).in_backup
    assert gallery["c"]["bride"].get(media_url(c)).status_code == 200
    assert Notification.objects.filter(user=bride, kind=NotificationKind.BACKUP_RELEASED).exists()

    # Premium ended 10 days ago → notified once, open for 3 months from that end, not in Backup
    Subscription.objects.filter(user=bride).update(
        starts_at=timezone.now() - timedelta(days=40), ends_at=timezone.now() - timedelta(days=10)
    )
    state = services.sync(bride)
    services.sync(bride)
    assert not state.in_backup and state.grace_reason == "PREMIUM_ENDED"
    assert state.grace_started_at == Subscription.objects.get(user=bride).ends_at
    assert Notification.objects.filter(user=bride, kind=NotificationKind.PREMIUM_ENDED).count() == 1
    first_end = state.grace_ends_at
    assert services.sync(bride).grace_ends_at == first_end  # one period at a time, never stacked


@pytest.mark.django_db
def test_premium_that_ended_long_ago_goes_to_backup(gallery):
    bride = gallery["users"]["bride"]
    video_uploaded(gallery, days_ago=400)
    past_premium(bride, ended_days_ago=120)
    state = services.sync(bride)
    assert state.in_backup


@pytest.mark.django_db
def test_no_video_means_no_period_and_no_backup(wedding):
    bride = wedding["users"]["bride"]
    state = services.sync(bride)
    assert state.grace_ends_at is None and not state.in_backup
    assert services.status_of(state, bride) == services.NO_VIDEO


@pytest.mark.django_db
def test_admin_sees_states_moves_users_and_views_backed_up_media(gallery, make_user, client_for):
    bride, c = gallery["users"]["bride"], gallery["ceremony"]
    video_uploaded(gallery, days_ago=200)
    viewer = staff(make_user, client_for, "backup.view")
    manager = staff(make_user, client_for, "backup.view", "backup.manage")
    assert staff(make_user, client_for, "dashboard.view").get(ADMIN).status_code == 403

    rows = viewer.get(ADMIN).data
    rows = rows["results"] if isinstance(rows, dict) else rows
    row = next(r for r in rows if r["id"] == str(bride.pk))
    assert row["status"] == "BACKUP" and row["videos"] == 1 and row["ceremonies"] == 1  # list syncs itself

    # only staff see what is in Backup — originals included
    media = viewer.get(f"{ADMIN}ceremonies/{c.pk}/media/")
    assert media.status_code == 200 and len(media.data) == 2
    assert viewer.get(f"{ADMIN}ceremonies/{c.pk}/media/{gallery['video'].pk}/stream/").status_code == 200
    assert gallery["c"]["bride"].get(media_url(c)).status_code == 404
    assert viewer.post(f"{ADMIN}{bride.pk}/release/", {"days": 30}).status_code == 403

    # release for 30 days, then put back
    res = manager.post(f"{ADMIN}{bride.pk}/release/", {"days": 30}, format="json")
    assert res.status_code == 200 and res.data["status"] == "TRIAL"
    assert gallery["c"]["bride"].get(media_url(c)).status_code == 200
    assert services.sync(bride).in_backup is False  # the admin's date holds against the cycle
    assert manager.post(f"{ADMIN}{bride.pk}/backup/", {"note": "Test"}, format="json").data["status"] == "BACKUP"

    # with Premium running the user cannot be put into Backup; admins can extend Premium
    subscribe(bride)
    services.sync(bride)
    assert manager.post(f"{ADMIN}{bride.pk}/backup/", {}, format="json").status_code == 400
    until = (timezone.now() + timedelta(days=200)).isoformat()
    res = manager.post(f"{ADMIN}{bride.pk}/extend-premium/", {"until": until}, format="json")
    assert res.status_code == 200 and res.data["status"] == "PREMIUM"
    assert abs((Subscription.objects.get(user=bride).ends_at - timezone.now()).days - 200) <= 1

    # staff can remove a file kept in Backup
    assert manager.delete(f"{ADMIN}ceremonies/{c.pk}/media/{gallery['photo'].pk}/").status_code == 204
    assert CeremonyMedia.objects.get(pk=gallery["photo"].pk).status == "DELETED"
