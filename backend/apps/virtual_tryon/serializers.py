from decimal import Decimal

from rest_framework import serializers

from apps.core.uploads import process_image

from . import assets
from .models import (
    AiEndReason,
    AiTryOnSession,
    ApprovalStatus,
    AssetKind,
    FavoriteGarment,
    Garment,
    GarmentAsset,
    GarmentCategory,
    SavedLook,
    TryOnSession,
)


def _absolute(context, url: str) -> str:
    request = context.get("request")
    return request.build_absolute_uri(url) if request is not None else url


class CategorySerializer(serializers.ModelSerializer):
    garment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = GarmentCategory
        fields = ["id", "name", "slug", "audience", "sort_order", "garment_count"]
        read_only_fields = fields


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = GarmentCategory
        fields = ["id", "name", "slug", "audience"]
        read_only_fields = fields


class ColorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=40)
    hex = serializers.RegexField(r"^#[0-9A-Fa-f]{6}$", required=False, allow_blank=True)


class GarmentAssetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = GarmentAsset
        fields = ["id", "kind", "url", "width", "height", "size_bytes", "anchors", "updated_at"]
        read_only_fields = fields

    def get_url(self, asset) -> str:
        return _absolute(self.context, asset.file.url)


class GarmentSerializer(serializers.ModelSerializer):
    """What a USER sees in the catalogue."""

    category = CategoryRefSerializer(read_only=True)
    cover_image = serializers.SerializerMethodField()
    studio_name = serializers.SerializerMethodField()
    tryon_ready = serializers.SerializerMethodField(
        help_text="Kamerada kiyib ko'rish mumkin: yoqilgan va asosiy (BODY_FRONT) qatlami bor."
    )
    is_favorite = serializers.SerializerMethodField()
    colors = ColorSerializer(many=True, read_only=True)
    sizes = serializers.ListField(child=serializers.CharField(), read_only=True)
    ai_ready = serializers.SerializerMethodField(help_text="AI (Decart) bilan jonli kiyib ko'rish mumkin.")
    ai_reference_image = serializers.SerializerMethodField(
        help_text="AI'ga yuboriladigan kiyim rasmi (fonsiz, odamsiz)."
    )

    class Meta:
        model = Garment
        fields = [
            "id",
            "category",
            "name",
            "description",
            "price",
            "currency",
            "sizes",
            "colors",
            "cover_image",
            "asset_type",
            "tryon_ready",
            "ai_ready",
            "ai_reference_image",
            "ai_prompt",
            "is_favorite",
            "studio_name",
            "updated_at",
        ]
        read_only_fields = fields

    def get_cover_image(self, garment) -> str | None:
        return _absolute(self.context, garment.cover_image.url) if garment.cover_image else None

    def get_studio_name(self, garment) -> str | None:
        return garment.studio.name if garment.studio_id else None

    def get_tryon_ready(self, garment) -> bool:
        has_front = getattr(garment, "has_front", None)
        if has_front is None:
            has_front = garment.assets.filter(kind=AssetKind.BODY_FRONT).exists()
        return bool(garment.is_tryon_enabled and has_front)

    def get_ai_ready(self, garment) -> bool:
        return bool(garment.ai_reference_image)

    def get_ai_reference_image(self, garment) -> str | None:
        return _absolute(self.context, garment.ai_reference_image.url) if garment.ai_reference_image else None

    def get_is_favorite(self, garment) -> bool:
        ids = self.context.get("favorite_ids")
        if ids is not None:
            return garment.pk in ids
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and garment.favorites.filter(user=user).exists())


# ---------------------------------------------------------------- sessions / favourites
class SessionCreateSerializer(serializers.Serializer):
    garment = serializers.UUIDField()


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TryOnSession
        fields = ["id", "garment", "started_at", "ended_at", "duration_seconds"]
        read_only_fields = fields


class FavoriteCreateSerializer(serializers.Serializer):
    garment = serializers.UUIDField()


class FavoriteSerializer(serializers.ModelSerializer):
    garment = GarmentSerializer(read_only=True)

    class Meta:
        model = FavoriteGarment
        fields = ["id", "garment", "created_at"]
        read_only_fields = fields


