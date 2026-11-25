"""AI try-on session lifecycle and cost controls (Decart realtime, billed per generated second).

Limits enforced here, all configurable in ``settings.AI_TRYON``:
* one ACTIVE session per user (DB constraint + check);
* per session: ``MAX_SESSION_SECONDS`` wall-clock, fixed at creation as ``expires_at``;
* per user and day: ``DAILY_SESSIONS_PER_USER`` and ``DAILY_SECONDS_PER_USER`` (the session length
  is cut to what is left of the daily budget);
* platform-wide per day: ``GLOBAL_DAILY_SECONDS`` (0 = off);
* per session: at most ``MAX_TOKENS_PER_SESSION`` client tokens (reconnects), each restricted to
  the model, the allowed origins and the seconds the session has left.

Seconds are counted as wall-clock time of the session (an upper bound of what Decart bills).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from . import decart
from .models import AiEndReason, AiSessionStatus, AiTryOnSession

MIN_USEFUL_SECONDS = decart.MIN_SESSION_SECONDS


class AiTryOnError(APIException):
    """API error with a stable ``code`` (shown to the client) and an Uzbek message."""

    def __init__(self, code: str, message: str, http_status: int):
        self.status_code = http_status
        super().__init__(detail=message, code=code)


PROVIDER_MESSAGES = {
    "ai_tryon_not_configured": ("AI kiyib ko'rish hozircha yoqilmagan.", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_auth_failed": ("AI xizmatiga ulanib bo'lmadi (sozlama xatosi).", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_insufficient_credits": ("AI xizmati vaqtincha mavjud emas.", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_rejected_request": ("AI xizmati so'rovni qabul qilmadi.", status.HTTP_502_BAD_GATEWAY),
    "provider_rate_limited": ("AI xizmati band. Birozdan so'ng urinib ko'ring.", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_timeout": ("AI xizmati javob bermadi.", status.HTTP_504_GATEWAY_TIMEOUT),
    "provider_bad_response": ("AI xizmatidan noto'g'ri javob keldi.", status.HTTP_502_BAD_GATEWAY),
    "provider_unavailable": ("AI xizmati vaqtincha mavjud emas.", status.HTTP_503_SERVICE_UNAVAILABLE),
}


def _cfg() -> dict:
    return settings.AI_TRYON


def _day_start(now: datetime) -> datetime:
    local = timezone.localtime(now)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def used_seconds(session: AiTryOnSession, now: datetime) -> int:
    end = session.ended_at or min(now, session.expires_at)
    return max(0, int((end - session.started_at).total_seconds()))


def close_expired(now: datetime | None = None, user=None) -> int:
    """Mark ACTIVE sessions past ``expires_at`` as EXPIRED (they can no longer get tokens)."""
    now = now or timezone.now()
    qs = AiTryOnSession.objects.filter(status=AiSessionStatus.ACTIVE, expires_at__lte=now)
    if user is not None:
        qs = qs.filter(user=user)
    rows = list(qs)
    for s in rows:
        s.status, s.ended_at, s.end_reason = AiSessionStatus.EXPIRED, s.expires_at, AiEndReason.EXPIRED
        s.save(update_fields=["status", "ended_at", "end_reason", "updated_at"])
    return len(rows)


@dataclass
class Budget:
    sessions_today: int
    seconds_used_today: int
    seconds_left_today: int
    sessions_left_today: int
    global_seconds_left: int | None


def budget(user, now: datetime | None = None) -> Budget:
    now = now or timezone.now()
    cfg = _cfg()
    start = _day_start(now)
    mine = list(AiTryOnSession.objects.filter(user=user, started_at__gte=start))
    used = sum(used_seconds(s, now) for s in mine)
    global_left = None
    if cfg["GLOBAL_DAILY_SECONDS"] > 0:
        everyone = AiTryOnSession.objects.filter(started_at__gte=start).only("started_at", "ended_at", "expires_at")
        global_left = max(0, cfg["GLOBAL_DAILY_SECONDS"] - sum(used_seconds(s, now) for s in everyone))
    return Budget(
        sessions_today=len(mine),
        seconds_used_today=used,
        seconds_left_today=max(0, cfg["DAILY_SECONDS_PER_USER"] - used),
        sessions_left_today=max(0, cfg["DAILY_SESSIONS_PER_USER"] - len(mine)),
        global_seconds_left=global_left,
    )


def active_session(user) -> AiTryOnSession | None:
    close_expired(user=user)
    return AiTryOnSession.objects.filter(user=user, status=AiSessionStatus.ACTIVE).first()


def start_session(user) -> AiTryOnSession:
    """Create the user's only ACTIVE session, its length capped by every budget. Consent is checked by the caller."""
    if not decart.is_configured():
        raise AiTryOnError("ai_tryon_not_configured", *PROVIDER_MESSAGES["ai_tryon_not_configured"])
    now = timezone.now()
    existing = active_session(user)
    if existing is not None:
        raise AiTryOnError(
            "ai_session_already_active",
            "Sizda ochiq AI seansi bor. Avval uni yakunlang.",
            status.HTTP_409_CONFLICT,
        )
    left = budget(user, now)
    if left.sessions_left_today <= 0:
        raise AiTryOnError(
            "ai_daily_session_limit", "Bugungi AI seanslari soni tugadi.", status.HTTP_429_TOO_MANY_REQUESTS
        )
    seconds = min(_cfg()["MAX_SESSION_SECONDS"], left.seconds_left_today)
    if left.global_seconds_left is not None:
        seconds = min(seconds, left.global_seconds_left)
    if seconds < MIN_USEFUL_SECONDS:
        raise AiTryOnError("ai_daily_time_limit", "Bugungi AI vaqti tugadi.", status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        with transaction.atomic():
            return AiTryOnSession.objects.create(
                user=user,
                provider_model=_cfg()["MODEL"],
                consent_at=now,
                started_at=now,
                expires_at=now + timedelta(seconds=seconds),
            )
    except IntegrityError:  # a concurrent request created one first
        raise AiTryOnError(
            "ai_session_already_active", "Sizda ochiq AI seansi bor. Avval uni yakunlang.", status.HTTP_409_CONFLICT
        ) from None


def issue_token(session: AiTryOnSession) -> decart.ClientToken:
    """A short-lived Decart client token for this session, limited to the seconds it has left."""
    now = timezone.now()
    if session.status == AiSessionStatus.ACTIVE and session.expires_at <= now:
        close_expired(now, user=session.user)
        session.refresh_from_db()
    if session.status != AiSessionStatus.ACTIVE:
        raise AiTryOnError("ai_session_ended", "AI seansi yakunlangan.", status.HTTP_410_GONE)
    remaining = int((session.expires_at - now).total_seconds())
    if remaining < MIN_USEFUL_SECONDS:
        raise AiTryOnError("ai_session_ended", "AI seansi vaqti tugadi.", status.HTTP_410_GONE)
    if session.token_count >= _cfg()["MAX_TOKENS_PER_SESSION"]:
        raise AiTryOnError(
            "ai_token_limit", "Qayta ulanishlar soni tugadi. Yangi seans boshlang.", status.HTTP_429_TOO_MANY_REQUESTS
        )
    try:
        token = decart.mint_client_token(max_session_seconds=remaining)
    except decart.DecartError as exc:
        message, http_status = PROVIDER_MESSAGES.get(exc.code, PROVIDER_MESSAGES["provider_unavailable"])
        raise AiTryOnError(exc.code, message, http_status) from None
    session.token_count += 1
    session.last_token_at = now
    session.save(update_fields=["token_count", "last_token_at", "updated_at"])
    return token


def finish(session: AiTryOnSession, reason: str, metrics: dict) -> AiTryOnSession:
    if session.status == AiSessionStatus.ACTIVE:
        now = timezone.now()
        session.status = AiSessionStatus.FINISHED if now < session.expires_at else AiSessionStatus.EXPIRED
        session.ended_at = min(now, session.expires_at)
        session.end_reason = reason if session.status == AiSessionStatus.FINISHED else AiEndReason.EXPIRED
    if metrics:
        session.metrics = {**session.metrics, **metrics}
    session.save(update_fields=["status", "ended_at", "end_reason", "metrics", "updated_at"])
    return session
