"""Plan and budget writes. Every rule about prices, sources and double counting lives here.

* Platform services are priced by the server: a hall's price is read from the database (hall price →
  venue price) and marked VERIFIED with ``price_checked_at``; a studio has no platform price (PENDING
  until the user enters one, then ESTIMATED). Clients can never mark a price VERIFIED.
* A venue item may declare ``package_includes``; any other active item in such a category must be marked
  ``is_included_in_package`` (it then costs 0) — otherwise the write is rejected, so nothing is paid twice.
* The same hall / studio can be in a plan only once (DB constraint → 409).
* Totals are recomputed (``recalculate``) after every item write and after every guest-count change.
* An AI proposal becomes a plan only through ``confirm_proposal`` (explicit user action, idempotent).
"""

import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from . import calculator, catalog
from .models import (
    ITEM_CATEGORIES,
    AIConversation,
    AIMessage,
    AIReport,
    AIUsageLog,
    BudgetCategory,
    BudgetItem,
    BudgetUnit,
    EventPlan,
    MessageRole,
    MessageStatus,
    PlanSource,
    PlanStatus,
    PriceStatus,
    SourceKind,
    SourceType,
)

#: Items one plan may hold (abuse bound).
MAX_ITEMS_PER_PLAN = 200
MAX_PLANS_PER_USER = 100


class PlannerError(APIException):
    """API error with a stable ``code`` and an Uzbek message (same shape as every other API error)."""

    def __init__(self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST):
        self.status_code = http_status
        super().__init__(detail=message, code=code)


def user_plans(user):
    return EventPlan.objects.filter(owner=user, deleted_at__isnull=True)


def user_conversations(user):
    return AIConversation.objects.filter(user=user)


# --------------------------------------------------------------------- totals
def recalculate(plan: EventPlan) -> None:
    """Re-price every line of ``plan`` (per-guest lines follow the current guest count)."""
    items = list(plan.items.all())
    for item in items:
        item.total_price, item.total_price_max = calculator.line_totals(calculator.Line.of(item), plan.guest_count)
    BudgetItem.objects.bulk_update(items, ["total_price", "total_price_max"])


def summary(plan: EventPlan) -> dict:
    lines = [calculator.Line.of(i) for i in plan.items.all()]
    return calculator.summarize(
        lines,
        guest_count=plan.guest_count,
        total_budget=plan.total_budget,
        reserve_percent=plan.reserve_percent,
        currency=plan.currency,
    )


def package_categories(plan: EventPlan, exclude_pk=None) -> set[str]:
    rows = plan.items.filter(category=BudgetCategory.VENUE, is_active=True)
    if exclude_pk is not None:
        rows = rows.exclude(pk=exclude_pk)
    return {c for item in rows for c in (item.package_includes or [])}


# ---------------------------------------------------------------------- items
def _platform_fields(kind: str, reference: str) -> dict:
    """Server-owned fields of a PLATFORM_SERVICE item (re-checked against the public catalog)."""
    now = timezone.now()
    if kind == SourceKind.VENUE_HALL:
        hall = catalog.resolve_hall(reference)
        if hall is None:
            raise ValidationError({"source_reference": ["Bu zal platformada topilmadi yoki hozir ko'rsatilmaydi."]})
        return {
            "source_reference": str(hall.pk),
            "default_title": f"{hall.venue.name} · {hall.name}",
            "unit_price": hall.effective_base_price,
            "unit_price_max": None,
            "price_status": PriceStatus.VERIFIED,
            "price_checked_at": now,
            "category": BudgetCategory.VENUE,
        }
    if kind == SourceKind.STUDIO:
        studio = catalog.resolve_studio(reference)
        if studio is None:
            raise ValidationError({"source_reference": ["Bu studiya platformada topilmadi."]})
        return {
            "source_reference": str(studio.pk),
            "default_title": studio.name,
            "price_checked_at": None,
            "category": BudgetCategory.PHOTO_VIDEO,
        }
    raise ValidationError({"source_kind": ["Platforma xizmati uchun turini tanlang (zal yoki studiya)."]})


