"""Virtual try-on catalogue: user API (visibility, favourites, sessions) and staff management."""

import io
import json
import struct

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.accounts.models import PlatformPolicy, Role
from apps.virtual_tryon.models import (
    ApprovalStatus,
    AssetKind,
    FavoriteGarment,
    Garment,
    GarmentAsset,
    GarmentCategory,
    TryOnSession,
)

from .conftest import bearer_client

API = "/api/v1/virtual-tryon"
ADMIN_API = "/api/v1/admin/virtual-tryon/garments"
BODY_ANCHORS = {
    "right_shoulder": [0.3, 0.1],
    "left_shoulder": [0.7, 0.1],
    "right_hip": [0.35, 0.4],
    "left_hip": [0.65, 0.4],
}


def layer_png(transparent=True, size=(120, 240), name="layer.png") -> SimpleUploadedFile:
    image = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    image.paste((200, 30, 60, 255), (30, 20, 90, 220))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def glb(valid=True) -> SimpleUploadedFile:
    body = b'{"asset":{"version":"2.0"}}  '
    chunk = struct.pack("<I4s", len(body), b"JSON") + body
    header = struct.pack("<4sII", b"glTF" if valid else b"nope", 2, 12 + len(chunk))
    return SimpleUploadedFile("model.glb", header + chunk, content_type="model/gltf-binary")


def category(slug="kelinlik-liboslari") -> GarmentCategory:
    return GarmentCategory.objects.get(slug=slug)


def make_garment(name="Oq libos", status=ApprovalStatus.APPROVED, front=True, slug="kelinlik-liboslari", **extra):
    garment = Garment.objects.create(category=category(slug), name=name, approval_status=status, price=1500000, **extra)
    if front:
        GarmentAsset.objects.create(
            garment=garment,
            kind=AssetKind.BODY_FRONT,
            file=SimpleUploadedFile("f.webp", b"x"),
            width=100,
            height=200,
            anchors=BODY_ANCHORS,
        )
    return garment


@pytest.fixture
def user_client(plain_user):
    return bearer_client(plain_user)


# ------------------------------------------------------------------ catalogue
ORIGINAL_SECTIONS = [
    "Kelinlik liboslari",
    "Kuyovlik kostyumlari",
    "Milliy to'y liboslari",
    "Erkaklar kiyimlari",
    "Ayollar kiyimlari",
]


@pytest.mark.django_db
def test_categories_are_seeded_in_order(user_client):
    make_garment()
    make_garment("Qoralama", status=ApprovalStatus.DRAFT)
    res = user_client.get(f"{API}/categories/")
    assert res.status_code == 200
    # the five original sections first, then the AI Fashion Studio sections (migration 0005)
    assert [c["name"] for c in res.data] == [
        *ORIGINAL_SECTIONS,
        "Smokinglar",
        "Erkaklar ko'ylaklari",
        "Chopon",
        "Erkaklar milliy liboslari",
        "Kechki liboslar",
        "Ayollar milliy liboslari",
        "Atlas va adras liboslar",
        "Hijob va aksessuarlar",
        "Boshqa kiyimlar",
    ]
    assert res.data[0]["garment_count"] == 1  # the draft is not counted


@pytest.mark.django_db
def test_users_see_only_active_approved_garments(user_client):
    visible = make_garment("Ko'rinadi")
    hidden = [
        make_garment("Qoralama", status=ApprovalStatus.DRAFT),
        make_garment("Kutilmoqda", status=ApprovalStatus.PENDING),
        make_garment("Rad etilgan", status=ApprovalStatus.REJECTED),
        make_garment("Nofaol", is_active=False),
    ]
    deleted = make_garment("O'chirilgan")
    deleted.soft_delete()
    hidden.append(deleted)

    res = user_client.get(f"{API}/garments/")
    assert res.status_code == 200
    assert [g["id"] for g in res.data["results"]] == [str(visible.pk)]
    assert res.data["results"][0]["tryon_ready"] is True
    for garment in hidden:
        assert user_client.get(f"{API}/garments/{garment.pk}/").status_code == 404
        assert user_client.get(f"{API}/garments/{garment.pk}/assets/").status_code == 404


