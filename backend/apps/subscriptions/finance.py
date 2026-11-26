"""Income / expense report of the platform for the admin panel ("Kirim-chiqim").

* Income: subscription payments recorded by admins (``paid_amount`` on ``paid_at``), split into
  couples (USER Premium), studios and venues.
* Expenses: computed AI usage (try-on renders, the AI planner's logged token cost, live Decart
  seconds) converted to so'm at the admin's USD rate, plus costs admins enter by hand (``Expense``).
* Receivables: businesses whose mandatory monthly fee is due (grace / overdue).
"""

import datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from apps.studios.models import Studio
from apps.venues.models import Venue

from . import billing, pricing
from .models import Expense, ExpenseCategory, PlanAudience, Subscription, SubscriptionStatus

ZERO = Decimal("0")


def month_bounds(year: int, month: int) -> tuple[datetime.datetime, datetime.datetime]:
    tz = timezone.get_current_timezone()
    start = datetime.datetime(year, month, 1, tzinfo=tz)
    end = datetime.datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    return start, end


def _income(start, end) -> dict:
    paid = Subscription.objects.filter(
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED],
        paid_amount__isnull=False,
        paid_at__gte=start,
        paid_at__lt=end,
    )
    rows = {r["plan__audience"]: r for r in paid.values("plan__audience").annotate(s=Sum("paid_amount"), n=Count("id"))}
    by = {
        aud: {"amount": (rows.get(aud) or {}).get("s") or ZERO, "count": (rows.get(aud) or {}).get("n") or 0}
        for aud in PlanAudience.values
    }
    return {"total": sum((v["amount"] for v in by.values()), ZERO), "by_audience": by}


def _ai_costs_usd(start, end) -> dict[str, Decimal]:
    from apps.event_planner.models import AIUsageLog
    from apps.virtual_tryon.ai import used_seconds
    from apps.virtual_tryon.models import AiRenderLog, AiTryOnSession, RenderKind, RenderLogStatus

    renders = (
        AiRenderLog.objects.filter(created_at__gte=start, created_at__lt=end, status=RenderLogStatus.DONE)
        .values("kind")
        .annotate(s=Sum("cost_usd"), n=Count("id"))
    )
    by_kind = {r["kind"]: r for r in renders}
    planner = AIUsageLog.objects.filter(created_at__gte=start, created_at__lt=end).aggregate(
        s=Sum("estimated_cost_usd"), n=Count("id")
    )
    sessions = AiTryOnSession.objects.filter(started_at__gte=start, started_at__lt=end)
    live_seconds = sum(used_seconds(s, min(end, timezone.now())) for s in sessions)
    live_usd = Decimal(str(settings.AI_TRYON["PRICE_PER_SECOND_USD"])) * live_seconds
    return {
        "video": (by_kind.get(RenderKind.VIDEO) or {}).get("s") or ZERO,
        "video_count": (by_kind.get(RenderKind.VIDEO) or {}).get("n") or 0,
        "photo": (by_kind.get(RenderKind.PHOTO) or {}).get("s") or ZERO,
        "photo_count": (by_kind.get(RenderKind.PHOTO) or {}).get("n") or 0,
        "planner": planner["s"] or ZERO,
        "planner_count": planner["n"] or 0,
        "live": live_usd,
        "live_seconds": live_seconds,
    }