def apply_item(plan: EventPlan, item: BudgetItem, data: dict) -> BudgetItem:
    """Validate and save one item. ``data`` comes from ``BudgetItemWriteSerializer`` (already type-checked)."""
    creating = item._state.adding
    price_changed = any(k in data for k in ("unit_price", "unit_price_max"))
    for key, value in data.items():
        setattr(item, key, value)

    if item.source_type == SourceType.PLATFORM_SERVICE:
        fields = _platform_fields(item.source_kind, item.source_reference)
        item.source_reference = fields["source_reference"]
        item.category = fields["category"]
        item.title = item.title or fields["default_title"]
        if item.source_kind == SourceKind.VENUE_HALL:
            # Always the database price: a client cannot "verify" a different number.
            item.unit_price, item.unit_price_max = fields["unit_price"], None
            item.price_status, item.price_checked_at = PriceStatus.VERIFIED, fields["price_checked_at"]
            item.quantity, item.per_guest, item.unit = Decimal("1"), False, BudgetUnit.EVENT
        else:
            item.price_status = PriceStatus.ESTIMATED if item.unit_price > 0 else PriceStatus.PENDING
            item.price_checked_at = None
    else:
        if item.source_type == SourceType.AI_ESTIMATE and price_changed and not creating:
            item.source_type = SourceType.USER_INPUT  # the user's own number now
        item.source_kind, item.source_reference = SourceKind.NONE, ""
        if item.price_status == PriceStatus.VERIFIED:
            raise ValidationError({"price_status": ["Faqat platformadagi xizmat narxi tasdiqlangan bo'lishi mumkin."]})
        if item.unit_price == 0 and item.unit_price_max is None:
            item.price_status = PriceStatus.PENDING

    if item.category == BudgetCategory.CONTINGENCY:
        raise ValidationError({"category": ["Zaxira avtomatik hisoblanadi — uni alohida band qilib bo'lmaydi."]})
    if item.category != BudgetCategory.VENUE:
        item.package_includes = []
    else:
        bad = [c for c in item.package_includes or [] if c not in ITEM_CATEGORIES or c == BudgetCategory.VENUE]
        if bad:
            raise ValidationError({"package_includes": ["Noto'g'ri toifa."]})
        item.package_includes = [c for c in ITEM_CATEGORIES if c in set(item.package_includes or [])]
    if item.unit_price_max is not None and item.unit_price_max < item.unit_price:
        raise ValidationError({"unit_price_max": ["Yuqori narx pastki narxdan kichik bo'lmasligi kerak."]})
    if item.unit_price_max is not None and item.unit_price_max == item.unit_price:
        item.unit_price_max = None
    if (
        item.is_active
        and not item.is_included_in_package
        and item.category != BudgetCategory.VENUE
        and item.category in package_categories(plan, exclude_pk=item.pk)
    ):
        raise PlannerError(
            "included_in_package",
            'Bu xizmat to\'yxona paketiga kiritilgan. Ikki marta hisoblanmasligi uchun uni "paketda" deb belgilang.',
        )
    if creating and plan.items.count() >= MAX_ITEMS_PER_PLAN:
        raise PlannerError("too_many_items", f"Bitta rejada ko'pi bilan {MAX_ITEMS_PER_PLAN} ta band bo'lishi mumkin.")

    item.plan = plan
    item.currency = plan.currency
    item.total_price, item.total_price_max = calculator.line_totals(calculator.Line.of(item), plan.guest_count)
    try:
        with transaction.atomic():
            item.save()
    except IntegrityError:
        raise PlannerError("duplicate_service", "Bu xizmat rejada allaqachon bor.", status.HTTP_409_CONFLICT) from None
    if item.category == BudgetCategory.VENUE:
        _guard_package_conflicts(plan)
    plan.save(update_fields=["updated_at"])
    return item


def _guard_package_conflicts(plan: EventPlan) -> None:
    """After a venue package changes, mark lines it now covers as included (they would be paid twice)."""
    covered = package_categories(plan)
    if not covered:
        return
    rows = plan.items.filter(category__in=covered, is_active=True, is_included_in_package=False).exclude(
        category=BudgetCategory.VENUE
    )
    if rows.exists():
        rows.update(is_included_in_package=True, total_price=Decimal("0"), total_price_max=Decimal("0"))


