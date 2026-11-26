"""MarosimGo backend settings.

Every secret and environment-specific value comes from environment variables
(or a local ``backend/.env`` file in development). See ``.env.example``.
"""

import warnings
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

from config import secret_guard

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

# --------------------------------------------------------------------------- core
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    # local
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.studios",
    "apps.dashboard",
    "apps.monitoring",
    "apps.storage",
    "apps.ceremonies",
    "apps.media",
    "apps.venues",
    "apps.reviews",
    "apps.subscriptions",
    "apps.devcenter",
    "apps.support",
    "apps.virtual_tryon",
    "apps.event_planner",
]

MIDDLEWARE = [
    # Outermost, so request timing covers the whole stack.
    "apps.monitoring.middleware.RequestMetricsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ApiSecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]

# ----------------------------------------------------------------------- database
# SQLite by default; switch to PostgreSQL by setting e.g.
# DATABASE_URL=postgres://marosimgo:password@localhost:5432/marosimgo
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # Many concurrent users on SQLite: WAL lets readers run during a write, writers queue up to
    # 20 s instead of failing with "database is locked", and IMMEDIATE transactions take the write
    # lock up front (no deadlock when two requests upgrade a read to a write).
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=20000;",
        }
    )
else:
    # PostgreSQL / MySQL: reuse connections between requests instead of reconnecting every time.
    DATABASES["default"].setdefault("CONN_MAX_AGE", env.int("DB_CONN_MAX_AGE", default=60))
    DATABASES["default"].setdefault("CONN_HEALTH_CHECKS", True)
# No ATOMIC_REQUESTS: audit/security records must survive a failed request.
# Write paths use explicit transaction.atomic blocks instead.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Login lockout, throttling and the readiness probe need ONE cache shared by every worker process.
# Production default: a table in the main database (created by `migrate`); set CACHE_URL=redis://...
# when Redis is available. Development keeps the in-process cache.
CACHES = {
    "default": env.cache("CACHE_URL", default="locmemcache://marosimgo" if DEBUG else "dbcache://marosimgo_cache")
}

# --------------------------------------------------------------------------- auth
AUTH_USER_MODEL = "accounts.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("phone_number", "first_name", "last_name", "email")},
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Number of reverse proxies in front of Django (Next.js rewrite proxy = 1).
# Used for client IP detection (throttling, audit). Never trust X-Forwarded-For otherwise.
NUM_PROXIES = env.int("NUM_PROXIES", default=0)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.CookieJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env.str("THROTTLE_ANON", default="60/min"),
        "user": env.str("THROTTLE_USER", default="600/min"),
        "login": env.str("THROTTLE_LOGIN", default="5/min"),
        "register": env.str("THROTTLE_REGISTER", default="10/hour"),
        "ceremony_invite": env.str("THROTTLE_CEREMONY_INVITE", default="60/hour"),
        "invitation_respond": env.str("THROTTLE_INVITATION_RESPOND", default="30/hour"),
        "media_upload": env.str("THROTTLE_MEDIA_UPLOAD", default="600/hour"),
        "venue_member_add": env.str("THROTTLE_VENUE_MEMBER_ADD", default="30/hour"),
        "storage_connect": env.str("THROTTLE_STORAGE_CONNECT", default="20/hour"),
        "storage_callback": env.str("THROTTLE_STORAGE_CALLBACK", default="30/hour"),
        "token_refresh": env.str("THROTTLE_REFRESH", default="30/min"),
        "pinfl_reveal": env.str("THROTTLE_PINFL_REVEAL", default="20/hour"),
        "support_write": env.str("THROTTLE_SUPPORT_WRITE", default="60/hour"),
        "partner_apply": env.str("THROTTLE_PARTNER_APPLY", default="5/hour"),
        "partner_challenge": env.str("THROTTLE_PARTNER_CHALLENGE", default="60/hour"),
        "ai_tryon_session": env.str("THROTTLE_AI_TRYON_SESSION", default="20/hour"),
        "ai_tryon_token": env.str("THROTTLE_AI_TRYON_TOKEN", default="60/hour"),
        "tryon_look": env.str("THROTTLE_TRYON_LOOK", default="60/hour"),
        "ai_planner_message": env.str("THROTTLE_AI_PLANNER_MESSAGE", default="30/min"),
        "ai_planner_write": env.str("THROTTLE_AI_PLANNER_WRITE", default="600/hour"),
        "ai_planner_admin_write": env.str("THROTTLE_AI_PLANNER_ADMIN_WRITE", default="120/hour"),
    },
    "NUM_PROXIES": NUM_PROXIES or None,
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "apps.core.schema.MarosimAutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}
if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append("rest_framework.renderers.BrowsableAPIRenderer")

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=10)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY"),
    "ISSUER": "marosimgo",
    "AUDIENCE": "marosimgo-api",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "LEEWAY": 5,
}