def _expenses(start, end, rate: Decimal) -> dict:
    usd = _ai_costs_usd(start, end)
    to_uzs = lambda v: (Decimal(v) * rate).quantize(Decimal("1"))  # noqa: E731
    ai = [
        {"key": "ai_video", "label": "AI video kiyib ko'rish (fal.ai Kling)", "count": usd["video_count"],
         "usd": usd["video"], "amount": to_uzs(usd["video"])},
        {"key": "ai_photo", "label": "AI foto kiyib ko'rish (fal.ai FASHN)", "count": usd["photo_count"],
         "usd": usd["photo"], "amount": to_uzs(usd["photo"])},
        {"key": "ai_planner", "label": "AI maslahatchi (token sarfi)", "count": usd["planner_count"],
         "usd": usd["planner"], "amount": to_uzs(usd["planner"])},
        {"key": "ai_live", "label": "Jonli AI kiyib ko'rish (soniya)", "count": usd["live_seconds"],
         "usd": usd["live"], "amount": to_uzs(usd["live"])},
    ]
    manual_qs = Expense.objects.filter(spent_on__gte=start.date(), spent_on__lt=end.date())
    manual = {r["category"]: r["s"] for r in manual_qs.values("category").annotate(s=Sum("amount"))}
    manual_rows = [
        {"category": c, "label": label, "amount": manual.get(c) or ZERO}
        for c, label in ExpenseCategory.choices
        if manual.get(c)
    ]
    ai_total = sum((r["amount"] for r in ai), ZERO)
    manual_total = sum((r["amount"] for r in manual_rows), ZERO)
    return {
        "total": ai_total + manual_total,
        "ai_total": ai_total,
        "manual_total": manual_total,
        "ai": ai,
        "manual": manual_rows,
    }


def receivables() -> dict:
    """Businesses whose mandatory fee is due now (GRACE = will be hidden soon, OVERDUE = hidden)."""
    rows = []
    for kind, qs in (
        ("venue", Venue.objects.filter(deleted_at__isnull=True, is_active=True)),
        ("studio", Studio.objects.filter(deleted_at__isnull=True, is_active=True)),
    ):
        for business in qs.order_by("name"):
            st = billing.standing(**{kind: business})
            if st.state == billing.OK:
                continue
            rows.append(
                {
                    "kind": kind,
                    "id": business.pk,
                    "name": business.name,
                    "state": st.state,
                    "monthly_fee": st.monthly_fee,
                    "paid_until": st.paid_until,
                    "grace_until": st.grace_until,
                }
            )
    paying = {
        kind: Subscription.objects.filter(
            **{f"{kind}__isnull": False},
            status=SubscriptionStatus.ACTIVE,
            starts_at__lte=timezone.now(),
            ends_at__gt=timezone.now(),
        )
        .values(kind)
        .distinct()
        .count()
        for kind in ("venue", "studio")
    }
    return {
        "rows": rows,
        "total_due": sum((Decimal(r["monthly_fee"]) for r in rows), ZERO),
        "paying_venues": paying["venue"],
        "paying_studios": paying["studio"],
        "monthly_recurring": Decimal(
            paying["venue"] * billing.monthly_fee("venue") + paying["studio"] * billing.monthly_fee("studio")
        ),
    }


def report(year: int, month: int, trend_months: int = 6) -> dict:
    rate = pricing.usd_rate()
    start, end = month_bounds(year, month)
    income = _income(start, end)
    expenses = _expenses(start, end, rate)

    trend = []
    y, m = year, month
    for _ in range(trend_months):
        s, e = month_bounds(y, m)
        inc = _income(s, e)["total"]
        exp = _expenses(s, e, rate)["total"]
        trend.append({"month": f"{y:04d}-{m:02d}", "income": inc, "expense": exp, "profit": inc - exp})
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    trend.reverse()

    units = pricing.unit_costs(rate)
    return {
        "month": f"{year:04d}-{month:02d}",
        "usd_rate": rate,
        "income": income,
        "expenses": expenses,
        "profit": income["total"] - expenses["total"],
        "trend": trend,
        "receivables": receivables(),
        "unit_costs": units,
        "plans": [
            {
                "id": e.plan.pk,
                "code": e.plan.code,
                "name": e.plan.name,
                "audience": e.plan.audience,
                "price": e.plan.price,
                "duration_months": e.plan.duration_months,
                "ai_video_per_month": e.plan.ai_video_per_month,
                "ai_photo_per_month": e.plan.ai_photo_per_month,
                "price_per_month": e.price_per_month,
                "max_cost_per_month": e.max_cost_per_month,
                "margin": e.margin,
                "healthy": e.healthy,
            }
            for e in pricing.all_plan_economics()
        ],
    }
