"""AI event planner API for USER accounts (frontend-user) — ``/api/v1/ai-planner/…``.

Every queryset is scoped to ``request.user``: a known id of someone else's plan, item, conversation or
message is a 404. The AI part can be unavailable (switched off, maintenance, no key, provider error)
while plans, items and the calculator keep working. Booking stays in ``me/venue-bookings`` — this API
only reads availability and never creates a booking.
"""

import datetime
from decimal import Decimal

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.access import AccessNote
from apps.audit.services import AuditAction, record
from apps.ceremonies.permissions import IsClientUser
from apps.core.pagination import StandardPagination
from apps.venues.models import Region

from . import assistant, catalog, services
from .models import (
    FEATURE_FLAGS,
    AIConfiguration,
    AIConversation,
    AIMessage,
    AIReport,
    AIUsageLog,
    BudgetCategory,
    BudgetItem,
    ConversationStatus,
    EventPlan,
    MessageRole,
    PlanStatus,
    SourceKind,
    UsageStatus,
)
from .serializers import (
    AIMessageSerializer,
    BudgetItemSerializer,
    BudgetItemWriteSerializer,
    ConfirmPlanSerializer,
    ConfirmResultSerializer,
    ConversationSerializer,
    ConversationWriteSerializer,
    DeleteDataSerializer,
    EventPlanSerializer,
    EventPlanWriteSerializer,
    FeedbackSerializer,
    MyReportSerializer,
    ReportCreateSerializer,
    SendMessageSerializer,
    SendResultSerializer,
)

UUID_RE = "[0-9a-fA-F-]{36}"
TAG = "ai-planner"
OWN_PLANS = "Faqat o'z rejalari (boshqalarniki 404)."
OWN_ITEMS = "Faqat o'z rejasining bandlari (boshqa reja / band id si 404)."
OWN_CHATS = "Faqat o'z suhbatlari va xabarlari (boshqalarniki 404)."
NO_BOOKING = "Hech qachon bron yaratmaydi — bron faqat me/venue-bookings orqali, foydalanuvchi tasdig'i bilan."
PUBLIC_DATA = "Faqat ommaviy (tasdiqlangan, faol) to'yxona zallari va studiyalar; narx va bandlik serverdan."


class PlannerThrottleMixin:
    """Writes get their own budget on top of the global user rate; sending a chat message an even tighter one."""

    message_actions = ("messages",)

    def get_throttles(self):
        if self.request.method in SAFE_METHODS:
            return super().get_throttles()
        action_name = getattr(self, "action", None)
        self.throttle_scope = "ai_planner_message" if action_name in self.message_actions else "ai_planner_write"
        return [*super().get_throttles(), ScopedRateThrottle()]


def _date_param(value) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValidationError({"date": ["Sana YYYY-MM-DD formatida bo'lishi kerak."]}) from None


def _int_param(value, field: str, *, low: int = 1, high: int = 10_000) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except ValueError:
        raise ValidationError({field: ["Butun son bo'lishi kerak."]}) from None
    if not low <= number <= high:
        raise ValidationError({field: [f"{low}–{high} oralig'ida bo'lishi kerak."]})
    return number


