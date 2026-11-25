# Architecture

An English overview. The original, more detailed design documents (Uzbek) are linked at the end.

## System

```
 Browser ── superadmin./admin. ─┐
 Browser ── studio.            ─┤   same origin: static panel + /api/v1/
 Browser ── userlogin.         ─┼──►  Django (one WSGI app, Passenger)  ──► SQLite / PostgreSQL
 Browser ── toyxona.           ─┤        │  config/panel.py picks the panel by host
 Mobile  ── api.  (Bearer JWT) ─┘        │
                                         ├──► Google Drive API (OAuth, drive.file)
 Studio browser ──── resumable upload ───┘    (bytes go browser → Drive directly)
```

- **All business logic and authorization live in Django.** The Next.js apps are UI only; in
  production they are static exports in `backend/panel*/` served by `config/panel.py`. In
  development each Next.js server proxies `/api/v1` and `/media` to Django.
- **One API for every client:** `/api/v1/` (`config/api_v1.py`). The web panels authenticate with
  httpOnly cookies + CSRF; mobile clients send `X-Client: mobile` and use `Authorization: Bearer`.

## Backend modules (`backend/apps/`)

| App | Responsibility |
|---|---|
| `core` | encryption helpers (Fernet + HMAC blind index), error format, pagination, upload validation, security headers, `rotate_encryption_keys` |
| `accounts` | user model (phone login, E.164), roles, admin permission catalog, JWT cookie auth, lockout, PINFL handling, platform policy |
| `audit` | append-only audit log of every create/update/deactivate/delete/login/PINFL reveal |
| `studios` | studios, memberships (OWNER / MANAGER / UPLOADER), portfolio (photos, reels), reactions, comments, studio ↔ customer chat, schedule |
| `ceremonies` | ceremonies, invitations by phone or PINFL (encrypted + blind index), ownership with multi-owner approval, viewer access, folders |
| `media` | ceremony photos/videos: upload sessions to Drive, viewing, watermarking (ffmpeg), deletion requests |
| `storage` | Google Drive OAuth connection, encrypted token vault, folder layout |
| `venues` | venues, halls, sessions, availability search, booking requests and owner confirmation |
| `reviews` | ratings, reviews and likes for venues and studios |
| `subscriptions` | plans, subscriptions, business verification badges |
| `support` | support tickets, partner applications (with proof-of-work anti-bot challenge) |
| `virtual_tryon` | garments, AR layers, try-on sessions, favourites |
| `monitoring` | request metrics (no bodies/headers/tokens), health probes, API catalog and access contract |
| `dashboard`, `devcenter` | Super Admin dashboard and developer centre |

## Roles and access

`SUPER_ADMIN`, `ADMIN` (granular permissions granted by the Super Admin), `STUDIO`, `VENUE_OWNER`,
`USER`. Every check happens server-side in DRF permission classes. The role × endpoint matrix is
generated into `backend/contracts/api_access_contract.json` and verified by
`tests/test_api_access_contract.py` with real requests per role.

## Authentication

- Login: phone number + password (Argon2). Uniform error for wrong phone/password/inactive account.
- JWT: access 10 min, refresh 7 days, rotated on every use. A reused refresh token is treated as
  theft and revokes all of that user's sessions.
- Web: tokens only in httpOnly cookies (refresh cookie limited to `/api/v1/auth/`, `SameSite=Strict`),
  CSRF double-submit for every state-changing cookie request; nothing in localStorage.
- Brute force: IP throttling plus a per-phone lockout after repeated failures.

## Sensitive data

- **PINFL** (national ID): Fernet-encrypted, unique via HMAC blind index, shown masked
  (`**********1234`). The full value comes from a dedicated, permissioned, audited and throttled endpoint.
- **Invitation identifiers** (phone/PINFL): stored the same way; matching uses the blind index only.
- **Google refresh token**: encrypted with a separate key set (`GOOGLE_TOKEN_ENCRYPTION_KEY`).
- Keys are lists (first encrypts, all decrypt). `manage.py rotate_encryption_keys` re-keys stored rows.
- Production refuses to start with empty or placeholder secrets (`config/secret_guard.py`).

## Media flow

1. A studio member asks the API for an upload session (`POST /ceremonies/{id}/media/uploads/`).
2. Django opens a Google Drive resumable session (encrypted at rest) and returns it.
3. The browser uploads the bytes **directly to Drive**. Django never proxies large files.
4. The client completes the upload; Django verifies size/checksum with Drive.
5. Videos get a watermarked preview copy (ffmpeg, inline thread or `process_watermarks` worker).
6. Couples and invited guests stream media through permission-checked endpoints. Nothing on Drive
   is public.

## Original design documents (Uzbek)

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/CEREMONY_OWNERSHIP.md](docs/CEREMONY_OWNERSHIP.md) ·
[docs/STORAGE_ARCHITECTURE.md](docs/STORAGE_ARCHITECTURE.md) · [docs/VENUE_AVAILABILITY.md](docs/VENUE_AVAILABILITY.md) ·
[docs/DEPLOY.md](docs/DEPLOY.md) · [docs/ROADMAP.md](docs/ROADMAP.md) · [docs/PROGRESS.md](docs/PROGRESS.md)
