# AI marosim rejalashtiruvchisi — "Marosim GO AI Maslahatchisi"

An event-planning assistant for USER accounts: it chats in Uzbek (or the user's language), asks only the
most important missing question, drafts a plan and a budget, and recommends **only real services that the
backend returned** (approved venues/halls and active studios). It never books or pays; a booking is the
existing venue request form, opened and submitted by the user.

| Part | Where |
|---|---|
| Backend app | `backend/apps/event_planner/` |
| User screens | `frontend-user` → `/ai-reja` (hub, chat) and `/ai-reja/<plan id>` (budget, plan, services, chat) |
| Admin / Super Admin | admin panel (`frontend`) → `/ai-planner` |
| Tests | `backend/tests/test_event_planner.py`, `frontend-user/src/features/ai-planner/budget.test.ts`, `frontend/src/features/ai-planner/access.test.ts` |

## Setup

1. `pip install -r backend/requirements.txt` (adds the official `anthropic` SDK) and `python manage.py migrate`
   (creates `event_planner` tables and new audit actions).
2. Set `ANTHROPIC_API_KEY` in the backend environment (never in a frontend `.env`, never in the database).
   Without it the chat shows "AI maslahatchi vaqtincha mavjud emas"; plans, the calculator and bookings work.
3. Optional: give admins the new codes in **Adminlar → ruxsatlar** (`ai.view`, `ai.reports`,
   `ai.conversations`, `ai.disable`).
4. Super Admin → **AI maslahatchi → Sozlamalar**: model (default `claude-opus-5-5`), effort, limits,
   feature flags, maintenance mode. Press **Tekshirish** to validate the key and model without generating.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Server-side key. Empty = AI unavailable (honestly shown). |
| `AI_PLANNER_TIMEOUT_SECONDS` | `45` | Per-attempt timeout. |
| `AI_PLANNER_MAX_RETRIES` | `2` | SDK retries (connection errors, 408/409/429, 5xx). |
| `AI_PLANNER_REFUSAL_FALLBACK` | `true` | Anthropic server-side refusal fallback (`fallbacks="default"`). |
| `THROTTLE_AI_PLANNER_MESSAGE` | `30/min` | Chat sends per user. |
| `THROTTLE_AI_PLANNER_WRITE` | `600/hour` | Other planner writes per user. |
| `THROTTLE_AI_PLANNER_ADMIN_WRITE` | `120/hour` | Admin/Super Admin writes. |

Token prices used for the admin cost estimate live in `settings.AI_PLANNER["PRICES_USD_PER_MTOK"]`; a cost is
shown **only** when the provider reported usage and a price for that model is known.

## Data model (`apps/event_planner/models.py`)

* `EventPlan` — owner, title, event type (to'y, nikoh, sunnat to'yi, tug'ilgan kun, yubiley, korporativ,
  boshqa), date or approximate date, region (`venues.Region`) + district, guest count, total budget (UZS),
  fixed/flexible, style, priorities, wishes, notes, status (draft/active/completed/archived),
  reserve %, source (manual / AI-confirmed), soft delete, idempotency key.
* `BudgetItem` — category, title, quantity, unit, per-guest flag, unit price (+ optional max for ranges),
  server-computed `total_price` / `total_price_max`, currency, source type (platform service / user input /
  AI estimate / manual), source kind + reference (hall or studio id), price status (verified / estimated /
  pending), `price_checked_at`, notes, `is_included_in_package`, venue `package_includes`, actual amount,
  active flag. DB constraints: positive quantity, non-negative prices, ordered ranges, UZS only, VERIFIED only
  for platform services, one platform service once per plan, no item in the computed contingency category.
* `AIConversation`, `AIMessage` (role, plain-text content, validated `structured_data`, status, error code,
  token usage, model, idempotency key, feedback), `AIUsageLog`, `AIConfiguration` (singleton, no secrets,
  optimistic `version`), `PromptVersion` (draft → tested → active → archived), `AIReport`.
* Audit: the existing `apps.audit.AuditLog` with new `AI_*` actions (before/after values, no secrets).

## Budget rules (`calculator.py`)

* line = unit price × quantity; per-guest line = unit price × guest count (re-priced on every guest-count change);
* ranges give separate min and max totals; lines inside the venue package and inactive lines count 0;
* reserve = reserve % × subtotal (5–10 % recommended, 0–30 % allowed), never a budget item;
* total = subtotal + reserve; remaining = budget − total; status `NO_ITEMS / NO_BUDGET / WITHIN / AT_RISK / OVER`;
* an overrun is reported with its amount, the three biggest lines and cut suggestions that are only offered;
* all values `Decimal`, rounded half-up to 0.01 per line, serialised as exact strings.

Platform prices: a hall's price is read from the database (hall price → venue price), marked VERIFIED with
the time it was read, and labelled as a starting price until the venue confirms. Studios have no price on the
platform, so their lines stay PENDING until the user enters one (then ESTIMATED). Clients can never mark a
price VERIFIED. AI category prices are always ESTIMATED.

## AI turn (`assistant.py`)

1. Gates: enabled, feature flag `chat`, maintenance, key configured → otherwise a stable 503 code.
2. Limits: per-user/day, platform/day, platform tokens/month → 429; DRF throttles on top.
3. Card numbers (Luhn), CVV and one-time codes are removed before anything is stored or sent.
4. Context: the system prompt (active `PromptVersion` or the built-in one) + fixed safety and output rules that
   cannot be edited; the last `history_limit` messages (each cut); this user's plan and server budget summary;
   real candidate services from the public catalog with ids, prices, ratings and availability. User text and
   catalog text are marked as data, not instructions.
5. Provider: `providers/anthropic_provider.py` — Messages API with `output_config.format` (JSON schema) and
   `effort`; timeout + SDK retries; typed SDK errors mapped to stable codes; refusals handled.
6. Validation (`schema.py`): every field re-checked; unknown ids dropped; platform prices never taken from the
   model; invalid JSON → a safe Uzbek fallback answer; a reply that leaks the prompt is replaced.
7. The server computes a budget preview of the proposal. Saving it is a separate, explicit user action
   (`confirm-plan`), idempotent, audited, and never creates a booking.

## API

USER (`IsClientUser`, own rows only — another user's id is 404; feature switch `USER.ai_planner`):

| Method | Path |
|---|---|
| GET | `/api/v1/ai-planner/status/`, `/usage/`, `/export/` · POST `/delete-data/` (`{"confirm": "DELETE"}`) |
| CRUD | `/api/v1/ai-planner/plans/` (+ `archive/`, `unarchive/`, `duplicate/`, `summary/`, `recommendations/`) |
| CRUD | `/api/v1/ai-planner/plans/{plan_id}/items/` |
| CRUD | `/api/v1/ai-planner/conversations/` (+ `archive/`, `unarchive/`, `messages/` GET/POST, `confirm-plan/`) |
| POST | `/api/v1/ai-planner/messages/{id}/feedback/`, `/report/` |
| GET | `/api/v1/ai-planner/services/search/`, `/services/compare/` |

ADMIN / SUPER ADMIN (`/api/v1/admin/ai-planner/…`):

| Endpoint | ADMIN needs | SUPER_ADMIN |
|---|---|---|
| `dashboard/`, `usage/` | `ai.view` | ✓ |
| `reports/` (list, retrieve, PATCH) | `ai.reports` | ✓ |
| `conversations/` (masked, every view audited) | `ai.conversations` | ✓ |
| `disable/` (off only, reason + `confirm`) | `ai.disable` | ✓ |
| `config/` GET/PATCH (`expected_version`, `confirm` for critical fields), `config/validate/` | — | ✓ |
| `prompts/` CRUD (draft only) + `test/`, `activate/` (also rollback) | — | ✓ |
| `audit/` | — | ✓ |

Full schemas: `docs/openapi.yaml`; access metadata: `backend/contracts/api_access_contract.json`.

## Error codes shown to users

`ai_disabled`, `ai_maintenance`, `ai_not_configured`, `ai_daily_limit`, `ai_global_limit`, `ai_token_budget`,
`provider_timeout`, `provider_rate_limited`, `provider_unavailable`, `provider_auth_failed`,
`provider_model_not_found`, `provider_rejected_request`, `included_in_package`, `duplicate_service`,
`nothing_to_confirm`, `confirmation_required`, `prompt_not_tested` — all in the standard
`{"error": {"code", "message", "details"}}` shape with Uzbek messages.

## Known limits

* No live call to Anthropic was made while building this (no key available); the adapter is covered by tests
  with a fake SDK client and the chat by a scripted provider. Run **Tekshirish** after setting the key.
* The platform has no catalog for artists, decor, catering or transport — those categories can only be the
  user's own numbers or clearly marked AI estimates, never named companies.
* Studios publish no price or region; their availability is the studio's own calendar, not a booking.
