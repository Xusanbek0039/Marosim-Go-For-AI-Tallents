"""The structured answer the model must return, and its server-side validation.

The JSON schema is sent to the provider (structured output), but nothing in it is trusted: ``sanitize``
re-checks every field, keeps only known enums, bounded numbers and parseable dates, drops recommendations
and service references that are not among the real candidates the server supplied, and never takes a
price for a platform service from the model. Anything unusable yields ``None`` → a safe fallback answer.
"""

import datetime
import json
from decimal import Decimal, InvalidOperation

from apps.venues.models import Region

from .models import (
    ITEM_CATEGORIES,
    MAX_GUESTS,
    BudgetFlexibility,
    BudgetUnit,
    EventType,
    PlanStyle,
    SourceKind,
)

INTENTS = (
    "greeting",
    "collect_info",
    "propose_plan",
    "update_budget",
    "recommend_services",
    "answer_question",
    "booking_handoff",
    "refuse",
    "other",
)
PLAN_FIELDS = (
    "event_type",
    "event_date",
    "region",
    "guest_count",
    "total_budget",
    "budget_flexibility",
    "style",
    "priorities",
)
MAX_ITEMS = 15
MAX_RECOMMENDATIONS = 6
MAX_MONEY = Decimal("100000000000")  # 100 billion so'm — anything above is an illogical value
MAX_QUANTITY = Decimal("100000")


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _enum(values) -> dict:
    return {"type": "string", "enum": list(values)}


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "assistant_message",
        "language",
        "intent",
        "missing_information",
        "next_question",
        "event_plan",
        "budget_items",
        "recommendations",
        "warnings",
    ],
    "properties": {
        "assistant_message": {"type": "string"},
        "language": {"type": "string"},
        "intent": _enum(INTENTS),
        "missing_information": {"type": "array", "items": _enum(PLAN_FIELDS)},
        "next_question": _nullable({"type": "string"}),
        "event_plan": _nullable(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
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
                ],
                "properties": {
                    "title": _nullable({"type": "string"}),
                    "event_type": _nullable(_enum(EventType.values)),
                    "event_date": _nullable({"type": "string"}),
                    "date_is_approximate": _nullable({"type": "boolean"}),
                    "approximate_date": _nullable({"type": "string"}),
                    "region": _nullable(_enum(Region.values)),
                    "district": _nullable({"type": "string"}),
                    "guest_count": _nullable({"type": "integer"}),
                    "total_budget": _nullable({"type": "number"}),
                    "budget_flexibility": _nullable(_enum(BudgetFlexibility.values)),
                    "style": _nullable(_enum(PlanStyle.values)),
                    "priorities": {"type": "array", "items": _enum(ITEM_CATEGORIES)},
                    "wishes": _nullable({"type": "string"}),
                },
            }
        ),
        "budget_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "category",
                    "title",
                    "quantity",
                    "unit",
                    "per_guest",
                    "unit_price_min",
                    "unit_price_max",
                    "service_id",
                    "is_included_in_package",
                    "notes",
                ],
                "properties": {
                    "category": _enum(ITEM_CATEGORIES),
                    "title": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": _enum(BudgetUnit.values),
                    "per_guest": {"type": "boolean"},
                    "unit_price_min": {"type": "number"},
                    "unit_price_max": _nullable({"type": "number"}),
                    "service_id": _nullable({"type": "string"}),
                    "is_included_in_package": {"type": "boolean"},
                    "notes": _nullable({"type": "string"}),
                },
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["service_id", "kind", "reason"],
                "properties": {
                    "service_id": {"type": "string"},
                    "kind": _enum([SourceKind.VENUE_HALL, SourceKind.STUDIO]),
                    "reason": {"type": "string"},
                },
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}


def _text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    # Control characters out; markup stays inert because every client renders plain text.
    cleaned = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    return cleaned.strip()[:limit]


