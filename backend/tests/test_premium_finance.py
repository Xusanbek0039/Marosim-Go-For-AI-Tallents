"""Premium AI quotas, the mandatory business fee and the admin income/expense report (2026-11-26)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import Role
from apps.studios.models import Studio
from apps.subscriptions.models import Subscription, SubscriptionPlan, SubscriptionStatus
from apps.subscriptions.services import add_months
from apps.virtual_tryon import fal_tryon, openai_tryon, video_jobs
from apps.virtual_tryon.models import AiRenderLog, RenderKind, RenderLogStatus, VideoTryOnJob
from tests.conftest import subscribe
from tests.test_ai_tryon import make_garment, reference_png

BASE = "/api/v1/virtual-tryon"
FINANCE = "/api/v1/admin/finance/"


@pytest.fixture
def fal(settings):
    settings.AI_TRYON = {**settings.AI_TRYON, "FAL_KEY": "fal_test", "API_KEY": ""}
    settings.AI_FREE_PHOTOS_PER_MONTH = 3


def _photo(client, garment):
    upload = SimpleUploadedFile("me.png", reference_png(size=(256, 320)), content_type="image/png")
    return client.post(f"{BASE}/ai/render/", {"garment": str(garment.pk), "photo": upload}, format="multipart")


def _fake_photo(monkeypatch, fail=False):
    def render(**kwargs):
        if fail:
            raise openai_tryon.OpenAITryOnError("provider_unavailable")
        return openai_tryon.TryOnRenderResult(
            image_bytes=reference_png(size=(64, 80)), content_type="image/png", width=64, height=80,
            model="fal-ai/fashn/tryon/v1.6", latency_ms=5,
        )

    monkeypatch.setattr(fal_tryon, "render_photo_tryon", render)


# ------------------------------------------------------------------ AI quotas
@pytest.mark.django_db
def test_free_user_gets_three_photos_a_month_and_failed_renders_are_refunded(fal, monkeypatch, plain_user, client_for):
    garment = make_garment()
    client = client_for(plain_user)

    _fake_photo(monkeypatch, fail=True)
    assert _photo(client, garment).status_code == 503
    assert AiRenderLog.objects.get().status == RenderLogStatus.REFUNDED  # a failure costs nothing

    _fake_photo(monkeypatch)
    for _ in range(3):
        assert _photo(client, garment).status_code == 200
    blocked = _photo(client, garment)
    assert blocked.status_code == 403 and blocked.data["error"]["code"] == "ai_quota_exhausted"

    status = client.get(f"{BASE}/ai/status/").data
    assert status["quota"] == {"video_limit": 0, "video_left": 0, "photo_limit": 3, "photo_left": 0}
    done = AiRenderLog.objects.filter(status=RenderLogStatus.DONE)
    assert done.count() == 3 and done.first().cost_usd == Decimal("0.0750")


@pytest.mark.django_db
def test_ai_video_is_premium_only_with_a_monthly_quota_and_failed_jobs_refund(fal, monkeypatch, plain_user, client_for):
    garment = make_garment()
    client = client_for(plain_user)
    clip = lambda: SimpleUploadedFile("c.webm", b"0" * 2048, content_type="video/webm")  # noqa: E731
    post = lambda: client.post(  # noqa: E731
        f"{BASE}/ai/render-video/", {"garment": str(garment.pk), "video": clip()}, format="multipart"
    )

    free = post()
    assert free.status_code == 403 and free.data["error"]["code"] == "ai_premium_required"

    counter = iter(range(100))

    def start(*, user, video_upload, garment):
        n = next(counter)
        return VideoTryOnJob.objects.create(
            user=user, garment=garment, model="fal-ai/kling", request_id=f"req_{n}",
            status_url=f"https://queue.fal.run/s/{n}", response_url=f"https://queue.fal.run/r/{n}",
        )

    monkeypatch.setattr(video_jobs, "start", start)
    subscribe(plain_user, "M1")  # 2 videos a month
    assert post().status_code == 202 and post().status_code == 202
    assert post().data["error"]["code"] == "ai_quota_exhausted"

    # fal failed the first job: the user gets that video back
    video_jobs._fail(VideoTryOnJob.objects.get(request_id="req_0"), "provider_rejected_request")
    assert AiRenderLog.objects.get(ref="req_0").status == RenderLogStatus.REFUNDED
    assert client.get(f"{BASE}/ai/status/").data["quota"]["video_left"] == 1


# ------------------------------------------------------------- business fee
@pytest.mark.django_db
def test_unpaid_studio_leaves_the_catalog_after_grace_and_returns_when_paid(settings, make_user, client_for, anon):
    settings.BUSINESS_BILLING = {**settings.BUSINESS_BILLING, "START": "2020-01-01", "ENFORCE": True}
    owner = make_user(Role.STUDIO)
    studio = Studio.objects.create(name="Nur", address="Toshkent", responsible_user=owner)
    def ids():
        data = anon.get("/api/v1/public/studios/").data
        return {row["id"] for row in (data["results"] if isinstance(data, dict) else data)}


    billing_of = lambda: client_for(owner).get("/api/v1/me/subscriptions/billing/").data[0]  # noqa: E731

    assert str(studio.pk) in ids() and billing_of()["state"] == "GRACE"  # new business: 7 days grace

    Studio.objects.filter(pk=studio.pk).update(created_at=timezone.now() - timedelta(days=30))
    assert str(studio.pk) not in ids()
    row = billing_of()
    assert row["state"] == "OVERDUE" and row["visible"] is False and row["monthly_fee"] == 150_000

    plan = SubscriptionPlan.objects.get(code="STUDIO_M1")
    now = timezone.now()
    Subscription.objects.create(
        user=owner, studio=studio, plan=plan, status=SubscriptionStatus.ACTIVE, price=plan.price,
        duration_months=1, max_viewers=1, starts_at=now, ends_at=add_months(now, 1), paid_amount=plan.price,
        paid_at=now,
    )
    assert str(studio.pk) in ids() and billing_of()["state"] == "OK"


@pytest.mark.django_db
def test_business_fees_are_the_agreed_monthly_prices():
    prices = dict(SubscriptionPlan.objects.filter(code__in=["VENUE_M1", "STUDIO_M1"]).values_list("code", "price"))
    assert prices == {"VENUE_M1": Decimal("300000.00"), "STUDIO_M1": Decimal("150000.00")}


@pytest.mark.django_db
def test_user_plans_keep_a_healthy_margin_at_full_ai_use():
    from apps.subscriptions import pricing

    for e in pricing.all_plan_economics():
        assert e.healthy, (e.plan.code, e.margin)


# ---------------------------------------------------------------- finance
@pytest.mark.django_db
def test_finance_report_counts_income_ai_costs_and_manual_expenses(make_user, client_for, plain_user):
    viewer = client_for(make_user(Role.ADMIN, admin_permissions=["finance.view"]))
    manager = client_for(make_user(Role.ADMIN, admin_permissions=["finance.view", "finance.manage"]))
    assert client_for(make_user(Role.ADMIN, admin_permissions=["dashboard.view"])).get(f"{FINANCE}report/").status_code == 403

    sub = subscribe(plain_user, "M1")
    Subscription.objects.filter(pk=sub.pk).update(paid_at=timezone.now())
    AiRenderLog.objects.create(user=plain_user, kind=RenderKind.VIDEO, status=RenderLogStatus.DONE, cost_usd=Decimal("0.63"))
    AiRenderLog.objects.create(user=plain_user, kind=RenderKind.PHOTO, status=RenderLogStatus.REFUNDED)

    expense = {"category": "SERVER", "title": "Hosting", "amount": "200000", "spent_on": timezone.localdate().isoformat()}
    assert viewer.post(FINANCE, expense, format="json").status_code == 403
    created = manager.post(FINANCE, expense, format="json")
    assert created.status_code == 201
    assert manager.patch(f"{FINANCE}rate/", {"usd_rate": "12000"}, format="json").status_code == 200

    report = viewer.get(f"{FINANCE}report/").data
    assert Decimal(str(report["income"]["total"])) == Decimal("59000")
    ai_video = next(r for r in report["expenses"]["ai"] if r["key"] == "ai_video")
    assert ai_video["count"] == 1 and Decimal(str(ai_video["amount"])) == Decimal("7560")  # 0.63 × 12 000
    assert Decimal(str(report["expenses"]["manual_total"])) == Decimal("200000")
    assert Decimal(str(report["profit"])) == Decimal("59000") - Decimal("7560") - Decimal("200000")
    assert len(report["trend"]) == 6 and report["plans"]

    assert manager.delete(f"{FINANCE}{created.data['id']}/").status_code == 204
