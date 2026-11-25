import datetime
import re
from decimal import Decimal

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.venues.models import MONEY

from . import calculator
from .models import (
    CLIENT_PRICE_STATUSES,
    CLIENT_SOURCE_TYPES,
    DISABLE_SCOPES,
    ITEM_CATEGORIES,
    MAX_GUESTS,
    PACKAGE_CATEGORIES,
    AIConfiguration,
    AIConversation,
    AIMessage,
    AIReport,
    AIUsageLog,
    BudgetItem,
    EventPlan,
    Feedback,
    PromptVersion,
    ReportReason,
    ReportStatus,
    SourceKind,
    SourceType,
)

MAX_MONEY = Decimal("100000000000")
MAX_QUANTITY = Decimal("100000")
MAX_YEARS_AHEAD = 5


def _money_field(**extra):
    return serializers.DecimalField(
        **MONEY, min_value=Decimal("0"), max_value=MAX_MONEY, coerce_to_string=True, **extra
    )


# ----------------------------------------------------------------------- plans
class EventPlanSerializer(serializers.ModelSerializer):
    total_budget = _money_field(allow_null=True, read_only=True)
    reserve_percent = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    item_count = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()

    class Meta:
        model = EventPlan
        fields = [
            "id",
            "title",
            "event_type",
            "event_date",
            "date_is_approximate",
            "approximate_date",
            "region",
            "district",
            "guest_count",
            "total_budget",
            "currency",
            "budget_flexibility",
            "style",
            "priorities",
            "wishes",
            "notes",
            "status",
            "reserve_percent",
            "source",
            "item_count",
            "totals",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_item_count(self, obj) -> int:
        return len(obj.items.all())

    @extend_schema_field(
        {
            "type": "object",
            "properties": {
                "total_min": {"type": "string"},
                "total_max": {"type": "string"},
                "status": {"type": "string"},
            },
        }
    )
    def get_totals(self, obj) -> dict:
        lines = [calculator.Line.of(i) for i in obj.items.all()]
        data = calculator.summarize(
            lines, guest_count=obj.guest_count, total_budget=obj.total_budget, reserve_percent=obj.reserve_percent
        )
        return {"total_min": data["total_min"], "total_max": data["total_max"], "status": data["status"]}


class EventPlanWriteSerializer(serializers.ModelSerializer):
    total_budget = _money_field(allow_null=True, required=False)
    guest_count = serializers.IntegerField(min_value=1, max_value=MAX_GUESTS, allow_null=True, required=False)
    reserve_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("30"), required=False
    )
    priorities = serializers.ListField(
        child=serializers.ChoiceField(choices=ITEM_CATEGORIES), required=False, max_length=len(ITEM_CATEGORIES)
    )
    client_request_id = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = EventPlan
        fields = [
            "title",
            "event_type",
            "event_date",
            "date_is_approximate",
            "approximate_date",
            "region",
            "district",
            "guest_count",
            "total_budget",
            "budget_flexibility",
            "style",
            "priorities",
            "wishes",
            "notes",
            "status",
            "reserve_percent",
            "client_request_id",
        ]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Reja nomini kiriting.")
        return value

    def validate_event_date(self, value):
        if value and value > timezone.localdate() + datetime.timedelta(days=365 * MAX_YEARS_AHEAD):
            raise serializers.ValidationError(f"Sana {MAX_YEARS_AHEAD} yildan uzoq bo'lmasligi kerak.")
        return value

    def validate_priorities(self, value):
        return [c for c in ITEM_CATEGORIES if c in set(value)]