# ---------------------------------------------------------------------- plans
def create_plan(user, data: dict, client_request_id=None, *, source=PlanSource.MANUAL) -> tuple[EventPlan, bool]:
    if client_request_id:
        existing = EventPlan.objects.filter(owner=user, client_request_id=client_request_id).first()
        if existing is not None:
            return existing, False
    if user_plans(user).count() >= MAX_PLANS_PER_USER:
        raise PlannerError("too_many_plans", f"Ko'pi bilan {MAX_PLANS_PER_USER} ta reja saqlash mumkin.")
    try:
        with transaction.atomic():
            plan = EventPlan.objects.create(owner=user, client_request_id=client_request_id, source=source, **data)
    except IntegrityError:  # a parallel retry with the same key won
        return EventPlan.objects.get(owner=user, client_request_id=client_request_id), False
    return plan, True


def update_plan(plan: EventPlan, data: dict) -> EventPlan:
    guests_changed = "guest_count" in data and data["guest_count"] != plan.guest_count
    for key, value in data.items():
        setattr(plan, key, value)
    plan.save()
    if guests_changed:
        recalculate(plan)
    return plan


@transaction.atomic
def duplicate_plan(plan: EventPlan) -> EventPlan:
    if user_plans(plan.owner).count() >= MAX_PLANS_PER_USER:
        raise PlannerError("too_many_plans", f"Ko'pi bilan {MAX_PLANS_PER_USER} ta reja saqlash mumkin.")
    items = list(plan.items.all())
    copy = EventPlan.objects.get(pk=plan.pk)
    copy.pk = None
    copy.id = None
    copy._state.adding = True
    copy.title = f"{plan.title} (nusxa)"[:150]
    copy.status = PlanStatus.DRAFT
    copy.client_request_id = None
    copy.save()
    for item in items:
        item.pk = None
        item.id = None
        item._state.adding = True
        item.plan = copy
        item.client_request_id = None
        if item.source_kind == SourceKind.VENUE_HALL:  # re-read the platform price (it may have changed)
            hall = catalog.resolve_hall(item.source_reference)
            if hall is None:
                item.source_type, item.source_kind, item.source_reference = SourceType.MANUAL, SourceKind.NONE, ""
                item.price_status, item.price_checked_at = PriceStatus.PENDING, None
                item.notes = (item.notes + " · Zal endi platformada ko'rsatilmaydi.").strip(" ·")[:1000]
            else:
                item.unit_price, item.price_checked_at = hall.effective_base_price, timezone.now()
        item.total_price, item.total_price_max = calculator.line_totals(calculator.Line.of(item), copy.guest_count)
        item.save()
    return copy


def soft_delete_plan(plan: EventPlan) -> None:
    plan.deleted_at = timezone.now()
    plan.save(update_fields=["deleted_at", "updated_at"])
    AIConversation.objects.filter(event_plan=plan).update(event_plan=None)


# ------------------------------------------------------------ AI proposal → plan
PLAN_PROPOSAL_FIELDS = (
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
)


def _plan_values(proposal: dict) -> dict:
    values = {}
    for key in PLAN_PROPOSAL_FIELDS:
        value = proposal.get(key)
        if value in (None, "", []):
            continue
        if key == "event_date":
            value = datetime.date.fromisoformat(value)
        elif key == "total_budget":
            value = Decimal(value)
        values[key] = value
    return values


