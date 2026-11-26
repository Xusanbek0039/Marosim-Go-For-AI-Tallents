"""Sync tried-on ``SavedLook`` images to the platform Google Drive (``MarosimGo / VirtualTryOn``)."""

import logging
import mimetypes
from pathlib import Path

from apps.storage import folders
from apps.storage.google import GoogleError
from apps.storage.models import StorageStatus
from apps.storage.services import StorageError, connection, gateway

logger = logging.getLogger("apps.virtual_tryon.drive")


def drive_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view" if file_id else ""


def upload_look_to_drive(look) -> bool:
    """Upload ``look.image`` to Google Drive if Drive is connected.

    Never raises: a disconnected or transiently unavailable Drive must not block the user's try-on.
    Returns ``True`` when uploaded (or already synced).
    """
    if look.drive_file_id:
        return True
    if not look.image:
        return False
    try:
        conn = connection()
        if conn.status != StorageStatus.CONNECTED:
            return False
        local_path = Path(look.image.path)
        if not local_path.is_file():
            return False
        folder_id, creds = folders.ensure_path([("virtual_tryon", "VirtualTryOn")])
        mime_type = mimetypes.guess_type(local_path.name)[0] or "image/jpeg"
        ext = local_path.suffix or ".jpg"
        meta = gateway().upload_file(
            creds,
            name=f"tryon_{look.pk}{ext}",
            parent_id=folder_id,
            path=local_path,
            mime_type=mime_type,
            app_properties={
                "kind": "virtual_tryon_look",
                "look_id": str(look.pk),
                "garment_id": str(look.garment_id or ""),
                "user_id": str(look.user_id),
            },
        )
        file_id = str(meta.get("id") or "")
        if not file_id:
            return False
        look.drive_file_id = file_id
        look.drive_web_url = drive_view_url(file_id)
        look.save(update_fields=["drive_file_id", "drive_web_url", "updated_at"])
        return True
    except (StorageError, GoogleError, OSError) as exc:
        logger.warning("Could not upload try-on look %s to Google Drive: %s", look.pk, exc)
        return False
