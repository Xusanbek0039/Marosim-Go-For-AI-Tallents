"""AI event planner ("Marosim GO AI Maslahatchisi"): plans, budgets, AI chats and their controls.

Dependency direction: event_planner → venues / studios / reviews / accounts / audit / core. Nothing
depends on this app, so switching the AI off (or deleting a user's planner data) never touches bookings.

* ``EventPlan`` / ``BudgetItem`` — the user's own plan and estimate. Money is ``Decimal`` in UZS and every
  total is computed by ``calculator`` on the server, never taken from AI text.
* ``AIConversation`` / ``AIMessage`` — the chat. Assistant messages keep the *validated* structured
  proposal in ``structured_data``; a proposal becomes a plan only through an explicit user confirmation.
* ``AIUsageLog`` — one row per provider call (tokens / cost only when the provider reports usage).
* ``AIConfiguration`` (singleton) and ``PromptVersion`` — managed by the Super Admin. No secrets here:
  the provider key is read from the environment only.
* ``AIReport`` — a user's complaint about one assistant message, handled by admins.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.models import BaseModel
from apps.venues.models import MONEY, BookingEventType, Currency, Region

#: Largest guest count a plan accepts (a sanity bound, not a venue capacity).
MAX_GUESTS = 10_000
#: Recommended contingency reserve, percent of the subtotal.
RESERVE_RECOMMENDED = (Decimal("5"), Decimal("10"))
RESERVE_DEFAULT = Decimal("7")
RESERVE_MAX = Decimal("30")


class EventType(models.TextChoices):
    TOY = "TOY", "To'y"
    NIKOH = "NIKOH", "Nikoh"
    SUNNAT = "SUNNAT", "Sunnat to'yi"
    BIRTHDAY = "BIRTHDAY", "Tug'ilgan kun"
    ANNIVERSARY = "ANNIVERSARY", "Yubiley"
    CORPORATE = "CORPORATE", "Korporativ"
    OTHER = "OTHER", "Boshqa"


#: Event type of the existing venue booking flow a plan hands off to.
BOOKING_EVENT_TYPE = {
    EventType.TOY: BookingEventType.WEDDING,
    EventType.NIKOH: BookingEventType.WEDDING,
    EventType.SUNNAT: BookingEventType.SUNNAT,
    EventType.BIRTHDAY: BookingEventType.BIRTHDAY,
    EventType.ANNIVERSARY: BookingEventType.ANNIVERSARY,
    EventType.CORPORATE: BookingEventType.CORPORATE,
    EventType.OTHER: BookingEventType.OTHER,
}


class PlanStyle(models.TextChoices):
    ECONOMY = "ECONOMY", "Tejamkor"
    STANDARD = "STANDARD", "Standart"
    PREMIUM = "PREMIUM", "Premium"
    CUSTOM = "CUSTOM", "O'zim belgilayman"


class BudgetFlexibility(models.TextChoices):
    FIXED = "FIXED", "Qat'iy byudjet"
    FLEXIBLE = "FLEXIBLE", "Moslashuvchan byudjet"


class PlanStatus(models.TextChoices):
    DRAFT = "DRAFT", "Qoralama"
    ACTIVE = "ACTIVE", "Faol"
    COMPLETED = "COMPLETED", "Yakunlangan"
    ARCHIVED = "ARCHIVED", "Arxivlangan"


class PlanSource(models.TextChoices):
    MANUAL = "MANUAL", "Qo'lda yaratilgan"
    AI_CONFIRMED = "AI_CONFIRMED", "AI taklifi (foydalanuvchi tasdiqlagan)"


class BudgetCategory(models.TextChoices):
    VENUE = "VENUE", "To'yxona / joy"
    FOOD = "FOOD", "Dasturxon / ovqat"
    PHOTO_VIDEO = "PHOTO_VIDEO", "Foto va video"
    HOST_DJ = "HOST_DJ", "Boshlovchi / DJ"
    ARTISTS = "ARTISTS", "Xonandalar / artistlar"
    DECOR = "DECOR", "Bezak"
    CAKE_EXTRAS = "CAKE_EXTRAS", "Tort, ichimliklar, qo'shimchalar"
    TRANSPORT = "TRANSPORT", "Transport"
    INVITATIONS_OTHER = "INVITATIONS_OTHER", "Taklifnomalar va boshqalar"
    #: Computed from ``EventPlan.reserve_percent`` only — never a budget item (no double counting).
    CONTINGENCY = "CONTINGENCY", "Kutilmagan xarajatlar zaxirasi"


ITEM_CATEGORIES = [c for c in BudgetCategory.values if c != BudgetCategory.CONTINGENCY]
#: What a venue package may cover.
PACKAGE_CATEGORIES = [c for c in ITEM_CATEGORIES if c != BudgetCategory.VENUE]


class BudgetUnit(models.TextChoices):
    EVENT = "EVENT", "marosim"
    PERSON = "PERSON", "kishi"
    PIECE = "PIECE", "dona"
    HOUR = "HOUR", "soat"
    SET = "SET", "to'plam"
    SERVICE = "SERVICE", "xizmat"


class SourceType(models.TextChoices):
    PLATFORM_SERVICE = "PLATFORM_SERVICE", "Platformadagi xizmat"
    USER_INPUT = "USER_INPUT", "Foydalanuvchi kiritgan"
    AI_ESTIMATE = "AI_ESTIMATE", "AI taxmini"
    MANUAL = "MANUAL", "Qo'lda"


#: Sources a client may set; AI_ESTIMATE is written only by the server (confirmed AI proposals).
CLIENT_SOURCE_TYPES = [SourceType.USER_INPUT.value, SourceType.MANUAL.value, SourceType.PLATFORM_SERVICE.value]


class SourceKind(models.TextChoices):
    """What ``source_reference`` points to (only for PLATFORM_SERVICE items)."""

    NONE = "", "—"
    VENUE_HALL = "VENUE_HALL", "To'yxona zali"
    STUDIO = "STUDIO", "Studiya"


class PriceStatus(models.TextChoices):
    #: The price was read from the platform database by the server at ``price_checked_at``.
    VERIFIED = "VERIFIED", "Platformada tasdiqlangan"
    ESTIMATED = "ESTIMATED", "Taxminiy"
    PENDING = "PENDING", "Narx aniqlanmagan"


#: Statuses a client may set; VERIFIED is set only by the server from platform data.
CLIENT_PRICE_STATUSES = [PriceStatus.ESTIMATED.value, PriceStatus.PENDING.value]


class EventPlan(BaseModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="event_plans")
    title = models.CharField(max_length=150)
    event_type = models.CharField(max_length=20, choices=EventType.choices, default=EventType.TOY)
    event_date = models.DateField(null=True, blank=True)
    #: True when ``event_date`` is only a guess; ``approximate_date`` keeps the user's words ("2027 bahor").
    date_is_approximate = models.BooleanField(default=False)
    approximate_date = models.CharField(max_length=60, blank=True)
    region = models.CharField(max_length=20, choices=Region.choices, blank=True)
    district = models.CharField(max_length=100, blank=True)
    guest_count = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(MAX_GUESTS)]
    )
    total_budget = models.DecimalField(**MONEY, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    budget_flexibility = models.CharField(
        max_length=10, choices=BudgetFlexibility.choices, default=BudgetFlexibility.FLEXIBLE
    )
    style = models.CharField(max_length=10, choices=PlanStyle.choices, default=PlanStyle.STANDARD)
    #: Budget categories the user cares most about (subset of ``ITEM_CATEGORIES``).
    priorities = models.JSONField(default=list, blank=True)
    wishes = models.TextField(max_length=2000, blank=True)
    notes = models.TextField(max_length=4000, blank=True)
    status = models.CharField(max_length=10, choices=PlanStatus.choices, default=PlanStatus.DRAFT)
    reserve_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=RESERVE_DEFAULT,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(RESERVE_MAX)],
    )
    source = models.CharField(max_length=12, choices=PlanSource.choices, default=PlanSource.MANUAL)
    #: Idempotency key sent by the client on create (a retried POST returns the same plan).
    client_request_id = models.UUIDField(null=True, blank=True, editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "status", "updated_at"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(guest_count__isnull=True) | Q(guest_count__gte=1, guest_count__lte=MAX_GUESTS),
                name="planner_plan_guest_count_range",
            ),
            models.CheckConstraint(
                condition=Q(total_budget__isnull=True) | Q(total_budget__gte=0), name="planner_plan_budget_non_negative"
            ),
            models.CheckConstraint(condition=Q(currency="UZS"), name="planner_plan_currency_uzs"),
            models.CheckConstraint(
                condition=Q(reserve_percent__gte=0, reserve_percent__lte=RESERVE_MAX), name="planner_plan_reserve_range"
            ),
            models.CheckConstraint(
                condition=Q(status__in=[s.value for s in PlanStatus]), name="planner_plan_status_valid"
            ),
            models.UniqueConstraint(
                fields=["owner", "client_request_id"],
                condition=Q(client_request_id__isnull=False),
                name="planner_plan_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class BudgetItem(BaseModel):
    plan = models.ForeignKey(EventPlan, on_delete=models.CASCADE, related_name="items")
    category = models.CharField(max_length=20, choices=BudgetCategory.choices)
    title = models.CharField(max_length=150)
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("1"), validators=[MinValueValidator(Decimal("0.01"))]
    )
    unit = models.CharField(max_length=10, choices=BudgetUnit.choices, default=BudgetUnit.SERVICE)
    #: Quantity follows the plan's guest count (e.g. menu per person × guests); ``quantity`` is then ignored.
    per_guest = models.BooleanField(default=False)
    unit_price = models.DecimalField(**MONEY, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))])
    #: Upper end of a price range; ``None`` = a single price.
    unit_price_max = models.DecimalField(**MONEY, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    #: Written by ``calculator.line_totals`` on every save — never accepted from a client or the AI.
    total_price = models.DecimalField(**MONEY, default=Decimal("0"), editable=False)
    total_price_max = models.DecimalField(**MONEY, default=Decimal("0"), editable=False)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.MANUAL)
    source_kind = models.CharField(max_length=12, choices=SourceKind.choices, blank=True, default=SourceKind.NONE)
    #: Primary key of the hall / studio (PLATFORM_SERVICE), checked against the database on every write.
    source_reference = models.CharField(max_length=64, blank=True)
    price_status = models.CharField(max_length=10, choices=PriceStatus.choices, default=PriceStatus.ESTIMATED)
    price_checked_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=1000, blank=True)
    #: Already paid for inside the venue package: listed for clarity, counted as 0.
    is_included_in_package = models.BooleanField(default=False)
    #: VENUE items only: categories the venue package covers (other items there must be marked included).
    package_includes = models.JSONField(default=list, blank=True)
    #: What was really paid (planned vs actual). Optional, never used for the planned total.
    actual_amount = models.DecimalField(**MONEY, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    #: Inactive items stay in the list (e.g. a cut the user is considering) but are not summed.
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    client_request_id = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["plan", "category"]), models.Index(fields=["plan", "is_active"])]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="planner_item_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="planner_item_price_non_negative"),
            models.CheckConstraint(
                condition=Q(unit_price_max__isnull=True) | Q(unit_price_max__gte=F("unit_price")),
                name="planner_item_price_range",
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0, total_price_max__gte=F("total_price")),
                name="planner_item_totals_valid",
            ),
            models.CheckConstraint(condition=Q(currency="UZS"), name="planner_item_currency_uzs"),
            models.CheckConstraint(condition=~Q(category="CONTINGENCY"), name="planner_item_not_contingency"),
            models.CheckConstraint(
                condition=~Q(price_status="VERIFIED") | Q(source_type="PLATFORM_SERVICE"),
                name="planner_item_verified_only_platform",
            ),
            models.UniqueConstraint(
                fields=["plan", "source_kind", "source_reference"],
                condition=~Q(source_reference=""),
                name="planner_item_platform_service_once",
            ),
            models.UniqueConstraint(
                fields=["plan", "client_request_id"],
                condition=Q(client_request_id__isnull=False),
                name="planner_item_idempotency",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plan_id} · {self.category} · {self.title}"


# ------------------------------------------------------------------------- chat
class ConversationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Faol"
    ARCHIVED = "ARCHIVED", "Arxivlangan"


class AIConversation(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations")
    event_plan = models.ForeignKey(
        EventPlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations"
    )
    title = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=10, choices=ConversationStatus.choices, default=ConversationStatus.ACTIVE)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "status", "updated_at"])]

    def __str__(self) -> str:
        return self.title or str(self.pk)


class MessageRole(models.TextChoices):
    USER = "user", "Foydalanuvchi"
    ASSISTANT = "assistant", "AI maslahatchi"
    SYSTEM = "system", "Tizim"
    TOOL = "tool", "Platforma ma'lumoti"


class MessageStatus(models.TextChoices):
    OK = "OK", "Muvaffaqiyatli"
    #: The provider failed; the user message stays and can be retried with the same client_request_id.
    FAILED = "FAILED", "Xatolik"
    #: The provider answered but the structure was invalid; a safe generic answer was stored instead.
    FALLBACK = "FALLBACK", "Zaxira javob"
    #: Refused before reaching the provider (limits, disabled, maintenance).
    BLOCKED = "BLOCKED", "Bloklangan"


class Feedback(models.TextChoices):
    NONE = "", "—"
    UP = "UP", "Foydali"
    DOWN = "DOWN", "Foydasiz"


class AIMessage(BaseModel):
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=MessageRole.choices)
    #: Plain text, rendered as text by every client (never as HTML).
    content = models.TextField(max_length=8000)
    #: Server-validated proposal (assistant) — see ``schema.sanitize``. Never raw provider output.
    structured_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=MessageStatus.choices, default=MessageStatus.OK)
    error_code = models.CharField(max_length=64, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    #: User messages only: the idempotency key of the send (retry = same key).
    client_request_id = models.UUIDField(null=True, blank=True, editable=False)
    reply_to = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies")
    feedback = models.CharField(max_length=4, choices=Feedback.choices, blank=True, default=Feedback.NONE)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"]), models.Index(fields=["role", "created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "client_request_id"],
                condition=Q(client_request_id__isnull=False),
                name="planner_message_idempotency",
            ),
            models.CheckConstraint(
                condition=Q(role__in=[r.value for r in MessageRole]), name="planner_message_role_valid"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.conversation_id} · {self.role}"


class UsageStatus(models.TextChoices):
    SUCCESS = "SUCCESS", "Muvaffaqiyatli"
    FALLBACK = "FALLBACK", "Noto'g'ri tuzilma (zaxira javob)"
    ERROR = "ERROR", "Provayder xatosi"
    BLOCKED = "BLOCKED", "Limit / o'chirilgan"


class AIUsageLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    conversation = models.ForeignKey(
        AIConversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage_logs"
    )
    provider = models.CharField(max_length=30, blank=True)
    model_name = models.CharField(max_length=80, blank=True)
    #: ``None`` = the provider did not report usage (then cost stays ``None`` too).
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=UsageStatus.choices)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"]), models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.status} {self.error_code}"


# ---------------------------------------------------------------- configuration
class ProviderName(models.TextChoices):
    OPENAI = "openai", "OpenAI (GPT)"
    ANTHROPIC = "anthropic", "Anthropic (Claude)"


class Effort(models.TextChoices):
    LOW = "low", "Past (tez, arzon)"
    MEDIUM = "medium", "O'rta"
    HIGH = "high", "Yuqori"


def default_feature_flags() -> dict:
    return {"chat": True, "recommendations": True, "booking_handoff": True}


FEATURE_FLAGS = ("chat", "recommendations", "booking_handoff")
DISABLE_SCOPES = ["all", *FEATURE_FLAGS]


class AIConfiguration(models.Model):
    """Singleton (pk=1). Secrets never live here — ``provider_configured`` is derived from the environment."""

    provider = models.CharField(max_length=30, choices=ProviderName.choices, default=ProviderName.OPENAI)
    model_name = models.CharField(max_length=80, default="gpt-4o-mini")
    #: Global on/off (emergency stop sets it to False).
    enabled = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.CharField(max_length=300, blank=True)
    effort = models.CharField(max_length=10, choices=Effort.choices, default=Effort.LOW)
    #: Kept for providers that accept it; current Claude models reject sampling parameters, so the
    #: Anthropic adapter never sends it (see ``providers.anthropic_provider``).
    temperature = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    max_tokens = models.PositiveIntegerField(
        default=4000, validators=[MinValueValidator(512), MaxValueValidator(16000)]
    )
    #: Earlier messages sent with each request (the rest of the history stays on the server).
    history_limit = models.PositiveSmallIntegerField(
        default=12, validators=[MinValueValidator(2), MaxValueValidator(40)]
    )
    max_input_chars = models.PositiveIntegerField(
        default=2000, validators=[MinValueValidator(100), MaxValueValidator(8000)]
    )
    daily_messages_per_user = models.PositiveIntegerField(default=40, validators=[MaxValueValidator(10_000)])
    #: 0 = no platform-wide daily cap.
    daily_messages_global = models.PositiveIntegerField(default=0)
    #: Provider-reported tokens per calendar month for the whole platform (0 = no cap).
    monthly_token_budget = models.PositiveBigIntegerField(default=0)
    feature_flags = models.JSONField(default=default_feature_flags, blank=True)
    #: Bumped on every change; PATCH must send the version it saw (no silent overwrite of a parallel edit).
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "AI rejalashtiruvchi sozlamalari"

    @classmethod
    def load(cls) -> "AIConfiguration":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def flag(self, name: str) -> bool:
        return bool((self.feature_flags or {}).get(name, True))


class PromptStatus(models.TextChoices):
    DRAFT = "DRAFT", "Qoralama"
    TESTED = "TESTED", "Sinovdan o'tgan"
    ACTIVE = "ACTIVE", "Faol"
    ARCHIVED = "ARCHIVED", "Arxiv"


class PromptVersion(BaseModel):
    """Versioned system prompt: draft → test → activate (Super Admin) → rollback = activate an older one.

    The fixed safety rules in ``prompts.SAFETY_RULES`` are always appended and cannot be edited here.
    """

    number = models.PositiveIntegerField(unique=True, editable=False)
    title = models.CharField(max_length=120)
    system_prompt = models.TextField(max_length=20_000)
    status = models.CharField(max_length=10, choices=PromptStatus.choices, default=PromptStatus.DRAFT)
    notes = models.CharField(max_length=1000, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    tested_at = models.DateTimeField(null=True, blank=True)
    test_result = models.JSONField(default=dict, blank=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["status"], condition=Q(status="ACTIVE"), name="planner_prompt_one_active"),
        ]

    def __str__(self) -> str:
        return f"v{self.number} {self.title}"


# --------------------------------------------------------------------- reports
class ReportReason(models.TextChoices):
    WRONG_INFO = "WRONG_INFO", "Noto'g'ri ma'lumot"
    FAKE_SERVICE = "FAKE_SERVICE", "Mavjud bo'lmagan xizmat"
    WRONG_PRICE = "WRONG_PRICE", "Noto'g'ri narx"
    OFFENSIVE = "OFFENSIVE", "Haqoratli / nomaqbul"
    PRIVACY = "PRIVACY", "Shaxsiy ma'lumot muammosi"
    OTHER = "OTHER", "Boshqa"


class ReportStatus(models.TextChoices):
    OPEN = "OPEN", "Yangi"
    IN_REVIEW = "IN_REVIEW", "Ko'rib chiqilmoqda"
    RESOLVED = "RESOLVED", "Hal qilindi"
    REJECTED = "REJECTED", "Rad etildi"


class AIReport(BaseModel):
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_reports")
    message = models.ForeignKey(AIMessage, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=16, choices=ReportReason.choices)
    description = models.CharField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=ReportStatus.choices, default=ReportStatus.OPEN)
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolution = models.CharField(max_length=2000, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]
        constraints = [
            models.UniqueConstraint(fields=["reporter", "message"], name="planner_report_once_per_message"),
        ]

    def __str__(self) -> str:
        return f"{self.reason} ({self.status})"