@pytest.mark.django_db
def test_category_search_and_tryon_filters(user_client):
    dress = make_garment("Oq libos")
    suit = make_garment("Qora smoking", slug="kuyovlik-kostyumlari")
    no_ar = make_garment("Atlas", slug="milliy-toy-liboslari", front=False)

    ids = lambda res: {g["id"] for g in res.data["results"]}  # noqa: E731
    assert ids(user_client.get(f"{API}/garments/", {"category": "kuyovlik-kostyumlari"})) == {str(suit.pk)}
    assert ids(user_client.get(f"{API}/garments/", {"q": "libos"})) == {str(dress.pk)}
    assert str(no_ar.pk) not in ids(user_client.get(f"{API}/garments/", {"tryon": "true"}))
    row = user_client.get(f"{API}/garments/{no_ar.pk}/").data
    assert row["tryon_ready"] is False


@pytest.mark.django_db
def test_assets_carry_layers_and_anchors(user_client):
    garment = make_garment()
    res = user_client.get(f"{API}/garments/{garment.pk}/assets/")
    assert res.status_code == 200
    assert [a["kind"] for a in res.data] == ["BODY_FRONT"]
    assert res.data[0]["anchors"] == BODY_ANCHORS
    assert res.data[0]["url"].startswith("http")

    garment.is_tryon_enabled = False
    garment.save()
    assert user_client.get(f"{API}/garments/{garment.pk}/assets/").data == []


@pytest.mark.django_db
def test_only_user_accounts_use_the_catalogue(make_user):
    for role in (Role.STUDIO, Role.VENUE_OWNER):
        assert bearer_client(make_user(role)).get(f"{API}/garments/").status_code == 403
    from rest_framework.test import APIClient

    assert APIClient().get(f"{API}/categories/").status_code == 401


@pytest.mark.django_db
def test_platform_can_switch_the_feature_off(user_client):
    policy = PlatformPolicy.load()
    policy.disabled_features = ["USER.tryon"]
    policy.save()
    assert user_client.get(f"{API}/garments/").status_code == 403


# ------------------------------------------------------------------ sessions
@pytest.mark.django_db
def test_sessions_are_own_and_only_for_wearable_garments(user_client, make_user):
    garment = make_garment()
    no_ar = make_garment("AR yo'q", front=False)

    assert user_client.post(f"{API}/sessions/", {"garment": str(no_ar.pk)}).status_code == 404
    res = user_client.post(f"{API}/sessions/", {"garment": str(garment.pk)})
    assert res.status_code == 201 and res.data["ended_at"] is None
    session_id = res.data["id"]

    other = bearer_client(make_user(Role.USER))
    assert other.post(f"{API}/sessions/{session_id}/finish/").status_code == 404

    done = user_client.post(f"{API}/sessions/{session_id}/finish/")
    assert done.status_code == 200 and done.data["ended_at"] is not None
    again = user_client.post(f"{API}/sessions/{session_id}/finish/")
    assert again.data["ended_at"] == done.data["ended_at"]  # idempotent
    assert TryOnSession.objects.get(pk=session_id).duration_seconds >= 0


@pytest.mark.django_db
def test_long_forgotten_session_is_capped(user_client):
    from datetime import timedelta

    from django.utils import timezone

    garment = make_garment()
    session_id = user_client.post(f"{API}/sessions/", {"garment": str(garment.pk)}).data["id"]
    TryOnSession.objects.filter(pk=session_id).update(started_at=timezone.now() - timedelta(days=1))
    res = user_client.post(f"{API}/sessions/{session_id}/finish/")
    assert res.data["duration_seconds"] == 2 * 3600


# ----------------------------------------------------------------- favourites
@pytest.mark.django_db
def test_favorites_are_personal(user_client, make_user):
    garment = make_garment()
    draft = make_garment("Qoralama", status=ApprovalStatus.DRAFT)

    first = user_client.post(f"{API}/favorites/", {"garment": str(garment.pk)})
    assert first.status_code == 201
    assert user_client.post(f"{API}/favorites/", {"garment": str(garment.pk)}).status_code == 200  # idempotent
    assert user_client.post(f"{API}/favorites/", {"garment": str(draft.pk)}).status_code == 404

    listed = user_client.get(f"{API}/favorites/").data["results"]
    assert [f["garment"]["id"] for f in listed] == [str(garment.pk)]
    assert listed[0]["garment"]["is_favorite"] is True
    assert user_client.get(f"{API}/garments/{garment.pk}/").data["is_favorite"] is True

    other = bearer_client(make_user(Role.USER))
    assert other.get(f"{API}/favorites/").data["results"] == []
    assert other.delete(f"{API}/favorites/{first.data['id']}/").status_code == 404
    assert other.get(f"{API}/garments/{garment.pk}/").data["is_favorite"] is False

    # by the favourite's id, or by the garment's id
    assert user_client.delete(f"{API}/favorites/{first.data['id']}/").status_code == 204
    user_client.post(f"{API}/favorites/", {"garment": str(garment.pk)})
    assert user_client.delete(f"{API}/favorites/{garment.pk}/").status_code == 204
    assert not FavoriteGarment.objects.exists()


