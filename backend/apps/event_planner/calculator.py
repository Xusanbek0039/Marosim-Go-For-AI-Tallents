"""Deterministic budget calculator — the only place planner money is added up.

Rules (all amounts ``Decimal``, currency UZS, rounded to 0.01 half-up per line):

* a line is ``unit_price × quantity``; a per-guest line (menu per person) uses the plan's ``guest_count``
  as quantity, so changing the guest count re-prices every such line;
* a price range (``unit_price_max``) gives separate min and max line totals;
* lines marked ``is_included_in_package`` cost 0 (already inside the venue package) and inactive lines
  are not summed — nothing is counted twice;
* the contingency reserve is ``reserve_percent`` of the subtotal and is never a budget item;
* ``remaining = budget − total``; an overrun is reported with its amount and the biggest lines, and cut
  suggestions are only *offered* (never applied here).

The AI never supplies totals: proposals are run through this same calculator before they are shown.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import RESERVE_RECOMMENDED, BudgetCategory, PriceStatus

CENT = Decimal("0.01")
ZERO = Decimal("0")


def q(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money(value: Decimal | None) -> str | None:
    """Exact JSON representation (DRF would turn a Decimal into a float)."""
    return None if value is None else str(q(value))


def human(value: Decimal) -> str:
    """Amount for Uzbek message text: ``5400000.00`` -> ``5 400 000``, ``1500.50`` -> ``1 500,50``."""
    whole, frac = f"{q(value):.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", " ")
    return whole if frac == "00" else f"{whole},{frac}"


@dataclass
class Line:
    category: str
    title: str
    unit_price: Decimal
    quantity: Decimal = Decimal("1")
    per_guest: bool = False
    unit_price_max: Decimal | None = None
    is_included_in_package: bool = False
    is_active: bool = True
    price_status: str = PriceStatus.ESTIMATED
    actual_amount: Decimal | None = None
    id: str | None = None

    @classmethod
    def of(cls, item) -> "Line":
        return cls(
            id=str(item.pk) if getattr(item, "pk", None) else None,
            category=item.category,
            title=item.title,
            unit_price=item.unit_price,
            quantity=item.quantity,
            per_guest=item.per_guest,
            unit_price_max=item.unit_price_max,
            is_included_in_package=item.is_included_in_package,
            is_active=item.is_active,
            price_status=item.price_status,
            actual_amount=item.actual_amount,
        )


def check_line(line: Line) -> None:
    """Reject negative or illogical values (the serializers check the same before saving)."""
    if line.unit_price < 0 or (line.unit_price_max is not None and line.unit_price_max < 0):
        raise ValueError("negative_price")
    if line.unit_price_max is not None and line.unit_price_max < line.unit_price:
        raise ValueError("price_range_inverted")
    if not line.per_guest and line.quantity <= 0:
        raise ValueError("quantity_not_positive")
    if line.category == BudgetCategory.CONTINGENCY:
        raise ValueError("contingency_is_computed")


def effective_quantity(line: Line, guest_count: int | None) -> Decimal | None:
    if line.per_guest:
        return Decimal(guest_count) if guest_count else None
    return Decimal(line.quantity)


def line_totals(line: Line, guest_count: int | None) -> tuple[Decimal, Decimal]:
    """``(min, max)`` cost of one line as it counts toward the plan total."""
    check_line(line)
    if line.is_included_in_package or not line.is_active:
        return ZERO, ZERO
    qty = effective_quantity(line, guest_count)
    if qty is None:  # per-guest line without a guest count: cannot be priced yet
        return ZERO, ZERO
    low = q(line.unit_price * qty)
    high = q((line.unit_price_max if line.unit_price_max is not None else line.unit_price) * qty)
    return low, high


def _warn(code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, **extra}


def summarize(
    lines: list[Line],
    *,
    guest_count: int | None,
    total_budget: Decimal | None,
    reserve_percent: Decimal,
    currency: str = "UZS",
) -> dict:
    """Everything the budget dashboard shows, recomputed from scratch on every call."""
    labels = dict(BudgetCategory.choices)
    by_category: dict[str, dict] = {}
    by_status = {s: ZERO for s in PriceStatus.values}
    priced: list[tuple[Line, Decimal, Decimal]] = []
    warnings: list[dict] = []
    needs_guests = False
    actual_total = ZERO
    has_actual = False

    for line in lines:
        low, high = line_totals(line, guest_count)
        if line.per_guest and not guest_count and line.is_active and not line.is_included_in_package:
            needs_guests = True
        bucket = by_category.setdefault(
            line.category,
            {
                "category": line.category,
                "label": labels.get(line.category, line.category),
                "min": ZERO,
                "max": ZERO,
                "verified": ZERO,
                "estimated": ZERO,
                "pending": ZERO,
                "actual": ZERO,
                "count": 0,
            },
        )
        bucket["count"] += 1
        bucket["min"] += low
        bucket["max"] += high
        bucket[line.price_status.lower()] += low
        by_status[line.price_status] += low
        if line.actual_amount is not None:
            has_actual = True
            bucket["actual"] += q(line.actual_amount)
            actual_total += q(line.actual_amount)
        if high > 0:
            priced.append((line, low, high))

    subtotal_min = sum((b["min"] for b in by_category.values()), ZERO)
    subtotal_max = sum((b["max"] for b in by_category.values()), ZERO)
    pct = Decimal(reserve_percent)
    reserve_min = q(subtotal_min * pct / 100)
    reserve_max = q(subtotal_max * pct / 100)
    total_min = subtotal_min + reserve_min
    total_max = subtotal_max + reserve_max

    low_pct, high_pct = RESERVE_RECOMMENDED
    if lines and not (low_pct <= pct <= high_pct):
        warnings.append(
            _warn("reserve_outside_recommended", f"Zaxira {low_pct}–{high_pct}% oralig'ida bo'lishi tavsiya etiladi.")
        )
    if needs_guests:
        warnings.append(
            _warn(
                "guest_count_missing", "Mehmonlar soni kiritilmagan: kishi boshiga hisoblanadigan bandlar 0 deb olindi."
            )
        )
    if any(line.price_status == PriceStatus.PENDING and line.is_active for line in lines):
        warnings.append(_warn("prices_pending", "Ba'zi narxlar hali aniqlanmagan — jami summa o'zgarishi mumkin."))
    if by_status[PriceStatus.ESTIMATED] > 0:
        warnings.append(_warn("contains_estimates", "Jami summada taxminiy narxlar bor — bu aniq narx emas."))

    biggest = sorted(priced, key=lambda row: row[2], reverse=True)[:3]
    budget = q(total_budget) if total_budget is not None else None
    overrun_min = overrun_max = ZERO
    if not lines:
        status = "NO_ITEMS"
    elif budget is None:
        status = "NO_BUDGET"
    elif total_min > budget:
        status = "OVER"
    elif total_max > budget:
        status = "AT_RISK"
    else:
        status = "WITHIN"
    if budget is not None:
        overrun_min = max(ZERO, total_min - budget)
        overrun_max = max(ZERO, total_max - budget)

    if status in ("OVER", "AT_RISK"):
        warnings.append(
            _warn(
                "budget_overrun",
                f"Byudjetdan {human(overrun_max)} so'mgacha oshib ketish bor.",
                overrun_min=money(overrun_min),
                overrun_max=money(overrun_max),
            )
        )

    return {
        "currency": currency,
        "guest_count": guest_count,
        "total_budget": money(budget),
        "subtotal_min": money(subtotal_min),
        "subtotal_max": money(subtotal_max),
        "reserve_percent": money(pct),
        "reserve_recommended": [money(low_pct), money(high_pct)],
        "reserve_min": money(reserve_min),
        "reserve_max": money(reserve_max),
        "total_min": money(total_min),
        "total_max": money(total_max),
        "is_range": total_min != total_max,
        "remaining_min": money(budget - total_max) if budget is not None else None,
        "remaining_max": money(budget - total_min) if budget is not None else None,
        "status": status,
        "overrun_min": money(overrun_min),
        "overrun_max": money(overrun_max),
        "by_category": [
            {**b, **{k: money(b[k]) for k in ("min", "max", "verified", "estimated", "pending", "actual")}}
            for b in sorted(by_category.values(), key=lambda b: list(labels).index(b["category"]))
        ]
        + (
            [
                {
                    "category": BudgetCategory.CONTINGENCY,
                    "label": labels[BudgetCategory.CONTINGENCY],
                    "min": money(reserve_min),
                    "max": money(reserve_max),
                    "verified": "0.00",
                    "estimated": money(reserve_min),
                    "pending": "0.00",
                    "actual": "0.00",
                    "count": 0,
                }
            ]
            if lines
            else []
        ),
        "by_price_status": {k.lower(): money(v) for k, v in by_status.items()},
        "actual_total": money(actual_total) if has_actual else None,
        "biggest_items": [
            {"id": line.id, "title": line.title, "category": line.category, "min": money(low), "max": money(high)}
            for line, low, high in biggest
        ],
        "cut_suggestions": cut_suggestions(lines, guest_count) if status in ("OVER", "AT_RISK") else [],
        "warnings": warnings,
    }


def cut_suggestions(lines: list[Line], guest_count: int | None) -> list[dict]:
    """Options the user may apply — exact savings where they can be computed, nothing applied here."""
    out: list[dict] = []
    per_guest = [line for line in lines if line.per_guest and line.is_active and not line.is_included_in_package]
    if guest_count and guest_count >= 20 and per_guest:
        fewer = max(1, guest_count // 10)
        saving = sum((q(line.unit_price * fewer) for line in per_guest), ZERO)
        out.append(
            {
                "code": "reduce_guests",
                "message": f"Mehmonlar sonini {fewer} kishiga kamaytirish kamida {human(saving)} so'm tejaydi.",
                "saving_min": money(saving),
            }
        )
    optional = [
        line
        for line in lines
        if line.is_active
        and not line.is_included_in_package
        and line.category
        in (
            BudgetCategory.DECOR,
            BudgetCategory.ARTISTS,
            BudgetCategory.TRANSPORT,
            BudgetCategory.CAKE_EXTRAS,
            BudgetCategory.INVITATIONS_OTHER,
        )
    ]
    for line in sorted(optional, key=lambda line: line_totals(line, guest_count)[1], reverse=True)[:2]:
        low, high = line_totals(line, guest_count)
        if high <= 0:
            continue
        out.append(
            {
                "code": "drop_or_downgrade",
                "item_id": line.id,
                "message": (
                    f'"{line.title}" bandini olib tashlash kamida {human(low)} so\'m tejaydi '
                    "(yoki arzonroq variant tanlang)."
                ),
                "saving_min": money(low),
            }
        )
    return out
