"""Live check of the Decart configuration (talks to the real API; costs nothing — no video is sent).

    python manage.py check_ai_tryon

Mints one short-lived client token exactly like ``POST /api/v1/virtual-tryon/ai-sessions/{id}/token/``
does and reports the outcome. It proves the key, the model permission and the network path; the
WebRTC stream itself can only be verified in a browser (see docs/AI_FASHION_STUDIO.md, "Live test").
The token is never printed.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.virtual_tryon import decart


class Command(BaseCommand):
    help = "Decart AI kalitini haqiqiy API orqali tekshiradi (bitta qisqa muddatli token yaratadi)."

    def handle(self, *args, **options):
        cfg = settings.AI_TRYON
        self.stdout.write(f"API: {cfg['API_BASE']}  model: {cfg['MODEL']}")
        self.stdout.write(f"allowedOrigins: {', '.join(cfg['ALLOWED_ORIGINS']) or '(cheklanmagan)'}")
        if not decart.is_configured():
            raise CommandError("DECART_API_KEY o'rnatilmagan: AI Fashion Studio o'chiq. docs/AI_FASHION_STUDIO.md ga qarang.")
        try:
            token = decart.mint_client_token(max_session_seconds=decart.MIN_SESSION_SECONDS)
        except decart.DecartError as exc:
            hint = {
                "provider_auth_failed": "Kalit noto'g'ri yoki bekor qilingan (HTTP 401/403).",
                "provider_insufficient_credits": "Decart hisobida kredit yetarli emas (HTTP 402).",
                "provider_rejected_request": "So'rov rad etildi (HTTP 422): DECART_TRYON_MODEL yoki origin'larni tekshiring.",
                "provider_rate_limited": "Decart so'rovlar chegarasi (HTTP 429).",
                "provider_timeout": "Decart javob bermadi (tarmoq/proksi).",
            }.get(exc.code, "Decart bilan aloqa bo'lmadi.")
            raise CommandError(f"{exc.code}: {hint}") from None
        prefix = token.api_key[:3] if token.api_key.startswith("ek_") else "?"
        self.stdout.write(
            self.style.SUCCESS(f"OK: Decart client token berildi (prefiks {prefix}…, amal qiladi {token.expires_at}).")
        )
