"""Staff management of the try-on catalogue: ``/admin/virtual-tryon/garments/``.

SUPER_ADMIN always; ADMIN with the ``tryon.*`` codes. Garments are created as DRAFT, get their
transparent layers through ``assets/`` and become visible to users only after ``approve``.
Studios cannot manage garments: their role is photo/video, not selling clothes.
"""

import django_filters
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasAdminPermission
from apps.audit.models import AuditAction
from apps.audit.services import record

from . import drive_sync
from .assets import IMAGE_KINDS
from .models import ApprovalStatus, AssetKind, Garment, GarmentAsset, GarmentCategory, GarmentOrder, SavedLook
from .serializers import (
    AdminGarmentOrderSerializer,
    AdminGarmentSerializer,
    AdminOrderStatusUpdateSerializer,
    AdminSavedLookSerializer,
    AiReferenceUploadSerializer,
    AssetUploadSerializer,
    CategoryRefSerializer,
    RejectSerializer,
)

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
        "upload_ai_reference": "tryon.update",
        "delete_ai_reference": "tryon.update",
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
        summary="AI kiyib ko'rish rasmi (odamsiz, oddiy fonda, ≥512 px) — tekshiriladi va almashtiriladi",
        description=(
            "Format, o'lcham, nisbat va fon avtomatik tekshiriladi. Rasmda odam yo'qligini xodim "
            "tasdiqlashdan oldin o'zi tekshiradi. `prompt` — kiyim tavsifi (ixtiyoriy)."
        ),
        tags=["admin-virtual-tryon"],
        request={"multipart/form-data": AiReferenceUploadSerializer},
        responses={200: AdminGarmentSerializer},
    )
    @action(detail=True, methods=["post"], url_path="ai-reference")
    def upload_ai_reference(self, request, pk=None):
        garment = self.get_object()
        body = AiReferenceUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        with transaction.atomic():
            raw = data["image"].read()
            if garment.ai_reference_image:
                garment.ai_reference_image.delete(save=False)
            garment.ai_reference_image.save("reference.jpg", ContentFile(raw), save=False)
            fields = ["ai_reference_image", "updated_at"]
            if not garment.cover_image:
                garment.cover_image.save("cover.jpg", ContentFile(raw), save=False)
                fields.append("cover_image")
            if "prompt" in data:
                garment.ai_prompt = " ".join(data["prompt"].split())
                fields.append("ai_prompt")
            if garment.approval_status == ApprovalStatus.APPROVED:
                garment.approval_status = ApprovalStatus.PENDING
                fields.append("approval_status")
            garment.save(update_fields=fields)
        record(request, AuditAction.UPDATE, garment, changes={"ai_reference_image": "uploaded"})
        return self._detail(garment)

    @extend_schema(
        summary="AI kiyib ko'rish rasmini o'chirish", tags=["admin-virtual-tryon"], responses=AdminGarmentSerializer
    )
    @upload_ai_reference.mapping.delete
    def delete_ai_reference(self, request, pk=None):
        garment = self.get_object()
        if garment.ai_reference_image:
            garment.ai_reference_image.delete(save=False)
            garment.save(update_fields=["ai_reference_image", "updated_at"])
            record(request, AuditAction.UPDATE, garment, changes={"ai_reference_image": "deleted"})
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
        # AR needs the BODY_FRONT layer; an AI-only garment (reference image) may skip the AR layers.
        if garment.is_tryon_enabled and AssetKind.BODY_FRONT not in kinds and not garment.ai_reference_image:
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


class AiUsageView(APIView):
    """Cost-control dashboard for AI try-on: sessions, seconds, estimated cost, measured quality."""

    permission_classes = [HasAdminPermission]
    required_permission = "tryon.view"

    @extend_schema(
        summary="AI kiyib ko'rish sarfi (seanslar, soniyalar, taxminiy narx, o'lchovlar)",
        tags=["admin-virtual-tryon"],
        parameters=[OpenApiParameter("days", OpenApiTypes.INT, description="Oxirgi necha kun (1-90, standart 7)")],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request):
        from datetime import timedelta
        from statistics import mean

        from django.conf import settings
        from django.utils import timezone

        from . import ai, decart
        from .models import AiTryOnSession

        try:
            days = min(90, max(1, int(request.query_params.get("days", 7))))
        except ValueError:
            days = 7
        ai.close_expired()
        now = timezone.now()
        since = ai._day_start(now) - timedelta(days=days - 1)
        rows = list(AiTryOnSession.objects.filter(started_at__gte=since).order_by("started_at"))
        per_day: dict = {}
        reasons: dict = {}
        for s in rows:
            day = timezone.localtime(s.started_at).date().isoformat()
            bucket = per_day.setdefault(day, {"date": day, "sessions": 0, "seconds": 0})
            bucket["sessions"] += 1
            bucket["seconds"] += ai.used_seconds(s, now)
            if s.end_reason:
                reasons[s.end_reason] = reasons.get(s.end_reason, 0) + 1

        def avg(key):
            values = [s.metrics[key] for s in rows if isinstance(s.metrics.get(key), (int, float))]
            return round(mean(values), 1) if values else None

        seconds = sum(b["seconds"] for b in per_day.values())
        price = settings.AI_TRYON["PRICE_PER_SECOND_USD"]
        return Response(
            {
                "enabled": decart.is_configured(),
                "model": settings.AI_TRYON["MODEL"],
                "days": days,
                "sessions": len(rows),
                "users": len({s.user_id for s in rows}),
                "active_now": sum(1 for s in rows if s.status == "ACTIVE"),
                "seconds": seconds,
                "estimated_cost_usd": round(seconds * price, 2),
                "price_per_second_usd": price,
                "per_day": list(per_day.values()),
                "end_reasons": reasons,
                "measured": {
                    "connect_ms_avg": avg("connect_ms"),
                    "first_frame_ms_avg": avg("first_frame_ms"),
                    "glass_to_glass_ms_avg": avg("glass_to_glass_ms"),
                    "fps_avg": avg("fps"),
                    "interruptions_avg": avg("interruptions"),
                    "sessions_with_metrics": sum(1 for s in rows if s.metrics),
                },
                "note": (
                    "Soniyalar seansning devor-soati vaqti (Decart hisoblaydigan generatsiya vaqtidan katta yoki teng)."
                ),
            }
        )


