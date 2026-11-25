"""AI virtual try-on (Decart lucy-vton): sessions, client tokens, cost limits, references, saved looks.

Decart's HTTP layer is replaced by ``FakeDecart`` using the response shapes verified against the live
API (200 {"apiKey","expiresAt"}, 401 {"error": ...}). No test talks to Decart; the live check is
``tools/smoke-ai-tryon.mjs`` / docs (needs a real DECART_API_KEY).
"""

import io
import logging
from datetime import timedelta
from pathlib import Path

import pytest
import requests
from django.conf import settings as dj_settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image, ImageDraw

from apps.accounts.models import Role
from apps.virtual_tryon import decart
from apps.virtual_tryon.models import AiTryOnSession, ApprovalStatus, Garment, GarmentCategory, SavedLook

BASE = "/api/v1/virtual-tryon"
PERMANENT_KEY = "dk_permanent_secret_never_leaves_server_123"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code, self._payload = status_code, payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeDecart:
    def __init__(self):
        self.calls = []
        self.response = FakeResponse(200, {"apiKey": "ek_short_lived_token", "expiresAt": "2026-11-25T10:00:00Z"})
        self.raise_exc = None

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.raise_exc:
            raise self.raise_exc
        return self.response


@pytest.fixture
def fake_decart(monkeypatch):
    fake = FakeDecart()
    monkeypatch.setattr(decart.requests, "post", fake.post)
    return fake


@pytest.fixture
def ai_on(settings):
    settings.AI_TRYON = {**settings.AI_TRYON, "API_KEY": PERMANENT_KEY}
    return settings


@pytest.fixture
def user(make_user):
    return make_user(Role.USER)


def start(client):
    return client.post(f"{BASE}/ai-sessions/", {"consent": True}, format="json")


# ------------------------------------------------------------------ status / sessions
def test_status_reports_not_configured_honestly(user, client_for):
    res = client_for(user).get(f"{BASE}/ai/status/")
    assert res.status_code == 200 and res.data["enabled"] is False
    assert res.data["model"] == "lucy-vton-latest"
    res = start(client_for(user))
    assert res.status_code == 503 and res.data["error"]["code"] == "ai_tryon_not_configured"


def test_session_requires_explicit_consent(ai_on, user, client_for):
    res = client_for(user).post(f"{BASE}/ai-sessions/", {"consent": False}, format="json")
    assert res.status_code == 400 and "consent" in res.data["error"]["details"]
    assert client_for(user).post(f"{BASE}/ai-sessions/", {}, format="json").status_code == 400


@pytest.mark.parametrize("role", [Role.STUDIO, Role.VENUE_OWNER, Role.ADMIN, Role.SUPER_ADMIN])
def test_only_client_users_use_ai_tryon(ai_on, role, make_user, client_for, anon):
    assert start(client_for(make_user(role))).status_code == 403
    assert start(anon).status_code == 401


def test_one_active_session_per_user(ai_on, user, client_for):
    client = client_for(user)
    first = start(client)
    assert first.status_code == 201 and first.data["status"] == "ACTIVE"
    assert first.data["seconds_left"] <= dj_settings.AI_TRYON["MAX_SESSION_SECONDS"]
    second = start(client)
    assert second.status_code == 409 and second.data["error"]["code"] == "ai_session_already_active"
    assert str(client.get(f"{BASE}/ai/status/").data["active_session"]) == first.data["id"]
    client.post(f"{BASE}/ai-sessions/{first.data['id']}/finish/", {"reason": "USER"}, format="json")
    assert start(client).status_code == 201


def test_daily_session_and_time_budgets(ai_on, user, client_for):
    ai_on.AI_TRYON = {**ai_on.AI_TRYON, "DAILY_SESSIONS_PER_USER": 2, "DAILY_SECONDS_PER_USER": 100}
    client = client_for(user)
    s1 = start(client).data
    assert (
        timezone.datetime.fromisoformat(s1["expires_at"]) - timezone.datetime.fromisoformat(s1["started_at"])
    ).total_seconds() <= 100  # cut to the daily budget
    AiTryOnSession.objects.filter(pk=s1["id"]).update(
        started_at=timezone.now() - timedelta(seconds=95), expires_at=timezone.now() - timedelta(seconds=1)
    )
    res = start(client)
    assert res.status_code == 429 and res.data["error"]["code"] == "ai_daily_time_limit"
    ai_on.AI_TRYON = {**ai_on.AI_TRYON, "DAILY_SECONDS_PER_USER": 10_000}
    assert start(client).status_code == 201
    active = client.get(f"{BASE}/ai/status/").data["active_session"]
    client.post(f"{BASE}/ai-sessions/{active}/finish/", {}, format="json")
    res = start(client)
    assert res.status_code == 429 and res.data["error"]["code"] == "ai_daily_session_limit"


