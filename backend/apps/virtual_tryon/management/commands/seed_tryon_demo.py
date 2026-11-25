"""Fill the try-on catalogue with clearly labelled demo garments (procedurally drawn layers).

    python manage.py seed_tryon_demo            # create / refresh the 10 demo garments
    python manage.py seed_tryon_demo --remove   # delete them again

Layers go through the same validation as real uploads (``assets.process_layer`` / ``parse_anchors``).
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.uploads import process_image
from apps.virtual_tryon import assets, demo_art
from apps.virtual_tryon.models import ApprovalStatus, AssetKind, Garment, GarmentAsset, GarmentCategory

DEMO_PREFIX = "Namuna (demo). "


def _upload(image, name):
    return SimpleUploadedFile(name, demo_art.png_bytes(image), content_type="image/png")


class Command(BaseCommand):
    help = "Demo kiyimlarni (shaffof AR qatlamlari bilan) yaratadi yoki --remove bilan o'chiradi."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Demo kiyimlarni o'chirish")

    def handle(self, *args, remove=False, **options):
        demo = Garment.objects.filter(description__startswith=DEMO_PREFIX)
        if remove:
            for garment in demo:
                for asset in garment.assets.all():
                    asset.file.delete(save=False)
                garment.cover_image.delete(save=False)
            count = demo.count()
            demo.delete()
            self.stdout.write(self.style.SUCCESS(f"{count} ta demo kiyim o'chirildi."))
            return

        for order, design in enumerate(demo_art.DESIGNS, start=1):
            with transaction.atomic():
                self._seed(design, order)
            self.stdout.write(f"  ✓ {design.name}")
        self.stdout.write(self.style.SUCCESS(f"{len(demo_art.DESIGNS)} ta demo kiyim tayyor."))

    def _seed(self, design, order):
        category = GarmentCategory.objects.get(slug=design.category)
        garment = Garment.objects.filter(description__startswith=DEMO_PREFIX, name=design.name).first()
        if garment is None:
            garment = Garment(name=design.name)
        garment.category = category
        garment.description = DEMO_PREFIX + design.description
        garment.price = design.price
        garment.sizes = design.sizes
        garment.colors = design.colors
        garment.is_tryon_enabled = True
        garment.is_active = True
        garment.approval_status = ApprovalStatus.APPROVED
        garment.sort_order = order
        garment.save()

        body = demo_art.draw_body(design)
        upper = demo_art.draw_sleeve(design, "upper")
        fore = demo_art.draw_sleeve(design, "fore")
        lower = demo_art.draw_lower(design)
        layers = [(AssetKind.BODY_FRONT, body, {**demo_art.BODY_ANCHORS, "legs": design.legs})]
        if lower is not None:
            layers.append((AssetKind.LOWER_BODY, lower, demo_art.LOWER_ANCHORS))
        if upper is not None:
            layers += [
                (AssetKind.RIGHT_UPPER_ARM, upper, demo_art.LIMB_ANCHORS),
                (AssetKind.LEFT_UPPER_ARM, upper, demo_art.LIMB_ANCHORS),
            ]
        if fore is not None:
            layers += [
                (AssetKind.RIGHT_FOREARM, fore, demo_art.LIMB_ANCHORS),
                (AssetKind.LEFT_FOREARM, fore, demo_art.LIMB_ANCHORS),
            ]

        for old in garment.assets.all():
            old.file.delete(save=False)
        garment.assets.all().delete()
        for kind, image, anchors in layers:
            content, width, height = assets.process_layer(_upload(image, f"{kind}.png"))
            GarmentAsset.objects.create(
                garment=garment,
                kind=kind,
                file=content,
                width=width,
                height=height,
                size_bytes=content.size,
                anchors=assets.parse_anchors(kind, anchors),
            )

        cover = demo_art.draw_cover(design, body, upper, fore, lower)
        if garment.cover_image:
            garment.cover_image.delete(save=False)
        garment.cover_image = process_image(_upload(cover, "cover.png"), max_side=1000)
        garment.save(update_fields=["cover_image", "updated_at"])