class AdminCategoryListView(APIView):
    """List active garment categories for the Admin / Super Admin garment creation form."""

    permission_classes = [HasAdminPermission]
    required_permission = "tryon.view"

    @extend_schema(summary="Kiyim kategoriyalari (admin)", tags=["admin-virtual-tryon"], responses=CategoryRefSerializer(many=True))
    def get(self, request):
        rows = GarmentCategory.objects.filter(is_active=True).order_by("sort_order", "name")
        return Response(CategoryRefSerializer(rows, many=True).data)


@extend_schema_view(
    list=extend_schema(summary="Foydalanuvchilar kiyib ko'rgan obrazlar (admin)", tags=["admin-virtual-tryon"]),
    retrieve=extend_schema(summary="Kiyib ko'rilgan obraz tafsilotlari", tags=["admin-virtual-tryon"]),
)
class AdminSavedLookViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Staff gallery of every virtual try-on look generated by users (with Google Drive sync status)."""

    permission_classes = [HasAdminPermission]
    permission_module = "tryon"
    action_permissions = {
        "image": "tryon.view",
        "video": "tryon.view",
        "sync_drive": "tryon.update",
    }
    serializer_class = AdminSavedLookSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        qs = SavedLook.objects.select_related("user", "garment", "garment__category").order_by("-created_at")
        if garment_id := self.request.query_params.get("garment", "").strip():
            qs = qs.filter(garment_id=garment_id)
        if q := self.request.query_params.get("q", "").strip()[:100]:
            from django.db.models import Q

            qs = qs.filter(
                Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(user__phone_number__icontains=q)
                | Q(garment__name__icontains=q)
            )
        return qs

    @extend_schema(
        summary="Kiyib ko'rilgan obraz rasmi (admin)",
        tags=["admin-virtual-tryon"],
        responses={(200, "image/jpeg"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="image", url_name="image")
    def image(self, request, pk=None):
        look = self.get_object()
        name = (look.image.name or "").lower()
        ctype = "image/jpeg" if name.endswith((".jpg", ".jpeg")) else "image/webp"
        response = FileResponse(look.image.open("rb"), content_type=ctype)
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(
        summary="Kiyib ko'rilgan obraz videosi (admin)",
        tags=["admin-virtual-tryon"],
        responses={(200, "video/mp4"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="video", url_name="video")
    def video(self, request, pk=None):
        look = self.get_object()
        if not look.video:
            raise NotFound("Video mavjud emas.")
        response = FileResponse(look.video.open("rb"), content_type="video/mp4")
        response["Cache-Control"] = "private, no-store"
        return response

    @extend_schema(
        summary="Obrazni Google Drive'ga yuklash",
        tags=["admin-virtual-tryon"],
        request=None,
        responses={200: AdminSavedLookSerializer},
    )
    @action(detail=True, methods=["post"], url_path="sync-drive")
    def sync_drive(self, request, pk=None):
        look = self.get_object()
        drive_sync.upload_look_to_drive(look)
        look.refresh_from_db()
        return Response(AdminSavedLookSerializer(look, context=self.get_serializer_context()).data)


@extend_schema_view(
    list=extend_schema(summary="Sotib olingan kiyim buyurtmalari (admin)", tags=["admin-virtual-tryon"]),
    retrieve=extend_schema(summary="Buyurtma tafsilotlari (admin)", tags=["admin-virtual-tryon"]),
)
class AdminGarmentOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Staff view of all garment orders placed by users."""

    permission_classes = [HasAdminPermission]
    permission_module = "tryon"
    action_permissions = {
        "partial_update": "tryon.update",
    }
    serializer_class = AdminGarmentOrderSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        qs = (
            GarmentOrder.objects.select_related("user", "garment", "garment__category", "look")
            .order_by("-created_at")
        )
        if st := self.request.query_params.get("status", "").strip():
            qs = qs.filter(status=st)
        if q := self.request.query_params.get("q", "").strip()[:100]:
            from django.db.models import Q

            qs = qs.filter(
                Q(customer_name__icontains=q)
                | Q(customer_phone__icontains=q)
                | Q(garment__name__icontains=q)
                | Q(delivery_address__icontains=q)
            )
        return qs

    @extend_schema(
        summary="Buyurtma holatini yangilash",
        tags=["admin-virtual-tryon"],
        request=AdminOrderStatusUpdateSerializer,
        responses={200: AdminGarmentOrderSerializer},
    )
    def partial_update(self, request, pk=None):
        order = self.get_object()
        body = AdminOrderStatusUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        new_status = body.validated_data["status"]
        old_status = order.status
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        record(request, AuditAction.UPDATE, order, changes={"status": {"from": old_status, "to": new_status}})
        return Response(AdminGarmentOrderSerializer(order, context=self.get_serializer_context()).data)
