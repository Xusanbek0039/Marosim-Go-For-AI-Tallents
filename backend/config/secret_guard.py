"""Refuse to run production with missing or publicly known secrets.

The repository's ``.env.example`` files are public, so a deployment that copies one and forgets to
replace a value runs with a secret everybody knows. For ``JWT_SIGNING_KEY`` that means anyone can
mint a valid access token for any account, Super Admin included. This module lists such problems;
``config/settings.py`` raises ``ImproperlyConfigured`` when ``DEBUG`` is off and only warns in DEBUG.

Values are never echoed — problems name the variable only.
"""

from collections.abc import Iterable

from cryptography.fernet import Fernet

#: Values shipped in the public ``.env.example`` / ``backend/.env.production.example`` templates.
KNOWN_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "change-me-too",
        "another-long-random-secret",
        "generate-a-fernet-key",
    }
)


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in KNOWN_PLACEHOLDERS


def problems(
    *, secret_key: str, jwt_signing_key: str, pinfl_hash_key: str, pinfl_encryption_keys: Iterable[str]
) -> list[str]:
    """Human-readable problems with the core secrets (empty list = OK)."""
    found = []
    for name, value in (
        ("DJANGO_SECRET_KEY", secret_key),
        ("JWT_SIGNING_KEY", jwt_signing_key),
        ("PINFL_HASH_KEY", pinfl_hash_key),
    ):
        if not (value or "").strip():
            found.append(f"{name} is empty.")
        elif _is_placeholder(value):
            found.append(f"{name} still has the public placeholder value from .env.example.")

    if (jwt_signing_key or "").strip() and jwt_signing_key == secret_key:
        found.append("JWT_SIGNING_KEY must differ from DJANGO_SECRET_KEY.")

    keys = [k.strip() for k in pinfl_encryption_keys if k.strip()]
    if not keys:
        found.append("PINFL_ENCRYPTION_KEYS is empty.")
    for position, key in enumerate(keys, start=1):
        if _is_placeholder(key):
            found.append(f"PINFL_ENCRYPTION_KEYS key #{position} is the public placeholder from .env.example.")
            continue
        try:
            Fernet(key.encode())
        except ValueError:
            found.append(f"PINFL_ENCRYPTION_KEYS key #{position} is not a valid Fernet key.")
    return found
