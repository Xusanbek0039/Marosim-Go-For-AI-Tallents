# API documentation

The MarosimGo REST API is versioned under **`/api/v1/`** and serves every client: the four web
panels and future mobile apps. It has 239 operations.

## Full reference (generated from the code)

| Source | Use it for |
|---|---|
| Swagger UI: `/api/v1/docs/` | interactive reference (open with `DJANGO_DEBUG=true`, otherwise Super Admin only) |
| [`docs/openapi.yaml`](docs/openapi.yaml) | OpenAPI 3 schema, for client generation (CI fails if it drifts from the code) |
| [`docs/API_ENDPOINTS.md`](docs/API_ENDPOINTS.md) | every endpoint with roles, admin permission code and ownership rule (Uzbek) |
| `backend/contracts/api_access_contract.json` | machine-readable role × endpoint contract, verified by tests |

Regenerate after changing the API:

```bash
cd backend
python manage.py spectacular --validate --fail-on-warn --file ../docs/openapi.yaml
python manage.py export_api_endpoints
python manage.py api_contract --write    # only when an access change is intentional
```

## Authentication

**Web panels (cookies)**

1. `GET /api/v1/auth/csrf/` sets the `csrftoken` cookie.
2. `POST /api/v1/auth/login/` with `{"phone_number": "+998901234567", "password": "..."}` and header
   `X-CSRFToken`. Sets the httpOnly `mg_access` / `mg_refresh` cookies (host-only, so each panel
   subdomain has its own session) and returns `{"user": {...}}`.
3. Every state-changing request sends `X-CSRFToken`.
4. `POST /api/v1/auth/refresh/` rotates the tokens. `POST /api/v1/auth/logout/` returns 204.

**Mobile (Bearer)**: send `X-Client: mobile` to `login`/`refresh`. Tokens come back in the body;
call the API with `Authorization: Bearer <access>`.

`POST /api/v1/auth/register/` creates a `USER` account (phone + password + confirmation) and
returns 201. Web clients then log in; registration does not start a session.

## Conventions

- **Trailing slash** on every path (`/api/v1/venues/`).
- **Pagination** (list endpoints that paginate): `?page=` and `?page_size=` (max 100). Response:
  `{"count", "page", "page_size", "total_pages", "next", "previous", "results": [...]}`.
  Some lists return a plain array; see the schema.
- **Filtering / search / ordering**: `django-filter` query params, `?search=`, `?ordering=`, per
  endpoint.
- **IDs** are UUIDs.

## Errors

Every error has one shape:

```json
{"error": {"code": "permission_denied", "message": "Bu amal uchun ruxsatingiz yo'q.", "details": null}}
```

| Status | Typical `code` |
|---|---|
| 400 | `validation_error` (`details` = field → messages), `parse_error` |
| 401 | `not_authenticated`, `authentication_failed` |
| 403 | `permission_denied` |
| 404 | `not_found`. Objects the caller may not see answer 404, not 403 |
| 409 | `conflict` and domain codes (for example a booked hall session) |
| 429 | `throttled`, `account_locked` |
| 503 | storage codes, for example `storage_unavailable` when Google Drive is not connected |

Messages are in Uzbek; clients should branch on `code`.

## Main resource groups

| Prefix | Who | What |
|---|---|---|
| `auth/` | everyone | csrf, register, login, refresh, logout, me |
| `users/`, `admins/`, `admin/platform-policy/` | Super Admin / Admin | client and staff accounts, permissions, PINFL reveal |
| `studios/`, `studios/me/…` | staff / studio | studio management, portfolio, reels, schedule, chats, storage usage |
| `ceremonies/`, `ceremonies/{id}/media/` | studio / Super Admin | ceremonies, invitations, media uploads |
| `me/ceremonies/`, `me/invitations/` | user | own ceremonies, galleries, sharing with guests |
| `venues/`, `me/venue-bookings/` | public / user | venue catalogue, availability search, booking requests |
| `venue-owner/venues/` | venue owner | halls, sessions, bookings: confirm, reject, cancel |
| `public/studios/`, `…/reviews/`, `…/like/` | public / user | studio catalogue, portfolio reactions, reviews |
| `subscriptions/…`, `me/subscriptions/`, `admin/subscriptions/` | all | plans, own subscriptions, staff management |
| `support/tickets/`, `public/partner-applications/` | all | support tickets, partner applications |
| `virtual-tryon/…` | user / staff | garments, try-on sessions, favourites |
| `admin/storage/google/…` | Super Admin | Google Drive connect / status / test / disconnect |
| `monitoring/`, `devcenter/`, `dashboard/` | staff | metrics, API catalogue, dashboard |
| `health/live/`, `health/ready/` | probes | liveness / readiness |
