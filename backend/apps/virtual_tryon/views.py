"""Virtual try-on API for USER accounts (frontend-user).

* ``virtual-tryon/categories/``            — active categories with the number of visible garments
* ``virtual-tryon/garments/``              — approved + active garments (filter: category, q, tryon)
* ``virtual-tryon/garments/{id}/assets/``  — the transparent layers + anchors the camera renderer needs
* ``virtual-tryon/sessions/``              — try-on statistics (start / finish). No camera data.
* ``virtual-tryon/favorites/``             — the user's own favourites
* ``virtual-tryon/ai/status/``             — is AI try-on available, the user's remaining budget
* ``virtual-tryon/ai-sessions/``           — AI try-on sessions: start, client token, finish
* ``virtual-tryon/looks/``                 — the user's saved AI looks (private files)

AR mode: the camera, body tracking and drawing all run in the browser; nothing here receives frames.
AI mode: the browser streams the camera straight to Decart over WebRTC with a short-lived client
token from ``ai-sessions/{id}/token/``; this server never receives video (see ``decart.py``).
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.access import AccessNote
from apps.ceremonies.permissions import IsClientUser

from . import ai, decart
from .models import (
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
from .serializers import (
    AiFinishSerializer,
    AiSessionCreateSerializer,
    AiSessionSerializer,
    AiStatusSerializer,
    AiTokenSerializer,
    CategorySerializer,
    FavoriteCreateSerializer,
    FavoriteSerializer,
    GarmentAssetSerializer,
    GarmentSerializer,
    SavedLookCreateSerializer,
    SavedLookSerializer,
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
            OpenApiParameter("ai", OpenApiTypes.BOOL, description="Faqat AI bilan kiyib ko'rsa bo'ladiganlari"),
            OpenApiParameter("audience", OpenApiTypes.STR, enum=["MEN", "WOMEN", "UNISEX"]),
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
        if params.get("ai") in ("1", "true"):
            qs = qs.exclude(ai_reference_image="")
        if audience := params.get("audience", "").strip().upper():
            qs = qs.filter(category__audience=audience)
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


# ------------------------------------------------------------------ AI try-on (Decart)
class AiStatusView(APIView):
    permission_classes = [IsClientUser]
    access_notes = {"*": AccessNote(ownership="Faqat o'z limitlari.")}

    @extend_schema(
        summary="AI kiyib ko'rish holati va bugungi limit", tags=["virtual-tryon"], responses=AiStatusSerializer
    )
    def get(self, request):
        cfg = settings.AI_TRYON
        left = ai.budget(request.user)
        active = ai.active_session(request.user)
        return Response(
            {
                "enabled": decart.is_configured(),
                "model": cfg["MODEL"],
                "max_session_seconds": cfg["MAX_SESSION_SECONDS"],
                "seconds_left_today": left.seconds_left_today,
                "sessions_left_today": left.sessions_left_today,
                "active_session": active.pk if active else None,
            }
        )


class AiSessionViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    serializer_class = AiSessionSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {
        "*": AccessNote(ownership="Faqat o'z AI seanslari (boshqalarniki 404)."),
        "create": AccessNote(
            conditions=(
                "Kamera va AI qayta ishlashga rozilik (consent=true) majburiy.",
                "Bir vaqtda bitta faol seans (409); kunlik soni va soniyalari cheklangan (429).",
            )
        ),
        "token": AccessNote(
            ownership="Faqat o'z faol seansi.",
            conditions=("Qisqa muddatli Decart client token; doimiy kalit hech qachon qaytarilmaydi.",),
        ),
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AiTryOnSession.objects.none()
        return AiTryOnSession.objects.filter(user=self.request.user)

    def get_throttles(self):
        if self.action in ("create", "token"):
            self.throttle_scope = "ai_tryon_session" if self.action == "create" else "ai_tryon_token"
            return [*super().get_throttles(), ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        summary="AI kiyib ko'rish seansini boshlash",
        tags=["virtual-tryon"],
        request=AiSessionCreateSerializer,
        responses={201: AiSessionSerializer},
    )
    def create(self, request):
        AiSessionCreateSerializer(data=request.data).is_valid(raise_exception=True)
        session = ai.start_session(request.user)
        return Response(AiSessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="AI seansi", tags=["virtual-tryon"])
    def retrieve(self, request, *args, **kwargs):
        ai.close_expired(user=request.user)
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Decart uchun qisqa muddatli client token (WebRTC ulanishini boshlash/qayta ulash)",
        tags=["virtual-tryon"],
        request=None,
        responses=AiTokenSerializer,
    )
    @action(detail=True, methods=["post"])
    def token(self, request, pk=None):
        session = self.get_object()
        token = ai.issue_token(session)
        return Response(
            {
                "api_key": token.api_key,
                "expires_at": token.expires_at,
                "model": session.provider_model,
                "session_expires_at": session.expires_at,
            }
        )

    @extend_schema(
        summary="AI seansini yakunlash (o'lchovlar bilan)",
        tags=["virtual-tryon"],
        request=AiFinishSerializer,
        responses=AiSessionSerializer,
    )
    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        body = AiFinishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        session = ai.finish(self.get_object(), body.validated_data["reason"], body.validated_data.get("metrics") or {})
        return Response(AiSessionSerializer(session).data)


@extend_schema_view(
    list=extend_schema(summary="Saqlangan AI obrazlarim", tags=["virtual-tryon"]),
    destroy=extend_schema(summary="Saqlangan obrazni o'chirish", tags=["virtual-tryon"]),
)
class SavedLookViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    serializer_class = SavedLookSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {
        "*": AccessNote(ownership="Faqat o'z obrazlari (boshqalarniki 404)."),
        "create": AccessNote(conditions=("Faqat foydalanuvchi o'zi tanlagan kadr; soni cheklangan.",)),
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SavedLook.objects.none()
        return SavedLook.objects.filter(user=self.request.user).select_related("garment")

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "tryon_look"
            return [*super().get_throttles(), ScopedRateThrottle()]
        return super().get_throttles()

    @extend_schema(
        summary="AI natijasidan kadrni saqlash",
        tags=["virtual-tryon"],
        request={"multipart/form-data": SavedLookCreateSerializer},
        responses={201: SavedLookSerializer},
    )
    def create(self, request):
        body = SavedLookCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        if SavedLook.objects.filter(user=request.user).count() >= settings.AI_TRYON["MAX_SAVED_LOOKS_PER_USER"]:
            raise ValidationError({"image": ["Saqlangan obrazlar soni chegarasiga yetdi. Eskilarini o'chiring."]})
        garment = visible_garments().filter(pk=data["garment"]).first() if data.get("garment") else None
        session = (
            AiTryOnSession.objects.filter(user=request.user, pk=data["session"]).first()
            if data.get("session")
            else None
        )
        from PIL import Image

        content = data["image"]
        with Image.open(content) as img:
            width, height = img.size
        content.seek(0)
        look = SavedLook(user=request.user, garment=garment, session=session, width=width, height=height)
        look.image.save(content.name, content, save=False)
        look.save()
        return Response(SavedLookSerializer(look, context={"request": request}).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, look):
        look.image.delete(save=False)
        look.delete()

    @extend_schema(
        summary="Saqlangan obraz rasmi (faqat egasi)",
        tags=["virtual-tryon"],
        responses={(200, "image/webp"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="image", url_name="image")
    def image(self, request, pk=None):
        look = self.get_object()
        response = FileResponse(look.image.open("rb"), content_type="image/webp")
        response["Cache-Control"] = "private, no-store"
        return response
