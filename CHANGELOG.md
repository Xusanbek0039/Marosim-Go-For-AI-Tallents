# Changelog

All notable changes in this repository. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — hackathon submission

### Baseline (inherited, not new work)

- Imported the complete original project from
  [Xusanbek0039/Marosim-Go@c12be31d](https://github.com/Xusanbek0039/Marosim-Go/commit/c12be31d713ff363e472ac4630c0d684f40bf386)
  (MIT). The file tree is byte-identical to upstream (git tree `b303ef23`). Upstream git history
  was not carried over because it contains committed credentials and databases.

### Added

- **Secret guard:** with `DJANGO_DEBUG=false` the backend refuses to start if
  `DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY`, `PINFL_HASH_KEY` or `PINFL_ENCRYPTION_KEYS` is empty,
  a public `.env.example` placeholder or an invalid Fernet key, or if the JWT key equals the
  Django key (`backend/config/secret_guard.py`, 15 tests).
- **`manage.py rotate_encryption_keys`:** re-encrypts PINFL, ceremony-invitation identifiers,
  the Google Drive refresh token, PKCE verifiers and upload sessions with the new primary keys,
  and rebuilds the HMAC blind indexes. Dry run by default, verify-before-write, one transaction
  per key set (6 tests).
- **Runbook:** `docs/SECURITY_INCIDENT_RESPONSE.md` (Google OAuth secret rotation, JWT/Django
  key rotation, data re-keying, backups, git-history cleanup plan).
- **CI:** `frontend` workflow (all four apps: `tsc`, build, lint, unit tests, API-client
  contract); `repo-hygiene` workflow (`tools/check-no-secrets.sh`, static-panel integrity);
  backend workflow now also checks formatting, missing migrations and OpenAPI drift.
- **End-to-end test:** `tools/smoke-workflows.mjs` (register/login/logout, role restrictions,
  ceremony creation, booking request → venue-owner confirmation, Drive-status reporting) through
  the real Next.js proxies.
- English `README.md`, `INSTALLATION.md`, `ARCHITECTURE.md`, `API_DOCUMENTATION.md`, this
  changelog. The original Uzbek README moved to `docs/README.uz.md`.

### Fixed

- Backend lint gate: `ruff check` failed with 15 errors and `ruff format --check` with 6 files,
  so the upstream `backend` CI workflow could not pass. Mechanical fixes only.
- `frontend-user`: `npm run lint` failed (267 problems) after every `dev`/`build` because the
  generated MediaPipe wasm runtime was not ignored by ESLint.
- `docs/openapi.yaml` and `docs/API_ENDPOINTS.md` were stale (196 of 239 operations); regenerated
  from the code.
- Documentation no longer claims per-app cookie prefixes. All apps share the `mg_*` cookie names,
  and sessions are separated by subdomain.

### Security notes

- `npm audit` reports 4 moderate advisories in `frontend` (`minimatch` / `ts-morph`). They are
  pulled in by the `shadcn` CLI's code generator, which never runs in the shipped static panels.
  npm's suggested fix is a downgrade to `shadcn@1.0.0`, which would break the build. Accepted
  until upstream `shadcn` updates. Other apps: 0 advisories. Python: `pip-audit` reports none.
