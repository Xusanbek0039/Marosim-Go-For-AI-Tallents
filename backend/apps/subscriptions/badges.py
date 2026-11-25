"""Read-only paid badges. Payment never implies identity or phone verification."""

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import serializers

from .models import Subscription, SubscriptionStatus


class PaidBadgeSerializer(serializers.Serializer):
    is_verified = serializers.SerializerMethodField(
        help_text="Faol pulli obuna / biznes galichkasi (shaxs tasdig'i emas)"
    )

    def get_is_verified(self, obj) -> bool:
        model = obj._meta.model_name
        target = {"user": "user", "studio": "studio", "venue": "venue"}[model]
        key = f"_paid_badges_{target}"
        cache = self.context.setdefault(key, {})
        if obj.pk not in cache:
            rows = self._batch_rows(obj)
            ids = [row.pk for row in rows if type(row) is type(obj)]
            if obj.pk not in ids:
                ids.append(obj.pk)
            now = timezone.now()
            qs = Subscription.objects.filter(
                status=SubscriptionStatus.ACTIVE, starts_at__lte=now, ends_at__gt=now, **{f"{target}_id__in": ids}
            )
            if target == "user":
                qs = qs.filter(studio__isnull=True, venue__isnull=True)
            verified = set(qs.values_list(f"{target}_id", flat=True))
            cache.update({pk: pk in verified for pk in ids})
        return cache[obj.pk] and getattr(obj, "is_active", True) and not obj.is_deleted

    def _batch_rows(self, obj) -> list:
        """The rows whose badges are looked up together with ``obj``'s, in one query.

        * directly inside a list (``many=True``): every row of that list;
        * nested inside a listed row (e.g. ``Studio.responsible_user`` in the studio list): the same
          attribute (``source``) of every row of the outer list;
        * otherwise just ``obj``.

        DRF hands the outer list to the per-row serializer as well, so a candidate list may hold
        rows of another type; those are mapped through ``source`` instead of used directly.
        """
        kind = type(obj)
        source = getattr(self, "source", None)
        mappable = bool(source) and "." not in source and source != "*"
        candidates = (
            getattr(self.parent, "instance", None),
            getattr(getattr(self.parent, "parent", None), "instance", None),
        )
        for rows in candidates:
            if not isinstance(rows, (list, tuple, QuerySet)):
                continue
            rows = list(rows)
            if any(type(row) is kind for row in rows):
                return rows
            if mappable:
                related = [getattr(row, source, None) for row in rows]
                if any(type(row) is kind for row in related):
                    return related
        return [obj]