# ----------------------------------------------------------------------- items
class BudgetItemSerializer(serializers.ModelSerializer):
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    unit_price = _money_field(read_only=True)
    unit_price_max = _money_field(read_only=True, allow_null=True)
    total_price = _money_field(read_only=True)
    total_price_max = _money_field(read_only=True)
    actual_amount = _money_field(read_only=True, allow_null=True)

    class Meta:
        model = BudgetItem
        fields = [
            "id",
            "category",
            "title",
            "quantity",
            "unit",
            "per_guest",
            "unit_price",
            "unit_price_max",
            "total_price",
            "total_price_max",
            "currency",
            "source_type",
            "source_kind",
            "source_reference",
            "price_status",
            "price_checked_at",
            "notes",
            "is_included_in_package",
            "package_includes",
            "actual_amount",
            "is_active",
            "position",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class BudgetItemWriteSerializer(serializers.ModelSerializer):
    category = serializers.ChoiceField(choices=ITEM_CATEGORIES, required=False)
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), max_value=MAX_QUANTITY, required=False
    )
    unit_price = _money_field(required=False)
    unit_price_max = _money_field(required=False, allow_null=True)
    actual_amount = _money_field(required=False, allow_null=True)
    source_type = serializers.ChoiceField(choices=CLIENT_SOURCE_TYPES, required=False)
    source_kind = serializers.ChoiceField(choices=SourceKind.choices, required=False, allow_blank=True)
    price_status = serializers.ChoiceField(choices=CLIENT_PRICE_STATUSES, required=False)
    package_includes = serializers.ListField(
        child=serializers.ChoiceField(choices=PACKAGE_CATEGORIES),
        required=False,
        max_length=len(ITEM_CATEGORIES),
    )
    client_request_id = serializers.UUIDField(required=False, write_only=True)

    class Meta:
        model = BudgetItem
        fields = [
            "category",
            "title",
            "quantity",
            "unit",
            "per_guest",
            "unit_price",
            "unit_price_max",
            "source_type",
            "source_kind",
            "source_reference",
            "price_status",
            "notes",
            "is_included_in_package",
            "package_includes",
            "actual_amount",
            "is_active",
            "position",
            "client_request_id",
        ]
        extra_kwargs = {"title": {"required": False, "allow_blank": True}}

    def validate_title(self, value):
        return value.strip()

    def validate(self, attrs):
        creating = self.instance is None
        source = attrs.get("source_type", getattr(self.instance, "source_type", SourceType.MANUAL))
        if creating and source != SourceType.PLATFORM_SERVICE:
            if not attrs.get("category"):
                raise serializers.ValidationError({"category": ["Toifani tanlang."]})
            if not attrs.get("title"):
                raise serializers.ValidationError({"title": ["Nomini kiriting."]})
        if source == SourceType.PLATFORM_SERVICE and creating and not attrs.get("source_reference"):
            raise serializers.ValidationError({"source_reference": ["Platformadagi xizmatni tanlang."]})
        low = attrs.get("unit_price", getattr(self.instance, "unit_price", Decimal("0")))
        high = attrs.get("unit_price_max", getattr(self.instance, "unit_price_max", None))
        if high is not None and low is not None and high < low:
            raise serializers.ValidationError(
                {"unit_price_max": ["Yuqori narx pastki narxdan kichik bo'lmasligi kerak."]}
            )
        return attrs


# ------------------------------------------------------------------------ chat
class ConversationSerializer(serializers.ModelSerializer):
    event_plan_title = serializers.CharField(source="event_plan.title", read_only=True, default=None)

    class Meta:
        model = AIConversation
        fields = [
            "id",
            "title",
            "status",
            "event_plan",
            "event_plan_title",
            "last_message_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ConversationWriteSerializer(serializers.ModelSerializer):
    event_plan = serializers.UUIDField(required=False, allow_null=True)

    class Meta:
        model = AIConversation
        fields = ["title", "event_plan"]

    def validate_title(self, value):
        return value.strip()


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = [
            "id",
            "role",
            "content",
            "structured_data",
            "status",
            "error_code",
            "feedback",
            "reply_to",
            "model_name",
            "token_usage",
            "client_request_id",
            "created_at",
        ]
        read_only_fields = fields


class SendMessageSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=8000, trim_whitespace=True, allow_blank=False)
    client_request_id = serializers.UUIDField()


class SendResultSerializer(serializers.Serializer):
    user_message = AIMessageSerializer()
    assistant_message = AIMessageSerializer()
    replayed = serializers.BooleanField()


class ConfirmPlanSerializer(serializers.Serializer):
    message = serializers.UUIDField()


