"""Provider-agnostic contract of the AI planner. Only ``providers.*`` modules talk to an LLM vendor."""

from dataclasses import dataclass, field
from decimal import Decimal

from rest_framework import status

#: Stable error codes → (Uzbek message, HTTP status). Raw provider text never reaches a client or a log.
ERRORS = {
    "ai_not_configured": ("AI maslahatchi vaqtincha mavjud emas (sozlanmagan).", status.HTTP_503_SERVICE_UNAVAILABLE),
    "ai_disabled": ("AI maslahatchi vaqtincha o'chirilgan.", status.HTTP_503_SERVICE_UNAVAILABLE),
    "ai_maintenance": ("AI maslahatchida texnik ishlar olib borilmoqda.", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_auth_failed": ("AI xizmatiga ulanib bo'lmadi (sozlama xatosi).", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_model_not_found": ("AI modeli topilmadi (sozlama xatosi).", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_rate_limited": ("AI xizmati band. Birozdan so'ng urinib ko'ring.", status.HTTP_503_SERVICE_UNAVAILABLE),
    "provider_rejected_request": ("AI xizmati so'rovni qabul qilmadi.", status.HTTP_502_BAD_GATEWAY),
    "provider_refused": ("AI bu so'rovga javob bera olmadi. Savolni boshqacha yozib ko'ring.", status.HTTP_200_OK),
    "provider_timeout": ("AI xizmati javob bermadi. Qayta urinib ko'ring.", status.HTTP_504_GATEWAY_TIMEOUT),
    "provider_bad_response": ("AI xizmatidan noto'g'ri javob keldi.", status.HTTP_502_BAD_GATEWAY),
    "provider_unavailable": ("AI xizmati vaqtincha mavjud emas.", status.HTTP_503_SERVICE_UNAVAILABLE),
}


class ProviderError(Exception):
    """Carries only a stable ``code`` (and the HTTP status of the vendor, if any) — never vendor text."""

    def __init__(self, code: str, http_status: int | None = None):
        super().__init__(code)
        self.code = code if code in ERRORS else "provider_unavailable"
        self.http_status = http_status


@dataclass
class ProviderReply:
    text: str
    model: str
    stop_reason: str = "end_turn"
    #: ``None`` = the vendor did not report usage.
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class ProviderRequest:
    system: str
    messages: list[dict]
    output_schema: dict
    model: str
    max_tokens: int
    effort: str = "low"
    temperature: Decimal | None = None


class BaseProvider:
    name = "base"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def send_message(self, request: ProviderRequest) -> ProviderReply:
        raise NotImplementedError

    def validate_configuration(self, model: str) -> dict:
        """``{"ok": bool, "code": str | None}`` — a cheap live check, no generation."""
        raise NotImplementedError

    def get_usage(self, reply: ProviderReply) -> dict:
        return {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens}

    def normalize_error(self, exc: Exception) -> ProviderError:
        return exc if isinstance(exc, ProviderError) else ProviderError("provider_unavailable")
