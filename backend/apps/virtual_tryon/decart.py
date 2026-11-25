"""The only module that talks to Decart (https://docs.platform.decart.ai).

The browser streams the camera to Decart over WebRTC with the official JS SDK (`@decartai/sdk`); this
server never sees video. It only mints *client tokens* so the permanent key never reaches a browser:

    POST {API_BASE}/v1/client/tokens
    x-api-key: <DECART_API_KEY>
    {"expiresIn": 60, "allowedModels": ["lucy-vton-latest"], "allowedOrigins": [...],
     "constraints": {"realtime": {"maxSessionDuration": 120}}}
    → 200 {"apiKey": "ek_...", "expiresAt": "...", "permissions": ..., "constraints": ...}

Verified against the live API: no header → 422, invalid key → 401 {"error": "..."}, GET → 405.
A token only *starts* connections; an open session keeps running after the token expires, and
``maxSessionDuration`` (seconds, ≥ 10) caps how long each connection may generate.
"""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger("apps.virtual_tryon.decart")

MIN_SESSION_SECONDS = 10  # Decart: constraints.realtime.maxSessionDuration minimum


class DecartError(Exception):
    """Stable, non-secret error ``code`` for the API layer; never carries the provider's raw text."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ClientToken:
    api_key: str
    expires_at: str

    def __repr__(self) -> str:  # never let the token reach logs or tracebacks
        return f"ClientToken(expires_at={self.expires_at!r})"


def is_configured() -> bool:
    return bool(settings.AI_TRYON["API_KEY"].strip())


def mint_client_token(*, max_session_seconds: int) -> ClientToken:
    cfg = settings.AI_TRYON
    if not is_configured():
        raise DecartError("ai_tryon_not_configured")
    body = {
        "expiresIn": max(1, min(int(cfg["TOKEN_TTL_SECONDS"]), 3600)),
        "allowedModels": [cfg["MODEL"]],
        "constraints": {"realtime": {"maxSessionDuration": max(MIN_SESSION_SECONDS, int(max_session_seconds))}},
    }
    if cfg["ALLOWED_ORIGINS"]:
        body["allowedOrigins"] = list(cfg["ALLOWED_ORIGINS"])[:20]
    try:
        res = requests.post(
            f"{cfg['API_BASE']}/v1/client/tokens",
            json=body,
            headers={"x-api-key": cfg["API_KEY"]},
            timeout=cfg["REQUEST_TIMEOUT_SECONDS"],
        )
    except requests.Timeout:
        logger.warning("decart token request timed out")
        raise DecartError("provider_timeout") from None
    except requests.RequestException as exc:
        logger.warning("decart token request failed: %s", type(exc).__name__)
        raise DecartError("provider_unavailable") from None

    if res.status_code == 200:
        try:
            data = res.json()
            return ClientToken(api_key=str(data["apiKey"]), expires_at=str(data["expiresAt"]))
        except (ValueError, KeyError, TypeError):
            logger.error("decart token response had an unexpected shape")
            raise DecartError("provider_bad_response", 200) from None

    code = {
        401: "provider_auth_failed",  # wrong / revoked DECART_API_KEY
        403: "provider_auth_failed",
        402: "provider_insufficient_credits",
        422: "provider_rejected_request",
        429: "provider_rate_limited",
    }.get(res.status_code, "provider_unavailable")
    # Status only: Decart's body can echo request details; the key is never logged.
    log = logger.error if code in ("provider_auth_failed", "provider_rejected_request") else logger.warning
    log("decart token request rejected: HTTP %s → %s", res.status_code, code)
    raise DecartError(code, res.status_code)