class ConfirmResultSerializer(serializers.Serializer):
    plan = EventPlanSerializer()
    created = serializers.BooleanField()
    notes = serializers.ListField(child=serializers.CharField())


class FeedbackSerializer(serializers.Serializer):
    value = serializers.ChoiceField(choices=Feedback.choices, allow_blank=True)


class ReportCreateSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReportReason.choices)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class MyReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIReport
        fields = ["id", "message", "reason", "description", "status", "resolution", "created_at"]
        read_only_fields = fields


class ConfirmSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()

    def validate_confirm(self, value):
        if value is not True:
            raise serializers.ValidationError("Amalni tasdiqlang (confirm=true).")
        return value


class DeleteDataSerializer(serializers.Serializer):
    confirm = serializers.CharField()

    def validate_confirm(self, value):
        if value != "DELETE":
            raise serializers.ValidationError('Tasdiqlash uchun "DELETE" deb yozing.')
        return value


# ----------------------------------------------------------------------- admin
_PHONE = re.compile(r"\+?\d[\d\s()-]{7,}\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_pii(text: str) -> str:
    """Phone numbers and emails are hidden from staff readers (card data never reaches storage at all)."""
    return _EMAIL.sub("[email yashirildi]", _PHONE.sub("[telefon yashirildi]", text or ""))


def masked_user(user) -> dict | None:
    if user is None:
        return None
    phone = user.phone_number or ""
    return {
        "id": str(user.pk),
        "label": f"Foydalanuvchi {str(user.pk)[:8]}",
        "phone_masked": f"+998 ** *** ** {phone[-2:]}" if len(phone) >= 4 else None,
    }


@extend_schema_field(OpenApiTypes.OBJECT)
class MaskedUserField(serializers.Field):
    def to_representation(self, value):
        return masked_user(value)


class AdminReportSerializer(serializers.ModelSerializer):
    reporter = serializers.SerializerMethodField()
    message_excerpt = serializers.SerializerMethodField()
    conversation = serializers.UUIDField(source="message.conversation_id", read_only=True)
    assigned_admin_label = serializers.SerializerMethodField()

    class Meta:
        model = AIReport
        fields = [
            "id",
            "reporter",
            "message",
            "conversation",
            "message_excerpt",
            "reason",
            "description",
            "status",
            "assigned_admin",
            "assigned_admin_label",
            "resolution",
            "resolved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_reporter(self, obj):
        return masked_user(obj.reporter)

    def get_message_excerpt(self, obj) -> str:
        return mask_pii(obj.message.content)[:500]

    def get_assigned_admin_label(self, obj) -> str | None:
        return obj.assigned_admin.full_name or obj.assigned_admin.identifier if obj.assigned_admin else None


class AdminReportUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReportStatus.choices, required=False)
    resolution = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    assign_to_me = serializers.BooleanField(required=False)


class AdminConversationSerializer(serializers.ModelSerializer):
    user = MaskedUserField(read_only=True)
    title = serializers.SerializerMethodField()
    message_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AIConversation
        fields = ["id", "user", "title", "status", "message_count", "last_message_at", "created_at"]
        read_only_fields = fields

    def get_title(self, obj) -> str:
        return mask_pii(obj.title)


class AdminMessageSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()
    validation_notes = serializers.SerializerMethodField()

    class Meta:
        model = AIMessage
        fields = [
            "id",
            "role",
            "content",
            "status",
            "error_code",
            "feedback",
            "model_name",
            "token_usage",
            "validation_notes",
            "created_at",
        ]
        read_only_fields = fields

    def get_content(self, obj) -> str:
        return mask_pii(obj.content)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_validation_notes(self, obj):
        return (obj.structured_data or {}).get("validation_notes", [])


class UsageLogSerializer(serializers.ModelSerializer):
    estimated_cost_usd = serializers.DecimalField(max_digits=12, decimal_places=6, read_only=True, allow_null=True)

    class Meta:
        model = AIUsageLog
        fields = [
            "id",
            "provider",
            "model_name",
            "input_tokens",
            "output_tokens",
            "estimated_cost_usd",
            "latency_ms",
            "status",
            "error_code",
            "created_at",
        ]
        read_only_fields = fields


class DisableSerializer(ConfirmSerializer):
    scope = serializers.ChoiceField(choices=DISABLE_SCOPES)
    reason = serializers.CharField(max_length=500)


class ConfigSerializer(serializers.ModelSerializer):
    provider_configured = serializers.SerializerMethodField()
    key_source = serializers.SerializerMethodField()
    updated_by_label = serializers.SerializerMethodField()
    temperature = serializers.DecimalField(max_digits=3, decimal_places=2, allow_null=True, read_only=True)

    class Meta:
        model = AIConfiguration
        fields = [
            "provider",
            "model_name",
            "enabled",
            "maintenance_mode",
            "maintenance_message",
            "effort",
            "temperature",
            "max_tokens",
            "history_limit",
            "max_input_chars",
            "daily_messages_per_user",
            "daily_messages_global",
            "monthly_token_budget",
            "feature_flags",
            "version",
            "provider_configured",
            "key_source",
            "updated_by_label",
            "updated_at",
        ]
        read_only_fields = fields

    def get_provider_configured(self, obj) -> bool:
        from . import providers

        return providers.is_configured(obj.provider)

    def get_key_source(self, obj) -> str:
        return "ANTHROPIC_API_KEY (environment)"

    def get_updated_by_label(self, obj) -> str | None:
        return obj.updated_by.identifier if obj.updated_by else None


#: Changing any of these needs ``confirm=true`` (they switch the AI on/off or change what it runs on).
CRITICAL_CONFIG_FIELDS = ("provider", "model_name", "enabled", "maintenance_mode", "feature_flags")


class ConfigUpdateSerializer(serializers.ModelSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    confirm = serializers.BooleanField(required=False, default=False)
    temperature = serializers.DecimalField(
        max_digits=3, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("1"), allow_null=True, required=False
    )
    model_name = serializers.RegexField(r"^[a-z0-9][a-z0-9.\-]{2,79}$", required=False)
    feature_flags = serializers.DictField(child=serializers.BooleanField(), required=False)

    class Meta:
        model = AIConfiguration
        fields = [
            "provider",
            "model_name",
            "enabled",
            "maintenance_mode",
            "maintenance_message",
            "effort",
            "temperature",
            "max_tokens",
            "history_limit",
            "max_input_chars",
            "daily_messages_per_user",
            "daily_messages_global",
            "monthly_token_budget",
            "feature_flags",
            "expected_version",
            "confirm",
        ]

    def validate_feature_flags(self, value):
        unknown = set(value) - set(DISABLE_SCOPES[1:])
        if unknown:
            raise serializers.ValidationError(f"Noma'lum flaglar: {', '.join(sorted(unknown))}.")
        return value


class PromptSerializer(serializers.ModelSerializer):
    created_by_label = serializers.SerializerMethodField()
    activated_by_label = serializers.SerializerMethodField()

    class Meta:
        model = PromptVersion
        fields = [
            "id",
            "number",
            "title",
            "system_prompt",
            "status",
            "notes",
            "created_by_label",
            "tested_at",
            "test_result",
            "activated_by_label",
            "activated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_created_by_label(self, obj) -> str | None:
        return obj.created_by.identifier if obj.created_by else None

    def get_activated_by_label(self, obj) -> str | None:
        return obj.activated_by.identifier if obj.activated_by else None


class PromptWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptVersion
        fields = ["title", "system_prompt", "notes"]

    def validate_system_prompt(self, value):
        value = value.strip()
        if len(value) < 50:
            raise serializers.ValidationError("Prompt juda qisqa (kamida 50 belgi).")
        if re.search(r"sk-ant-|api[_-]?key\s*[:=]", value, re.I):
            raise serializers.ValidationError("Promptda kalit yoki maxfiy ma'lumot bo'lmasligi kerak.")
        return value


class PromptTestSerializer(serializers.Serializer):
    sample_message = serializers.CharField(max_length=1000, required=False, default="Salom, to'y rejalashtirmoqchiman.")


class AuditEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_label",
            "action",
            "target_type",
            "target_id",
            "target_label",
            "changes",
            "ip_address",
            "created_at",
        ]
        read_only_fields = fields