def _money(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or amount > MAX_MONEY:
        return None
    return amount.quantize(Decimal("0.01"))


def _choice(value, choices) -> str | None:
    return value if isinstance(value, str) and value in choices else None


def _date(value) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _plan(raw, notes: list[str]) -> dict | None:
    if not isinstance(raw, dict):
        return None
    guests = raw.get("guest_count")
    if isinstance(guests, bool) or not isinstance(guests, int) or not 1 <= guests <= MAX_GUESTS:
        if guests is not None:
            notes.append("invalid_guest_count")
        guests = None
    budget = _money(raw.get("total_budget"))
    if raw.get("total_budget") is not None and budget is None:
        notes.append("invalid_budget")
    event_date = _date(raw.get("event_date"))
    if raw.get("event_date") and event_date is None:
        notes.append("invalid_date")
    priorities = raw.get("priorities") if isinstance(raw.get("priorities"), list) else []
    plan = {
        "title": _text(raw.get("title"), 150),
        "event_type": _choice(raw.get("event_type"), EventType.values),
        "event_date": event_date.isoformat() if event_date else None,
        "date_is_approximate": bool(raw.get("date_is_approximate")),
        "approximate_date": _text(raw.get("approximate_date"), 60),
        "region": _choice(raw.get("region"), Region.values),
        "district": _text(raw.get("district"), 100),
        "guest_count": guests,
        "total_budget": str(budget) if budget is not None else None,
        "budget_flexibility": _choice(raw.get("budget_flexibility"), BudgetFlexibility.values),
        "style": _choice(raw.get("style"), PlanStyle.values),
        "priorities": [p for p in dict.fromkeys(priorities) if p in ITEM_CATEGORIES],
        "wishes": _text(raw.get("wishes"), 2000),
    }
    return plan if any(v not in (None, "", [], False) for v in plan.values()) else None


def _items(raw, candidates: dict, notes: list[str]) -> list[dict]:
    out: list[dict] = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict) or len(out) >= MAX_ITEMS:
            continue
        category = _choice(row.get("category"), ITEM_CATEGORIES)
        title = _text(row.get("title"), 150)
        unit = _choice(row.get("unit"), BudgetUnit.values) or BudgetUnit.SERVICE
        per_guest = row.get("per_guest") is True
        quantity = _money(row.get("quantity"))
        low = _money(row.get("unit_price_min"))
        high = _money(row.get("unit_price_max")) if row.get("unit_price_max") is not None else None
        if not category or not title:
            notes.append("item_dropped_invalid")
            continue
        service_id = row.get("service_id") if isinstance(row.get("service_id"), str) else None
        if service_id:
            candidate = candidates.get(service_id)
            if candidate is None:  # an id the server never offered = an invented service
                notes.append("unknown_service_dropped")
                continue
            # A platform service is priced by the server from the database, never by the model.
            out.append(
                {
                    "category": category,
                    "title": _text(candidate["name"], 150),
                    "quantity": "1.00",
                    "unit": BudgetUnit.EVENT if candidate["kind"] == SourceKind.VENUE_HALL else BudgetUnit.SERVICE,
                    "per_guest": False,
                    "service_id": service_id,
                    "service_kind": candidate["kind"],
                    "is_included_in_package": False,
                    "notes": _text(row.get("notes"), 500),
                }
            )
            continue
        if per_guest:
            quantity = Decimal("1")
        if quantity is None or quantity <= 0 or quantity > MAX_QUANTITY or low is None or low <= 0:
            notes.append("item_dropped_invalid")
            continue
        if high is not None and high < low:
            notes.append("item_dropped_invalid")
            continue
        out.append(
            {
                "category": category,
                "title": title,
                "quantity": str(quantity),
                "unit": BudgetUnit.PERSON if per_guest else unit,
                "per_guest": per_guest,
                "unit_price": str(low),
                "unit_price_max": str(high) if high is not None and high != low else None,
                "service_id": None,
                "is_included_in_package": row.get("is_included_in_package") is True,
                "notes": _text(row.get("notes"), 500),
            }
        )
    return out


def _recommendations(raw, candidates: dict, notes: list[str]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict) or len(out) >= MAX_RECOMMENDATIONS:
            continue
        service_id = row.get("service_id")
        if not isinstance(service_id, str) or service_id in seen:
            continue
        if service_id not in candidates:
            notes.append("unknown_service_dropped")
            continue
        seen.add(service_id)
        out.append(
            {"service_id": service_id, "kind": candidates[service_id]["kind"], "reason": _text(row.get("reason"), 500)}
        )
    return out


def _list(value) -> list:
    return value if isinstance(value, list) else []


def parse(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def sanitize(data: dict | None, candidates: list[dict]) -> tuple[dict | None, list[str]]:
    """``(clean, notes)``; ``clean`` is ``None`` when the answer cannot be used at all."""
    notes: list[str] = []
    if not isinstance(data, dict):
        return None, ["invalid_structure"]
    message = _text(data.get("assistant_message"), 6000)
    if not message:
        return None, ["invalid_structure"]
    by_id = {c["id"]: c for c in candidates}
    missing = _list(data.get("missing_information"))
    clean = {
        "assistant_message": message,
        "language": _text(data.get("language"), 8) or "uz",
        "intent": _choice(data.get("intent"), INTENTS) or "other",
        "missing_information": [m for m in dict.fromkeys(missing) if m in PLAN_FIELDS],
        "next_question": _text(data.get("next_question"), 500) or None,
        "event_plan": _plan(data.get("event_plan"), notes),
        "budget_items": _items(data.get("budget_items"), by_id, notes),
        "recommendations": _recommendations(data.get("recommendations"), by_id, notes),
        "warnings": [w for w in (_text(x, 300) for x in _list(data.get("warnings"))[:8]) if w],
    }
    return clean, list(dict.fromkeys(notes))
