"""Backup endpoints.

* ``me/backup/``                       — the couple's own Backup state (banner in the user panel).
* ``me/notifications/``                — in-app notifications (+ ``read``, ``read-all``).
* ``admin/backup/``                    — Admin / Super Admin: every couple's state, actions.
* ``admin/backup/ceremonies/{id}/media/…`` — Admin / Super Admin view and remove media kept in Backup.
"""

import datetime

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.access import AccessNote
from apps.accounts.models import Role, User
from apps.accounts.permissions import HasAdminPermission
from apps.audit.services import AuditAction, record
from apps.ceremonies.models import AccessRole, Ceremony, CeremonyOwnership, OwnershipStatus
from apps.ceremonies.permissions import IsClientUser
from apps.media.models import CeremonyMedia, MediaKind, MediaStatus
from apps.media.viewing import MyMediaViewSet

from . import services
from .models import BackupState, Notification

UUID_RE = "[0-9a-fA-F-]{36}"
STATES = [services.NO_VIDEO, services.TRIAL, services.PREMIUM, services.BACKUP]


# =================================================================== user
class MyBackupSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=STATES)
    in_backup = serializers.BooleanField()
    grace_ends_at = serializers.DateTimeField(allow_null=True)
    premium_until = serializers.DateTimeField(allow_null=True)
    backup_since = serializers.DateTimeField(allow_null=True)


class MyBackupView(APIView):
    permission_classes = [IsClientUser]
    access_notes = {"*": AccessNote(ownership="Faqat o'z holati.")}

    @extend_schema(summary="Mening Backup holatim", tags=["me"], responses=MyBackupSerializer)
    def get(self, request):
        state = BackupState.objects.filter(user=request.user).first()
        data = {
            "status": services.status_of(state, request.user),
            "in_backup": bool(state and state.in_backup),
            "grace_ends_at": state.grace_ends_at if state else None,
            "premium_until": services.premium_until(request.user),
            "backup_since": state.backup_since if state else None,
        }
        return Response(MyBackupSerializer(data).data)


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "link", "read_at", "created_at"]
        read_only_fields = fields


@extend_schema_view(list=extend_schema(summary="Bildirishnomalarim", tags=["me"]))
class MyNotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsClientUser]
    pagination_class = None
    filter_backends = []
    queryset = Notification.objects.none()
    lookup_value_regex = UUID_RE
    access_notes = {"*": AccessNote(ownership="Faqat o'z bildirishnomalari; boshqasiniki 404.")}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(user=self.request.user)[:50]

    @extend_schema(summary="O'qildi deb belgilash", tags=["me"], request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        row = get_object_or_404(Notification, pk=pk, user=request.user)
        if row.read_at is None:
            row.read_at = timezone.now()
            row.save(update_fields=["read_at", "updated_at"])
        return Response(NotificationSerializer(row).data)

    @extend_schema(summary="Hammasini o'qildi deb belgilash", tags=["me"], request=None, responses={204: None})
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


# ================================================================== admin
class AdminBackupRowSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="user.pk")
    full_name = serializers.CharField()
    phone_number = serializers.CharField(source="user.phone_number", allow_null=True)
    status = serializers.ChoiceField(choices=STATES)
    first_video_at = serializers.DateTimeField(allow_null=True)
    grace_started_at = serializers.DateTimeField(allow_null=True)
    grace_ends_at = serializers.DateTimeField(allow_null=True)
    grace_reason = serializers.CharField(allow_blank=True)
    backup_since = serializers.DateTimeField(allow_null=True)
    premium_until = serializers.DateTimeField(allow_null=True)
    ceremonies = serializers.IntegerField()
    videos = serializers.IntegerField()
    media_bytes = serializers.IntegerField()


class DateBodySerializer(serializers.Serializer):
    until = serializers.DateTimeField(required=False, help_text="Yangi tugash sanasi (ISO)")
    days = serializers.IntegerField(required=False, min_value=1, max_value=3650, help_text="Yoki bugundan N kun")
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)

    def validate(self, attrs):
        if not attrs.get("until") and not attrs.get("days"):
            raise serializers.ValidationError({"until": ["Sana yoki kunlar sonini kiriting."]})
        if not attrs.get("until"):
            attrs["until"] = timezone.now() + datetime.timedelta(days=attrs["days"])
        return attrs


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


def _owned(user_ids):
    return CeremonyOwnership.objects.filter(user_id__in=user_ids, status=OwnershipStatus.ACCEPTED)


