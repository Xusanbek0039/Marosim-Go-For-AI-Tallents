# Secret rotation and incident-response runbook

Use this when a secret may have been exposed: committed to git, pasted into a chat or issue, left
in a backup, or held by someone who should no longer have it. **Assume exposure means compromise**:
removing a file from git later does not remove it from history, forks, clones or caches.

The order matters. Cut off live access first, then re-key stored data, and clean history last.

> Never paste secret values into tickets, chat, commit messages or this file. Refer to variables
> by name only.

---

## 0. Inventory: what each secret protects

| Variable | Protects | If it leaks, an attacker can… | Rotation impact |
|---|---|---|---|
| `JWT_SIGNING_KEY` | API access/refresh tokens (HS256) | **mint a valid token for any account, Super Admin included** | everyone is logged out |
| `DJANGO_SECRET_KEY` | Django signing (CSRF, `django.core.signing`, partner-application challenges) | forge signed values | open forms / challenges must be retried |
| `PINFL_ENCRYPTION_KEYS` | Fernet encryption of PINFL (JSHSHIR) and ceremony-invitation phone/PINFL | decrypt that personal data **from any copy of the database** | none, if rotated with the command below |
| `PINFL_HASH_KEY` | HMAC blind indexes for PINFL / invitation lookup | confirm guesses of PINFL / phone numbers against a DB copy | indexes rebuilt by the command below |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Fernet encryption of the Drive refresh token, PKCE verifiers, upload sessions | decrypt the **Drive refresh token** from a DB copy | none, if rotated with the command below |
| `GOOGLE_OAUTH_CLIENT_SECRET` (+ client JSON) | the OAuth client | combined with a refresh token: **use the Drive account** | Drive must be reconnected |
| Google **refresh token** (in the DB) | the connected Drive account | read/write files the app created | revoke + reconnect |
| `DATABASE_URL` / Postgres passwords | the database | read/modify everything | update the app's env |
| The database file / dump itself | all of the above that is stored | offline password cracking (Argon2), decryption with leaked keys | see §6 |

If a **database copy and its encryption keys** leaked together, treat the protected data (PINFL,
invitation identifiers, Drive token) as disclosed. Re-keying protects the future only.

---

## 1. Contain (first hour)

1. **Google Drive:** in the Super Admin panel → Storage → *Disconnect*. This revokes the refresh
   token at Google (best effort). Then confirm in the Google account used for Drive:
   <https://myaccount.google.com/permissions> → remove the MarosimGo app if it is still listed.
2. **Google OAuth client secret** (Google Cloud Console → APIs & Services → Credentials → the
   *Web application* client):
   1. **Add secret** to create a second secret (the client then has two).
   2. Put the new secret in production (`GOOGLE_OAUTH_CLIENT_SECRET`, or a newly downloaded
      `backend/credentials/google_oauth_client.json`) and restart the app.
   3. `python manage.py google_oauth_check`: it must report the configuration as valid.
   4. **Disable**, then **delete** the old secret.
   5. Reconnect Drive (Storage → Connect) and run *Test connection*.
   6. Review the Drive account's activity (drive.google.com → *Activity*) for files you did not create.
3. **JWT_SIGNING_KEY:** generate a new value (§3), deploy, restart. All existing tokens become
   invalid immediately; forged tokens stop working.

## 2. Re-key stored data (PINFL and Drive vault)

Fernet keys are lists: the **first** key encrypts, **every** key decrypts. That is what lets you
rotate without losing data. The `rotate_encryption_keys` command moves all stored rows onto the
new primary key and rebuilds the HMAC indexes.

```bash
cd backend
# generate keys (run on the server; never paste them anywhere else)
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
python -c "import secrets;print(secrets.token_urlsafe(50))"
```

Generate the new values on the server without displaying them:
`python tools/generate_secrets.py backend/.env.new-secrets` (mode 600, never overwrites, prints only
the variable names). Copy the lines from that file, then delete it.

1. **Back up the database first** (§6). Stop the web workers (cPanel: *Stop App*), because PINFL
   and invitation lookups do not match while indexes are being rebuilt.
2. Edit `backend/.env`:
   - `PINFL_ENCRYPTION_KEYS=<new>,<old>` (new first, old kept for now)
   - `PINFL_HASH_KEY=<new>` (the old hash key is not needed; indexes are rebuilt from plaintext)
   - `GOOGLE_TOKEN_ENCRYPTION_KEY=<new>,<old>`
3. Dry run. It verifies that every row decrypts and writes nothing:
   ```bash
   python manage.py rotate_encryption_keys
   ```
   If it reports rows that cannot be decrypted, **stop**: a key is missing from the list.
4. Apply. Each key set is rewritten in a single transaction:
   ```bash
   python manage.py rotate_encryption_keys --apply
   ```
5. Remove the old keys from `.env` (`PINFL_ENCRYPTION_KEYS=<new>`, `GOOGLE_TOKEN_ENCRYPTION_KEY=<new>`)
   and run the dry run once more. It must succeed with only the new keys.

   While a key from the known-compromised list (`config/secret_guard.py`, SHA-256 fingerprints only)
   is still listed **second**, the app starts with a warning, so the rotation can run. Listed
   **first**, it refuses to start in production.
6. Start the app. Spot-check: search a user by PINFL in the admin panel, and accept a pending
   ceremony invitation.

## 3. Rotate Django and JWT keys

```bash
python -c "import secrets;print(secrets.token_urlsafe(50))"   # once for each key
```

