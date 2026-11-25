"""Validation of uploaded garment layers and their anchor points.

Image layers go through ``apps.core.uploads.process_image`` (full decode, size/pixel limits,
metadata stripped, re-encoded as WEBP under a random name), then must still have a real alpha
channel — an opaque photo cannot be worn. GLB files are only checked for the glTF 2.0 header and
size; they are not rendered yet.

Anchor coordinates are normalized to the layer image: ``[x, y]`` with 0..1, x to the right,
y downwards. Body layers also carry ``legs``: ``"joined"`` (skirt, coat tail — default) or
``"split"`` (trousers: each leg follows its own thigh). Sleeve layers must be drawn at the same
pixel scale as the body layer (the renderer scales them across the arm by the body layer's scale).
Sides are the *wearer's* sides: on a front view the wearer's right shoulder is on the image's left.
"""

import io
import json
import struct
import uuid

from django.core.files.base import ContentFile
from PIL import Image
from rest_framework.exceptions import ValidationError

from apps.core.uploads import process_image

from .models import AssetKind

ASSET_MAX_SIDE = 1600
GLB_MAX_BYTES = 25 * 1024 * 1024

BODY_KEYS = ("right_shoulder", "left_shoulder", "right_hip", "left_hip")
LIMB_KEYS = ("start", "end")
LOWER_KEYS = ("right_hip", "left_hip", "right_knee", "left_knee")
ANCHOR_KEYS: dict[str, tuple[str, ...]] = {
    AssetKind.BODY_FRONT: BODY_KEYS,
    AssetKind.BODY_BACK: BODY_KEYS,
    AssetKind.LOWER_BODY: LOWER_KEYS,
    AssetKind.RIGHT_UPPER_ARM: LIMB_KEYS,
    AssetKind.RIGHT_FOREARM: LIMB_KEYS,
    AssetKind.LEFT_UPPER_ARM: LIMB_KEYS,
    AssetKind.LEFT_FOREARM: LIMB_KEYS,
    AssetKind.MODEL_GLB: (),
}
IMAGE_KINDS = tuple(kind for kind in AssetKind.values if kind != AssetKind.MODEL_GLB)


def _point(value, key: str) -> list[float]:
    if not (isinstance(value, list | tuple) and len(value) == 2):
        raise ValidationError({"anchors": [f"'{key}' [x, y] ko'rinishida bo'lishi kerak."]})
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        raise ValidationError({"anchors": [f"'{key}' koordinatalari son bo'lishi kerak."]}) from None
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValidationError({"anchors": [f"'{key}' koordinatalari 0 dan 1 gacha bo'lishi kerak."]})
    return [round(x, 4), round(y, 4)]


def parse_anchors(kind: str, raw) -> dict:
    """Anchors from JSON (multipart sends a string). Unknown keys are dropped, missing ones refused."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            raise ValidationError({"anchors": ["JSON noto'g'ri."]}) from None
    if not isinstance(raw, dict):
        raise ValidationError({"anchors": ["Obyekt bo'lishi kerak."]})
    keys = ANCHOR_KEYS[kind]
    missing = [k for k in keys if k not in raw]
    if missing:
        raise ValidationError({"anchors": [f"Yetishmayapti: {', '.join(missing)}."]})
    anchors = {k: _point(raw[k], k) for k in keys}

    if kind in (AssetKind.BODY_FRONT, AssetKind.BODY_BACK):
        rs, ls, rh, lh = (anchors[k] for k in BODY_KEYS)
        # Front view: wearer's right is on the image's left. Back view: the opposite.
        front = kind == AssetKind.BODY_FRONT
        if (rs[0] < ls[0]) != front or (rh[0] < lh[0]) != front:
            side = "chapda" if front else "o'ngda"
            raise ValidationError({"anchors": [f"Kiyuvchining o'ng yelkasi/sonini rasmda {side} bo'lishi kerak."]})
        if abs(rs[0] - ls[0]) < 0.05:
            raise ValidationError({"anchors": ["Yelkalar orasi juda kichik."]})
        if min(rh[1], lh[1]) <= max(rs[1], ls[1]):
            raise ValidationError({"anchors": ["Son nuqtalari yelkalardan pastda bo'lishi kerak."]})
        legs = raw.get("legs", "joined")
        if legs not in ("joined", "split"):
            raise ValidationError(
                {"anchors": ["'legs' — 'joined' (ko'ylak, chopon) yoki 'split' (shim) bo'lishi kerak."]}
            )
        anchors["legs"] = legs
    elif kind == AssetKind.LOWER_BODY:
        rh, lh, rk, lk = (anchors[k] for k in LOWER_KEYS)
        if not (rh[0] < lh[0] and rk[0] < lk[0]):
            raise ValidationError({"anchors": ["Kiyuvchining o'ng soni/tizzasi rasmda chapda bo'lishi kerak."]})
        if min(rk[1], lk[1]) <= max(rh[1], lh[1]) + 0.05:
            raise ValidationError({"anchors": ["Tizza nuqtalari son nuqtalaridan pastda bo'lishi kerak."]})
        legs = raw.get("legs", "split")
        if legs not in ("joined", "split"):
            raise ValidationError({"anchors": ["'legs' — 'split' (shim) yoki 'joined' (yubka) bo'lishi kerak."]})
        anchors["legs"] = legs
    elif keys == LIMB_KEYS:
        (x1, y1), (x2, y2) = anchors["start"], anchors["end"]
        if abs(x1 - x2) + abs(y1 - y2) < 0.05:
            raise ValidationError({"anchors": ["Yengning boshi va oxiri bir-biriga juda yaqin."]})
    return anchors


def process_layer(upload) -> tuple[ContentFile, int, int]:
    """A transparent garment layer → WEBP with alpha. Returns (file, width, height)."""
    content = process_image(upload, max_side=ASSET_MAX_SIDE)
    image = Image.open(io.BytesIO(content.read()))
    content.seek(0)
    if image.mode != "RGBA":
        raise ValidationError({"file": ["Qatlam shaffof (alpha kanalli PNG/WEBP) bo'lishi kerak."]})
    low, high = image.getchannel("A").getextrema()
    if low == 255:
        raise ValidationError({"file": ["Rasmda shaffof joy yo'q — fon olib tashlangan PNG yuklang."]})
    if high == 0:
        raise ValidationError({"file": ["Rasm butunlay shaffof."]})
    return content, image.width, image.height


def process_glb(upload) -> ContentFile:
    """Only the binary glTF 2.0 container is accepted (header magic + declared length)."""
    if upload.size > GLB_MAX_BYTES:
        raise ValidationError({"file": [f"3D model {GLB_MAX_BYTES // (1024 * 1024)} MB dan oshmasligi kerak."]})
    upload.seek(0)
    data = upload.read()
    if len(data) < 12:
        raise ValidationError({"file": ["Fayl GLB emas."]})
    magic, version, length = struct.unpack("<4sII", data[:12])
    if magic != b"glTF" or version != 2 or length != len(data):
        raise ValidationError({"file": ["Faqat glTF 2.0 (.glb) fayl qabul qilinadi."]})
    return ContentFile(data, name=f"{uuid.uuid4().hex}.glb")