@transaction.atomic
def confirm_proposal(user, conversation: AIConversation, message: AIMessage) -> tuple[EventPlan, list[str], bool]:
    """Save an assistant proposal as (or into) the conversation's plan — only on the user's explicit request.

    Returns ``(plan, notes, created_now)``. Confirming the same message again returns the same plan unchanged.
    Prices of platform services are re-read from the database; AI category prices stay ESTIMATED.
    Nothing here creates a booking.
    """
    message = AIMessage.objects.select_for_update().get(pk=message.pk)
    data = message.structured_data or {}
    done = data.get("confirmed_plan_id")
    if done:
        plan = user_plans(user).filter(pk=done).first()
        if plan is not None:
            return plan, [], False
    proposal = data.get("event_plan") or {}
    items = data.get("budget_items") or []
    if message.role != MessageRole.ASSISTANT or message.status != MessageStatus.OK or not (proposal or items):
        raise PlannerError("nothing_to_confirm", "Bu javobda saqlanadigan reja yo'q.")

    notes: list[str] = []
    plan = conversation.event_plan if conversation.event_plan and conversation.event_plan.deleted_at is None else None
    values = _plan_values(proposal)
    if plan is None:
        values.setdefault("title", conversation.title or "AI bilan tuzilgan reja")
        plan, _ = create_plan(user, values, source=PlanSource.AI_CONFIRMED)
        conversation.event_plan = plan
        conversation.save(update_fields=["event_plan", "updated_at"])
    elif values:
        values.pop("title", None)  # keep the user's own title
        update_plan(plan, values)

    position = plan.items.count()
    for row in items:
        item = BudgetItem(plan=plan, position=position)
        if row.get("service_id"):
            fields = {
                "source_type": SourceType.PLATFORM_SERVICE,
                "source_kind": row.get("service_kind") or SourceKind.VENUE_HALL,
                "source_reference": row["service_id"],
                "title": row.get("title", ""),
                "notes": row.get("notes", ""),
                "unit_price": Decimal("0"),
            }
        else:
            fields = {
                "category": row["category"],
                "title": row["title"],
                "quantity": Decimal(row["quantity"]),
                "unit": row["unit"],
                "per_guest": row["per_guest"],
                "unit_price": Decimal(row["unit_price"]),
                "unit_price_max": Decimal(row["unit_price_max"]) if row.get("unit_price_max") else None,
                "is_included_in_package": row.get("is_included_in_package", False),
                "source_type": SourceType.AI_ESTIMATE,
                "price_status": PriceStatus.ESTIMATED,
                "notes": row.get("notes", ""),
            }
        try:
            with transaction.atomic():
                apply_item(plan, item, fields)
        except PlannerError as exc:
            notes.append(exc.get_codes() if isinstance(exc.get_codes(), str) else "item_skipped")
            continue
        except ValidationError:
            notes.append("service_unavailable")
            continue
        position += 1

    message.structured_data = {**data, "confirmed_plan_id": str(plan.pk), "confirmed_at": timezone.now().isoformat()}
    message.save(update_fields=["structured_data", "updated_at"])
    return plan, list(dict.fromkeys(notes)), True


# ------------------------------------------------------------- export / delete
def export_user_data(user) -> dict:
    plans = user_plans(user).prefetch_related("items")
    conversations = user_conversations(user).prefetch_related("messages")
    return {
        "exported_at": timezone.now().isoformat(),
        "plans": [
            {
                "id": str(p.pk),
                "title": p.title,
                "event_type": p.event_type,
                "event_date": p.event_date.isoformat() if p.event_date else None,
                "approximate_date": p.approximate_date,
                "region": p.region,
                "district": p.district,
                "guest_count": p.guest_count,
                "total_budget": calculator.money(p.total_budget),
                "currency": p.currency,
                "style": p.style,
                "status": p.status,
                "wishes": p.wishes,
                "notes": p.notes,
                "items": [
                    {
                        "category": i.category,
                        "title": i.title,
                        "quantity": str(i.quantity),
                        "unit": i.unit,
                        "per_guest": i.per_guest,
                        "unit_price": calculator.money(i.unit_price),
                        "unit_price_max": calculator.money(i.unit_price_max),
                        "total_price": calculator.money(i.total_price),
                        "source_type": i.source_type,
                        "price_status": i.price_status,
                        "notes": i.notes,
                    }
                    for i in p.items.all()
                ],
                "summary": summary(p),
            }
            for p in plans
        ],
        "conversations": [
            {
                "id": str(c.pk),
                "title": c.title,
                "status": c.status,
                "messages": [
                    {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
                    for m in c.messages.all()
                ],
            }
            for c in conversations
        ],
    }


@transaction.atomic
def delete_user_data(user) -> dict:
    """Hard-deletes the user's planner content. Usage logs are kept for cost accounting, without the user."""
    counts = {
        "reports": AIReport.objects.filter(Q(reporter=user) | Q(message__conversation__user=user)).delete()[0],
        "conversations": AIConversation.objects.filter(user=user).count(),
        "plans": EventPlan.objects.filter(owner=user).count(),
    }
    AIConversation.objects.filter(user=user).delete()
    EventPlan.objects.filter(owner=user).delete()
    AIUsageLog.objects.filter(user=user).update(user=None, conversation=None)
    return counts
