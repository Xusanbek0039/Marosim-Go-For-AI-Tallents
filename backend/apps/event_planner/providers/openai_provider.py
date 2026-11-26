"""OpenAI Chat Completions adapter (REST API via ``requests``, no extra SDK required).

* Structured output: ``response_format = {"type": "json_schema", "json_schema": {"strict": True, ...}}`` —
  ``schema.sanitize`` still validates every field on the server.
* Reasoning models (``o1``, ``o3``, ``o4``, ``gpt-5``) receive ``reasoning_effort`` and no ``temperature``;
  standard chat models (``gpt-4o-mini``, ``gpt-4o``, ``gpt-4.1``) receive ``temperature`` when configured.
* Timeout + retry: retries connection errors, 408/409/429 and 5xx with exponential backoff up to
  ``AI_PLANNER["MAX_RETRIES"]``.
* The key comes from ``OPENAI_API_KEY`` only and is never logged or returned.
"""

import logging
import time

import requests
from django.conf import settings

from .base import BaseProvider, ProviderError, ProviderReply, ProviderRequest

logger = logging.getLogger("apps.event_planner.provider")

RETRYABLE_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})
REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _cfg() -> dict:
    return settings.AI_PLANNER


def _is_reasoning_model(model: str) -> bool:
    name = (model or "").lower()
    return any(name == p or name.startswith(f"{p}-") for p in REASONING_PREFIXES)


class _OpenAIHTTPError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class OpenAIProvider(BaseProvider):
    name = "openai"

    def is_configured(self) -> bool:
        return bool(_cfg().get("OPENAI_API_KEY", "").strip())

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {_cfg()['OPENAI_API_KEY'].strip()}",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        return _cfg().get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        cfg = _cfg()
        url = f"{self._base_url()}/{path.lstrip('/')}"
        timeout = float(cfg["TIMEOUT_SECONDS"])
        retries = max(0, int(cfg["MAX_RETRIES"]))

        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(min(2.0, 0.4 * (2**attempt)))
                    continue
                raise

            if response.status_code in RETRYABLE_STATUSES and attempt < retries:
                time.sleep(min(2.0, 0.4 * (2**attempt)))
                continue

            if response.status_code >= 400:
                raise _OpenAIHTTPError(response.status_code)

            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderError("provider_bad_response", response.status_code) from exc
            if not isinstance(data, dict):
                raise ProviderError("provider_bad_response", response.status_code)
            return data

        assert last_exc is not None  # pragma: no cover
        raise last_exc

    def send_message(self, request: ProviderRequest) -> ProviderReply:
        if not self.is_configured():
            raise ProviderError("ai_not_configured")

        payload: dict = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system}, *request.messages],
            "max_completion_tokens": request.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "event_planner_response",
                    "strict": True,
                    "schema": request.output_schema,
                },
            },
        }
        if _is_reasoning_model(request.model):
            if request.effort in ("low", "medium", "high"):
                payload["reasoning_effort"] = request.effort
        elif request.temperature is not None:
            payload["temperature"] = float(request.temperature)

        started = time.monotonic()
        try:
            data = self._request("POST", "/chat/completions", json_body=payload)
        except Exception as exc:  # noqa: BLE001 - mapped to a stable code below
            raise self.normalize_error(exc) from None
        latency = int((time.monotonic() - started) * 1000)

        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise ProviderError("provider_bad_response", 200)
        choice = choices[0]
        message = choice.get("message") or {}
        finish_reason = str(choice.get("finish_reason") or "")
        usage = data.get("usage") or {}

        reply = ProviderReply(
            text="",
            model=str(data.get("model") or request.model),
            stop_reason=finish_reason,
            input_tokens=usage.get("prompt_tokens") if isinstance(usage, dict) else None,
            output_tokens=usage.get("completion_tokens") if isinstance(usage, dict) else None,
            latency_ms=latency,
        )
        if message.get("refusal") or finish_reason == "content_filter":
            raise ProviderError("provider_refused", 200)

        content = message.get("content")
        if isinstance(content, list):
            reply.text = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        elif isinstance(content, str):
            reply.text = content

        if finish_reason == "length" or not reply.text.strip():
            reply.extra["truncated"] = finish_reason == "length"
        return reply

    def validate_configuration(self, model: str) -> dict:
        if not self.is_configured():
            return {"ok": False, "code": "ai_not_configured"}
        try:
            self._request("GET", f"/models/{model}")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "code": self.normalize_error(exc).code}
        return {"ok": True, "code": None}

    def normalize_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, requests.Timeout):
            code, http = "provider_timeout", None
        elif isinstance(exc, requests.RequestException):
            code, http = "provider_unavailable", None
        elif isinstance(exc, _OpenAIHTTPError):
            http = exc.status_code
            if http in (401, 403):
                code = "provider_auth_failed"
            elif http == 404:
                code = "provider_model_not_found"
            elif http == 429:
                code = "provider_rate_limited"
            elif http in (400, 422):
                code = "provider_rejected_request"
            else:
                code = "provider_unavailable"
        else:
            code, http = "provider_unavailable", None
        log = logger.error if code in ("provider_auth_failed", "provider_model_not_found") else logger.warning
        log("openai request failed: %s (HTTP %s)", code, http or "-")  # type + status only, never the body
        return ProviderError(code, http)