# HttpOnly auth cookies for the web panel (mobile clients use the Authorization header).
AUTH_COOKIES = {
    "ACCESS": "mg_access",
    "REFRESH": "mg_refresh",
    # Non-secret marker ("1") so the Next.js proxy can tell a session probably exists.
    "SESSION_HINT": "mg_session",
    "REFRESH_PATH": "/api/v1/auth/",
    "SECURE": env.bool("AUTH_COOKIE_SECURE", default=not DEBUG),
    "DOMAIN": env.str("AUTH_COOKIE_DOMAIN", default=None),
}

# Login identifier: E.164 phone numbers from these regions (ISO 3166-1 alpha-2, first = default).
PHONE_ALLOWED_REGIONS = tuple(env.list("PHONE_ALLOWED_REGIONS", default=["UZ"]))

# Optional challenge verifier for public sign-up: dotted path to ``guard(request) -> bool``.
BOT_PROTECTION = {"GUARD": env.str("BOT_PROTECTION_GUARD", default="") or None}

# Brute-force protection (per phone number), on top of IP-based throttling.
LOGIN_LOCKOUT = {
    "MAX_FAILURES": env.int("LOGIN_MAX_FAILURES", default=5),
    "WINDOW_SECONDS": env.int("LOGIN_FAILURE_WINDOW", default=15 * 60),
    "LOCK_SECONDS": env.int("LOGIN_LOCK_SECONDS", default=15 * 60),
}

# --------------------------------------------------------------- PINFL protection
# Comma separated Fernet keys; the first one encrypts, all of them decrypt (rotation).
PINFL_ENCRYPTION_KEYS = env.list("PINFL_ENCRYPTION_KEYS")
# Separate secret for the deterministic HMAC used for uniqueness / exact search.
PINFL_HASH_KEY = env("PINFL_HASH_KEY")