def test_global_daily_budget(ai_on, make_user, client_for):
    ai_on.AI_TRYON = {**ai_on.AI_TRYON, "GLOBAL_DAILY_SECONDS": 5}
    res = start(client_for(make_user(Role.USER)))
    assert res.status_code == 429 and res.data["error"]["code"] == "ai_daily_time_limit"


# ------------------------------------------------------------------ client tokens
def test_token_is_short_lived_and_scoped(ai_on, user, client_for, fake_decart):
    ai_on.AI_TRYON = {**ai_on.AI_TRYON, "ALLOWED_ORIGINS": ["https://userlogin.marosimgo.uz"]}
    client = client_for(user)
    session = start(client).data
    res = client.post(f"{BASE}/ai-sessions/{session['id']}/token/")
    assert res.status_code == 200
    assert res.data["api_key"] == "ek_short_lived_token" and res.data["model"] == "lucy-vton-latest"
    assert PERMANENT_KEY not in res.content.decode()

    (call,) = fake_decart.calls
    assert call["url"] == "https://api.decart.ai/v1/client/tokens"
    assert call["headers"] == {"x-api-key": PERMANENT_KEY}
    body = call["json"]
    assert body["allowedModels"] == ["lucy-vton-latest"]
    assert body["allowedOrigins"] == ["https://userlogin.marosimgo.uz"]
    assert 1 <= body["expiresIn"] <= 3600
    assert 10 <= body["constraints"]["realtime"]["maxSessionDuration"] <= session["seconds_left"] + 1
    assert AiTryOnSession.objects.get(pk=session["id"]).token_count == 1