# ---------------------------------------------------------------------- staff
@pytest.mark.django_db
def test_staff_creates_uploads_and_approves(super_admin, user_client):
    staff = bearer_client(super_admin)
    created = staff.post(
        ADMIN_API + "/",
        {
            "category_id": str(category("kuyovlik-kostyumlari").pk),
            "name": "Qora smoking",
            "price": "2500000",
            "sizes": ["48", "50"],
            "colors": [{"name": "Qora", "hex": "#111111"}],
        },
    )
    assert created.status_code == 201, created.data
    gid = created.data["id"]
    assert created.data["approval_status"] == "DRAFT"
    assert user_client.get(f"{API}/garments/{gid}/").status_code == 404

    # Approval needs the front layer.
    assert staff.post(f"{ADMIN_API}/{gid}/approve/").status_code == 400

    up = staff.post(
        f"{ADMIN_API}/{gid}/assets/",
        {"kind": "BODY_FRONT", "file": layer_png(), "anchors": json.dumps({**BODY_ANCHORS, "legs": "split"})},
        format="multipart",
    )
    assert up.status_code == 200, up.data
    asset = up.data["assets"][0]
    assert asset["kind"] == "BODY_FRONT" and asset["anchors"]["legs"] == "split"
    assert asset["url"].endswith(".webp") and asset["width"] == 120

    sleeve = staff.post(
        f"{ADMIN_API}/{gid}/assets/",
        {
            "kind": "RIGHT_UPPER_ARM",
            "file": layer_png(),
            "anchors": json.dumps({"start": [0.5, 0.05], "end": [0.5, 0.95]}),
        },
        format="multipart",
    )
    assert sleeve.status_code == 200
    model = staff.post(f"{ADMIN_API}/{gid}/assets/", {"kind": "MODEL_GLB", "file": glb()}, format="multipart")
    assert model.status_code == 200

    approved = staff.post(f"{ADMIN_API}/{gid}/approve/")
    assert approved.status_code == 200 and approved.data["approval_status"] == "APPROVED"
    kinds = {a["kind"] for a in user_client.get(f"{API}/garments/{gid}/assets/").data}
    assert kinds == {"BODY_FRONT", "RIGHT_UPPER_ARM", "MODEL_GLB"}

    # A new layer sends the garment back to review; replacing keeps one per kind.
    staff.post(
        f"{ADMIN_API}/{gid}/assets/",
        {"kind": "BODY_FRONT", "file": layer_png(), "anchors": json.dumps(BODY_ANCHORS)},
        format="multipart",
    )
    assert Garment.objects.get(pk=gid).approval_status == ApprovalStatus.PENDING
    assert GarmentAsset.objects.filter(garment_id=gid, kind=AssetKind.BODY_FRONT).count() == 1

    rejected = staff.post(f"{ADMIN_API}/{gid}/reject/", {"reason": "Rasm sifati past"})
    assert rejected.data["approval_status"] == "REJECTED" and rejected.data["rejection_reason"] == "Rasm sifati past"

    assert staff.delete(f"{ADMIN_API}/{gid}/assets/RIGHT_UPPER_ARM/").status_code == 200
    assert staff.delete(f"{ADMIN_API}/{gid}/").status_code == 204
    assert Garment.objects.get(pk=gid).is_deleted


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind, file, anchors, field",
    [
        ("BODY_FRONT", lambda: layer_png(transparent=False), BODY_ANCHORS, "file"),  # opaque photo
        ("BODY_FRONT", layer_png, {"right_shoulder": [0.3, 0.1]}, "anchors"),  # missing points
        ("BODY_FRONT", layer_png, {**BODY_ANCHORS, "right_shoulder": [0.8, 0.1]}, "anchors"),  # sides swapped
        ("BODY_FRONT", layer_png, {**BODY_ANCHORS, "right_hip": [0.35, 0.05]}, "anchors"),  # hips above shoulders
        ("BODY_FRONT", layer_png, {**BODY_ANCHORS, "left_hip": [1.4, 0.4]}, "anchors"),  # outside the image
        ("RIGHT_FOREARM", layer_png, {"start": [0.5, 0.5], "end": [0.5, 0.51]}, "anchors"),
        (  # knees above the hips
            "LOWER_BODY",
            layer_png,
            {"right_hip": [0.4, 0.5], "left_hip": [0.6, 0.5], "right_knee": [0.4, 0.3], "left_knee": [0.6, 0.3]},
            "anchors",
        ),
        ("MODEL_GLB", lambda: glb(valid=False), {}, "file"),
        ("MODEL_GLB", lambda: SimpleUploadedFile("x.glb", b"<script>"), {}, "file"),
    ],
)
def test_bad_layers_are_refused(super_admin, kind, file, anchors, field):
    garment = make_garment(front=False, status=ApprovalStatus.DRAFT)
    res = bearer_client(super_admin).post(
        f"{ADMIN_API}/{garment.pk}/assets/",
        {"kind": kind, "file": file(), "anchors": json.dumps(anchors)},
        format="multipart",
    )
    assert res.status_code == 400
    assert field in res.data["error"]["details"]
    assert not garment.assets.exists()


