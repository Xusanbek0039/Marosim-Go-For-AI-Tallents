"""Production must not boot with empty or publicly known secrets (config/secret_guard.py)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

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
