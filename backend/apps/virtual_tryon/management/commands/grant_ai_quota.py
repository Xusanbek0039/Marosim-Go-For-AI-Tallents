"""Give one user extra AI try-ons for the current month.

    python manage.py grant_ai_quota +998934243408 --videos 10
    python manage.py grant_ai_quota 934243408 --videos 5 --photos 20 --note "Taqdimot uchun"
"""

from django.core.management.base import BaseCommand, CommandError

from apps.accounts import phone as phone_utils
from apps.accounts.models import User
from apps.virtual_tryon import quota
from apps.virtual_tryon.models import AiQuotaBonus


class Command(BaseCommand):
    help = "Grant extra AI video / photo try-ons to a user for the current month."

    def add_arguments(self, parser):
        parser.add_argument("phone")
        parser.add_argument("--videos", type=int, default=0)
        parser.add_argument("--photos", type=int, default=0)
        parser.add_argument("--note", default="")

    def handle(self, phone, videos, photos, note, **options):
        if videos < 0 or photos < 0 or not (videos or photos):
            raise CommandError("--videos va/yoki --photos musbat son bo'lsin.")
        digits = "".join(ch for ch in phone if ch.isdigit())
        number = phone_utils.normalize(phone if phone.startswith("+") else ("+998" + digits[-9:]))
        user = User.objects.filter(phone_number=number).first()
        if user is None:
            raise CommandError(f"{number} raqamli foydalanuvchi topilmadi.")
        AiQuotaBonus.objects.create(
            user=user, month=quota.month_start().date(), extra_videos=videos, extra_photos=photos, note=note
        )
        q = quota.quota(user)
        self.stdout.write(
            f"{user.first_name} {number}: bu oy video {q.video_left}/{q.video_limit} qoldi, "
            f"rasm {q.photo_left}/{q.photo_limit} qoldi."
        )