# ------------------------------------------------------------------- CORS & CSRF
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ["accept", "authorization", "content-type", "x-csrftoken", "x-client"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:3000"])
CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_HTTPONLY = False  # the SPA must read it to send X-CSRFToken (double submit)
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = AUTH_COOKIES["SECURE"]
SESSION_COOKIE_SECURE = AUTH_COOKIES["SECURE"]

# ------------------------------------------------------------- security headers
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
# Behind the Next.js proxy: build absolute URLs (pagination, media) with the panel's host.
USE_X_FORWARDED_HOST = env.bool("USE_X_FORWARDED_HOST", default=False)
if env.bool("USE_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ------------------------------------------------------------------ uploads/media
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# Let Django serve uploads (development / small deployments). In production prefer nginx.
SERVE_MEDIA = env.bool("SERVE_MEDIA", default=DEBUG)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 200
IMAGE_UPLOAD = {
    "MAX_BYTES": 5 * 1024 * 1024,
    "MAX_PIXELS": 25_000_000,
    "MAX_SIDE": 1024,
    "ALLOWED_FORMATS": ("JPEG", "PNG", "WEBP"),
}
#: Studio portfolio reels (vertical videos); the panel proxies must allow the same body size.
STUDIO_REEL_MAX_MB = env.int("STUDIO_REEL_MAX_MB", default=100)
#: Where new portfolio files go: "auto" (Drive when connected), "drive" or "local".
STUDIO_PORTFOLIO_STORAGE = env.str("STUDIO_PORTFOLIO_STORAGE", default="auto")

# ------------------------------------------------------------------- i18n / time
LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

# ----------------------------------------------------------------------- OpenAPI
SPECTACULAR_SETTINGS = {
    "TITLE": "MarosimGo API",
    "DESCRIPTION": (
        "MarosimGo REST API (v1). Login identifikatori — telefon raqam (E.164).\n\n"
        "* **Mobil:** `X-Client: mobile` + `Authorization: Bearer <access>`.\n"
        "* **Web panel:** httpOnly cookie + `X-CSRFToken`.\n\n"
        "Har bir operatsiyada `x-access` (rol/ruxsat) va standart xato javoblari avtomatik hujjatlashtiriladi."
    ),
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "SubscriptionAudienceEnum": "apps.subscriptions.models.PlanAudience",
        "RoleEnum": "apps.accounts.models.Role",
        "ClientRoleEnum": ["USER", "STUDIO"],
        "AdminRoleEnum": ["ADMIN"],
        "CeremonyStatusEnum": "apps.ceremonies.models.CeremonyStatus",
        "ParticipantAccessStatusEnum": "apps.ceremonies.models.AccessStatus",
        "ParticipantTypeEnum": "apps.ceremonies.models.ParticipantType",
        "CeremonyAccessRoleEnum": "apps.ceremonies.models.AccessRole",
        "CeremonyOwnerTypeEnum": "apps.ceremonies.models.OwnerType",
        "InvitationIdentifierTypeEnum": "apps.ceremonies.models.IdentifierType",
        "InviterKindEnum": "apps.ceremonies.models.InviterKind",
        "InvitationStatusEnum": "apps.ceremonies.models.InvitationStatus",
        "OwnershipStatusEnum": "apps.ceremonies.models.OwnershipStatus",
        "InvitationAcceptStatusEnum": ["ACCEPTED", "PENDING_APPROVAL"],
        "MediaKindEnum": "apps.media.models.MediaKind",
        "BookingStatusEnum": "apps.venues.models.BookingStatus",
        "EventTypeEnum": "apps.ceremonies.models.EventType",
        "BookingEventTypeEnum": "apps.venues.models.BookingEventType",
        "BookingSourceEnum": "apps.venues.models.BookingSource",
        "VenueEntryStatusEnum": ["CONFIRMED", "BLOCKED"],
        "SubscriptionStatusEnum": "apps.subscriptions.models.SubscriptionStatus",
        "SubscriptionStateEnum": ["PENDING", "ACTIVE", "SCHEDULED", "EXPIRED", "REJECTED", "CANCELLED"],
        "PaymentMethodEnum": "apps.subscriptions.models.PaymentMethod",
        "MediaStatusEnum": "apps.media.models.MediaStatus",
        "MediaDeletionStatusEnum": "apps.media.models.DeletionRequestStatus",
        "PortfolioKindEnum": "apps.studios.models.PortfolioKind",
        "PortfolioReactionEnum": ["like", "dislike"],
        "StudioDayStatusEnum": "apps.studios.models.StudioDayStatus.Status",
        "PortfolioStorageEnum": "apps.studios.models.PortfolioStorage",
        "SupportTicketStatusEnum": "apps.support.models.TicketStatus",
        "SupportAudienceEnum": "apps.support.models.TicketAudience",
        "PartnerApplicationStatusEnum": "apps.support.models.ApplicationStatus",
        "PartnerApplicationKindEnum": "apps.support.models.ApplicationKind",
        "StorageConnectionStatusEnum": "apps.storage.models.ConnectionStatus",
        "VenueRegionEnum": "apps.venues.models.Region",
        "VenueTypeEnum": "apps.venues.models.VenueType",
        "VenuePublicationStatusEnum": "apps.venues.models.PublicationStatus",
        "VenueMembershipRoleEnum": "apps.venues.models.MembershipRole",
        "CurrencyEnum": "apps.venues.models.Currency",
        "GarmentAssetKindEnum": "apps.virtual_tryon.models.AssetKind",
        "GarmentApprovalStatusEnum": "apps.virtual_tryon.models.ApprovalStatus",
        "GarmentAssetTypeEnum": "apps.virtual_tryon.models.GarmentAssetType",
        "GarmentAudienceEnum": "apps.virtual_tryon.models.Audience",
        "AiTryOnEndReasonEnum": "apps.virtual_tryon.models.AiEndReason",
        "AiTryOnSessionStatusEnum": "apps.virtual_tryon.models.AiSessionStatus",
        "PlannerEventTypeEnum": "apps.event_planner.models.EventType",
        "PlannerStyleEnum": "apps.event_planner.models.PlanStyle",
        "PlannerBudgetFlexibilityEnum": "apps.event_planner.models.BudgetFlexibility",
        "PlannerPlanStatusEnum": "apps.event_planner.models.PlanStatus",
        "PlannerPlanSourceEnum": "apps.event_planner.models.PlanSource",
        "PlannerBudgetCategoryEnum": "apps.event_planner.models.BudgetCategory",
        "PlannerItemCategoryEnum": "apps.event_planner.models.ITEM_CATEGORIES",
        "PlannerPackageCategoryEnum": "apps.event_planner.models.PACKAGE_CATEGORIES",
        "PlannerBudgetUnitEnum": "apps.event_planner.models.BudgetUnit",
        "PlannerSourceTypeEnum": "apps.event_planner.models.SourceType",
        "PlannerClientSourceTypeEnum": "apps.event_planner.models.CLIENT_SOURCE_TYPES",
        "PlannerSourceKindEnum": "apps.event_planner.models.SourceKind",
        "PlannerPriceStatusEnum": "apps.event_planner.models.PriceStatus",
        "PlannerClientPriceStatusEnum": "apps.event_planner.models.CLIENT_PRICE_STATUSES",
        "AiConversationStatusEnum": "apps.event_planner.models.ConversationStatus",
        "AiMessageRoleEnum": "apps.event_planner.models.MessageRole",
        "AiMessageStatusEnum": "apps.event_planner.models.MessageStatus",
        "AiFeedbackEnum": "apps.event_planner.models.Feedback",
        "AiUsageStatusEnum": "apps.event_planner.models.UsageStatus",
        "AiProviderEnum": "apps.event_planner.models.ProviderName",
        "AiEffortEnum": "apps.event_planner.models.Effort",
        "AiPromptStatusEnum": "apps.event_planner.models.PromptStatus",
        "AiReportReasonEnum": "apps.event_planner.models.ReportReason",
        "AiReportStatusEnum": "apps.event_planner.models.ReportStatus",
        "AiDisableScopeEnum": "apps.event_planner.models.DISABLE_SCOPES",
    },
    "SERVE_PERMISSIONS": (
        ["rest_framework.permissions.AllowAny"] if DEBUG else ["apps.accounts.permissions.IsSuperAdmin"]
    ),
}

# -------------------------------------------------------------------- ceremonies
# Accepting a ceremony invitation proves ownership of the invited phone number only if the
# number is OTP-verified. Until an SMS provider exists this is relaxed in DEBUG only.
CEREMONY_INVITE_REQUIRE_VERIFIED_PHONE = env.bool("CEREMONY_INVITE_REQUIRE_VERIFIED_PHONE", default=not DEBUG)
# OWNER access is never granted on an unverified number — not even in DEBUG. Knowing a number
# (or having registered it first) must not be enough to claim a ceremony.
CEREMONY_OWNER_REQUIRE_VERIFIED_PHONE = env.bool("CEREMONY_OWNER_REQUIRE_VERIFIED_PHONE", default=True)
CEREMONY_INVITATION_TTL_DAYS = env.int("CEREMONY_INVITATION_TTL_DAYS", default=14)
# Abuse limits: open invitations per ceremony, renewals per invitation.
CEREMONY_MAX_PENDING_INVITATIONS = env.int("CEREMONY_MAX_PENDING_INVITATIONS", default=50)
#: How many people one ceremony owner may share the gallery with at a time (live access + pending invitations).
CEREMONY_MAX_VIEWERS_PER_OWNER = env.int("CEREMONY_MAX_VIEWERS_PER_OWNER", default=5)
#: Burn the MarosimGo logo into videos in a background thread of the web process (needs ffmpeg).
#: Off: run `manage.py process_watermarks --loop` as a separate worker instead.
MEDIA_WATERMARK_INLINE = env.bool("MEDIA_WATERMARK_INLINE", default=True)
#: The logo copy is a preview: its shorter side is scaled down to this (0 = keep the original size).
MEDIA_WATERMARK_MAX_HEIGHT = env.int("MEDIA_WATERMARK_MAX_HEIGHT", default=720)
#: "auto" picks the first working GPU encoder (h264_nvenc / h264_qsv / h264_amf), else libx264.
MEDIA_WATERMARK_ENCODER = env.str("MEDIA_WATERMARK_ENCODER", default="auto")
#: ffmpeg reads the original straight from Drive while encoding (no full download first).
MEDIA_WATERMARK_STREAM_SOURCE = env.bool("MEDIA_WATERMARK_STREAM_SOURCE", default=True)
CEREMONY_MAX_INVITATION_SENDS = env.int("CEREMONY_MAX_INVITATION_SENDS", default=5)

# Landing page partner applications: anti-bot proof-of-work (apps/support/challenge.py).
PARTNER_APPLY = {
    "POW_BITS": env.int("PARTNER_APPLY_POW_BITS", default=16),
    "MIN_SECONDS": env.int("PARTNER_APPLY_MIN_SECONDS", default=3),
    "MAX_AGE_SECONDS": 2 * 3600,
}

# Ceremony media (Phase D): client → Google Drive resumable sessions; nothing is public.
MEDIA_UPLOAD = {
    "PHOTO_MAX_BYTES": env.int("MEDIA_PHOTO_MAX_MB", default=50) * 1024 * 1024,
    "VIDEO_MAX_BYTES": env.int("MEDIA_VIDEO_MAX_MB", default=20 * 1024) * 1024 * 1024,
    "MAX_ACTIVE_PER_CEREMONY": env.int("MEDIA_MAX_ACTIVE_UPLOADS", default=50),
    # Google keeps a resumable session for about a week; close ours a little earlier.
    "SESSION_TTL_HOURS": env.int("MEDIA_SESSION_TTL_HOURS", default=144),
    # Web apps that PUT bytes to Google directly (studio cabinet). The session is opened with this
    # Origin so Google returns CORS headers on the final response; anything else is not forwarded.
    "BROWSER_ORIGINS": env.list(
        "MEDIA_UPLOAD_BROWSER_ORIGINS", default=["http://localhost:3001", "http://127.0.0.1:3001"]
    ),
}

# -------------------------------------------------------- AI virtual try-on (Decart)
# Live try-on with Decart's realtime model (WebRTC, browser ↔ Decart). The permanent API key stays on
# the server: browsers only receive short-lived client tokens minted by POST /v1/client/tokens.
# Docs: https://docs.platform.decart.ai/models/realtime/virtual-try-on — empty key = feature off.
AI_TRYON = {
    "API_KEY": env.str("DECART_API_KEY", default=""),
    "API_BASE": env.str("DECART_API_BASE", default="https://api.decart.ai").rstrip("/"),
    "MODEL": env.str("DECART_TRYON_MODEL", default="lucy-vton-latest"),
    #: Lifetime of a browser client token (Decart: 1-3600 s). Only needed to *start* a connection.
    "TOKEN_TTL_SECONDS": env.int("DECART_TOKEN_TTL_SECONDS", default=60),
    #: Web origins the token may be used from (Decart `allowedOrigins`); empty = not restricted.
    "ALLOWED_ORIGINS": env.list("DECART_ALLOWED_ORIGINS", default=[]),
    "REQUEST_TIMEOUT_SECONDS": env.int("DECART_REQUEST_TIMEOUT_SECONDS", default=10),
    # Cost controls (Decart bills per second of active generation).
    "MAX_SESSION_SECONDS": env.int("AI_TRYON_MAX_SESSION_SECONDS", default=180),
    "DAILY_SECONDS_PER_USER": env.int("AI_TRYON_DAILY_SECONDS_PER_USER", default=900),
    "DAILY_SESSIONS_PER_USER": env.int("AI_TRYON_DAILY_SESSIONS_PER_USER", default=10),
    #: Platform-wide budget per day in seconds (0 = no global cap).
    "GLOBAL_DAILY_SECONDS": env.int("AI_TRYON_GLOBAL_DAILY_SECONDS", default=0),
    "MAX_TOKENS_PER_SESSION": env.int("AI_TRYON_MAX_TOKENS_PER_SESSION", default=20),
    #: Only for the admin usage estimate (USD per second; Decart list price for lucy-vton at 720p).
    "PRICE_PER_SECOND_USD": env.float("AI_TRYON_PRICE_PER_SECOND_USD", default=0.02),
    "MAX_SAVED_LOOKS_PER_USER": env.int("AI_TRYON_MAX_SAVED_LOOKS", default=50),
    #: Snapshot AI try-on fallback via OpenAI Image Edit when DECART_API_KEY is not set.
    "OPENAI_MODEL": env.str("OPENAI_TRYON_MODEL", default="gpt-image-1.5"),
    "OPENAI_QUALITY": env.str("OPENAI_TRYON_QUALITY", default="medium"),
    "OPENAI_INPUT_FIDELITY": env.str("OPENAI_TRYON_INPUT_FIDELITY", default="high"),
    "OPENAI_TIMEOUT_SECONDS": env.int("OPENAI_TRYON_TIMEOUT_SECONDS", default=90),
    #: Primary Virtual Try-On via fal.ai (FASHN v1.6 photo + Kling O3 video-to-video edit).
    "FAL_KEY": env.str("FAL_KEY", default=""),
    "FAL_PHOTO_MODEL": env.str("FAL_TRYON_PHOTO_MODEL", default="fal-ai/fashn/tryon/v1.6"),
    "FAL_VIDEO_MODEL": env.str("FAL_TRYON_VIDEO_MODEL", default="fal-ai/kling-video/o3/standard/video-to-video/edit"),
    "FAL_TIMEOUT_SECONDS": env.int("FAL_TRYON_TIMEOUT_SECONDS", default=420),
    # Video try-on pipeline:
    #   "kling" (default) — Kling O3 edits the user's own clip: their exact movements are kept. 5–12 min.
    #   "fast"  — dress one frame (~30 s, shown at once) → animate it (~30 s). ~1 min, but the motion is
    #             re-created, not the user's own (user decision 2026-11-26: real motion matters more).
    "FAL_VIDEO_PIPELINE": env.str("FAL_TRYON_VIDEO_PIPELINE", default="kling"),
    # Stage 1 dresses one frame. Seedream edit keeps the whole outfit incl. small accessories (bow tie,
    # shirt, trousers) — FASHN dropped them (user report 2026-11-26). Set to the FASHN model to go back.
    "FAL_PHOTO_STAGE_MODEL": env.str("FAL_TRYON_PHOTO_STAGE_MODEL", default="fal-ai/bytedance/seedream/v4/edit"),
    "FAL_MOTION_MODEL": env.str("FAL_TRYON_MOTION_MODEL", default="fal-ai/ltx-2.3/image-to-video/fast"),
    #: Real Video Virtual Try-On via Replicate (Kling v3 Omni direct video editing).
    "REPLICATE_API_TOKEN": env.str("REPLICATE_API_TOKEN", default=""),
    "REPLICATE_VIDEO_MODEL": env.str("REPLICATE_TRYON_VIDEO_MODEL", default="kwaivgi/kling-v3-omni-video"),
    "REPLICATE_VIDEO_MODE": env.str("REPLICATE_TRYON_VIDEO_MODE", default="standard"),
    "REPLICATE_TIMEOUT_SECONDS": env.int("REPLICATE_TRYON_TIMEOUT_SECONDS", default=240),
}
# ------------------------------------------------- AI event planner (OpenAI / Anthropic)
# The key is read from the environment only (never stored in the DB or shown in the panel; the panel only
# shows "configured / missing"). Empty key = the AI chat shows "temporarily unavailable"; plans, the budget
# calculator and bookings keep working. Model, limits and switches are managed by the Super Admin.
# What one unit of AI work costs the platform (USD, provider list prices checked 2026-11-26).
# Used for AI quotas, plan economics and the admin income/expense report (apps.subscriptions.pricing).
PLATFORM_COSTS = {
    # Kling O3 edit (default pipeline) ≈ $0.126 / s × 5 s = $0.63.
    # (Fast pipeline: Seedream $0.03 + LTX 6 s × $0.06 ≈ $0.40 — set COST_AI_VIDEO_USD=0.40 with it.)
    "AI_VIDEO_USD": env.float("COST_AI_VIDEO_USD", default=0.63),
    # fal.ai FASHN try-on v1.6: $0.075 per generation.
    "AI_PHOTO_USD": env.float("COST_AI_PHOTO_USD", default=0.075),
    # Google One 2 TB ≈ $9.99 / month → $0.005 per GB-month.
    "STORAGE_GB_MONTH_USD": env.float("COST_STORAGE_GB_MONTH_USD", default=0.005),
    # Extra margin on top of list prices: failed / retried renders, card fees, exchange-rate moves.
    "SAFETY_FACTOR": env.float("COST_SAFETY_FACTOR", default=1.10),
}

# Businesses pay a mandatory monthly fee (their Premium / galichka). Unpaid ones leave the public
# catalog after GRACE_DAYS. START = launch day: existing businesses get their grace from it.
BUSINESS_BILLING = {
    "ENFORCE": env.bool("BUSINESS_BILLING_ENFORCE", default=True),
    "GRACE_DAYS": env.int("BUSINESS_BILLING_GRACE_DAYS", default=7),
    "START": env.str("BUSINESS_BILLING_START", default="2026-11-26"),
    "VENUE_MONTHLY_FEE": env.int("BUSINESS_VENUE_MONTHLY_FEE", default=300_000),
    "STUDIO_MONTHLY_FEE": env.int("BUSINESS_STUDIO_MONTHLY_FEE", default=150_000),
}

# Users without Premium: AI photos per month (AI video is Premium only).
AI_FREE_PHOTOS_PER_MONTH = env.int("AI_FREE_PHOTOS_PER_MONTH", default=3)

AI_PLANNER = {
    "OPENAI_API_KEY": env.str("OPENAI_API_KEY", default=""),
    "OPENAI_BASE_URL": env.str("OPENAI_BASE_URL", default="https://api.openai.com/v1").rstrip("/"),
    "ANTHROPIC_API_KEY": env.str("ANTHROPIC_API_KEY", default=""),
    #: Per attempt; the client retries connection errors, 408/409/429 and 5xx with backoff.
    "TIMEOUT_SECONDS": env.float("AI_PLANNER_TIMEOUT_SECONDS", default=45.0),
    "MAX_RETRIES": env.int("AI_PLANNER_MAX_RETRIES", default=2),
    #: Server-side refusal fallback (Anthropic beta ``server-side-fallback-2026-07-01``).
    "REFUSAL_FALLBACK": env.bool("AI_PLANNER_REFUSAL_FALLBACK", default=True),
    #: USD per million (input, output) tokens — only for the admin cost estimate when usage is reported.
    "PRICES_USD_PER_MTOK": {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.0),
        "gpt-4.1-mini": (0.40, 1.60),
        "gpt-4.1": (2.0, 8.0),
        "gpt-5-mini": (0.25, 2.0),
        "gpt-5": (1.25, 10.0),
        "claude-opus-5-5": (4.0, 20.0),
        "claude-sonnet-5-5": (2.0, 10.0),
        "claude-haiku-5-5": (0.10, 0.50),
    },
}

