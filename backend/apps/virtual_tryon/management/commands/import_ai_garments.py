"""Bulk-load REAL garment photos into the AI Fashion Studio catalogue (Decart lucy-vton references).

    python manage.py import_ai_garments path/to/folder             # validate + import (PENDING)
    python manage.py import_ai_garments path/to/folder --dry-run   # only validate, write nothing
    python manage.py import_ai_garments path/to/folder --approve   # import as APPROVED (staff checked them)

The folder holds the photos and a ``manifest.json``::

    [
      {"file": "wedding-dress-01.jpg", "name": "Oq atlas kelinlik libosi",
       "category": "kelinlik-liboslari", "description": "...", "prompt": "a white satin wedding dress ...",
       "sort_order": 1},
      ...
    ]

``category`` is a ``GarmentCategory.slug`` (see migrations 0002 / 0005). Every photo goes through the
same validation as an admin upload (``reference.process_reference``: format, ≥512 px, aspect ratio,
plain background); rejected photos are reported and skipped. Nothing is generated: without real,
licensed product photos there is nothing to import. A garment is matched by (category, name), so
re-running the command updates instead of duplicating.
"""

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.virtual_tryon import reference
from apps.virtual_tryon.models import ApprovalStatus, Garment, GarmentCategory

MAX_PROMPT = 300


def _message(exc: ValidationError) -> str:
    detail = exc.detail
    if isinstance(detail, list | tuple):
        return " ".join(str(d) for d in detail)
    return str(detail)


class Command(BaseCommand):
    help = "Haqiqiy kiyim rasmlarini (manifest.json bo'yicha) AI kiyib ko'rish katalogiga yuklaydi."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Rasmlar va manifest.json joylashgan papka")
        parser.add_argument("--manifest", default="manifest.json", help="Manifest fayl nomi (papka ichida)")
        parser.add_argument("--dry-run", action="store_true", help="Faqat tekshirish, bazaga yozmaslik")
        parser.add_argument("--approve", action="store_true", help="Darhol APPROVED qilish (aks holda PENDING)")

    def handle(self, *args, folder, manifest, dry_run=False, approve=False, **options):
        root = Path(folder).expanduser().resolve()
        path = root / manifest
        if not path.is_file():
            raise CommandError(f"Manifest topilmadi: {path}")
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Manifestni o'qib bo'lmadi: {exc}") from None
        if not isinstance(rows, list):
            raise CommandError("Manifest JSON ro'yxat (list) bo'lishi kerak.")

        categories = {c.slug: c for c in GarmentCategory.objects.all()}
        ok = failed = 0
        for index, row in enumerate(rows, start=1):
            label = f"#{index}"
            try:
                label, garment_data, upload = self._prepare(root, row, categories, label)
                content, width, height = reference.process_reference(upload)
            except (ValueError, OSError) as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  ✗ {label}: {exc}"))
                continue
            except ValidationError as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  ✗ {label}: {_message(exc)}"))
                continue
            if not dry_run:
                with transaction.atomic():
                    self._save(garment_data, content, approve)
            ok += 1
            self.stdout.write(f"  ✓ {label} ({width}×{height})")

        verb = "tekshirildi" if dry_run else "yuklandi"
        self.stdout.write(self.style.SUCCESS(f"{ok} ta kiyim {verb}, {failed} ta rad etildi."))
        if failed and not ok:
            raise CommandError("Birorta ham rasm qabul qilinmadi.")

    def _prepare(self, root: Path, row, categories, label):
        if not isinstance(row, dict):
            raise ValueError("har bir yozuv obyekt bo'lishi kerak")
        name = " ".join(str(row.get("name", "")).split())[:150]
        label = name or label
        if not name:
            raise ValueError("'name' bo'sh")
        category = categories.get(str(row.get("category", "")))
        if category is None:
            raise ValueError(f"noma'lum kategoriya: {row.get('category')!r}")
        file_name = str(row.get("file", ""))
        file_path = (root / file_name).resolve()
        if not file_name or root not in file_path.parents or not file_path.is_file():
            raise ValueError(f"rasm fayli topilmadi: {file_name!r}")
        prompt = " ".join(str(row.get("prompt", "")).split())
        if len(prompt) > MAX_PROMPT:
            raise ValueError(f"'prompt' {MAX_PROMPT} belgidan uzun")
        upload = SimpleUploadedFile(file_path.name, file_path.read_bytes())
        data = {
            "name": name,
            "category": category,
            "description": str(row.get("description", ""))[:2000],
            "prompt": prompt,
            "sort_order": max(0, int(row.get("sort_order", 0) or 0)),
        }
        if "price" in row and row["price"] is not None:
            try:
                data["price"] = Decimal(str(row["price"]))
            except InvalidOperation:
                raise ValueError(f"noto'g'ri 'price': {row['price']!r}") from None
        if "currency" in row and row["currency"]:
            data["currency"] = str(row["currency"])[:3].upper()
        if "sizes" in row and isinstance(row["sizes"], list):
            data["sizes"] = [str(s)[:20] for s in row["sizes"] if str(s).strip()]
        if "colors" in row and isinstance(row["colors"], list):
            data["colors"] = [
                {"name": str(c.get("name", ""))[:40], "hex": str(c.get("hex", ""))[:7]}
                for c in row["colors"]
                if isinstance(c, dict) and str(c.get("name", "")).strip()
            ]
        if "brand" in row and row["brand"] is not None:
            data["brand"] = str(row["brand"])[:80]
        if "material" in row and row["material"] is not None:
            data["material"] = str(row["material"])[:120]
        if "delivery_days" in row and row["delivery_days"] is not None:
            data["delivery_days"] = max(1, int(row["delivery_days"]))
        if "care_instructions" in row and row["care_instructions"] is not None:
            data["care_instructions"] = str(row["care_instructions"])[:200]
        return label, data, upload

    def _save(self, data, content: ContentFile, approve: bool):
        garment = Garment.objects.filter(category=data["category"], name=data["name"]).first()
        if garment is None:
            garment = Garment(category=data["category"], name=data["name"])
        garment.description = data["description"]
        garment.ai_prompt = data["prompt"]
        garment.sort_order = data["sort_order"]
        for field in ("price", "currency", "sizes", "colors", "brand", "material", "delivery_days", "care_instructions"):
            if field in data:
                setattr(garment, field, data[field])
        garment.is_active = True
        garment.approval_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.PENDING
        garment.rejection_reason = ""
        garment.save()
        raw = content.read()
        if garment.ai_reference_image:
            garment.ai_reference_image.delete(save=False)
        garment.ai_reference_image.save("reference.jpg", ContentFile(raw), save=False)
        if not garment.cover_image:
            garment.cover_image.save("cover.jpg", ContentFile(raw), save=False)
        garment.save(update_fields=["ai_reference_image", "cover_image", "updated_at"])
