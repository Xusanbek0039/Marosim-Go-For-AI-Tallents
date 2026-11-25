"""Virtual try-on API for USER accounts (frontend-user).

* ``virtual-tryon/categories/``            — active categories with the number of visible garments
* ``virtual-tryon/garments/``              — approved + active garments (filter: category, q, tryon)
* ``virtual-tryon/garments/{id}/assets/``  — the transparent layers + anchors the camera renderer needs
* ``virtual-tryon/sessions/``              — try-on statistics (start / finish). No camera data.
* ``virtual-tryon/favorites/``             — the user's own favourites

The camera, body tracking and drawing all run in the browser; nothing here receives frames.
"""

from datetime import timedelta

from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.access import AccessNote
from apps.ceremonies.permissions import IsClientUser

from .models import (
    ApprovalStatus,
    AssetKind,
    FavoriteGarment,
    Garment,
    GarmentAsset,
    GarmentCategory,
    TryOnSession,
)
from .serializers import (
    CategorySerializer,
    FavoriteCreateSerializer,
    FavoriteSerializer,
    GarmentAssetSerializer,
    GarmentSerializer,
    SessionCreateSerializer,
    SessionSerializer,
)

UUID_RE = "[0-9a-fA-F-]{36}"
VISIBLE_ONLY = "Faqat faol va tasdiqlangan (APPROVED) kiyimlar; boshqalari 404."
#: A session left open (tab closed, phone locked) is cut at this length when finished late.
MAX_SESSION = timedelta(hours=2)


def visible_garments():
    front = GarmentAsset.objects.filter(garment=OuterRef("pk"), kind=AssetKind.BODY_FRONT)
    return (
        Garment.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
            approval_status=ApprovalStatus.APPROVED,
            category__is_active=True,
        )
        .select_related("category", "studio")
        .annotate(has_front=Exists(front))
    )


def favorite_ids(user) -> set:
    return set(FavoriteGarment.objects.filter(user=user).values_list("garment_id", flat=True))


@extend_schema_view(list=extend_schema(summary="Kiyim kategoriyalari", tags=["virtual-tryon"]))
class CategoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    serializer_class = CategorySerializer
    pagination_class = None
    filter_backends = []
    access_notes = {"*": AccessNote(conditions=("Faqat faol kategoriyalar; soni — ko'rinadigan kiyimlar.",))}

    def get_queryset(self):
        visible = Q(
            garments__is_active=True,
            garments__deleted_at__isnull=True,
            garments__approval_status=ApprovalStatus.APPROVED,
        )
        return (
            GarmentCategory.objects.filter(is_active=True)
            .annotate(garment_count=Count("garments", filter=visible))
            .order_by("sort_order", "name")  # GROUP BY drops Meta.ordering
        )


@extend_schema_view(
    list=extend_schema(
        summary="Kiyimlar katalogi",
        tags=["virtual-tryon"],
        parameters=[
            OpenApiParameter("category", OpenApiTypes.STR, description="Kategoriya slug'i"),
            OpenApiParameter("q", OpenApiTypes.STR, description="Nomi bo'yicha qidiruv"),
            OpenApiParameter("tryon", OpenApiTypes.BOOL, description="Faqat kamerada kiyib ko'rsa bo'ladiganlari"),
        ],
    ),
    retrieve=extend_schema(summary="Kiyim tafsilotlari", tags=["virtual-tryon"]),
)
class GarmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    serializer_class = GarmentSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {"*": AccessNote(conditions=(VISIBLE_ONLY,))}

    def get_queryset(self):
        qs = visible_garments()
        params = self.request.query_params
        if category := params.get("category", "").strip():
            qs = qs.filter(category__slug=category)
        if q := params.get("q", "").strip()[:100]:
            qs = qs.filter(name__icontains=q)
        if params.get("tryon") in ("1", "true"):
            qs = qs.filter(is_tryon_enabled=True, has_front=True)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        if user.is_authenticated:
            context["favorite_ids"] = favorite_ids(user)
        return context

    @extend_schema(summary="Kiyimning AR qatlamlari (shaffof rasmlar + anchor nuqtalar)", tags=["virtual-tryon"])
    @action(detail=True, methods=["get"], serializer_class=GarmentAssetSerializer, pagination_class=None)
    def assets(self, request, pk=None):
        garment = self.get_object()
        rows = garment.assets.all() if garment.is_tryon_enabled else garment.assets.none()
        return Response(GarmentAssetSerializer(rows, many=True, context=self.get_serializer_context()).data)


class SessionViewSet(viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    serializer_class = SessionSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {
        "create": AccessNote(conditions=("Faqat kamerada kiyib ko'rish mumkin bo'lgan kiyim uchun.",)),
        "finish": AccessNote(ownership="Faqat o'z seansini yakunlaydi (boshqalarniki 404)."),
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TryOnSession.objects.none()
        return TryOnSession.objects.filter(user=self.request.user)

    @extend_schema(
        summary="Kiyib ko'rish seansini boshlash (statistika, kadrlar yuborilmaydi)",
        tags=["virtual-tryon"],
        request=SessionCreateSerializer,
        responses={201: SessionSerializer},
    )
    def create(self, request):
        body = SessionCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        garment = get_object_or_404(
            visible_garments().filter(is_tryon_enabled=True, has_front=True), pk=body.validated_data["garment"]
        )
        session = TryOnSession.objects.create(user=request.user, garment=garment, started_at=timezone.now())
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Kiyib ko'rish seansini yakunlash", tags=["virtual-tryon"], request=None, responses=SessionSerializer
    )
    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        session = self.get_object()
        if session.ended_at is None:
            now = timezone.now()
            session.ended_at = min(now, session.started_at + MAX_SESSION)
            session.duration_seconds = int((session.ended_at - session.started_at).total_seconds())
            session.save(update_fields=["ended_at", "duration_seconds", "updated_at"])
        return Response(SessionSerializer(session).data)


@extend_schema_view(
    list=extend_schema(summary="Sevimli kiyimlarim", tags=["virtual-tryon"]),
    destroy=extend_schema(
        summary="Sevimlilardan olib tashlash",
        tags=["virtual-tryon"],
        description="`id` — sevimli yozuvining yoki kiyimning o'zining id'si.",
    ),
)
class FavoriteViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    serializer_class = FavoriteSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {"*": AccessNote(ownership="Faqat o'z sevimlilari (boshqalarniki 404).")}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FavoriteGarment.objects.none()
        visible = visible_garments().values("pk")
        return FavoriteGarment.objects.filter(user=self.request.user, garment__in=visible).select_related(
            "garment__category", "garment__studio"
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context["favorite_ids"] = favorite_ids(self.request.user)
        return context

    def get_object(self):
        key = self.kwargs["pk"]
        own = FavoriteGarment.objects.filter(user=self.request.user)
        return get_object_or_404(own, Q(pk=key) | Q(garment_id=key))

    @extend_schema(
        summary="Sevimlilarga qo'shish",
        tags=["virtual-tryon"],
        request=FavoriteCreateSerializer,
        responses={201: FavoriteSerializer, 200: FavoriteSerializer},
    )
    def create(self, request):
        body = FavoriteCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        garment = get_object_or_404(visible_garments(), pk=body.validated_data["garment"])
        favorite, created = FavoriteGarment.objects.get_or_create(user=request.user, garment=garment)
        data = FavoriteSerializer(favorite, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
