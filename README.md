# MarosimGo — for AI Talents

MarosimGo is a digital platform for weddings and family ceremonies in Uzbekistan. Photo/video
studios publish a ceremony's photos and videos to a private gallery that only the couple and their
invited guests can open. Couples find and book wedding venues (*to'yxona*). Platform staff manage
everything from an admin panel.

This repository is the hackathon submission. It is built on the existing open-source
[Marosim-Go](https://github.com/Xusanbek0039/Marosim-Go) project (MIT). See
[What is inherited and what is new](#what-is-inherited-and-what-is-new) for exactly which parts were
done here.

> Original project documentation (Uzbek): [docs/README.uz.md](docs/README.uz.md)

## Applications

| App | Who uses it | Dev port | Production host |
|---|---|---|---|
| `backend/` — Django REST API | every client (web panels, future mobile apps) | 8000 | `api.marosimgo.uz` |
| `frontend/` — Super Admin & Admin panel | platform staff | 3000 | `superadmin.` / `admin.marosimgo.uz` |
| `frontend-studio/` — Studio cabinet | studios (OWNER / MANAGER / UPLOADER) | 3001 | `studio.marosimgo.uz` |
| `frontend-user/` — User cabinet | couples and guests (galleries, venue booking, virtual try-on) | 3002 | `userlogin.marosimgo.uz` |
| `frontend-toyxona/` — Venue cabinet | wedding venues (OWNER / MANAGER / SCHEDULER / VIEWER) | 3003 | `toyxona.marosimgo.uz` |

In production the Next.js apps are **static exports served by Django itself** (`backend/panel*/`,
`config/panel.py`). One cPanel/Passenger deployment covers the API and every panel, and each panel
calls `/api/v1/` on its own origin, so the httpOnly auth cookies stay first-party.

## Technology

| Layer | Stack |
|---|---|
| Backend | Python 3.12, Django 5.2, Django REST Framework, SimpleJWT, drf-spectacular, django-filter |
| Database | SQLite (WAL) by default; PostgreSQL through `DATABASE_URL` without code changes |
| Frontends | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query, React Hook Form + Zod, Motion |
| Storage | Google Drive (OAuth 2.0, `drive.file` scope, PKCE); browser → Drive resumable uploads |
| Media | Pillow image re-encoding; ffmpeg video watermarking (optional worker) |
| Virtual try-on | MediaPipe pose tracking in the browser (user cabinet) |

## Quick start

```bash
# backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example .env        # then generate real secrets, see INSTALLATION.md
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000

# any frontend (example: the admin panel)
cd frontend
npm ci
echo BACKEND_URL=http://127.0.0.1:8000 > .env.local
npm run dev                    # http://localhost:3000
```

Full instructions, every environment variable and the PostgreSQL/Google Drive setup are in
**[INSTALLATION.md](INSTALLATION.md)**.

## Documentation

| Document | Contents |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | setup, environment, database, running every app, tests |
| [ARCHITECTURE.md](ARCHITECTURE.md) | system overview, modules, auth model, data flow |
| [API_DOCUMENTATION.md](API_DOCUMENTATION.md) | API conventions, auth, errors, where the full reference lives |
| [CHANGELOG.md](CHANGELOG.md) | what changed in this repository |
| [docs/SECURITY_INCIDENT_RESPONSE.md](docs/SECURITY_INCIDENT_RESPONSE.md) | secret rotation and incident runbook |
| [docs/](docs/) | detailed design documents from the original project (Uzbek) |

## Testing

```bash
cd backend && pytest                                   # 2897 tests
cd backend && ruff check . && ruff format --check .
cd frontend-user && npm test                           # 17 tests
cd <any frontend> && npx tsc --noEmit && npm run lint && npm run build
```

Live end-to-end checks through the real Next.js proxies are described in
[INSTALLATION.md → End-to-end tests](INSTALLATION.md#end-to-end-tests). CI runs all of the above
(`.github/workflows/`).

## What is inherited and what is new

**Inherited, unchanged in behaviour.** Everything in the first commit
(`chore: import Marosim-Go baseline…`) is the original project at upstream commit
[`c12be31d`](https://github.com/Xusanbek0039/Marosim-Go/commit/c12be31d713ff363e472ac4630c0d684f40bf386).
The file tree is byte-identical (git tree `b303ef23`). That covers the entire product: the
Django API, all four frontends, the RBAC and permission catalog, ceremonies/invitations/ownership,
Google Drive storage, media upload and watermarking, venues and booking, studios and portfolios,
reviews, subscriptions, support tickets, virtual try-on, monitoring, the 2861 backend tests, and
the original docs.

**New in this repository** (one commit each, see [CHANGELOG.md](CHANGELOG.md)):

| Area | Change |
|---|---|
| Security | Production refuses to start with empty or `.env.example`-placeholder secrets (`config/secret_guard.py`, 15 tests) |
| Security | `manage.py rotate_encryption_keys`: re-encrypts PINFL, invitation identifiers and Drive tokens with new keys and rebuilds blind indexes (6 tests) |
| Security | Secret rotation and incident-response runbook |
| CI | Frontend workflow (4 apps: type check, build, lint, tests), repo-hygiene workflow (tracked-secret scanner), stricter backend checks (format, migrations, OpenAPI drift) |
| Fix | Backend lint gate was failing (upstream CI red): 15 ruff errors, 6 unformatted files |
| Fix | `frontend-user` lint failed after every build (generated MediaPipe wasm was not ignored) |
| Docs | OpenAPI schema and endpoint list regenerated: 196 → 239 operations (43 were undocumented) |
| Tests | End-to-end write-workflow smoke through the real Next.js proxies (`tools/smoke-workflows.mjs`) |
| Docs | This README, INSTALLATION, ARCHITECTURE, API_DOCUMENTATION, CHANGELOG (English) |
| Security | Stricter guard: minimum length, Google keys, known-compromised fingerprints; `tools/generate_secrets.py` |
| Performance | N+1 queries removed from 4 list endpoints, with query-count regression tests |
| Licensing | `THIRD_PARTY_NOTICES.md`, Plus Jakarta Sans OFL text |

## License

MIT. Original work © 2026 Husanbek Suyunov, see [LICENSE](LICENSE). Changes in this repository are
released under the same license.