def test_token_only_for_own_active_unexpired_session(ai_on, user, make_user, client_for, fake_decart):
    session = start(client_for(user)).data
    assert client_for(make_user(Role.USER)).post(f"{BASE}/ai-sessions/{session['id']}/token/").status_code == 404

    AiTryOnSession.objects.filter(pk=session["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    res = client_for(user).post(f"{BASE}/ai-sessions/{session['id']}/token/")
    assert res.status_code == 410 and res.data["error"]["code"] == "ai_session_ended"
    assert AiTryOnSession.objects.get(pk=session["id"]).status == "EXPIRED"
    assert fake_decart.calls == []


def test_reconnect_token_limit(ai_on, user, client_for, fake_decart):
    ai_on.AI_TRYON = {**ai_on.AI_TRYON, "MAX_TOKENS_PER_SESSION": 2}
    client = client_for(user)
    sid = start(client).data["id"]
    assert [client.post(f"{BASE}/ai-sessions/{sid}/token/").status_code for _ in range(3)] == [200, 200, 429]


@pytest.mark.parametrize(
    "response,exc,code,http",
    [
        (FakeResponse(401, {"error": "Invalid or expired API key"}), None, "provider_auth_failed", 503),
        (FakeResponse(429, {"error": "slow down"}), None, "provider_rate_limited", 503),
        (FakeResponse(500, {"error": "boom"}), None, "provider_unavailable", 503),
        (FakeResponse(200, ValueError("not json")), None, "provider_bad_response", 502),
        (None, requests.Timeout(), "provider_timeout", 504),
        (None, requests.ConnectionError(), "provider_unavailable", 503),
    ],
)
def test_provider_errors_are_mapped_and_never_leak_the_key(
    ai_on, user, client_for, fake_decart, caplog, response, exc, code, http
):
    fake_decart.response, fake_decart.raise_exc = response, exc
    client = client_for(user)
    sid = start(client).data["id"]
    with caplog.at_level(logging.DEBUG):
        res = client.post(f"{BASE}/ai-sessions/{sid}/token/")
    assert res.status_code == http and res.data["error"]["code"] == code
    assert PERMANENT_KEY not in res.content.decode() and PERMANENT_KEY not in caplog.text
    assert AiTryOnSession.objects.get(pk=sid).token_count == 0


def test_client_token_repr_hides_the_token():
    assert "ek_" not in repr(decart.ClientToken(api_key="ek_secret", expires_at="x"))


# ------------------------------------------------------------------ finish / metrics
def test_finish_stores_reason_and_bounded_metrics(ai_on, user, client_for):
    client = client_for(user)
    sid = start(client).data["id"]
    bad = client.post(f"{BASE}/ai-sessions/{sid}/finish/", {"metrics": {"fps": 1000}}, format="json")
    assert bad.status_code == 400
    metrics = {"connect_ms": 1800, "glass_to_glass_ms": 240, "fps": 22.5, "interruptions": 1, "garments_tried": 3}
    res = client.post(f"{BASE}/ai-sessions/{sid}/finish/", {"reason": "PAGE_HIDDEN", "metrics": metrics}, format="json")
    assert res.status_code == 200 and res.data["status"] == "FINISHED" and res.data["end_reason"] == "PAGE_HIDDEN"
    assert AiTryOnSession.objects.get(pk=sid).metrics == metrics
    assert client.post(f"{BASE}/ai-sessions/{sid}/token/").status_code == 410


def test_finish_after_expiry_is_recorded_as_expired(ai_on, user, client_for):
    client = client_for(user)
    sid = start(client).data["id"]
    AiTryOnSession.objects.filter(pk=sid).update(expires_at=timezone.now() - timedelta(seconds=5))
    res = client.post(f"{BASE}/ai-sessions/{sid}/finish/", {"reason": "USER"}, format="json")
    assert res.data["status"] == "EXPIRED" and res.data["end_reason"] == "EXPIRED"


# ------------------------------------------------------------------ catalogue
def reference_png(size=(800, 1000), background=(255, 255, 255), noisy=False) -> bytes:
    img = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.rectangle([w * 0.25, h * 0.15, w * 0.75, h * 0.9], fill=(180, 20, 40))
    if noisy:
        import random

        rnd = random.Random(1)
        px = img.load()
        for y in range(h):
            for x in range(w):
                if x < w * 0.2 or x > w * 0.8 or y < h * 0.1 or y > h * 0.95:
                    px[x, y] = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_garment(category_slug="kelinlik-liboslari", ai=True, **extra):
    garment = Garment.objects.create(
        category=GarmentCategory.objects.get(slug=category_slug),
        name=extra.pop("name", "Atlas ko'ylak"),
        approval_status=extra.pop("approval_status", ApprovalStatus.APPROVED),
        is_tryon_enabled=False,
        **extra,
    )
    if ai:
        garment.ai_reference_image.save("ref.jpg", ContentFile(reference_png()), save=True)
    return garment


def test_catalogue_has_men_women_unisex_sections(user, client_for):
    rows = client_for(user).get(f"{BASE}/categories/").data
    audiences = {r["slug"]: r["audience"] for r in rows}
    assert audiences["kelinlik-liboslari"] == "WOMEN" and audiences["kuyovlik-kostyumlari"] == "MEN"
    for slug in ("smokinglar", "chopon", "kechki-liboslar", "atlas-va-adras", "hijob-va-aksessuarlar"):
        assert slug in audiences


def test_garment_list_ai_filter_and_fields(user, client_for):
    ai_garment = make_garment(name="AI")
    make_garment(name="AR only", ai=False)
    make_garment("smokinglar", name="Smoking")
    client = client_for(user)
    rows = client.get(f"{BASE}/garments/?ai=1").data["results"]
    assert {r["name"] for r in rows} == {"AI", "Smoking"}
    row = next(r for r in rows if r["id"] == str(ai_garment.pk))
    assert row["ai_ready"] is True and row["ai_reference_image"].endswith(".jpg")
    assert row["category"]["audience"] == "WOMEN"
    men = client.get(f"{BASE}/garments/?ai=1&audience=MEN").data["results"]
    assert [r["name"] for r in men] == ["Smoking"]


# ------------------------------------------------------------------ admin: reference images
def upload_ref(client, garment, content, name="ref.png", prompt=None):
    data = {"image": SimpleUploadedFile(name, content, "image/png")}
    if prompt is not None:
        data["prompt"] = prompt
    return client.post(f"/api/v1/admin/virtual-tryon/garments/{garment.pk}/ai-reference/", data, format="multipart")


def test_admin_uploads_valid_reference_and_prompt(super_admin, client_for):
    garment = make_garment(ai=False)
    res = upload_ref(
        client_for(super_admin),
        garment,
        reference_png(),
        prompt="  Substitute the current outfit  with a red atlas dress ",
    )
    assert res.status_code == 200, res.data
    assert (
        res.data["ai_ready"] is True and res.data["ai_prompt"] == "Substitute the current outfit with a red atlas dress"
    )
    garment.refresh_from_db()
    assert garment.approval_status == ApprovalStatus.PENDING  # an approved garment goes back to review
    with Image.open(garment.ai_reference_image) as stored:
        assert stored.format == "JPEG" and max(stored.size) <= 2048


@pytest.mark.parametrize(
    "content,needle",
    [
        (reference_png(size=(400, 400)), "512"),
        (reference_png(size=(600, 2000)), "nisbat"),
        (reference_png(noisy=True), "Fon"),
        (b"not an image at all", None),
    ],
)
def test_admin_reference_validation(super_admin, client_for, content, needle):
    res = upload_ref(client_for(super_admin), make_garment(ai=False), content)
    assert res.status_code == 400
    if needle:
        assert needle in str(res.data["error"]["details"])


def test_large_reference_is_downscaled(super_admin, client_for):
    garment = make_garment(ai=False)
    assert upload_ref(client_for(super_admin), garment, reference_png(size=(3000, 3000))).status_code == 200
    garment.refresh_from_db()
    with Image.open(garment.ai_reference_image) as stored:
        assert stored.size == (2048, 2048)


def test_reference_upload_permissions(make_user, client_for):
    garment = make_garment(ai=False)
    admin_without = make_user(Role.ADMIN, admin_permissions=["tryon.view"])
    assert upload_ref(client_for(admin_without), garment, reference_png()).status_code == 403
    assert upload_ref(client_for(make_user(Role.USER)), garment, reference_png()).status_code == 403
    admin_with = make_user(Role.ADMIN, admin_permissions=["tryon.view", "tryon.update"])
    assert upload_ref(client_for(admin_with), garment, reference_png()).status_code == 200


def test_ai_only_garment_can_be_approved_and_reference_deleted(super_admin, client_for):
    garment = make_garment(ai=False, approval_status=ApprovalStatus.DRAFT)
    Garment.objects.filter(pk=garment.pk).update(is_tryon_enabled=True)
    client = client_for(super_admin)
    upload_ref(client, garment, reference_png())
    garment.cover_image.save("c.jpg", ContentFile(reference_png()), save=True)
    assert client.post(f"/api/v1/admin/virtual-tryon/garments/{garment.pk}/approve/").status_code == 200
    res = client.delete(f"/api/v1/admin/virtual-tryon/garments/{garment.pk}/ai-reference/")
    assert res.status_code == 200 and res.data["ai_ready"] is False


# ------------------------------------------------------------------ saved looks
def look_upload(client, **extra):
    data = {"image": SimpleUploadedFile("frame.png", reference_png(size=(640, 960)), "image/png"), **extra}
    return client.post(f"{BASE}/looks/", data, format="multipart")


def test_saved_looks_are_private_files(ai_on, user, make_user, client_for):
    client = client_for(user)
    garment = make_garment()
    sid = start(client).data["id"]
    res = look_upload(client, garment=str(garment.pk), session=sid)
    assert res.status_code == 201 and res.data["garment"]["name"] == garment.name
    look = SavedLook.objects.get(pk=res.data["id"])
    stored = Path(look.image.path)
    assert stored.is_relative_to(Path(dj_settings.PRIVATE_MEDIA_ROOT))
    assert not stored.is_relative_to(Path(dj_settings.MEDIA_ROOT)) or Path(
        dj_settings.PRIVATE_MEDIA_ROOT
    ).is_relative_to(Path(dj_settings.MEDIA_ROOT))
    assert "/media/" not in res.data["image"]

    image = client.get(res.data["image"])
    assert image.status_code == 200 and "no-store" in image["Cache-Control"]
    assert b"".join(image.streaming_content)[:4] == b"RIFF"  # re-encoded WEBP, EXIF stripped

    stranger = client_for(make_user(Role.USER))
    assert stranger.get(res.data["image"]).status_code == 404
    assert stranger.get(f"{BASE}/looks/").data["results"] == []
    assert stranger.delete(f"{BASE}/looks/{look.pk}/").status_code == 404

    assert [r["id"] for r in client.get(f"{BASE}/looks/").data["results"]] == [str(look.pk)]
    assert client.delete(f"{BASE}/looks/{look.pk}/").status_code == 204
    assert not stored.exists()


def test_saved_look_limit_and_validation(ai_on, user, client_for):
    ai_on.AI_TRYON = {**ai_on.AI_TRYON, "MAX_SAVED_LOOKS_PER_USER": 1}
    client = client_for(user)
    assert look_upload(client).status_code == 201
    assert look_upload(client).status_code == 400
    bad = client.post(
        f"{BASE}/looks/", {"image": SimpleUploadedFile("x.png", b"nope", "image/png")}, format="multipart"
    )
    assert bad.status_code == 400


# ------------------------------------------------------------------ admin usage dashboard
def test_admin_usage_dashboard(ai_on, user, super_admin, make_user, client_for):
    client = client_for(user)
    sid = start(client).data["id"]
    client.post(f"{BASE}/ai-sessions/{sid}/finish/", {"metrics": {"fps": 20, "connect_ms": 1500}}, format="json")
    res = client_for(super_admin).get("/api/v1/admin/virtual-tryon/ai-usage/?days=1")
    assert res.status_code == 200
    assert res.data["sessions"] == 1 and res.data["users"] == 1 and res.data["end_reasons"] == {"USER": 1}
    assert res.data["measured"]["fps_avg"] == 20 and res.data["estimated_cost_usd"] >= 0
    assert client_for(make_user(Role.USER)).get("/api/v1/admin/virtual-tryon/ai-usage/").status_code == 403
    assert (
        client_for(make_user(Role.ADMIN, admin_permissions=[])).get("/api/v1/admin/virtual-tryon/ai-usage/").status_code
        == 403
    )
