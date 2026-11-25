"""Studio-side ceremony scoping (which studio member sees / manages which ceremony).

Couple / guest access lives in ``ownership.py`` (rules) and ``invitations.py`` (flows).
"""

from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import Role
from apps.studios.models import StudioMembership
from apps.studios.services import active_memberships

from .models import AccessRole, Ceremony, CeremonyInvitation, CeremonyOwnership, InvitationStatus, OwnershipStatus


# ------------------------------------------------------------------- scoping
def studio_ids(user, managing_only: bool = False) -> list:
    qs = active_memberships(user)
    if managing_only:
        qs = qs.filter(role__in=StudioMembership.MANAGING_ROLES)
    return list(qs.values_list("studio_id", flat=True))


def ceremonies_for(user):
    """Ceremonies a studio member or super admin may see (others: none)."""
    qs = Ceremony.objects.select_related("studio")
    if user.role == Role.SUPER_ADMIN:
        return qs
    if user.role == Role.STUDIO:
        return qs.filter(studio_id__in=studio_ids(user))
    return qs.none()


def _count(model, **filters):
    rows = model.objects.filter(ceremony=OuterRef("pk"), **filters).order_by().values("ceremony")
    return Coalesce(Subquery(rows.annotate(n=Count("pk")).values("n"), output_field=IntegerField()), 0)


def with_participant_counts(qs):
    """Annotate what ``CeremonySerializer.participants_summary`` needs, so a list costs one query
    instead of two COUNTs per ceremony. Same rules as the serializer's per-object fallback."""
    return qs.annotate(
        summary_invited=_count(
            CeremonyInvitation,
            requested_role=AccessRole.OWNER,
            status=InvitationStatus.PENDING,
            expires_at__gt=timezone.now(),
        ),
        summary_active=_count(CeremonyOwnership, status=OwnershipStatus.ACCEPTED),
    )


def can_manage(user, ceremony: Ceremony, managed_studio_ids=None) -> bool:
    """``managed_studio_ids`` lets a caller that checks many ceremonies resolve the user's
    OWNER/MANAGER studios once instead of once per ceremony."""
    if user.role == Role.SUPER_ADMIN:
        return True
    if user.role != Role.STUDIO:
        return False
    ids = studio_ids(user, managing_only=True) if managed_studio_ids is None else managed_studio_ids
    return ceremony.studio_id in ids


def ensure_can_manage(user, ceremony: Ceremony) -> None:
    if not can_manage(user, ceremony):
        raise PermissionDenied("Bu marosimni boshqarish uchun studiyada OWNER yoki MANAGER bo'lishingiz kerak.")