- `DJANGO_SECRET_KEY` and `JWT_SIGNING_KEY` must be **different** values. Production refuses to
  start if they (or `PINFL_HASH_KEY`) are equal, empty, shorter than 32 characters, an
  `.env.example` placeholder, or a known-compromised value (`config/secret_guard.py`).
- Do **not** put the leaked key into `SECRET_KEY_FALLBACKS`: a fallback keeps accepting
  signatures made with it.
- Effect: users sign in again; open CSRF tokens and partner-application challenges are
  re-requested automatically.

## 4. Database credentials

Change the database user's password (`ALTER ROLE … PASSWORD …` for PostgreSQL), update
`DATABASE_URL`, and restart. If the same password was reused anywhere else, change it there too.

## 5. Users and personal data

- Passwords are stored as Argon2 hashes. If a database copy leaked, ask affected users to change
  their passwords, and force it for staff/admin accounts first.
- If PINFL (personal identification numbers) or phone numbers were disclosed, check your
  obligations under the applicable data-protection law (Uzbekistan: Law No. ZRU-547 "On personal
  data") for notifying users and the regulator.

## 6. Backups and file access (SQLite on cPanel)

- Backup: `sqlite3 db.sqlite3 ".backup 'db-$(date +%F).sqlite3'"` (consistent even while running),
  or cPanel → *Backup*. Restore-test the copy on another machine with `python manage.py check` and
  `showmigrations`.
- Store backups **outside** the web root and outside the git checkout; encrypt them at rest.
- Permissions: `chmod 600 backend/.env backend/db.sqlite3*` and `chmod 700 backend/credentials`.
- Confirm the database is not downloadable over HTTP. Django only serves `MEDIA_ROOT` and the panel
  directories (with `safe_join`), but check the web server config too.
- Delete old backups that were made with retired keys once they are no longer needed. They remain
  decryptable with the leaked keys.

## 7. Git history

Removing a file in a new commit does **not** remove it from history. A rewrite changes public
commit hashes, so it needs an explicit owner decision and a coordinated force push. Finish §1–§5
first: cleaning history does not un-leak anything, rotation does.

> **Warning, verified the hard way.** `git filter-repo` *prunes* commits that become empty, and
> around merge commits that can rebuild later trees from the wrong parent. A dry run of the
> upstream repository with default options left **18 of 1,240 files** in the latest commit. Always
> pass `--prune-empty never --prune-degenerate never`, use literal paths, and compare tree hashes
> before pushing anything.

### 7.1 Upstream repository (`Xusanbek0039/Marosim-Go`)

Leaked paths (all branches): `backend/.env`, `backend/.env.bak-lan`, `backend/.env.bak-postgres`,
**`backend/env`** (no leading dot, holds the real keys), `backend/db.sqlite3`, and `.DS_Store` files.
The branches `feature/virtual-tryon` and `import-landing-page` still contain `backend/db.sqlite3`
**in their latest commit**, so it is browsable on GitHub until those branches are cleaned or deleted.

```bash
pip install git-filter-repo
git clone --mirror https://github.com/Xusanbek0039/Marosim-Go.git backup.git   # keep this safe, offline
git clone --mirror https://github.com/Xusanbek0039/Marosim-Go.git clean.git && cd clean.git
git rev-parse main^{tree} > ../tree-before.txt
# paths.txt: one literal path per line (the five above + every .DS_Store path from
#   git log --all --format= --name-only --diff-filter=A | grep -E '(^|/)\.DS_Store$' | sort -u)
git filter-repo --force --invert-paths --paths-from-file ../paths.txt \
  --prune-empty never --prune-degenerate never
```

Verify before pushing (a dry run of exactly this produced all four results):

1. `git rev-parse main^{tree}` equals `tree-before.txt` (the latest code is byte-identical).
2. `git ls-tree -r <branch>` for the other branches differs from the original only by the removed paths.
3. `git rev-list --all --objects | awk 'NF>1{print $2}' | grep -cxF -f ../paths.txt` prints `0`.
4. `git rev-list --all | wc -l` is unchanged (60 commits).

Then `git push --force --mirror`, ask collaborators to re-clone, and ask GitHub Support to purge
cached views and unreachable objects. Forks, clones and pull-request refs keep the old data;
that is why rotation (§1–§5) comes first.

### 7.2 This repository: `node_modules` committed in `c04df84d`

Commit `c04df84d` added 118,505 generated files (no secrets). They are untracked now, but stay in
history: about 116 MB. Optional cleanup (same safety rules):

```bash
git filter-repo --force --invert-paths --path-regex '(^|/)node_modules/' \
  --path-regex '(^|/)__pycache__/' --path frontend-user/public/mediapipe/wasm \
  --prune-empty never --prune-degenerate never
```

Dry run result: `main` tree byte-identical, all commits kept, no vendor paths left, repository
116 MB → 8.1 MB. Cost: `c04df84d` and every later commit get new hashes, so it needs a force
push and every clone must be re-cloned.

## 8. Prevention (already in this repository)

- `.gitignore` covers `.env*`, `*.sqlite3`, `backend/credentials/*`, client-secret JSON, keys.
- CI `repo-hygiene` runs `tools/check-no-secrets.sh` on every push and PR. It catches env files
  with or without the leading dot, databases, key files, and Fernet-shaped secret assignments in
  any file.
- Production refuses empty, short, placeholder or known-compromised secrets
  (`config/secret_guard.py`). The Google OAuth client loader also refuses a compromised client
  secret, whether it comes from env or from the JSON file.
- `tools/generate_secrets.py` creates new secrets without printing them.
- `rotate_encryption_keys` makes routine key rotation a ten-minute job. Consider doing it yearly.
