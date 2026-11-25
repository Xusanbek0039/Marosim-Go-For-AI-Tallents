"""Real platform services the planner may recommend — read only through the public querysets.

Only what customers can already see is used: approved + active venues and their active halls
(``venues.scheduling``), active studios (``studios.services``), public ratings (``reviews``). Prices come
from the database (hall price → venue price) and are stamped with the time they were read. Availability is
shown only from the server's own calendar data, never guessed:

* hall: free sessions on the plan's date (no CONFIRMED / BLOCKED booking) — a *request* may still be refused;
* studio: day marked busy / off, or how many ceremonies it already has that day (studios have no booking flow).

Nothing here writes; bookings are made only by the existing ``me/venue-bookings`` flow after the user confirms.
"""

import datetime
import uuid
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.reviews.models import TargetKind
from apps.reviews.services import stats_map
from apps.studios import services as studio_services
from apps.studios.models import Studio
from apps.venues import scheduling
from apps.venues.models import HallSession, Region, VenueHall

from .calculator import money
from .models import SourceKind

MAX_RESULTS = 20
SORTS = ("price", "-price", "rating", "capacity")


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def public_halls():
    venues = scheduling.public_venues()
    return VenueHall.objects.filter(venue__in=venues, deleted_at__isnull=True, is_active=True).select_related("venue")


def resolve_hall(pk) -> VenueHall | None:
    pk = _uuid(pk)
    return public_halls().filter(pk=pk).first() if pk else None


def resolve_studio(pk) -> Studio | None:
    pk = _uuid(pk)
    return studio_services.public_studios().filter(pk=pk).first() if pk else None


def _bookable_date(date: datetime.date | None) -> datetime.date | None:
    if date is None:
        return None
    today = scheduling.today()
    if date < today or date > today + datetime.timedelta(days=scheduling.MAX_DAYS_AHEAD):
        return None
    return date


def _hall_rows(halls: list[VenueHall], date: datetime.date | None) -> list[dict]:
    checked_at = timezone.now().isoformat()
    venue_ids = list({h.venue_id for h in halls})
    stats = stats_map(TargetKind.VENUE, venue_ids)
    sessions_by_hall: dict = {}
    bookable = _bookable_date(date)
    if bookable is not None:
        for s in HallSession.objects.filter(hall__in=halls, is_active=True).order_by("starts_at"):
            sessions_by_hall.setdefault(s.hall_id, []).append(s)
        taken = scheduling.taken_slots([h.pk for h in halls], bookable, bookable)
    rows = []
    for hall in halls:
        venue = hall.venue
        availability: dict = {"checked": False, "date": date.isoformat() if date else None, "free_sessions": []}
        if bookable is not None:
            free = [s for s in sessions_by_hall.get(hall.pk, []) if (s.pk, bookable) not in taken]
            availability = {
                "checked": True,
                "date": bookable.isoformat(),
                "free_sessions": [
                    {
                        "id": str(s.pk),
                        "name": s.name,
                        "starts_at": s.starts_at.strftime("%H:%M"),
                        "ends_at": s.ends_at.strftime("%H:%M"),
                    }
                    for s in free
                ],
            }
        stat = stats.get(venue.pk, {})
        rows.append(
            {
                "kind": SourceKind.VENUE_HALL,
                "id": str(hall.pk),
                "venue_id": str(venue.pk),
                "name": f"{venue.name} · {hall.name}",
                "venue_name": venue.name,
                "hall_name": hall.name,
                "region": venue.region,
                "region_label": Region(venue.region).label if venue.region in Region.values else venue.region,
                "district": venue.district,
                "address": venue.address,
                "capacity": hall.capacity,
                "price": money(hall.effective_base_price),
                "price_note": "Boshlang'ich narx (bir smena uchun), to'yxona tasdig'igacha o'zgarishi mumkin.",
                "price_source": "platform",
                "price_checked_at": checked_at,
                "currency": venue.currency,
                "rating_avg": stat.get("rating_avg"),
                "rating_count": stat.get("rating_count", 0),
                "availability": availability,
                "url": f"/toyxonalar/{venue.pk}",
            }
        )
    return rows