# ---------------------------------------------------------------- AI try-on
class AiStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Server AI xizmati (Decart yoki OpenAI) kaliti bilan sozlangan.")
    mode = serializers.ChoiceField(
        choices=["realtime", "snapshot"],
        default="realtime",
        help_text="realtime = Decart WebRTC jonli video; snapshot = OpenAI kamera kadri orqali AI kiyib ko'rish.",
    )
    model = serializers.CharField()
    max_session_seconds = serializers.IntegerField()
    seconds_left_today = serializers.IntegerField()
    sessions_left_today = serializers.IntegerField()
    active_session = serializers.UUIDField(allow_null=True)


class AiRenderRequestSerializer(serializers.Serializer):
    garment = serializers.UUIDField()
    photo = serializers.ImageField()


class AiRenderResponseSerializer(serializers.Serializer):
    image = serializers.CharField(help_text="Data URL (data:image/jpeg;base64,...) — AI kiyib ko'rish natijasi.")
    width = serializers.IntegerField()
    height = serializers.IntegerField()
    model = serializers.CharField()
    latency_ms = serializers.IntegerField()
    garment = serializers.UUIDField()


class AiSessionCreateSerializer(serializers.Serializer):
    consent = serializers.BooleanField(
        help_text="Foydalanuvchi kamera tasviri AI xizmatiga (Decart) qayta ishlash uchun yuborilishiga rozi."
    )

    def validate_consent(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError("Kamera va AI qayta ishlashga rozilik kerak.")
        return value


class AiSessionSerializer(serializers.ModelSerializer):
    seconds_left = serializers.SerializerMethodField()

    class Meta:
        model = AiTryOnSession
        fields = [
            "id",
            "status",
            "provider_model",
            "started_at",
            "expires_at",
            "seconds_left",
            "ended_at",
            "end_reason",
            "token_count",
        ]
        read_only_fields = fields

    def get_seconds_left(self, session) -> int:
        from django.utils import timezone

        if session.status != "ACTIVE":
            return 0
        return max(0, int((session.expires_at - timezone.now()).total_seconds()))


class AiTokenSerializer(serializers.Serializer):
    api_key = serializers.CharField(help_text="Qisqa muddatli Decart client token (ek_...). Doimiy kalit emas.")
    expires_at = serializers.CharField()
    model = serializers.CharField()
    session_expires_at = serializers.DateTimeField()


class AiMetricsSerializer(serializers.Serializer):
    """Measured in the browser; stored for the usage dashboard. No video or images."""

    connect_ms = serializers.IntegerField(min_value=0, max_value=600_000, required=False)
    first_frame_ms = serializers.IntegerField(min_value=0, max_value=600_000, required=False)
    glass_to_glass_ms = serializers.IntegerField(min_value=0, max_value=60_000, required=False)
    fps = serializers.FloatField(min_value=0, max_value=240, required=False)
    interruptions = serializers.IntegerField(min_value=0, max_value=10_000, required=False)
    generation_seconds = serializers.FloatField(min_value=0, max_value=86_400, required=False)
    garments_tried = serializers.IntegerField(min_value=0, max_value=10_000, required=False)


class AiFinishSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=AiEndReason.choices, default=AiEndReason.USER)
    metrics = AiMetricsSerializer(required=False)


class SavedLookSerializer(serializers.ModelSerializer):
    garment = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField(help_text="Faqat egasi yuklab oladigan himoyalangan manzil.")

    class Meta:
        model = SavedLook
        fields = ["id", "garment", "image", "width", "height", "created_at"]
        read_only_fields = fields

    def get_garment(self, look) -> dict | None:
        g = look.garment
        return {"id": str(g.pk), "name": g.name} if g is not None and g.deleted_at is None else None

    def get_image(self, look) -> str:
        from django.urls import reverse

        return _absolute(self.context, reverse("tryon-look-image", args=[look.pk]))


class SavedLookCreateSerializer(serializers.Serializer):
    image = serializers.ImageField(help_text="AI natijasidan olingan kadr (JPG/PNG/WEBP, ≤5 MB).")
    garment = serializers.UUIDField(required=False, allow_null=True)
    session = serializers.UUIDField(required=False, allow_null=True)

    def validate_image(self, value):
        return process_image(value, max_side=1600)


class AiReferenceUploadSerializer(serializers.Serializer):
    image = serializers.ImageField(
        help_text="Kiyimning toza rasmi: odamsiz, oq yoki bir xil rangli fonda, kamida 512×512, JPG/PNG/WEBP."
    )
    prompt = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate_image(self, value):
        from .reference import process_reference

        content, _w, _h = process_reference(value)
        return content


