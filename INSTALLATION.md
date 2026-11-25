# Installation

Requirements: **Python 3.12**, **Node.js 20+** (CI uses 24), npm. Optional: PostgreSQL, Redis,
ffmpeg (video watermarks).

## 1. Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt    # requirements.txt for production only
cp ../.env.example .env
```

### Secrets

Generate every secret yourself and paste it into `backend/.env`. Never commit that file (it is
git-ignored).

```bash
python -c "import secrets;print(secrets.token_urlsafe(50))"                               # DJANGO_SECRET_KEY
python -c "import secrets;print(secrets.token_urlsafe(50))"                               # JWT_SIGNING_KEY (different!)
python -c "import secrets;print(secrets.token_urlsafe(50))"                               # PINFL_HASH_KEY
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # PINFL_ENCRYPTION_KEYS
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # GOOGLE_TOKEN_ENCRYPTION_KEY
```

With `DJANGO_DEBUG=false` the app **refuses to start** if `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`,
`PINFL_HASH_KEY` or `PINFL_ENCRYPTION_KEYS` is empty, still a `.env.example` placeholder, or invalid,
or if the JWT key equals the Django key. With `DJANGO_DEBUG=true` it only prints a warning.

For local HTTP development also set `DJANGO_DEBUG=true` (or `AUTH_COOKIE_SECURE=false`), otherwise
the browser drops the `Secure` auth cookies.

### Database

```bash
python manage.py migrate
python manage.py createsuperuser        # the only way to create the Super Admin; login = phone number
python manage.py seed_demo              # optional demo data, only when DJANGO_DEBUG=true
python manage.py runserver 127.0.0.1:8000
```

- **SQLite** (default, `backend/db.sqlite3`) runs in WAL mode with IMMEDIATE transactions.
- **PostgreSQL:** `DATABASE_URL=postgres://user:password@localhost:5432/marosimgo`, then `migrate`.
  No code changes.
- **Several worker processes:** login lockout and throttling need a shared cache. In production the
  default is a database cache table (created by `migrate`); with Redis set
  `CACHE_URL=redis://localhost:6379/0`.
- Accounts created before phone login: `python manage.py set_phone --list-missing`.

API docs (Swagger): <http://127.0.0.1:8000/api/v1/docs/>. Open when `DJANGO_DEBUG=true`, otherwise
Super Admin only.

## 2. Frontends

Every app proxies `/api/v1/*` and `/media/*` to Django, so the browser only ever talks to its own
origin.

```bash
cd frontend            # or frontend-studio / frontend-user / frontend-toyxona
npm ci
echo BACKEND_URL=http://127.0.0.1:8000 > .env.local
npm run dev
```

| App | `npm run dev` port |
|---|---|
| `frontend` (Super Admin / Admin) | 3000 |
| `frontend-studio` | 3001 |
| `frontend-user` | 3002 |
| `frontend-toyxona` | 3003 |

All apps use the same auth cookie names (`mg_access`, `mg_refresh`). Browsers do not separate
cookies by port, so on `localhost` signing in to one cabinet replaces the session of another. To
use two roles at once locally, use separate browser profiles (or `localhost` for one and
`127.0.0.1` for the other). In production every panel has its own subdomain, so sessions are separate.

> **`frontend/` reads `BACKEND_URL` at build time.** The admin panel proxies through Next.js
> `rewrites`, which are fixed during `next build`. If you run `next start`, build with the same
> `BACKEND_URL`. The other three apps proxy through route handlers and read it at runtime.

`frontend-user` copies the MediaPipe runtime into `public/mediapipe/wasm/` before `dev`/`build`
(`scripts/prepare-mediapipe.mjs`). The folder is generated and git-ignored.

## 3. Google Drive (optional, needed for ceremony media)

Media files are stored in the platform owner's Google Drive. Without it the API keeps working, and
media upload answers `503 storage_unavailable`.

1. Follow [docs/GOOGLE_DRIVE_SETUP.md](docs/GOOGLE_DRIVE_SETUP.md) to create a *Web application*
   OAuth client.
2. Put the client JSON at `backend/credentials/google_oauth_client.json` (git-ignored), or set
   `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` and `GOOGLE_OAUTH_REDIRECT_URI`.
3. Set `GOOGLE_TOKEN_ENCRYPTION_KEY` and `PANEL_URL`.
4. `python manage.py google_oauth_check`, then Super Admin panel → Storage → Connect.
5. Live test: `python manage.py storage_selftest`.

## 4. Production

See [docs/DEPLOY.md](docs/DEPLOY.md) (cPanel/Passenger, one app for all domains) and
`backend/.env.production.example`. Build the static panels before deploying:

```bash
cd frontend && npm run build:panel && npm run build:panel:admin
cd ../frontend-studio && npm run build:panel     # same for frontend-user and frontend-toyxona
```

Background jobs (cron or a worker):

```bash
python manage.py process_watermarks --loop          # if MEDIA_WATERMARK_INLINE=false (needs ffmpeg)
python manage.py expire_media_uploads
python manage.py expire_ceremony_invitations
python manage.py prune_request_logs
```

Secret rotation: [docs/SECURITY_INCIDENT_RESPONSE.md](docs/SECURITY_INCIDENT_RESPONSE.md).

## 5. Tests

```bash
# backend (settings: config.settings_test, in-memory SQLite, throwaway secrets)
cd backend
pytest                                    # 2882 tests
ruff check . && ruff format --check .
python manage.py makemigrations --check --dry-run
python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml
diff -q /tmp/openapi.yaml ../docs/openapi.yaml   # docs/openapi.yaml must match the code
python manage.py api_contract             # role/permission contract is up to date

# frontends (each app)
npx tsc --noEmit && npm run build && npm run lint
cd frontend-user && npm test              # 17 tests

# repository
bash tools/check-no-secrets.sh            # no env files, databases or keys are tracked
node tools/check-static-panels.mjs        # exported panels reference existing assets
node tools/test-api-client.mjs            # CSRF / network-recovery of all four API clients (needs frontend/node_modules)
```

### End-to-end tests

These run against **disposable** servers. `tools/qa_backend.py` uses `.qa/ui.sqlite3` and never
touches `backend/db.sqlite3` or Google Drive.

```bash
python tools/qa_backend.py setup          # seed one account per role (run with the backend venv)
python tools/qa_backend.py                # Django on 127.0.0.1:8100
# in four more terminals (build each app first with the same BACKEND_URL):
BACKEND_URL=http://127.0.0.1:8100 npx next start -H 127.0.0.1 -p 3100   # in frontend/
BACKEND_URL=http://127.0.0.1:8100 npx next start -H 127.0.0.1 -p 3101   # in frontend-user/
BACKEND_URL=http://127.0.0.1:8100 npx next start -H 127.0.0.1 -p 3102   # in frontend-studio/
BACKEND_URL=http://127.0.0.1:8100 npx next start -H 127.0.0.1 -p 3103   # in frontend-toyxona/

node tools/smoke-panels.mjs               # login, cookies, CSRF and per-role reads through each proxy
node tools/smoke-workflows.mjs            # register/logout, role limits, ceremony, booking → confirm
node tools/smoke-static-rsc.mjs           # static panels served by Django
```
