"""Production must not boot with empty or publicly known secrets (config/secret_guard.py)."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from apps.storage import client_config
from config import secret_guard

BACKEND = Path(__file__).resolve().parent.parent
FERNET = Fernet.generate_key().decode()
GOOD = {
    "secret_key": "s" * 50,
    "jwt_signing_key": "j" * 50,
    "pinfl_hash_key": "h" * 50,
    "pinfl_encryption_keys": [FERNET],
}


def test_strong_configuration_has_no_problems():
    assert secret_guard.problems(**GOOD) == []


@pytest.mark.parametrize(
    "field,value,needle",
    [
        ("secret_key", "change-me", "DJANGO_SECRET_KEY"),
        ("jwt_signing_key", "change-me-too", "JWT_SIGNING_KEY"),
        ("jwt_signing_key", "  Change-Me-Too ", "JWT_SIGNING_KEY"),
        ("pinfl_hash_key", "another-long-random-secret", "PINFL_HASH_KEY"),
        ("jwt_signing_key", "", "JWT_SIGNING_KEY is empty"),
        ("pinfl_hash_key", "short-but-not-a-placeholder", "shorter than 32"),
        ("secret_key", "x" * 31, "DJANGO_SECRET_KEY is shorter"),
        ("pinfl_encryption_keys", ["generate-a-fernet-key"], "placeholder"),
        ("pinfl_encryption_keys", ["not-a-fernet-key"], "not a valid Fernet key"),
        ("pinfl_encryption_keys", [FERNET, "bad"], "key #2"),
        ("pinfl_encryption_keys", [], "PINFL_ENCRYPTION_KEYS is empty"),
    ],
)
def test_each_insecure_value_is_reported(field, value, needle):
    found = secret_guard.problems(**{**GOOD, field: value})
    assert any(needle in p for p in found), found


def test_jwt_key_must_differ_from_django_secret():
    found = secret_guard.problems(**{**GOOD, "jwt_signing_key": GOOD["secret_key"]})
    assert found == ["JWT_SIGNING_KEY must differ from DJANGO_SECRET_KEY."]


def test_problems_never_echo_secret_values():
    leaked = "super-secret-value-that-must-not-appear"
    found = secret_guard.problems(**{**GOOD, "pinfl_encryption_keys": [leaked]})
    assert found and all(leaked not in p for p in found)


def _import_settings(**overrides):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_SECRET_KEY": "s" * 50,
        "JWT_SIGNING_KEY": "j" * 50,
        "PINFL_HASH_KEY": "h" * 50,
        "PINFL_ENCRYPTION_KEYS": FERNET,
        "DATABASE_URL": "sqlite://:memory:",
        # explicit values win over a developer's backend/.env (read_env never overwrites)
        "GOOGLE_TOKEN_ENCRYPTION_KEY": "",
        "GOOGLE_OAUTH_CLIENT_ID": "",
        "GOOGLE_OAUTH_CLIENT_SECRET": "",
        **overrides,
    }
    return subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_production_refuses_to_boot_with_placeholder_jwt_key():
    result = _import_settings(DJANGO_DEBUG="false", JWT_SIGNING_KEY="change-me-too")
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr and "JWT_SIGNING_KEY" in result.stderr
    assert "change-me-too" not in result.stderr


def test_production_boots_with_strong_secrets():
    result = _import_settings(DJANGO_DEBUG="false")
    assert result.returncode == 0, result.stderr


def test_debug_only_warns():
    result = _import_settings(DJANGO_DEBUG="true", PINFL_HASH_KEY="another-long-random-secret")
    assert result.returncode == 0, result.stderr
    assert "PINFL_HASH_KEY" in result.stderr


# ------------------------------------------------------------ known-compromised values
LEAKED_FERNET = Fernet.generate_key().decode()  # stands in for a published key in these tests
LEAKED_TEXT = "a-previously-published-secret-value-0123456789"


@pytest.fixture
def leaked(monkeypatch):
    fingerprints = {hashlib.sha256(v.encode()).hexdigest() for v in (LEAKED_FERNET, LEAKED_TEXT)}
    monkeypatch.setattr(secret_guard, "COMPROMISED_SHA256", frozenset(fingerprints))


def test_compromised_primary_encryption_key_is_an_error(leaked):
    report = secret_guard.check(**{**GOOD, "pinfl_encryption_keys": [LEAKED_FERNET]})
    assert any("PINFL_ENCRYPTION_KEYS key #1" in e and "compromised" in e for e in report.errors)


def test_compromised_secondary_key_only_warns_so_rotation_can_run(leaked):
    report = secret_guard.check(**{**GOOD, "pinfl_encryption_keys": [FERNET, LEAKED_FERNET]})
    assert report.errors == []
    assert any("key #2" in w and "rotate_encryption_keys" in w for w in report.warnings)


def test_compromised_google_token_key_and_client_secret(leaked):
    report = secret_guard.check(**GOOD, google_token_keys=[LEAKED_FERNET], google_client_secret=LEAKED_TEXT)
    assert any(e.startswith("GOOGLE_TOKEN_ENCRYPTION_KEY key #1") for e in report.errors)
    assert any(e.startswith("GOOGLE_OAUTH_CLIENT_SECRET") for e in report.errors)


def test_compromised_hmac_secret_is_an_error(leaked):
    assert "JWT_SIGNING_KEY is a known compromised value. Rotate it." in secret_guard.problems(
        **{**GOOD, "jwt_signing_key": LEAKED_TEXT}
    )


def test_invalid_google_token_key_is_an_error():
    report = secret_guard.check(**GOOD, google_token_keys=["not-fernet"])
    assert report.errors == ["GOOGLE_TOKEN_ENCRYPTION_KEY key #1 is not a valid Fernet key."]


def test_compromised_values_are_never_echoed(leaked):
    report = secret_guard.check(**{**GOOD, "pinfl_encryption_keys": [LEAKED_FERNET, LEAKED_FERNET]})
    assert all(LEAKED_FERNET not in m for m in report.errors + report.warnings)


def test_oauth_client_loader_rejects_compromised_secret_from_file(leaked, tmp_path, settings):
    path = tmp_path / "client.json"
    redirect = settings.GOOGLE_OAUTH_REDIRECT_URI
    path.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "1-a.apps.googleusercontent.com",
                    "client_secret": LEAKED_TEXT,
                    "redirect_uris": [redirect],
                }
            }
        )
    )
    settings.GOOGLE_OAUTH_CLIENT_FILE, settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET = (
        path,
        "",
        "",
    )
    with pytest.raises(client_config.ClientConfigError) as exc:
        client_config.load()
    assert exc.value.code == "client_secret_compromised" and LEAKED_TEXT not in exc.value.message


def test_oauth_client_loader_rejects_compromised_secret_from_env(leaked, settings):
    settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET = "1-a.apps.googleusercontent.com", LEAKED_TEXT
    with pytest.raises(client_config.ClientConfigError, match="oshkor"):
        client_config.load()


def test_real_fingerprints_are_sha256_hex():
    assert secret_guard.COMPROMISED_SHA256 and all(
        len(h) == 64 and int(h, 16) >= 0 for h in secret_guard.COMPROMISED_SHA256
    )