#: Files only their owner may download (served by permission-checked views, never under /media/).
PRIVATE_MEDIA_ROOT = Path(env.str("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private-media")))

# ----------------------------------------------------------- Google Drive storage
# OAuth "Web application" client. Read from the JSON downloaded from Google Cloud Console
# (kept out of git in backend/credentials/); GOOGLE_OAUTH_CLIENT_ID / _SECRET / _REDIRECT_URI
# environment variables override the file (useful for production secret managers).
GOOGLE_OAUTH_CLIENT_FILE = Path(
    env.str("GOOGLE_OAUTH_CLIENT_FILE", default=str(BASE_DIR / "credentials" / "google_oauth_client.json"))
)
GOOGLE_OAUTH_CLIENT_ID = env.str("GOOGLE_OAUTH_CLIENT_ID", default="")
GOOGLE_OAUTH_CLIENT_SECRET = env.str("GOOGLE_OAUTH_CLIENT_SECRET", default="")
GOOGLE_OAUTH_REDIRECT_URI = env.str(
    "GOOGLE_OAUTH_REDIRECT_URI", default="http://localhost:8000/api/v1/admin/storage/google/callback/"
)
# Minimal scopes: drive.file = only files/folders this app creates or the owner picks (non-sensitive).
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/drive.file",
]
GOOGLE_OAUTH_STATE_TTL_SECONDS = env.int("GOOGLE_OAUTH_STATE_TTL_SECONDS", default=600)
# Refresh tokens are Fernet-encrypted with these keys (first encrypts, all decrypt — rotation).
GOOGLE_TOKEN_ENCRYPTION_KEYS = env.list("GOOGLE_TOKEN_ENCRYPTION_KEY", default=[])
# Optional default root folder (Phase B lets the Super Admin pick one instead).
GOOGLE_DRIVE_ROOT_FOLDER_ID = env.str("GOOGLE_DRIVE_ROOT_FOLDER_ID", default="")

