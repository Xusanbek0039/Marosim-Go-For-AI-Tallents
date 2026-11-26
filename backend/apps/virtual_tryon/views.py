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

import base64
import os
import re
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
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

from . import ai, decart, drive_sync, fal_tryon, openai_tryon, quota, video_jobs, video_tryon, watermark
from .models import (
    AiTryOnSession,
    ApprovalStatus,
    AssetKind,
    FavoriteGarment,
    Garment,
    GarmentAsset,
    GarmentCategory,
    GarmentOrder,
    RenderKind,
    SavedLook,
    TryOnSession,
    VideoJobStatus,
    VideoTryOnJob,
)
from .serializers import (
    AiFinishSerializer,
    AiRenderRequestSerializer,
    AiRenderResponseSerializer,
    AiRenderVideoRequestSerializer,
    AiSessionCreateSerializer,
    AiSessionSerializer,
    AiStatusSerializer,
    AiTokenSerializer,
    CategorySerializer,
    FavoriteCreateSerializer,
    FavoriteSerializer,
    GarmentAssetSerializer,
    GarmentOrderCreateSerializer,
    GarmentOrderSerializer,
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
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


def serve_mp4_range(request, file_field) -> HttpResponse:
    """Serve an MP4 with HTTP Range (206 Partial Content) support for Safari/Chrome/iOS ``<video>``."""
    path = file_field.path
    size = os.path.getsize(path)
    range_header = request.META.get("HTTP_RANGE", "").strip()
    match = _RANGE_RE.match(range_header) if range_header else None

    if match:
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            resp = HttpResponse(status=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        length = end - start + 1

        def _iter_range(chunk_size: int = 65536):
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        resp = StreamingHttpResponse(_iter_range(), status=status.HTTP_206_PARTIAL_CONTENT, content_type="video/mp4")
        resp["Content-Length"] = str(length)
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp["Accept-Ranges"] = "bytes"
        resp["Cache-Control"] = "private, max-age=300"
        return resp

    resp = FileResponse(open(path, "rb"), content_type="video/mp4")
    resp["Content-Length"] = str(size)
    resp["Accept-Ranges"] = "bytes"
    resp["Cache-Control"] = "private, max-age=300"
    return resp


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


# ------------------------------------------------------------------ AI try-on (Decart / OpenAI)
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
        q = quota.quota(request.user)
        if decart.is_configured():
            enabled, mode, model = True, "realtime", cfg["MODEL"]
        elif fal_tryon.is_configured():
            enabled, mode, model = True, "snapshot", cfg.get("FAL_PHOTO_MODEL", "fal-ai/fashn/tryon/v1.6")
        elif openai_tryon.is_configured():
            enabled, mode, model = True, "snapshot", cfg.get("OPENAI_MODEL", "gpt-image-1.5")
        else:
            enabled, mode, model = False, "realtime", cfg["MODEL"]
        return Response(
            {
                "enabled": enabled,
                "mode": mode,
                "model": model,
                "is_premium": watermark.is_premium_user(request.user),
                "quota": {
                    "video_limit": q.video_limit,
                    "video_left": q.video_left,
                    "photo_limit": q.photo_limit,
                    "photo_left": q.photo_left,
                },
                "max_session_seconds": cfg["MAX_SESSION_SECONDS"],
                "seconds_left_today": left.seconds_left_today,
                "sessions_left_today": left.sessions_left_today,
                "active_session": active.pk if active else None,
            }
        )


class AiRenderView(APIView):
    """Snapshot AI try-on: user camera photo + selected garment reference → OpenAI Image Edit."""

    permission_classes = [IsClientUser]
    throttle_scope = "ai_tryon_session"
    throttle_classes = [*APIView.throttle_classes, ScopedRateThrottle]
    access_notes = {
        "post": AccessNote(
            conditions=(
                "Faqat tasdiqlangan va ai_reference_image ga ega kiyimlar uchun.",
                "Foydalanuvchi surati serverda saqlanmaydi; faqat AI xizmatiga yuboriladi.",
            )
        )
    }

    @extend_schema(
        summary="Kamera surati ustida kiyimni AI bilan kiyib ko'rish (OpenAI)",
        tags=["virtual-tryon"],
        request={"multipart/form-data": AiRenderRequestSerializer},
        responses={200: AiRenderResponseSerializer},
    )
    def post(self, request):
        body = AiRenderRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        garment = get_object_or_404(
            visible_garments().exclude(ai_reference_image=""),
            pk=body.validated_data["garment"],
        )
        photo_bytes = openai_tryon.prepare_user_photo(body.validated_data["photo"])
        log = quota.reserve(request.user, RenderKind.PHOTO)
        try:
            if fal_tryon.is_configured():
                try:
                    result = fal_tryon.render_photo_tryon(photo_bytes=photo_bytes, garment=garment)
                except openai_tryon.OpenAITryOnError as exc:
                    if (
                        exc.code
                        in (
                            "provider_insufficient_credits",
                            "provider_auth_failed",
                            "provider_rate_limited",
                            "provider_unavailable",
                        )
                        and openai_tryon.is_configured()
                    ):
                        result = openai_tryon.render_tryon(photo_bytes=photo_bytes, garment=garment)
                    else:
                        raise
            else:
                result = openai_tryon.render_tryon(photo_bytes=photo_bytes, garment=garment)
        except openai_tryon.OpenAITryOnError as exc:
            quota.refund(log)
            message, http_status = ai.PROVIDER_MESSAGES.get(exc.code, ai.PROVIDER_MESSAGES["provider_unavailable"])
            raise ai.AiTryOnError(exc.code, message, http_status) from None
        except Exception:
            quota.refund(log)
            raise
        quota.done(log, result.model)
        data_url = f"data:{result.content_type};base64,{base64.b64encode(result.image_bytes).decode('ascii')}"
        look = SavedLook(
            user=request.user,
            garment=garment,
            width=result.width,
            height=result.height,
        )
        look.image.save(f"tryon-{garment.pk}.jpg", ContentFile(result.image_bytes), save=False)
        look.save()
        drive_sync.upload_look_to_drive(look)
        return Response(
            {
                "image": data_url,
                "width": result.width,
                "height": result.height,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "garment": str(garment.pk),
                "look_id": str(look.pk),
                "drive_file_id": look.drive_file_id,
                "drive_web_url": look.drive_web_url,
            }
        )


def _video_look_payload(request, look, *, model: str, latency_ms: int, frames: int = 0) -> dict:
    from django.urls import reverse

    return {
        "status": VideoJobStatus.DONE,
        "look_id": str(look.pk),
        "video_url": request.build_absolute_uri(reverse("tryon-look-video", args=[look.pk])),
        "poster_url": request.build_absolute_uri(reverse("tryon-look-image", args=[look.pk])),
        "download_url": request.build_absolute_uri(reverse("tryon-look-download", args=[look.pk])),
        "width": look.width,
        "height": look.height,
        "frames": frames,
        "model": model,
        "latency_ms": latency_ms,
        "garment": str(look.garment_id) if look.garment_id else None,
        "drive_file_id": look.drive_file_id,
        "drive_web_url": look.drive_web_url,
    }


def _video_job_payload(request, job: VideoTryOnJob) -> dict:
    if job.status == VideoJobStatus.DONE and job.look_id:
        latency_ms = int(((job.finished_at or job.updated_at) - job.created_at).total_seconds() * 1000)
        return {"job_id": str(job.pk), **_video_look_payload(request, job.look, model=job.model, latency_ms=latency_ms)}
    payload = {
        "job_id": str(job.pk),
        "status": job.status,
        "stage": job.stage,
        "garment": str(job.garment_id) if job.garment_id else None,
    }
    if job.look_id and job.status != VideoJobStatus.FAILED:
        # fast pipeline: the dressed photo is ready while the video is still rendering
        from django.urls import reverse

        payload["look_id"] = str(job.look_id)
        payload["preview_url"] = request.build_absolute_uri(reverse("tryon-look-image", args=[job.look_id]))
    if job.status == VideoJobStatus.FAILED:
        message, _ = ai.PROVIDER_MESSAGES.get(job.error_code, ai.PROVIDER_MESSAGES["provider_unavailable"])
        payload["error"] = {"code": job.error_code, "message": message}
    return payload


def _provider_error(exc: openai_tryon.OpenAITryOnError) -> ai.AiTryOnError:
    message, http_status = ai.PROVIDER_MESSAGES.get(exc.code, ai.PROVIDER_MESSAGES["provider_unavailable"])
    return ai.AiTryOnError(exc.code, message, http_status)


class AiRenderVideoView(APIView):
    """Video Virtual Try-On: short camera video + garment → MP4.

    With fal.ai configured the render runs in the background: the response is ``202`` with a
    ``job_id``; poll ``ai/render-video/{job_id}/`` until ``status`` is ``DONE`` or ``FAILED``.
    Otherwise (Replicate / OpenAI keyframes) it answers ``200`` with the finished video.
    """

    permission_classes = [IsClientUser]
    throttle_scope = "ai_tryon_session"
    throttle_classes = [*APIView.throttle_classes, ScopedRateThrottle]

    @extend_schema(
        summary="Kamera videosi ustida kiyimni AI bilan kiyib ko'rish (MP4 video)",
        tags=["virtual-tryon"],
        request={"multipart/form-data": AiRenderVideoRequestSerializer},
        responses={200: OpenApiTypes.OBJECT, 202: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        body = AiRenderVideoRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        garment = get_object_or_404(
            visible_garments().exclude(ai_reference_image=""),
            pk=body.validated_data["garment"],
        )

        log = quota.reserve(request.user, RenderKind.VIDEO)
        if fal_tryon.is_configured():
            try:
                job = video_jobs.start(user=request.user, video_upload=body.validated_data["video"], garment=garment)
            except openai_tryon.OpenAITryOnError as exc:
                quota.refund(log)
                raise _provider_error(exc) from None
            except Exception:
                quota.refund(log)
                raise
            log.ref = job.request_id
            log.save(update_fields=["ref", "updated_at"])
            return Response(_video_job_payload(request, job), status=status.HTTP_202_ACCEPTED)

        try:
            result = video_tryon.render_video_tryon(
                video_upload=body.validated_data["video"],
                garment=garment,
            )
        except openai_tryon.OpenAITryOnError as exc:
            quota.refund(log)
            raise _provider_error(exc) from None
        except Exception:
            quota.refund(log)
            raise
        quota.done(log, result.model)

        look = SavedLook(
            user=request.user,
            garment=garment,
            width=result.width,
            height=result.height,
        )
        look.image.save(f"tryon-{garment.pk}.jpg", ContentFile(result.poster_bytes), save=False)
        look.video.save(f"tryon-{garment.pk}.mp4", ContentFile(result.video_bytes), save=False)
        look.save()
        drive_sync.upload_look_to_drive(look)
        return Response(
            _video_look_payload(request, look, model=result.model, latency_ms=result.latency_ms, frames=result.frames)
        )


class AiRenderVideoJobView(APIView):
    """Status of a background video try-on; returns the finished video once it is ready."""

    permission_classes = [IsClientUser]

    @extend_schema(
        summary="AI video tayyorlanish holati (PENDING / FINALIZING / DONE / FAILED)",
        tags=["virtual-tryon"],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, job_id):
        job = get_object_or_404(VideoTryOnJob.objects.select_related("look"), pk=job_id, user=request.user)
        job = video_jobs.advance(job)
        return Response(_video_job_payload(request, job))


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
        return SavedLook.objects.filter(user=self.request.user, hidden_by_user=False).select_related("garment")

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
        if (
            SavedLook.objects.filter(user=request.user, hidden_by_user=False).count()
            >= settings.AI_TRYON["MAX_SAVED_LOOKS_PER_USER"]
        ):
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
        drive_sync.upload_look_to_drive(look)
        return Response(SavedLookSerializer(look, context={"request": request}).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, look):
        look.hidden_by_user = True
        look.save(update_fields=["hidden_by_user", "updated_at"])

    @extend_schema(
        summary="Saqlangan obraz rasmi (faqat egasi)",
        tags=["virtual-tryon"],
        responses={(200, "image/webp"): OpenApiTypes.BINARY},
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
        summary="Saqlangan AI video (faqat egasi)",
        tags=["virtual-tryon"],
        responses={(200, "video/mp4"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="video", url_name="video")
    def video(self, request, pk=None):
        look = self.get_object()
        if not look.video:
            return Response({"detail": "Video mavjud emas."}, status=status.HTTP_404_NOT_FOUND)
        return serve_mp4_range(request, look.video)

    @extend_schema(
        summary="Obrazni yuklab olish (Premium: logosiz, oddiy: MarosimGo logosi bilan)",
        tags=["virtual-tryon"],
        responses={(200, "image/jpeg"): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="download", url_name="download")
    def download(self, request, pk=None):
        look = self.get_object()
        if look.video:
            response = FileResponse(look.video.open("rb"), content_type="video/mp4")
            response["Content-Disposition"] = f'attachment; filename="marosimgo-tryon-{str(look.pk)[:8]}.mp4"'
            response["Cache-Control"] = "private, no-store"
            return response
        with look.image.open("rb") as fh:
            raw = fh.read()
        premium = watermark.is_premium_user(request.user)
        payload = raw if premium else watermark.apply_marosimgo_watermark(raw)
        name = (look.image.name or "").lower()
        ctype = "image/webp" if (premium and name.endswith(".webp")) else "image/jpeg"
        ext = "webp" if ctype == "image/webp" else "jpg"
        response = HttpResponse(payload, content_type=ctype)
        response["Content-Disposition"] = f'attachment; filename="marosimgo-look-{str(look.pk)[:8]}.{ext}"'
        response["Cache-Control"] = "private, no-store"
        response["X-MarosimGo-Watermarked"] = "false" if premium else "true"
        return response


@extend_schema_view(
    list=extend_schema(summary="Mening kiyim buyurtmalarim", tags=["virtual-tryon"]),
    retrieve=extend_schema(summary="Buyurtma tafsilotlari", tags=["virtual-tryon"]),
)
class GarmentOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """User garment orders placed after virtual try-on."""

    permission_classes = [IsClientUser]
    serializer_class = GarmentOrderSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {"*": AccessNote(ownership="Faqat o'z buyurtmalari (boshqalarniki 404).")}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GarmentOrder.objects.none()
        return GarmentOrder.objects.filter(user=self.request.user).select_related("garment", "garment__category")

    @extend_schema(
        summary="Kiyim sotib olish (buyurtma berish)",
        tags=["virtual-tryon"],
        request=GarmentOrderCreateSerializer,
        responses={201: GarmentOrderSerializer},
    )
    def create(self, request):
        body = GarmentOrderCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        garment = get_object_or_404(visible_garments(), pk=data["garment"])
        look = (
            SavedLook.objects.filter(user=request.user, pk=data["look"]).first()
            if data.get("look")
            else None
        )
        qty = data["quantity"]
        unit_price = garment.price
        order = GarmentOrder.objects.create(
            user=request.user,
            garment=garment,
            look=look,
            size=data["size"].strip(),
            color=(data.get("color") or "").strip(),
            quantity=qty,
            unit_price=unit_price,
            total_price=unit_price * qty,
            currency=garment.currency,
            customer_name=data["customer_name"].strip(),
            customer_phone=data["customer_phone"].strip(),
            delivery_type=data["delivery_type"],
            delivery_address=(data.get("delivery_address") or "").strip(),
            payment_method=data["payment_method"],
            notes=(data.get("notes") or "").strip(),
        )
        return Response(
            GarmentOrderSerializer(order, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