def _rows(users: list[User]) -> list[dict]:
    ids = [u.pk for u in users]
    states = {s.user_id: s for s in BackupState.objects.filter(user_id__in=ids)}
    media = {
        r["ceremony__ownerships__user_id"]: r
        for r in CeremonyMedia.objects.filter(
            ceremony__ownerships__user_id__in=ids,
            ceremony__ownerships__status=OwnershipStatus.ACCEPTED,
            status=MediaStatus.READY,
        )
        .values("ceremony__ownerships__user_id")
        .annotate(
            videos=Count("id", filter=Q(kind=MediaKind.VIDEO)),
            size=Sum("size_bytes"),
            ceremonies=Count("ceremony", distinct=True),
        )
    }
    rows = []
    for u in users:
        st = states.get(u.pk)
        m = media.get(u.pk) or {}
        rows.append(
            {
                "user": u,
                "full_name": f"{u.first_name} {u.last_name}".strip(),
                "status": services.status_of(st, u),
                "first_video_at": st.first_video_at if st else None,
                "grace_started_at": st.grace_started_at if st else None,
                "grace_ends_at": st.grace_ends_at if st else None,
                "grace_reason": st.grace_reason if st else "",
                "backup_since": st.backup_since if st else None,
                "premium_until": services.premium_until(u),
                "ceremonies": m.get("ceremonies") or 0,
                "videos": m.get("videos") or 0,
                "media_bytes": m.get("size") or 0,
            }
        )
    return rows