# Never boot production with empty, weak, publicly known or compromised secrets
# (config/secret_guard.py). Runs here, after every secret above has been read.
_secret_report = secret_guard.check(
    secret_key=SECRET_KEY,
    jwt_signing_key=SIMPLE_JWT["SIGNING_KEY"],
    pinfl_hash_key=PINFL_HASH_KEY,
    pinfl_encryption_keys=PINFL_ENCRYPTION_KEYS,
    google_token_keys=GOOGLE_TOKEN_ENCRYPTION_KEYS,
    google_client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
)
for _message in _secret_report.warnings:
    warnings.warn(_message, stacklevel=1)
if _secret_report.errors:
    if not DEBUG:
        raise ImproperlyConfigured("Insecure secret configuration: " + " ".join(_secret_report.errors))
    warnings.warn(
        "Insecure secret configuration (allowed only because DEBUG=true): " + " ".join(_secret_report.errors),
        stacklevel=1,
    )
# Where the OAuth callback sends the browser back to (the Super Admin panel).
# Production: PANEL_URL=https://superadmin.marosimgo.uz (served by this same Django app)
PANEL_URL = env.str("PANEL_URL", default="http://localhost:3000").rstrip("/")
# The panels are static exports served by this same Django app on every path outside /api/,
# /media/ and /static/ (see config/panel.py) — one cPanel deploy, no Node.js:
#   superadmin.marosimgo.uz → backend/panel/         (frontend/: npm run build:panel)
#   admin.marosimgo.uz      → backend/panel-admin/   (frontend/: npm run build:panel:admin)
#   studio.marosimgo.uz     → backend/panel-studio/  (frontend-studio/: npm run build:panel)
#   marosimgo.uz, www.      → backend/landing/       (the public landing page)
#   api.marosimgo.uz        → API only
SERVE_PANEL = env.bool("SERVE_PANEL", default=True)
PANEL_SITES = {
    "superadmin": BASE_DIR / "panel",
    "admin": BASE_DIR / "panel-admin",
    "studio": BASE_DIR / "panel-studio",
    "userlogin": BASE_DIR / "panel-user",  # couples and guests (frontend-user)
    "toyxona": BASE_DIR / "panel-toyxona",  # venue owners (frontend-toyxona)
    "landing": BASE_DIR / "landing",  # hand-written page, no build step
}
# A host picks its site by its first DNS label (studio.marosimgo.uz → studio, studio.localhost → studio).
# Explicit overrides (other domains, local development): PANEL_HOST_SITES=panel.example.com=superadmin,...
PANEL_HOST_SITES = {
    k.lower(): v
    for k, v in env.dict(
        "PANEL_HOST_SITES",
        default={
            "marosimgo.uz": "landing",
            "www.marosimgo.uz": "landing",
            "localhost": "superadmin",
            "127.0.0.1": "landing",  # http://127.0.0.1:8000/ = the marosimgo.uz landing page
        },
    ).items()
}
# Hosts that match no site get this one; empty = API only (api.marosimgo.uz).
PANEL_DEFAULT_SITE = env.str("PANEL_DEFAULT_SITE", default="")

