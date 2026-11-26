"""Settings used by the test-suite: deterministic throwaway secrets, in-memory DB."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production-0123456789")
os.environ.setdefault("JWT_SIGNING_KEY", "test-jwt-signing-key-not-for-production-0123456789")
os.environ.setdefault("PINFL_ENCRYPTION_KEYS", "bW9ja19rZXlfZm9yX3Rlc3RzX29ubHlfMDEyMzQ1Njc=")
os.environ.setdefault("PINFL_HASH_KEY", "test-pinfl-hash-key-not-for-production-0123456789")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
# Tests never use a developer's real Google credentials from backend/.env (and the secret guard
# would rightly refuse compromised ones); the throwaway test values are set again below.
os.environ.setdefault("GOOGLE_TOKEN_ENCRYPTION_KEY", "")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_ID", "")
os.environ.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", "")
os.environ.setdefault("DECART_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("ANTHROPIC_API_KEY", "")

from .settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
    "anon": "10000/min",
    "user": "10000/min",
    "login": "10000/min",
    "register": "10000/min",
    "storage_connect": "10000/min",
    "ceremony_invite": "10000/min",
    "invitation_respond": "10000/min",
    "media_upload": "10000/min",
    "venue_member_add": "10000/min",
    "storage_callback": "10000/min",
    "token_refresh": "10000/min",
    "pinfl_reveal": "10000/min",
    "support_write": "10000/min",
    "partner_apply": "10000/min",
    "partner_challenge": "10000/min",
    "ai_tryon_session": "10000/min",
    "ai_tryon_token": "10000/min",
    "tryon_look": "10000/min",
    "ai_planner_message": "10000/min",
    "ai_planner_write": "10000/min",
    "ai_planner_admin_write": "10000/min",
}
MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
PRIVATE_MEDIA_ROOT = BASE_DIR / ".test-media" / "private"  # noqa: F405
AI_TRYON = {**AI_TRYON, "API_KEY": "", "ALLOWED_ORIGINS": []}  # noqa: F405 - tests enable it explicitly
AI_PLANNER = {**AI_PLANNER, "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}  # noqa: F405 - tests install a fake provider
MONITORING = {**MONITORING, "ASYNC": False}  # noqa: F405 - deterministic, inline writes
GOOGLE_TOKEN_ENCRYPTION_KEYS = ["dGVzdF9nb29nbGVfdG9rZW5fa2V5X29ubHlfMDEyMzQ="]  # base64 of 32 test bytes
GOOGLE_OAUTH_CLIENT_FILE = BASE_DIR / ".test-missing-google-client.json"  # noqa: F405 - tests inject config
GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
GOOGLE_OAUTH_CLIENT_SECRET = "test-client-secret"
CEREMONY_INVITE_REQUIRE_VERIFIED_PHONE = False  # mirrors dev; the strict mode is tested explicitly
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests"}}
PANEL_HOST_SITES = {}  # host-based panel routing is tested explicitly
