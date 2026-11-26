"""Plan economics: what a plan costs the platform at full use versus what it brings in.

Unit costs are provider list prices in USD (``settings.PLATFORM_COSTS``) turned into so'm with the
admin-editable rate (``SubscriptionSettings.usd_rate``) and a safety factor. The finance report and
the plan editor show these numbers so a price change is checked against real costs.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from .models import PlanAudience, SubscriptionPlan, SubscriptionSettings

#: Below this margin at full quota use a plan is flagged in the admin panel.
MIN_HEALTHY_MARGIN = Decimal("0.35")


def usd_rate() -> Decimal:
    return SubscriptionSettings.load().usd_rate


def _uzs(usd: float, rate: Decimal, *, safety: bool = True) -> Decimal:
    factor = Decimal(str(settings.PLATFORM_COSTS["SAFETY_FACTOR"])) if safety else Decimal(1)
    return (Decimal(str(usd)) * rate * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def unit_costs(rate: Decimal | None = None) -> dict[str, Decimal]:
    """So'm the platform pays for one AI video / one AI photo / one GB-month of cloud storage."""
    rate = rate or usd_rate()
    cost = settings.PLATFORM_COSTS
    return {
        "ai_video": _uzs(cost["AI_VIDEO_USD"], rate),
        "ai_photo": _uzs(cost["AI_PHOTO_USD"], rate),
        "storage_gb_month": _uzs(cost["STORAGE_GB_MONTH_USD"], rate),
    }


@dataclass(frozen=True)
class PlanEconomics:
    plan: SubscriptionPlan
    price_per_month: Decimal
    max_cost_per_month: Decimal
    margin: Decimal  # 0..1 at full quota use

    @property
    def healthy(self) -> bool:
        return self.margin >= MIN_HEALTHY_MARGIN


def economics(plan: SubscriptionPlan, units: dict[str, Decimal]) -> PlanEconomics:
    per_month = (plan.price / plan.duration_months).quantize(Decimal("1"))
    cost = plan.ai_video_per_month * units["ai_video"] + plan.ai_photo_per_month * units["ai_photo"]
    if plan.audience != PlanAudience.USER:
        # Business galichka: storage of portfolio + ceremony media, ~50 GB a month on average.
        cost += 50 * units["storage_gb_month"]
    margin = (1 - cost / per_month) if per_month else Decimal(0)
    return PlanEconomics(plan, per_month, cost, margin.quantize(Decimal("0.001")))


def all_plan_economics() -> list[PlanEconomics]:
    units = unit_costs()
    return [economics(p, units) for p in SubscriptionPlan.objects.filter(is_active=True)]