@pytest.mark.django_db
def test_staff_rights_come_from_tryon_codes(make_user):
    garment = make_garment()
    viewer = bearer_client(make_user(Role.ADMIN, admin_permissions=["tryon.view"]))
    assert viewer.get(ADMIN_API + "/").status_code == 200
    assert viewer.post(f"{ADMIN_API}/{garment.pk}/approve/").status_code == 403
    assert viewer.patch(f"{ADMIN_API}/{garment.pk}/", {"name": "x"}).status_code == 403

    nobody = bearer_client(make_user(Role.ADMIN, admin_permissions=[]))
    assert nobody.get(ADMIN_API + "/").status_code == 403
    assert bearer_client(make_user(Role.STUDIO)).get(ADMIN_API + "/").status_code == 403

    approver = bearer_client(make_user(Role.ADMIN, admin_permissions=["tryon.approve"]))
    assert approver.post(f"{ADMIN_API}/{garment.pk}/reject/", {"reason": "x"}).status_code == 200

    editor = bearer_client(make_user(Role.ADMIN, admin_permissions=["tryon.update"]))
    res = editor.patch(f"{ADMIN_API}/{garment.pk}/", {"name": "Yangi nom"})
    assert res.status_code == 200 and res.data["approval_status"] == "PENDING"  # edits go back to review


# ------------------------------------------------------------------ demo data
@pytest.mark.django_db
def test_demo_seed_creates_wearable_garments_in_every_category(user_client):
    from django.core.management import call_command

    call_command("seed_tryon_demo", stdout=io.StringIO())
    call_command("seed_tryon_demo", stdout=io.StringIO())  # idempotent
    demo = Garment.objects.filter(description__startswith="Namuna (demo).")
    assert demo.count() == 10
    # the AR demo art exists for the five original sections (the AI sections need real garment photos)
    original = GarmentCategory.objects.filter(name__in=ORIGINAL_SECTIONS).values_list("slug", flat=True)
    assert {g.category.slug for g in demo} == set(original)

    listed = user_client.get(f"{API}/garments/", {"tryon": "true", "page_size": 100}).data["results"]
    assert len(listed) == 10 and all(g["tryon_ready"] and g["cover_image"] for g in listed)
    suit = demo.get(name="Klassik qora smoking")
    kinds = set(suit.assets.values_list("kind", flat=True))
    assert kinds == {"BODY_FRONT", "LOWER_BODY", "RIGHT_UPPER_ARM", "RIGHT_FOREARM", "LEFT_UPPER_ARM", "LEFT_FOREARM"}
    assert suit.assets.get(kind="LOWER_BODY").anchors["legs"] == "split"  # trousers: own layer, legs apart

    call_command("seed_tryon_demo", "--remove", stdout=io.StringIO())
    assert not Garment.objects.filter(description__startswith="Namuna (demo).").exists()
    assert not GarmentAsset.objects.exists()
