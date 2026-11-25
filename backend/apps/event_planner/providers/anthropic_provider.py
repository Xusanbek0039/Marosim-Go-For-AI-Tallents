"""Claude through the official ``anthropic`` Python SDK (Messages API).

* Structured output: ``output_config.format = {"type": "json_schema", ...}`` — the reply's text block is JSON,
  which ``schema.sanitize`` still validates on the server (the model can be wrong; the schema is not trusted).
* ``output_config.effort`` controls depth/cost. Current Claude models reject sampling parameters, so the
  configured ``temperature`` is never sent.
* Timeout + retry: the SDK client is built with ``timeout`` and ``max_retries`` (it retries connection
  errors, 408/409/429 and 5xx with backoff). Wall-clock worst case ≈ timeout × (retries + 1).
* Refusals: the server-side fallback (beta ``server-side-fallback-2026-07-01``, ``fallbacks="default"``) is
  on by default (``AI_PLANNER_REFUSAL_FALLBACK``); a refusal that remains is ``provider_refused``.
* The key comes from ``ANTHROPIC_API_KEY`` only and is never logged or returned.
"""

import logging
import time

from django.conf import settings

from .base import BaseProvider, ProviderError, ProviderReply, ProviderRequest

logger = logging.getLogger("apps.event_planner.provider")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _cfg() -> dict:
    return settings.AI_PLANNER


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def is_configured(self) -> bool:
        return bool(_cfg()["ANTHROPIC_API_KEY"].strip())

    def _client(self):
        import anthropic  # imported lazily: the platform keeps working if the SDK is missing

        cfg = _cfg()
        return anthropic.Anthropic(
            api_key=cfg["ANTHROPIC_API_KEY"],
            timeout=float(cfg["TIMEOUT_SECONDS"]),
            max_retries=int(cfg["MAX_RETRIES"]),
        )

    def send_message(self, request: ProviderRequest) -> ProviderReply:
        if not self.is_configured():
            raise ProviderError("ai_not_configured")
        params = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": request.messages,
            "output_config": {
                "effort": request.effort,
                "format": {"type": "json_schema", "schema": request.output_schema},
            },
        }
        started = time.monotonic()
        try:
            client = self._client()
            if _cfg()["REFUSAL_FALLBACK"]:
                response = client.beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
            else:
                response = client.messages.create(**params)
        except Exception as exc:  # noqa: BLE001 - mapped to a stable code below
            raise self.normalize_error(exc) from None
        latency = int((time.monotonic() - started) * 1000)

        usage = getattr(response, "usage", None)
        reply = ProviderReply(
            text="",
            model=str(getattr(response, "model", request.model) or request.model),
            stop_reason=str(getattr(response, "stop_reason", "") or ""),
            input_tokens=getattr(usage, "input_tokens", None) if usage is not None else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage is not None else None,
            latency_ms=latency,
        )
        if reply.stop_reason == "refusal":
            raise ProviderError("provider_refused", 200)
        reply.text = "".join(
            getattr(block, "text", "") for block in (response.content or []) if getattr(block, "type", "") == "text"
        )
        if reply.stop_reason == "max_tokens" or not reply.text.strip():
            # Truncated JSON is never parsed as a plan; the caller stores a safe fallback answer.
            reply.extra["truncated"] = reply.stop_reason == "max_tokens"
        return reply

    def validate_configuration(self, model: str) -> dict:
        if not self.is_configured():
            return {"ok": False, "code": "ai_not_configured"}
        try:
            self._client().models.retrieve(model)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "code": self.normalize_error(exc).code}
        return {"ok": True, "code": None}

    def normalize_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        try:
            import anthropic
        except ImportError:  # pragma: no cover - requirements.txt pins the SDK
            return ProviderError("ai_not_configured")
        # Most specific first: APITimeoutError is a subclass of APIConnectionError.
        if isinstance(exc, anthropic.APITimeoutError):
            code, http = "provider_timeout", None
        elif isinstance(exc, anthropic.APIConnectionError):
            code, http = "provider_unavailable", None
        elif isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            code, http = "provider_auth_failed", exc.status_code
        elif isinstance(exc, anthropic.NotFoundError):
            code, http = "provider_model_not_found", exc.status_code
        elif isinstance(exc, anthropic.RateLimitError):
            code, http = "provider_rate_limited", exc.status_code
        elif isinstance(exc, anthropic.BadRequestError):
            code, http = "provider_rejected_request", exc.status_code
        elif isinstance(exc, anthropic.APIStatusError):
            code, http = "provider_unavailable", exc.status_code
        else:
            code, http = "provider_unavailable", None
        log = logger.error if code in ("provider_auth_failed", "provider_model_not_found") else logger.warning
        log("anthropic request failed: %s (HTTP %s)", code, http or "-")  # type + status only, never the body
        return ProviderError(code, http)