# -------------------------------------------------------------------- monitoring
MONITORING = {
    "ENABLED": env.bool("MONITORING_ENABLED", default=True),
    # Write request metrics from a background thread (False = inline, used by tests).
    "ASYNC": env.bool("MONITORING_ASYNC", default=True),
    "BATCH_SIZE": 200,
    "FLUSH_INTERVAL_SECONDS": 2.0,
    "QUEUE_MAX": 10_000,
    "RETENTION_DAYS": env.int("MONITORING_RETENTION_DAYS", default=14),
    "MAX_ROWS": env.int("MONITORING_MAX_ROWS", default=2_000_000),
    "PRUNE_INTERVAL_SECONDS": 3600,
    "CATALOG_TTL_SECONDS": 300,
    "INCLUDE_PREFIXES": ["/api/"],
    # Probes, the monitoring UI itself and the docs would only add noise.
    "EXCLUDE_PREFIXES": ["/api/v1/health/", "/api/v1/monitoring/", "/api/v1/schema/", "/api/v1/docs/"],
}
# Base URL shown in the API command examples of the monitoring catalog (documentation only).
PUBLIC_API_BASE_URL = env.str("PUBLIC_API_BASE_URL", default="http://localhost:8000").rstrip("/")

# ----------------------------------------------------------------------- logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact": {"()": "apps.core.logging.SensitiveDataFilter"}},
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain", "filters": ["redact"]},
    },
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # runserver access log prints full URLs: redact OAuth ?code=&state= and tokens there too.
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
