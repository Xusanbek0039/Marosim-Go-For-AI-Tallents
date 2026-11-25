"""Refuse to run production with missing, weak, publicly known or compromised secrets.

The repository's ``.env.example`` files are public, so a deployment that copies one and forgets to
replace a value runs with a secret everybody knows. For ``JWT_SIGNING_KEY`` that means anyone can
mint a valid access token for any account, Super Admin included. Secrets that were exposed in the
past (``COMPROMISED_SHA256``) must never come back either.

``config/settings.py`` raises ``ImproperlyConfigured`` for any *error* when ``DEBUG`` is off (only a
warning in DEBUG) and always emits *warnings*. Messages name the variable, never the value.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

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

#: SHA-256 fingerprints of secret values that were published in the upstream project's git history
#: (high-entropy random keys, so a fingerprint does not reveal the value). A deployment that still
#: uses one of them is compromised. See docs/SECURITY_INCIDENT_RESPONSE.md.
COMPROMISED_SHA256 = frozenset(
    {
        "728c088e22bcb5af467546def2c9247171b2fe98ac95827e50dc80fbdc82cae8",  # a PINFL_ENCRYPTION_KEYS key
        "3da8ae9950e6008576a134f664739f06207ff3eccb5923b90d0896a728fd24a3",  # a GOOGLE_TOKEN_ENCRYPTION_KEY
        "309cc056df30a37c1d65f40a8ad9dd23acaa3df687b9f1553c7a4b50cb8637f2",  # a GOOGLE_OAUTH_CLIENT_SECRET
    }
)

#: Minimum length of the HMAC / signing secrets (``secrets.token_urlsafe(50)`` gives 67 characters).
MIN_SECRET_LENGTH = 32


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def is_placeholder(value: str) -> bool:
    return (value or "").strip().lower() in KNOWN_PLACEHOLDERS


def is_compromised(value: str) -> bool:
    value = (value or "").strip()
    return bool(value) and hashlib.sha256(value.encode()).hexdigest() in COMPROMISED_SHA256


def _check_fernet_list(report: Report, name: str, keys: list[str], *, required: bool) -> None:
    if not keys:
        if required:
            report.errors.append(f"{name} is empty.")
        return
    for position, key in enumerate(keys, start=1):
        if is_placeholder(key):
            report.errors.append(f"{name} key #{position} is the public placeholder from .env.example.")
            continue
        try:
            Fernet(key.encode())
        except ValueError:
            report.errors.append(f"{name} key #{position} is not a valid Fernet key.")
            continue
        if is_compromised(key):
            if position == 1:
                report.errors.append(f"{name} key #1 (the encryption key) is a known compromised value. Rotate it.")
            else:
                report.warnings.append(
                    f"{name} key #{position} is a known compromised value kept for decryption only: "
                    "run `manage.py rotate_encryption_keys --apply`, then remove it."
                )


def check(
    *,
    secret_key: str,
    jwt_signing_key: str,
    pinfl_hash_key: str,
    pinfl_encryption_keys: Iterable[str],
    google_token_keys: Iterable[str] = (),
    google_client_secret: str = "",
) -> Report:
    report = Report()
    for name, value in (
        ("DJANGO_SECRET_KEY", secret_key),
        ("JWT_SIGNING_KEY", jwt_signing_key),
        ("PINFL_HASH_KEY", pinfl_hash_key),
    ):
        value = (value or "").strip()
        if not value:
            report.errors.append(f"{name} is empty.")
        elif is_placeholder(value):
            report.errors.append(f"{name} still has the public placeholder value from .env.example.")
        elif is_compromised(value):
            report.errors.append(f"{name} is a known compromised value. Rotate it.")
        elif len(value) < MIN_SECRET_LENGTH:
            report.errors.append(f"{name} is shorter than {MIN_SECRET_LENGTH} characters.")

    if (jwt_signing_key or "").strip() and jwt_signing_key == secret_key:
        report.errors.append("JWT_SIGNING_KEY must differ from DJANGO_SECRET_KEY.")

    clean = lambda keys: [k.strip() for k in keys if k.strip()]  # noqa: E731
    _check_fernet_list(report, "PINFL_ENCRYPTION_KEYS", clean(pinfl_encryption_keys), required=True)
    _check_fernet_list(report, "GOOGLE_TOKEN_ENCRYPTION_KEY", clean(google_token_keys), required=False)

    if is_compromised(google_client_secret):
        report.errors.append("GOOGLE_OAUTH_CLIENT_SECRET is a known compromised value. Reset it in Google Cloud.")
    return report


def problems(**kwargs) -> list[str]:
    """Errors only (kept for callers that need a flat list)."""
    return check(**kwargs).errors
