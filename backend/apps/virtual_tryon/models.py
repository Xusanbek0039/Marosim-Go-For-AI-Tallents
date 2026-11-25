"""Garment catalogue for the live virtual try-on (frontend-user, camera AR).

Camera frames never reach the server: the browser tracks the body and draws the garment layers
itself. The server only keeps the catalogue (garments + their transparent layers with anchor
points), the user's favourites and anonymous-to-the-frame session statistics (who tried what, how long).

A garment is drawn from one or more ``GarmentAsset`` layers:

* ``BODY_FRONT`` (required for try-on) — the torso/skirt part, warped onto shoulders + hips.
* ``BODY_BACK`` (optional) — shown when the user turns their back to the camera.
* ``LOWER_BODY`` (optional) — trousers / a separate skirt, drawn under the body layer. Each
  trouser leg follows its own hip → knee → ankle, so a jacket hem above it stays in one piece.
* ``*_UPPER_ARM`` / ``*_FOREARM`` (optional) — sleeve pieces, each following one arm bone.
* ``MODEL_GLB`` (optional) — a glTF 3D model kept for the future 3D renderer. Not rendered yet.

Anchor points are stored per layer in ``anchors`` (normalized 0..1 image coordinates, see
``assets.ANCHOR_KEYS``).
"""

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, SoftDeleteModel
from apps.venues.models import Currency


class Audience(models.TextChoices):
    MEN = "MEN", "Erkaklar"
    WOMEN = "WOMEN", "Ayollar"
    UNISEX = "UNISEX", "Hamma uchun"


class GarmentCategory(BaseModel):
    """Catalogue sections (seeded by migrations 0002 and 0005)."""

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=60, unique=True)
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.UNISEX)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "garment categories"

    def __str__(self) -> str:
        return self.name


class ApprovalStatus(models.TextChoices):
    DRAFT = "DRAFT", "Qoralama"
    PENDING = "PENDING", "Tasdiqlash kutilmoqda"
    APPROVED = "APPROVED", "Tasdiqlangan"
    REJECTED = "REJECTED", "Rad etilgan"


class GarmentAssetType(models.TextChoices):
    #: Body-aware 2D: transparent layers warped onto the tracked skeleton (implemented).
    LAYERED_2D = "LAYERED_2D", "2D qatlamlar"
    #: glTF/GLB model on a skinned skeleton — reserved, the renderer does not exist yet.
    MODEL_3D = "MODEL_3D", "3D model (tez orada)"


def garment_upload_to(instance, filename):
    return f"tryon/garments/{filename}"


def asset_upload_to(instance, filename):
    return f"tryon/assets/{filename}"


def ai_reference_upload_to(instance, filename):
    return f"tryon/ai-reference/{filename}"


def private_storage():
    """Saved looks are photos of users: never under the public /media/ tree."""
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def look_upload_to(instance, filename):
    return f"tryon-looks/{instance.user_id}/{filename}"


class Garment(BaseModel, SoftDeleteModel):
    """One product a user can try on. Users see only ``is_active`` + ``APPROVED`` garments."""

    #: Seller. Empty = the platform's own catalogue. Studios cannot manage garments yet
    #: (their role is photo/video); the column is here so the seller side can be added later.
    studio = models.ForeignKey(
        "studios.Studio", on_delete=models.PROTECT, null=True, blank=True, related_name="garments"
    )
    category = models.ForeignKey(GarmentCategory, on_delete=models.PROTECT, related_name="garments")
    name = models.CharField(max_length=150)
    description = models.TextField(max_length=2000, blank=True)
    price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    #: e.g. ["S", "M", "L"] / ["46", "48"]
    sizes = models.JSONField(default=list, blank=True)
    #: e.g. [{"name": "Oq", "hex": "#FFFFFF"}]
    colors = models.JSONField(default=list, blank=True)
    cover_image = models.ImageField(upload_to=garment_upload_to, blank=True)
    asset_type = models.CharField(max_length=12, choices=GarmentAssetType.choices, default=GarmentAssetType.LAYERED_2D)
    is_tryon_enabled = models.BooleanField(default=True)
    #: AI try-on (Decart lucy-vton): a clean garment photo (no person, plain light background, ≥512 px),
    #: validated and re-encoded by ``reference.process_reference``. Empty = not available for AI try-on.
    ai_reference_image = models.ImageField(upload_to=ai_reference_upload_to, blank=True)
    #: Garment description sent with the image, e.g. "Substitute the current outfit with a white
    #: satin wedding dress with long lace sleeves". Optional; the image alone also works.
    ai_prompt = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    approval_status = models.CharField(max_length=10, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT)
    rejection_reason = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["sort_order", "-created_at"]
        indexes = [models.Index(fields=["category", "approval_status", "is_active"])]

    def __str__(self) -> str:
        return self.name