@extend_schema_view(
    list=extend_schema(
        summary="Foydalanuvchilarning Backup holati",
        tags=["admin-backup"],
        parameters=[
            OpenApiParameter("status", str, enum=STATES),
            OpenApiParameter("search", str, description="Ism yoki telefon"),
        ],
        responses=AdminBackupRowSerializer(many=True),
    ),
    retrieve=extend_schema(
        summary="Foydalanuvchi Backup tafsiloti", tags=["admin-backup"], responses=OpenApiTypes.OBJECT
    ),
)
class AdminBackupViewSet(viewsets.GenericViewSet):
    serializer_class = AdminBackupRowSerializer
    permission_classes = [HasAdminPermission]
    permission_module = "backup"
    action_permissions = {
        "list": "backup.view",
        "retrieve": "backup.view",
        "summary": "backup.view",
        "sync_all": "backup.manage",
        "put_in_backup": "backup.manage",
        "release": "backup.manage",
        "extend_premium": "backup.manage",
    }
    queryset = User.objects.none()
    lookup_value_regex = UUID_RE
    access_notes = {"*": AccessNote(ownership="Barcha mijoz (USER) hisoblarining Backup holati.")}

    def _users(self):
        return services.candidates().order_by("first_name", "last_name")

    def list(self, request):
        qs = self._users()
        term = (request.query_params.get("search") or "").strip()
        if term:
            qs = qs.filter(
                Q(first_name__icontains=term) | Q(last_name__icontains=term) | Q(phone_number__icontains=term)
            )
        wanted = request.query_params.get("status")
        if wanted == services.BACKUP:
            qs = qs.filter(backup_state__in_backup=True)
        page = self.paginate_queryset(qs)
        users = list(page if page is not None else qs)
        for u in users:  # the list is always current, even between cron runs
            services.sync(u)
        rows = _rows(users)
        if wanted and wanted != services.BACKUP:
            rows = [r for r in rows if r["status"] == wanted]
        data = AdminBackupRowSerializer(rows, many=True).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    def _user(self, pk) -> User:
        return get_object_or_404(User, pk=pk, role=Role.USER)

    def retrieve(self, request, pk=None):
        user = self._user(pk)
        services.sync(user)
        row = AdminBackupRowSerializer(_rows([user])[0]).data
        ceremonies = Ceremony.objects.filter(pk__in=_owned([user.pk]).values("ceremony_id")).annotate(
            media_count=Count("media", filter=Q(media__status=MediaStatus.READY)),
            video_count=Count("media", filter=Q(media__status=MediaStatus.READY, media__kind=MediaKind.VIDEO)),
        )
        row["ceremony_list"] = [
            {
                "id": str(c.pk),
                "title": getattr(c, "title", "") or str(c),
                "event_date": getattr(c, "event_date", None),
                "media_count": c.media_count,
                "video_count": c.video_count,
            }
            for c in ceremonies
        ]
        return Response(row)

    @extend_schema(summary="Holatlar soni", tags=["admin-backup"], responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"])
    def summary(self, request):
        users = list(self._users())
        counts = {s: 0 for s in STATES}
        for row in _rows(users):
            counts[row["status"]] += 1
        return Response(counts)

    @extend_schema(
        summary="Hammasini hozir qayta hisoblash", tags=["admin-backup"], request=None, responses=OpenApiTypes.OBJECT
    )
    @action(detail=False, methods=["post"], url_path="sync")
    def sync_all(self, request):
        return Response(services.sync_all())

    @extend_schema(
        summary="Backup rejimiga o'tkazish",
        tags=["admin-backup"],
        request=NoteSerializer,
        responses=AdminBackupRowSerializer,
    )
    @action(detail=True, methods=["post"], url_path="backup")
    def put_in_backup(self, request, pk=None):
        user = self._user(pk)
        body = NoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.put_in_backup(user, request.user, body.validated_data.get("note", ""))
        record(request, AuditAction.UPDATE, user, changes={"backup": [False, True]}, target_label="Backup rejimi")
        return Response(AdminBackupRowSerializer(_rows([user])[0]).data)

    @extend_schema(
        summary="Backupdan chiqarish / bepul muddatni belgilash",
        tags=["admin-backup"],
        request=DateBodySerializer,
        responses=AdminBackupRowSerializer,
    )
    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        user = self._user(pk)
        body = DateBodySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        until = body.validated_data["until"]
        services.release(user, request.user, until, body.validated_data.get("note", ""))
        record(
            request,
            AuditAction.UPDATE,
            user,
            changes={"backup": "released", "until": until.isoformat()},
            target_label="Backup rejimi",
        )
        return Response(AdminBackupRowSerializer(_rows([user])[0]).data)

    @extend_schema(
        summary="Premium tugash sanasini o'zgartirish (uzaytirish)",
        tags=["admin-backup"],
        request=DateBodySerializer,
        responses=AdminBackupRowSerializer,
    )
    @action(detail=True, methods=["post"], url_path="extend-premium")
    def extend_premium(self, request, pk=None):
        user = self._user(pk)
        body = DateBodySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        sub = services.extend_premium(user, body.validated_data["until"])
        record(
            request,
            AuditAction.UPDATE,
            sub,
            changes={"ends_at": sub.ends_at.isoformat()},
            target_label="Premium muddati",
        )
        return Response(AdminBackupRowSerializer(_rows([user])[0]).data)


class AdminBackupMediaViewSet(MyMediaViewSet):
    """Admin / Super Admin see (originals) and remove the media of any couple's ceremony."""

    permission_classes = [HasAdminPermission]
    permission_module = "backup"
    action_permissions = {
        "list": "backup.view",
        "thumbnail": "backup.view",
        "stream": "backup.view",
        "download": "backup.view",
        "destroy": "backup.manage",
    }
    access_notes = {"*": AccessNote(ownership="Istalgan mijoz marosimining media fayllari (faqat ruxsati borlar).")}

    def _ceremony_and_role(self):
        ceremony = get_object_or_404(Ceremony, pk=self.kwargs["ceremony_id"])
        return ceremony, AccessRole.OWNER

    def _clean(self, role) -> bool:
        return True  # staff see the originals

    @extend_schema(summary="Faylni o'chirish (Drive savatchasiga)", tags=["admin-backup"], responses={204: None})
    def destroy(self, request, ceremony_id=None, media_id=None):
        from apps.media import deletion
        from apps.media import services as media_services
        from apps.storage.google import GoogleError
        from apps.storage.services import StorageError, access_credentials

        ceremony, _ = self._ceremony_and_role()
        media = get_object_or_404(CeremonyMedia, pk=media_id, ceremony=ceremony, status=MediaStatus.READY)
        try:
            creds = access_credentials()
            deletion._trash(creds, media.drive_file_id)
            deletion._trash(creds, media.wm_drive_file_id)
        except (StorageError, GoogleError) as exc:
            raise media_services._storage_error(exc) from None
        now = timezone.now()
        CeremonyMedia.objects.filter(pk=media.pk).update(status=MediaStatus.DELETED, deleted_at=now, updated_at=now)
        record(
            request,
            AuditAction.DELETE,
            media,
            changes={"ceremony": str(ceremony.pk), "by": "backup-admin"},
            target_label=media.original_name,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
