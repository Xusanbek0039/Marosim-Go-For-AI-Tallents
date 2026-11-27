"""Move couples into / out of Backup and send the notifications. Run from cron (e.g. every 15 minutes).

python manage.py run_backup_cycle
"""

from django.core.management.base import BaseCommand

from apps.backup import services


class Command(BaseCommand):
    help = "Backup rejimi: sinov va Premium muddatlarini tekshirib, holatlarni yangilaydi."

    def handle(self, *args, **options):
        counts = services.sync_all()
        self.stdout.write(", ".join(f"{k}={v}" for k, v in counts.items()))