class AssetKind(models.TextChoices):
    BODY_FRONT = "BODY_FRONT", "Old tomoni (asosiy qatlam)"
    BODY_BACK = "BODY_BACK", "Orqa tomoni"
    LOWER_BODY = "LOWER_BODY", "Pastki kiyim (shim / yubka)"
    RIGHT_UPPER_ARM = "RIGHT_UPPER_ARM", "O'ng yeng (yelka–tirsak)"
    RIGHT_FOREARM = "RIGHT_FOREARM", "O'ng yeng (tirsak–bilak)"
    LEFT_UPPER_ARM = "LEFT_UPPER_ARM", "Chap yeng (yelka–tirsak)"
    LEFT_FOREARM = "LEFT_FOREARM", "Chap yeng (tirsak–bilak)"
    MODEL_GLB = "MODEL_GLB", "3D model (GLB)"


class GarmentAsset(BaseModel):
    """One layer of a garment. Images are re-encoded as WEBP with alpha; GLB is stored as is."""

    garment = models.ForeignKey(Garment, on_delete=models.CASCADE, related_name="assets")
    kind = models.CharField(max_length=16, choices=AssetKind.choices)
    file = models.FileField(upload_to=asset_upload_to)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    size_bytes = models.PositiveIntegerField(default=0)
    #: Normalized anchor points, e.g. {"right_shoulder": [0.3, 0.12], ...} — see ``assets.ANCHOR_KEYS``.
    anchors = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["kind"]
        constraints = [models.UniqueConstraint(fields=["garment", "kind"], name="tryon_asset_one_per_kind")]

    def __str__(self) -> str:
        return f"{self.garment_id} {self.kind}"


class TryOnSession(BaseModel):
    """A user wore one garment on camera from ``started_at`` to ``ended_at``. No image data."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tryon_sessions")
    garment = models.ForeignKey(Garment, on_delete=models.CASCADE, related_name="sessions")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["user", "started_at"]), models.Index(fields=["garment", "started_at"])]


class FavoriteGarment(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_garments")
    garment = models.ForeignKey(Garment, on_delete=models.CASCADE, related_name="favorites")

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "garment"], name="tryon_favorite_once")]


class AiSessionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Faol"
    FINISHED = "FINISHED", "Yakunlangan"
    EXPIRED = "EXPIRED", "Muddati tugagan"


class AiEndReason(models.TextChoices):
    USER = "USER", "Foydalanuvchi yakunladi"
    EXPIRED = "EXPIRED", "Vaqt tugadi"
    PAGE_HIDDEN = "PAGE_HIDDEN", "Sahifa yopildi / fonga o'tdi"
    CAMERA_ERROR = "CAMERA_ERROR", "Kamera xatosi"
    NETWORK_ERROR = "NETWORK_ERROR", "Tarmoq xatosi"
    PROVIDER_ERROR = "PROVIDER_ERROR", "AI xizmati xatosi"
    SESSION_LIMIT = "SESSION_LIMIT", "AI xizmati limiti"
    MODERATION = "MODERATION", "AI xizmati moderatsiyasi"
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS", "AI xizmatida kredit tugagan"
    OTHER = "OTHER", "Boshqa"


class AiTryOnSession(BaseModel):
    """One live AI try-on (camera ↔ Decart over WebRTC). Video never reaches this server.

    The server caps cost: ``expires_at`` is fixed at creation (per-session and daily budget), every
    client token is limited to the remaining seconds, and a user has at most one ACTIVE session.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_tryon_sessions")
    status = models.CharField(max_length=8, choices=AiSessionStatus.choices, default=AiSessionStatus.ACTIVE)
    provider_model = models.CharField(max_length=60)
    consent_at = models.DateTimeField()
    started_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, choices=AiEndReason.choices, blank=True)
    token_count = models.PositiveSmallIntegerField(default=0)
    last_token_at = models.DateTimeField(null=True, blank=True)
    #: Client-reported measurements (connect time, latency, fps, interruptions, generated seconds).
    metrics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["user", "started_at"]), models.Index(fields=["status", "expires_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=Q(status="ACTIVE"), name="tryon_ai_one_active_session_per_user"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.status} {self.started_at:%Y-%m-%d %H:%M}"


class SavedLook(BaseModel):
    """A frame of the AI result the user explicitly chose to keep. Private to its owner."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tryon_looks")
    garment = models.ForeignKey(Garment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    session = models.ForeignKey(AiTryOnSession, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    image = models.ImageField(upload_to=look_upload_to, storage=private_storage)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"])]
