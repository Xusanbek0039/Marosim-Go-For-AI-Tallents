"""Mounted at ``/api/v1/admin/backup/ceremonies/<ceremony_id>/media/``."""

from django.urls import path

from .views import AdminBackupMediaViewSet

urlpatterns = [
    path("", AdminBackupMediaViewSet.as_view({"get": "list"}), name="admin-backup-media-list"),
    path("<uuid:media_id>/", AdminBackupMediaViewSet.as_view({"delete": "destroy"}), name="admin-backup-media-detail"),
    path(
        "<uuid:media_id>/thumbnail/",
        AdminBackupMediaViewSet.as_view({"get": "thumbnail"}),
        name="admin-backup-media-thumbnail",
    ),
    path(
        "<uuid:media_id>/stream/", AdminBackupMediaViewSet.as_view({"get": "stream"}), name="admin-backup-media-stream"
    ),
    path(
        "<uuid:media_id>/download/",
        AdminBackupMediaViewSet.as_view({"get": "download"}),
        name="admin-backup-media-download",
    ),
]
