from django.db import migrations

CATEGORIES = [
    ("kelinlik-liboslari", "Kelinlik liboslari"),
    ("kuyovlik-kostyumlari", "Kuyovlik kostyumlari"),
    ("milliy-toy-liboslari", "Milliy to'y liboslari"),
    ("erkaklar-kiyimlari", "Erkaklar kiyimlari"),
    ("ayollar-kiyimlari", "Ayollar kiyimlari"),
]


def seed(apps, schema_editor):
    Category = apps.get_model("virtual_tryon", "GarmentCategory")
    for order, (slug, name) in enumerate(CATEGORIES, start=1):
        Category.objects.update_or_create(slug=slug, defaults={"name": name, "sort_order": order})


def unseed(apps, schema_editor):
    apps.get_model("virtual_tryon", "GarmentCategory").objects.filter(
        slug__in=[slug for slug, _ in CATEGORIES], garments__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("virtual_tryon", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
