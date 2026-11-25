"""Staff management of the try-on catalogue: ``/admin/virtual-tryon/garments/``.

SUPER_ADMIN always; ADMIN with the ``tryon.*`` codes. Garments are created as DRAFT, get their
transparent layers through ``assets/`` and become visible to users only after ``approve``.
Studios cannot manage garments: their role is photo/video, not selling clothes.
"""

import django_filters
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import HasAdminPermission
from apps.audit.models import AuditAction
from apps.audit.services import record

from .assets import IMAGE_KINDS
from .models import ApprovalStatus, AssetKind, Garment, GarmentAsset
from .serializers import AdminGarmentSerializer, AssetUploadSerializer, RejectSerializer

UUID_RE = "[0-9a-fA-F-]{36}"


class GarmentFilter(django_filters.FilterSet):
    approval_status = django_filters.ChoiceFilter(choices=ApprovalStatus.choices)
    category = django_filters.CharFilter(field_name="category__slug")
    q = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Garment
        fields = ["approval_status", "category", "is_active"]


@extend_schema_view(
    list=extend_schema(summary="Kiyimlar (boshqaruv)", tags=["admin-virtual-tryon"]),
    create=extend_schema(summary="Kiyim qo'shish (qoralama)", tags=["admin-virtual-tryon"]),
    retrieve=extend_schema(summary="Kiyim (qatlamlari bilan)", tags=["admin-virtual-tryon"]),
    partial_update=extend_schema(summary="Kiyimni tahrirlash", tags=["admin-virtual-tryon"]),
    destroy=extend_schema(summary="Kiyimni o'chirish (soft)", tags=["admin-virtual-tryon"]),
)
class AdminGarmentViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [HasAdminPermission]
    permission_module = "tryon"
    action_permissions = {
        "upload_asset": "tryon.update",
        "delete_asset": "tryon.update",
        "approve": "tryon.approve",
        "reject": "tryon.approve",
    }
    serializer_class = AdminGarmentSerializer
    filterset_class = GarmentFilter
    lookup_value_regex = UUID_RE
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return (
            Garment.objects.filter(deleted_at__isnull=True)
            .select_related("category", "studio")
            .prefetch_related("assets")
        )

    def perform_create(self, serializer):
        garment = serializer.save(created_by=self.request.user)
        record(self.request, AuditAction.CREATE, garment)

    def perform_update(self, serializer):
        garment = serializer.save()
        record(self.request, AuditAction.UPDATE, garment, changes={"fields": sorted(serializer.validated_data)})

    def perform_destroy(self, garment):
        garment.soft_delete()
        record(self.request, AuditAction.DELETE, garment)

    def _detail(self, garment):
        garment = self.get_queryset().get(pk=garment.pk)
        return Response(AdminGarmentSerializer(garment, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="AR qatlamini yuklash (shaffof PNG/WEBP yoki GLB) — shu turdagi eskisi almashtiriladi",
        tags=["admin-virtual-tryon"],
        request={"multipart/form-data": AssetUploadSerializer},
        responses={200: AdminGarmentSerializer},
    )
    @action(detail=True, methods=["post"], url_path="assets")
    def upload_asset(self, request, pk=None):
        garment = self.get_object()
        body = AssetUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        with transaction.atomic():
            old = GarmentAsset.objects.filter(garment=garment, kind=data["kind"]).first()
            if old is not None:
                old.file.delete(save=False)
                old.delete()
            GarmentAsset.objects.create(
                garment=garment,
                kind=data["kind"],
                file=data["content"],
                width=data["width"],
                height=data["height"],
                size_bytes=data["content"].size,
                anchors=data["anchors"],
            )
            if garment.approval_status == ApprovalStatus.APPROVED:
                garment.approval_status = ApprovalStatus.PENDING
                garment.save(update_fields=["approval_status", "updated_at"])
        record(request, AuditAction.UPDATE, garment, changes={"asset": data["kind"]})
        return self._detail(garment)

    @extend_schema(
        summary="AR qatlamini o'chirish",
        tags=["admin-virtual-tryon"],
        parameters=[OpenApiParameter("kind", OpenApiTypes.STR, OpenApiParameter.PATH, enum=AssetKind.values)],
        responses={200: AdminGarmentSerializer},
    )
    @action(detail=True, methods=["delete"], url_path=r"assets/(?P<kind>[^/.]+)")
    def delete_asset(self, request, pk=None, kind=None):
        garment = self.get_object()
        if kind not in AssetKind.values:
            raise NotFound("Bunday qatlam turi yo'q.")
        asset = GarmentAsset.objects.filter(garment=garment, kind=kind).first()
        if asset is not None:
            asset.file.delete(save=False)
            asset.delete()
            record(request, AuditAction.UPDATE, garment, changes={"asset_deleted": kind})
        return self._detail(garment)

    @extend_schema(
        summary="Kiyimni tasdiqlash (foydalanuvchilarga ko'rinadi)",
        tags=["admin-virtual-tryon"],
        request=None,
        responses={200: AdminGarmentSerializer},
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        garment = self.get_object()
        kinds = set(garment.assets.values_list("kind", flat=True))
        if garment.is_tryon_enabled and AssetKind.BODY_FRONT not in kinds:
            raise ValidationError({"assets": ["Kiyib ko'rish uchun BODY_FRONT qatlami yuklanmagan."]})
        if not garment.cover_image and not kinds & set(IMAGE_KINDS):
            raise ValidationError({"cover_image": ["Muqova rasmi yuklanmagan."]})
        garment.approval_status, garment.rejection_reason = ApprovalStatus.APPROVED, ""
        garment.save(update_fields=["approval_status", "rejection_reason", "updated_at"])
        record(request, AuditAction.UPDATE, garment, changes={"approval_status": ApprovalStatus.APPROVED})
        return self._detail(garment)

    @extend_schema(
        summary="Kiyimni rad etish",
        tags=["admin-virtual-tryon"],
        request=RejectSerializer,
        responses=AdminGarmentSerializer,
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        body = RejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        garment = self.get_object()
        garment.approval_status = ApprovalStatus.REJECTED
        garment.rejection_reason = body.validated_data["reason"]
        garment.save(update_fields=["approval_status", "rejection_reason", "updated_at"])
        record(request, AuditAction.UPDATE, garment, changes={"approval_status": ApprovalStatus.REJECTED})
        return self._detail(garment)
