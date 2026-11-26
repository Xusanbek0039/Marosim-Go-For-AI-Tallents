"""Premium prices computed from real AI costs (user decision 2026-11-26; see apps/subscriptions/pricing.py).

Unit costs at 12 024 so'm/$ + 10 %: AI video ≈ 8 330, AI photo ≈ 990 so'm. Every USER plan keeps
> 40 % margin even when its whole monthly AI quota is used. Businesses: mandatory monthly fee —
venue 300 000, studio 150 000 so'm (12 months = −10 %).
"""

from decimal import Decimal

from django.db import migrations

USER_PERKS = ["Profil galichkasi", "Logosiz video va rasmlar", "Yuklab olish"]
STUDIO_PERKS = [
    "Galichka — tasdiqlangan studiya belgisi",
    "Ommaviy katalogda va AI maslahatchi tavsiyalarida ko'rinish",
    "Portfolio: reels videolar",
    "Mijozlar bilan chat, izoh va reaksiyalar",
]
VENUE_PERKS = [
    "Galichka — tasdiqlangan to'yxona belgisi",
    "Ommaviy katalogda va AI maslahatchi tavsiyalarida ko'rinish",
    "Onlayn bron va bandlik kalendari",
    "Mijozlar sharhlari",
]

# code: (name, price, max_viewers, ai_video_per_month, ai_photo_per_month, perks)
PLANS = {
    "M1": ("1 oy", "59000", 15, 2, 15, USER_PERKS),
    "M3": ("3 oy", "159000", 20, 2, 15, USER_PERKS),
    "Y1": ("1 yil", "549000", 30, 2, 10, USER_PERKS),
    "Y5": ("5 yil", "1990000", 50, 1, 8, USER_PERKS),
    "STUDIO_M1": ("Studiya Premium — 1 oy", "150000", 1, 0, 0, STUDIO_PERKS),
    "STUDIO_Y1": ("Studiya Premium — 12 oy", "1620000", 1, 0, 0, STUDIO_PERKS),
    "VENUE_M1": ("To'yxona Premium — 1 oy", "300000", 1, 0, 0, VENUE_PERKS),
    "VENUE_Y1": ("To'yxona Premium — 12 oy", "3240000", 1, 0, 0, VENUE_PERKS),
}


def apply(apps, schema_editor):
    Plan = apps.get_model("subscriptions", "SubscriptionPlan")
    Subscription = apps.get_model("subscriptions", "Subscription")
    for code, (name, price, viewers, video, photo, perks) in PLANS.items():
        Plan.objects.filter(code=code).update(
            name=name,
            price=Decimal(price),
            max_viewers=viewers,
            ai_video_per_month=video,
            ai_photo_per_month=photo,
            perks=perks,
        )
    # Subscriptions already paid keep their price and period but get the new monthly AI quota.
    for plan in Plan.objects.filter(audience="USER"):
        Subscription.objects.filter(plan=plan, status__in=["ACTIVE", "PENDING"]).update(
            ai_video_per_month=plan.ai_video_per_month, ai_photo_per_month=plan.ai_photo_per_month
        )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0005_subscription_ai_photo_per_month_and_more")]
    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