def search_halls(
    *,
    region: str = "",
    guests: int | None = None,
    date: datetime.date | None = None,
    budget_max=None,
    q: str = "",
    sort: str = "price",
    limit: int = MAX_RESULTS,
) -> list[dict]:
    halls = public_halls()
    if region in Region.values:
        halls = halls.filter(venue__region=region)
    if guests:
        halls = halls.filter(capacity__gte=guests)
    if q:
        halls = halls.filter(Q(venue__name__icontains=q) | Q(venue__district__icontains=q) | Q(name__icontains=q))
    halls = list(halls.order_by("venue__base_price", "created_at")[:200])
    rows = _hall_rows(halls, date)
    if budget_max is not None:
        rows = [r for r in rows if Decimal(r["price"]) <= Decimal(budget_max)]
    key = {
        "price": lambda r: Decimal(r["price"]),
        "-price": lambda r: -Decimal(r["price"]),
        "rating": lambda r: -(r["rating_avg"] or 0),
        "capacity": lambda r: r["capacity"],
    }[sort if sort in SORTS else "price"]
    # With a date, halls that still have a free session come first; a fully booked hall stays visible, marked.
    rows.sort(key=lambda r: (0 if (date is None or r["availability"]["free_sessions"]) else 1, key(r)))
    return rows[:limit]


def _studio_rows(studios: list[Studio], date: datetime.date | None) -> list[dict]:
    stats = stats_map(TargetKind.STUDIO, [s.pk for s in studios])
    rows = []
    for studio in studios:
        availability: dict = {"checked": False, "date": date.isoformat() if date else None, "state": "UNKNOWN"}
        if date is not None:
            data = studio_services.schedule(studio, date, date)
            iso = date.isoformat()
            if data["days"].get(iso) == "OFF" or date.weekday() in data["off_weekdays"]:
                state = "OFF"
            elif data["days"].get(iso) == "BUSY":
                state = "BUSY"
            elif data["busy"].get(iso):
                state = "HAS_EVENTS"
            else:
                state = "FREE_ON_CALENDAR"
            availability = {
                "checked": True,
                "date": iso,
                "state": state,
                "events_that_day": data["busy"].get(iso, 0),
            }
        stat = stats.get(studio.pk, {})
        rows.append(
            {
                "kind": SourceKind.STUDIO,
                "id": str(studio.pk),
                "name": studio.name,
                "address": studio.address,
                "price": None,
                "price_note": "Studiya narxi platformada ko'rsatilmagan — studiyaning o'zidan so'rang.",
                "price_source": None,
                "price_checked_at": None,
                "currency": "UZS",
                "rating_avg": stat.get("rating_avg"),
                "rating_count": stat.get("rating_count", 0),
                "availability": availability,
                "url": f"/studiyalar/{studio.pk}",
            }
        )
    return rows


def search_studios(*, q: str = "", date: datetime.date | None = None, limit: int = MAX_RESULTS) -> list[dict]:
    studios = studio_services.public_studios()
    if q:
        studios = studios.filter(Q(name__icontains=q) | Q(address__icontains=q))
    studios = list(studios.order_by("name")[:100])
    rows = _studio_rows(studios, date)
    rows.sort(key=lambda r: (-(r["rating_avg"] or 0), -r["rating_count"], r["name"]))
    return rows[:limit]


def compare(ids, *, date: datetime.date | None = None) -> list[dict]:
    """Rows for the given hall / studio ids, in the given order; unknown or hidden ids are left out."""
    wanted = [u for u in (_uuid(i) for i in ids) if u][:6]
    halls = {h.pk: h for h in public_halls().filter(pk__in=wanted)}
    studios = {s.pk: s for s in studio_services.public_studios().filter(pk__in=wanted)}
    hall_rows = {r["id"]: r for r in _hall_rows(list(halls.values()), date)}
    studio_rows = {r["id"]: r for r in _studio_rows(list(studios.values()), date)}
    return [row for pk in wanted if (row := hall_rows.get(str(pk)) or studio_rows.get(str(pk)))]


def candidates_for(plan, *, limit_halls: int = 8, limit_studios: int = 5) -> list[dict]:
    """What the AI may recommend for this plan: real rows only, each with its id, price and availability."""
    budget_cap = plan.total_budget if plan is not None and plan.total_budget else None
    halls = search_halls(
        region=getattr(plan, "region", "") or "",
        guests=getattr(plan, "guest_count", None),
        date=getattr(plan, "event_date", None),
        budget_max=budget_cap,
        limit=limit_halls,
    )
    studios = search_studios(date=getattr(plan, "event_date", None), limit=limit_studios)
    return halls + studios
