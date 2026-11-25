"""List endpoints must not run extra queries per row (N+1).

Found by measuring every parameterless GET list endpoint with 1 vs 6 rows: these four grew linearly
(2-3 queries per ceremony, 2 per venue, 1 per studio). Each test measures the endpoint, adds rows,
and requires the same query count.
"""

from datetime import date, time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Role
from apps.ceremonies.models import AccessRole, Ceremony, CeremonyInvitation, CeremonyOwnership, InvitationStatus
from apps.ceremonies.ownership import default_expiry, seal_identifier
from apps.studios.models import StudioMembership
from apps.venues.models import HallSession, Venue, VenueHall, VenueMembership
from tests.conftest import subscribe


def queries(client, path) -> int:
    client.get(path)  # warm-up: the first request of a test fills one-off caches
    with CaptureQueriesContext(connection) as ctx:
        res = client.get(path)
    assert res.status_code == 200, res.data
    return len(ctx.captured_queries)


@pytest.fixture
def studio_world(make_user, make_studio):
    owner = make_user(Role.STUDIO)
    studio = make_studio(owner)
    StudioMembership.objects.create(studio=studio, user=owner, role="OWNER")
    return owner, studio


def add_ceremony(studio, owner, make_user, i):
    c = Ceremony.objects.create(
        studio=studio,
        title=f"To'y {i}",
        event_date=date.today() + timedelta(days=10 + i),
        created_by=owner,
        status="READY",
    )
    CeremonyOwnership.objects.create(
        ceremony=c, user=make_user(), status="ACCEPTED", owner_type="BRIDE", accepted_at=timezone.now()
    )
    CeremonyInvitation.objects.create(
        ceremony=c,
        requested_role=AccessRole.OWNER,
        owner_type="GROOM",
        inviter_kind="STUDIO",
        invited_by=owner,
        status=InvitationStatus.PENDING,
        expires_at=default_expiry(),
        **seal_identifier("PHONE", f"+99890555{i:04d}"),
    )
    return c


CEREMONY_LISTS = [("/api/v1/studios/me/ceremonies/", False), ("/api/v1/ceremonies/", True)]


@pytest.mark.parametrize("path,as_super_admin", CEREMONY_LISTS)
def test_ceremony_lists_do_not_query_per_ceremony(
    path, as_super_admin, studio_world, make_user, super_admin, client_for
):
    owner, studio = studio_world
    client = client_for(super_admin if as_super_admin else owner)
    add_ceremony(studio, owner, make_user, 0)
    one = queries(client, path)
    for i in range(1, 6):
        add_ceremony(studio, owner, make_user, i)
    assert queries(client, path) == one
    # and the summary is still right
    row = client.get(path).data["results"][0]
    assert row["participants_summary"] == {"invited": 1, "active": 1}
    assert row["can_manage"] is True


def add_venue(owner, i):
    venue = Venue.objects.create(
        name=f"To'yxona {i}",
        address="Toshkent",
        capacity_max=250,
        base_price="1000",
        publication_status="APPROVED",
        region="TASHKENT_CITY",
    )
    VenueMembership.objects.create(venue=venue, user=owner, role="OWNER")
    hall = VenueHall.objects.create(venue=venue, name="Zal", capacity=200)
    HallSession.objects.create(hall=hall, name="Kechki", starts_at=time(18), ends_at=time(23))
    return venue


def test_venue_owner_list_does_not_query_per_venue(make_user, client_for):
    owner = make_user(Role.VENUE_OWNER)
    client = client_for(owner)
    add_venue(owner, 0)
    one = queries(client, "/api/v1/venue-owner/venues/")
    for i in range(1, 6):
        add_venue(owner, i)
    assert queries(client, "/api/v1/venue-owner/venues/") == one
    rows = client.get("/api/v1/venue-owner/venues/").data
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert {r["membership_role"] for r in rows} == {"OWNER"} and all(r["membership_capabilities"] for r in rows)


def test_studio_list_does_not_query_per_studio(make_user, make_studio, super_admin, client_for):
    client = client_for(super_admin)

    def add(i):
        owner = make_user(Role.STUDIO)
        if i % 2:
            subscribe(owner)
        make_studio(owner, name=f"Studio {i}")

    add(0)
    one = queries(client, "/api/v1/studios/")
    for i in range(1, 6):
        add(i)
    assert queries(client, "/api/v1/studios/") == one
    badges = sorted(r["responsible_user"]["is_verified"] for r in client.get("/api/v1/studios/").data["results"])
    assert badges == [False, False, False, True, True, True]  # paid users keep their badge