# --------------------------------------------------------------------- status
class PlannerStatusView(APIView):
    permission_classes = [IsClientUser]
    access_notes = {"*": AccessNote(ownership="Faqat o'z limitlari.")}

    @extend_schema(summary="AI maslahatchi holati va bugungi limit", tags=[TAG], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        cfg = AIConfiguration.load()
        reason = assistant.availability(cfg)
        used = assistant.usage_today(request.user)
        limited = assistant.limit_error(cfg, request.user) if reason is None else None
        return Response(
            {
                "available": reason is None and limited is None,
                "reason": reason or limited,
                "message": (
                    (cfg.maintenance_message if reason == "ai_maintenance" and cfg.maintenance_message else None)
                    or (assistant.providers.ERRORS.get(reason, (None,))[0] if reason else None)
                    or (assistant.LIMIT_MESSAGES.get(limited) if limited else None)
                ),
                "features": {name: cfg.enabled and cfg.flag(name) for name in FEATURE_FLAGS},
                "messages_today": used["mine"],
                "daily_limit": cfg.daily_messages_per_user or None,
                "max_input_chars": cfg.max_input_chars,
            }
        )


class MyUsageView(APIView):
    permission_classes = [IsClientUser]
    access_notes = {"*": AccessNote(ownership="Faqat o'z AI sarfi.")}

    @extend_schema(summary="Mening AI sarfim (oxirgi 30 kun)", tags=[TAG], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        since = assistant._day_start(assistant.timezone.now()) - datetime.timedelta(days=29)
        rows = AIUsageLog.objects.filter(user=request.user, created_at__gte=since).exclude(status=UsageStatus.BLOCKED)
        per_day: dict = {}
        tokens_in = tokens_out = 0
        reported = False
        for row in rows:
            day = assistant.timezone.localtime(row.created_at).date().isoformat()
            per_day[day] = per_day.get(day, 0) + 1
            if row.input_tokens is not None:
                reported = True
                tokens_in += row.input_tokens or 0
                tokens_out += row.output_tokens or 0
        cfg = AIConfiguration.load()
        return Response(
            {
                "messages_today": assistant.usage_today(request.user)["mine"],
                "daily_limit": cfg.daily_messages_per_user or None,
                "messages_30_days": sum(per_day.values()),
                "per_day": [{"date": d, "messages": n} for d, n in sorted(per_day.items())],
                "tokens": {"input": tokens_in, "output": tokens_out} if reported else None,
            }
        )


class ExportView(APIView):
    permission_classes = [IsClientUser]
    access_notes = {"*": AccessNote(ownership="Faqat o'z rejalari va suhbatlari.")}

    @extend_schema(
        summary="Mening AI rejalashtiruvchi ma'lumotlarim (JSON eksport)", tags=[TAG], responses=OpenApiTypes.OBJECT
    )
    def get(self, request):
        response = Response(services.export_user_data(request.user))
        response["Content-Disposition"] = 'attachment; filename="marosimgo-ai-reja.json"'
        return response


class DeleteDataView(PlannerThrottleMixin, APIView):
    permission_classes = [IsClientUser]
    access_notes = {
        "*": AccessNote(
            ownership="Faqat o'z ma'lumotlari.",
            conditions=('confirm="DELETE" majburiy; bronlar va to\'lovlarga tegmaydi.',),
        )
    }

    @extend_schema(
        summary="AI rejalashtiruvchi ma'lumotlarimni o'chirish",
        tags=[TAG],
        request=DeleteDataSerializer,
        responses=OpenApiTypes.OBJECT,
    )
    def post(self, request):
        DeleteDataSerializer(data=request.data).is_valid(raise_exception=True)
        counts = services.delete_user_data(request.user)
        record(request, AuditAction.AI_DATA_DELETE, request.user, changes=counts)
        return Response({"deleted": counts})


# ---------------------------------------------------------------------- plans
@extend_schema_view(
    list=extend_schema(
        summary="Mening rejalarim", tags=[TAG], parameters=[OpenApiParameter("status", str, enum=PlanStatus.values)]
    ),
    retrieve=extend_schema(summary="Reja", tags=[TAG]),
    create=extend_schema(
        summary="Reja yaratish", tags=[TAG], request=EventPlanWriteSerializer, responses={201: EventPlanSerializer}
    ),
    partial_update=extend_schema(
        summary="Rejani tahrirlash (byudjet qayta hisoblanadi)",
        tags=[TAG],
        request=EventPlanWriteSerializer,
        responses=EventPlanSerializer,
    ),
    destroy=extend_schema(summary="Rejani o'chirish", tags=[TAG]),
)
class PlanViewSet(
    PlannerThrottleMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsClientUser]
    serializer_class = EventPlanSerializer
    queryset = EventPlan.objects.none()
    lookup_value_regex = UUID_RE
    filter_backends = []
    http_method_names = ["get", "post", "patch", "delete"]
    access_notes = {"*": AccessNote(ownership=OWN_PLANS)}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return EventPlan.objects.none()
        qs = services.user_plans(self.request.user).prefetch_related("items")
        wanted = self.request.query_params.get("status")
        if self.action == "list" and wanted in PlanStatus.values:
            qs = qs.filter(status=wanted)
        return qs.order_by("-updated_at")

    def create(self, request, *args, **kwargs):
        body = EventPlanWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        plan, created = services.create_plan(request.user, data, data.pop("client_request_id", None))
        plan = self.get_queryset().get(pk=plan.pk)
        return Response(
            EventPlanSerializer(plan).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    def partial_update(self, request, *args, **kwargs):
        plan = self.get_object()
        body = EventPlanWriteSerializer(plan, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        data.pop("client_request_id", None)
        services.update_plan(plan, data)
        return Response(EventPlanSerializer(self.get_queryset().get(pk=plan.pk)).data)

    def update(self, request, *args, **kwargs):  # PUT is not offered (http_method_names)
        return self.partial_update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        services.soft_delete_plan(instance)

    def _set_status(self, value):
        plan = self.get_object()
        services.update_plan(plan, {"status": value})
        return Response(EventPlanSerializer(self.get_queryset().get(pk=plan.pk)).data)

    @extend_schema(summary="Rejani arxivlash", tags=[TAG], request=None, responses=EventPlanSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._set_status(PlanStatus.ARCHIVED)

    @extend_schema(summary="Rejani arxivdan qaytarish", tags=[TAG], request=None, responses=EventPlanSerializer)
    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        return self._set_status(PlanStatus.DRAFT)

    @extend_schema(
        summary="Rejadan nusxa olish (platforma narxlari qayta o'qiladi)",
        tags=[TAG],
        request=None,
        responses={201: EventPlanSerializer},
    )
    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        copy = services.duplicate_plan(self.get_object())
        return Response(EventPlanSerializer(self.get_queryset().get(pk=copy.pk)).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Byudjet hisobi (server kalkulyatori, Decimal, UZS)", tags=[TAG], responses=OpenApiTypes.OBJECT
    )
    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        return Response(services.summary(self.get_object()))

    @extend_schema(
        summary="Reja uchun platformadagi real xizmatlar (narx, hudud, reyting, bandlik)",
        tags=[TAG],
        parameters=[
            OpenApiParameter("category", str, enum=[BudgetCategory.VENUE, BudgetCategory.PHOTO_VIDEO]),
            OpenApiParameter("sort", str, enum=list(catalog.SORTS)),
            OpenApiParameter("q", str),
        ],
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=True, methods=["get"])
    def recommendations(self, request, pk=None):
        plan = self.get_object()
        cfg = AIConfiguration.load()
        category = request.query_params.get("category", BudgetCategory.VENUE)
        q = request.query_params.get("q", "").strip()[:100]
        in_plan = set(plan.items.exclude(source_reference="").values_list("source_reference", flat=True))
        if category == BudgetCategory.VENUE:
            rows = catalog.search_halls(
                region=plan.region,
                guests=plan.guest_count,
                date=plan.event_date,
                q=q,
                sort=request.query_params.get("sort", "price"),
            )
        elif category == BudgetCategory.PHOTO_VIDEO:
            rows = catalog.search_studios(q=q, date=plan.event_date)
        else:
            rows = []
        for row in rows:
            row["in_plan"] = row["id"] in in_plan
            row["over_budget"] = bool(
                plan.total_budget and row.get("price") and Decimal(row["price"]) > plan.total_budget
            )
        return Response(
            {
                "category": category,
                "results": rows,
                "date_known": plan.event_date is not None and not plan.date_is_approximate,
                "booking_handoff": cfg.enabled and cfg.flag("booking_handoff"),
                "booking_event_type": services_booking_type(plan),
                "note": None if rows else "Platformada bu toifa yoki shartlar bo'yicha xizmat topilmadi.",
            }
        )


def services_booking_type(plan: EventPlan) -> str:
    from .models import BOOKING_EVENT_TYPE

    return BOOKING_EVENT_TYPE.get(plan.event_type, "OTHER")


@extend_schema_view(
    list=extend_schema(summary="Reja bandlari", tags=[TAG]),
    retrieve=extend_schema(summary="Byudjet bandi", tags=[TAG]),
    create=extend_schema(
        summary="Band qo'shish (jami serverda hisoblanadi)",
        tags=[TAG],
        request=BudgetItemWriteSerializer,
        responses={201: BudgetItemSerializer},
    ),
    partial_update=extend_schema(
        summary="Bandni tahrirlash", tags=[TAG], request=BudgetItemWriteSerializer, responses=BudgetItemSerializer
    ),
    destroy=extend_schema(summary="Bandni o'chirish", tags=[TAG]),
)
class PlanItemViewSet(
    PlannerThrottleMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsClientUser]
    serializer_class = BudgetItemSerializer
    queryset = BudgetItem.objects.none()
    lookup_value_regex = UUID_RE
    filter_backends = []
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]
    access_notes = {
        "*": AccessNote(ownership=OWN_ITEMS),
        "create": AccessNote(
            conditions=(
                "Platforma zali narxi bazadan olinadi (VERIFIED); mijoz VERIFIED belgilay olmaydi.",
                "To'yxona paketiga kirgan toifa qayta qo'shilmaydi (400 included_in_package).",
                "Bitta xizmat rejada bir marta (409 duplicate_service).",
            )
        ),
    }

    def _plan(self) -> EventPlan:
        return get_object_or_404(services.user_plans(self.request.user), pk=self.kwargs["plan_id"])

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BudgetItem.objects.none()
        return BudgetItem.objects.filter(plan=self._plan())

    def create(self, request, *args, **kwargs):
        plan = self._plan()
        body = BudgetItemWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        key = data.pop("client_request_id", None)
        if key:
            existing = plan.items.filter(client_request_id=key).first()
            if existing is not None:
                return Response(BudgetItemSerializer(existing).data, status=status.HTTP_200_OK)
        data.setdefault("position", plan.items.count())
        item = services.apply_item(plan, BudgetItem(plan=plan, client_request_id=key), data)
        return Response(BudgetItemSerializer(item).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        item = self.get_object()
        body = BudgetItemWriteSerializer(item, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        data.pop("client_request_id", None)
        item = services.apply_item(item.plan, item, data)
        return Response(BudgetItemSerializer(item).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        plan = instance.plan
        instance.delete()
        plan.save(update_fields=["updated_at"])


# ----------------------------------------------------------------------- chat
@extend_schema_view(
    list=extend_schema(
        summary="Mening AI suhbatlarim",
        tags=[TAG],
        parameters=[OpenApiParameter("status", str, enum=ConversationStatus.values)],
    ),
    retrieve=extend_schema(summary="AI suhbati", tags=[TAG]),
    create=extend_schema(
        summary="Yangi AI suhbati",
        tags=[TAG],
        request=ConversationWriteSerializer,
        responses={201: ConversationSerializer},
    ),
    partial_update=extend_schema(
        summary="Suhbat nomi / rejaga bog'lash",
        tags=[TAG],
        request=ConversationWriteSerializer,
        responses=ConversationSerializer,
    ),
    destroy=extend_schema(summary="Suhbatni o'chirish", tags=[TAG]),
)
class ConversationViewSet(
    PlannerThrottleMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsClientUser]
    serializer_class = ConversationSerializer
    queryset = AIConversation.objects.none()
    lookup_value_regex = UUID_RE
    filter_backends = []
    http_method_names = ["get", "post", "patch", "delete"]
    access_notes = {
        "*": AccessNote(ownership=OWN_CHATS),
        "messages": AccessNote(
            conditions=(
                "Bir xil client_request_id bilan qayta yuborish takror xabar yaratmaydi (retry).",
                "AI o'chirilgan / sozlanmagan bo'lsa 503; kunlik limit 429.",
                NO_BOOKING,
            )
        ),
        "confirm_plan": AccessNote(
            conditions=("Faqat o'z suhbatidagi AI javobi; qayta tasdiqlash o'sha rejani qaytaradi.", NO_BOOKING)
        ),
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIConversation.objects.none()
        qs = services.user_conversations(self.request.user).select_related("event_plan")
        wanted = self.request.query_params.get("status")
        if self.action == "list" and wanted in ConversationStatus.values:
            qs = qs.filter(status=wanted)
        return qs.order_by("-updated_at")

    def _own_plan(self, plan_id):
        if plan_id is None:
            return None
        plan = services.user_plans(self.request.user).filter(pk=plan_id).first()
        if plan is None:
            raise ValidationError({"event_plan": ["Reja topilmadi."]})
        return plan

    def create(self, request, *args, **kwargs):
        body = ConversationWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        conversation = AIConversation.objects.create(
            user=request.user,
            title=body.validated_data.get("title", ""),
            event_plan=self._own_plan(body.validated_data.get("event_plan")),
        )
        return Response(ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        conversation = self.get_object()
        body = ConversationWriteSerializer(conversation, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        if "title" in body.validated_data:
            conversation.title = body.validated_data["title"]
        if "event_plan" in body.validated_data:
            conversation.event_plan = self._own_plan(body.validated_data["event_plan"])
        conversation.save()
        return Response(ConversationSerializer(conversation).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def _set_status(self, value):
        conversation = self.get_object()
        conversation.status = value
        conversation.save(update_fields=["status", "updated_at"])
        return Response(ConversationSerializer(conversation).data)

    @extend_schema(summary="Suhbatni arxivlash", tags=[TAG], request=None, responses=ConversationSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._set_status(ConversationStatus.ARCHIVED)

    @extend_schema(summary="Suhbatni arxivdan qaytarish", tags=[TAG], request=None, responses=ConversationSerializer)
    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        return self._set_status(ConversationStatus.ACTIVE)

    @extend_schema(
        methods=["get"],
        summary="Suhbat xabarlari (eng yangilari birinchi, sahifalab)",
        tags=[TAG],
        responses=AIMessageSerializer(many=True),
    )
    @extend_schema(
        methods=["post"],
        summary="AI maslahatchiga xabar yuborish (retry: o'sha client_request_id)",
        tags=[TAG],
        request=SendMessageSerializer,
        responses={201: SendResultSerializer, 200: SendResultSerializer},
    )
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        if request.method == "GET":
            qs = conversation.messages.exclude(role__in=[MessageRole.SYSTEM, MessageRole.TOOL]).order_by("-created_at")
            paginator = StandardPagination()
            page = paginator.paginate_queryset(qs, request, view=self)
            return paginator.get_paginated_response(AIMessageSerializer(page, many=True).data)
        if conversation.status == ConversationStatus.ARCHIVED:
            raise services.PlannerError("conversation_archived", "Arxivdagi suhbatga yozib bo'lmaydi.")
        body = SendMessageSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user_msg, reply, replayed = assistant.send(
            request.user, conversation, body.validated_data["content"], body.validated_data["client_request_id"]
        )
        return Response(
            {
                "user_message": AIMessageSerializer(user_msg).data,
                "assistant_message": AIMessageSerializer(reply).data,
                "replayed": replayed,
            },
            status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="AI taklifini reja sifatida saqlash (faqat foydalanuvchi tasdig'i bilan)",
        tags=[TAG],
        request=ConfirmPlanSerializer,
        responses=ConfirmResultSerializer,
    )
    @action(detail=True, methods=["post"], url_path="confirm-plan")
    def confirm_plan(self, request, pk=None):
        conversation = self.get_object()
        body = ConfirmPlanSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        message = get_object_or_404(conversation.messages, pk=body.validated_data["message"])
        plan, notes, created = services.confirm_proposal(request.user, conversation, message)
        if created:
            record(request, AuditAction.AI_PLAN_CONFIRM, plan, changes={"message": str(message.pk), "notes": notes})
        plan = services.user_plans(request.user).prefetch_related("items").get(pk=plan.pk)
        return Response({"plan": EventPlanSerializer(plan).data, "created": created, "notes": notes})


class MessageViewSet(PlannerThrottleMixin, viewsets.GenericViewSet):
    """Feedback / report on one assistant message of the caller's own conversation."""

    permission_classes = [IsClientUser]
    queryset = AIMessage.objects.none()
    serializer_class = AIMessageSerializer
    lookup_value_regex = UUID_RE
    filter_backends = []
    access_notes = {"*": AccessNote(ownership="Faqat o'z suhbatidagi AI javoblari (boshqalarniki 404).")}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AIMessage.objects.none()
        return AIMessage.objects.filter(conversation__user=self.request.user, role=MessageRole.ASSISTANT)

    @extend_schema(
        summary="AI javobiga baho (foydali / foydasiz)",
        tags=[TAG],
        request=FeedbackSerializer,
        responses=AIMessageSerializer,
    )
    @action(detail=True, methods=["post"])
    def feedback(self, request, pk=None):
        message = self.get_object()
        body = FeedbackSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        message.feedback = body.validated_data["value"]
        message.save(update_fields=["feedback", "updated_at"])
        return Response(AIMessageSerializer(message).data)

    @extend_schema(
        summary="AI javobi ustidan shikoyat",
        tags=[TAG],
        request=ReportCreateSerializer,
        responses={201: MyReportSerializer, 200: MyReportSerializer},
    )
    @action(detail=True, methods=["post"])
    def report(self, request, pk=None):
        message = self.get_object()
        body = ReportCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        report, created = AIReport.objects.get_or_create(
            reporter=request.user, message=message, defaults=body.validated_data
        )
        return Response(
            MyReportSerializer(report).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


# -------------------------------------------------------------------- catalog
class ServiceViewSet(viewsets.GenericViewSet):
    permission_classes = [IsClientUser]
    queryset = EventPlan.objects.none()
    filter_backends = []
    pagination_class = None
    access_notes = {"*": AccessNote(conditions=(PUBLIC_DATA,))}

    @extend_schema(
        summary="Platformadagi xizmatlarni qidirish (to'yxona zallari / studiyalar)",
        tags=[TAG],
        parameters=[
            OpenApiParameter("kind", str, enum=[SourceKind.VENUE_HALL, SourceKind.STUDIO]),
            OpenApiParameter("region", str, enum=Region.values),
            OpenApiParameter("guests", int),
            OpenApiParameter("date", OpenApiTypes.DATE),
            OpenApiParameter("budget_max", int),
            OpenApiParameter("q", str),
            OpenApiParameter("sort", str, enum=list(catalog.SORTS)),
        ],
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["get"])
    def search(self, request):
        p = request.query_params
        date = _date_param(p.get("date"))
        q = p.get("q", "").strip()[:100]
        if p.get("kind") == SourceKind.STUDIO:
            rows = catalog.search_studios(q=q, date=date)
        else:
            rows = catalog.search_halls(
                region=p.get("region", ""),
                guests=_int_param(p.get("guests"), "guests"),
                date=date,
                budget_max=_int_param(p.get("budget_max"), "budget_max", low=0, high=10**11),
                q=q,
                sort=p.get("sort", "price"),
            )
        return Response({"results": rows})

    @extend_schema(
        summary="Tanlangan xizmatlarni solishtirish (ko'pi bilan 6 ta)",
        tags=[TAG],
        parameters=[
            OpenApiParameter("ids", str, required=True, description="Vergul bilan ajratilgan id lar"),
            OpenApiParameter("date", OpenApiTypes.DATE),
        ],
        responses=OpenApiTypes.OBJECT,
    )
    @action(detail=False, methods=["get"])
    def compare(self, request):
        ids = [i.strip() for i in request.query_params.get("ids", "").split(",") if i.strip()]
        return Response({"results": catalog.compare(ids, date=_date_param(request.query_params.get("date")))})
