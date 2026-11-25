from decimal import Decimal

from rest_framework import serializers

from apps.core.uploads import process_image

from . import assets
from .models import (
    ApprovalStatus,
    AssetKind,
    FavoriteGarment,
    Garment,
    GarmentAsset,
    GarmentCategory,
    TryOnSession,
)


def _absolute(context, url: str) -> str:
    request = context.get("request")
    return request.build_absolute_uri(url) if request is not None else url


class CategorySerializer(serializers.ModelSerializer):
    garment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = GarmentCategory
        fields = ["id", "name", "slug", "sort_order", "garment_count"]
        read_only_fields = fields


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = GarmentCategory
        fields = ["id", "name", "slug"]
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
            "created_at",
            "updated_at",
        ]

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
