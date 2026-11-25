"""AI Fashion Studio catalogue sections: men / women / unisex.

Existing sections keep their slug and garments; they only get an audience. New sections are added
(idempotent). Reversing removes only the new sections that have no garments and clears audiences.
"""

from django.db import migrations

EXISTING = {
    "kelinlik-liboslari": "WOMEN",  # wedding dresses
    "kuyovlik-kostyumlari": "MEN",  # wedding suits
    "milliy-toy-liboslari": "UNISEX",  # traditional outfits
    "erkaklar-kiyimlari": "MEN",
    "ayollar-kiyimlari": "WOMEN",
}

NEW = [
    # (slug, name, audience)
    ("smokinglar", "Smokinglar", "MEN"),
    ("erkaklar-koylaklari", "Erkaklar ko'ylaklari", "MEN"),
    ("chopon", "Chopon", "MEN"),
    ("erkaklar-milliy-liboslari", "Erkaklar milliy liboslari", "MEN"),
    ("kechki-liboslar", "Kechki liboslar", "WOMEN"),
    ("ayollar-milliy-liboslari", "Ayollar milliy liboslari", "WOMEN"),
    ("atlas-va-adras", "Atlas va adras liboslar", "WOMEN"),
    ("hijob-va-aksessuarlar", "Hijob va aksessuarlar", "WOMEN"),
    ("boshqa-kiyimlar", "Boshqa kiyimlar", "UNISEX"),
]


def forwards(apps, schema_editor):
    Category = apps.get_model("virtual_tryon", "GarmentCategory")
    for slug, audience in EXISTING.items():
        Category.objects.filter(slug=slug).update(audience=audience)
    start = (Category.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0) + 1
    for order, (slug, name, audience) in enumerate(NEW, start=start):
        Category.objects.get_or_create(slug=slug, defaults={"name": name, "audience": audience, "sort_order": order})


def backwards(apps, schema_editor):
    Category = apps.get_model("virtual_tryon", "GarmentCategory")
    Category.objects.filter(slug__in=[slug for slug, _, _ in NEW], garments__isnull=True).delete()
    Category.objects.filter(slug__in=EXISTING).update(audience="UNISEX")


class Migration(migrations.Migration):
    dependencies = [("virtual_tryon", "0004_ai_tryon_sessions_looks")]

    operations = [migrations.RunPython(forwards, backwards)]