# ---------------------------------------------------------------- staff
class AdminGarmentSerializer(serializers.ModelSerializer):
    category = CategoryRefSerializer(read_only=True)
    tryon_ready = serializers.SerializerMethodField()
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=GarmentCategory.objects.all(), write_only=True
    )
    cover_image = serializers.ImageField(write_only=True, required=False)
    cover_image_url = serializers.SerializerMethodField()
    sizes = serializers.ListField(child=serializers.CharField(max_length=20), max_length=20, required=False)
    colors = ColorSerializer(many=True, required=False)
    price = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0"), required=False)
    assets = GarmentAssetSerializer(many=True, read_only=True)
    ai_reference_image_url = serializers.SerializerMethodField()
    ai_ready = serializers.SerializerMethodField()

    class Meta:
        model = Garment
        fields = [
            "id",
            "category",
            "category_id",
            "studio",
            "name",
            "description",
            "price",
            "currency",
            "sizes",
            "colors",
            "cover_image",
            "cover_image_url",
            "asset_type",
            "is_tryon_enabled",
            "is_active",
            "approval_status",
            "rejection_reason",
            "sort_order",
            "tryon_ready",
            "assets",
            "ai_prompt",
            "ai_reference_image_url",
            "ai_ready",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "category",
            "studio",
            "approval_status",
            "rejection_reason",
            "tryon_ready",
            "assets",
            "ai_reference_image_url",
            "ai_ready",
            "created_at",
            "updated_at",
        ]

    def get_ai_reference_image_url(self, garment) -> str | None:
        return _absolute(self.context, garment.ai_reference_image.url) if garment.ai_reference_image else None

    def get_ai_ready(self, garment) -> bool:
        return bool(garment.ai_reference_image)

    def validate_ai_prompt(self, value: str) -> str:
        return " ".join(value.split())

    def get_cover_image_url(self, garment) -> str | None:
        return _absolute(self.context, garment.cover_image.url) if garment.cover_image else None

    def get_tryon_ready(self, garment) -> bool:
        return GarmentSerializer.get_tryon_ready(self, garment)

    def validate_cover_image(self, value):
        return process_image(value, max_side=1200)

    def update(self, instance, validated_data):
        # Any edit of an approved/rejected garment sends it back to review.
        if instance.approval_status != ApprovalStatus.DRAFT:
            validated_data.setdefault("approval_status", ApprovalStatus.PENDING)
        return super().update(instance, validated_data)


class AssetUploadSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=AssetKind.choices)
    file = serializers.FileField()
    anchors = serializers.JSONField(required=False, help_text="Normallashgan anchor nuqtalari (JSON).")

    def validate(self, attrs):
        kind = attrs["kind"]
        attrs["anchors"] = assets.parse_anchors(kind, attrs.get("anchors") or {})
        if kind == AssetKind.MODEL_GLB:
            attrs["content"], attrs["width"], attrs["height"] = assets.process_glb(attrs["file"]), 0, 0
        else:
            attrs["content"], attrs["width"], attrs["height"] = assets.process_layer(attrs["file"])
        return attrs


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class AdminSavedLookSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    garment = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()

    class Meta:
        model = SavedLook
        fields = [
            "id",
            "user",
            "garment",
            "image",
            "width",
            "height",
            "drive_file_id",
            "drive_web_url",
            "created_at",
        ]
        read_only_fields = fields

    def get_user(self, look) -> dict:
        u = look.user
        full = f"{u.first_name} {u.last_name}".strip() or u.phone_number or u.email or str(u.pk)
        return {
            "id": str(u.pk),
            "full_name": full,
            "phone_number": u.phone_number,
            "email": u.email,
        }

    def get_garment(self, look) -> dict | None:
        g = look.garment
        if g is None:
            return None
        return {
            "id": str(g.pk),
            "name": g.name,
            "category_name": g.category.name if g.category_id else "",
            "cover_image": _absolute(self.context, g.cover_image.url) if g.cover_image else None,
        }

    def get_image(self, look) -> str:
        from django.urls import reverse

        return _absolute(self.context, reverse("admin-tryon-look-image", args=[look.pk]))
