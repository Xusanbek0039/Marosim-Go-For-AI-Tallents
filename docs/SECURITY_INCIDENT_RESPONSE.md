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
6. Start the app. Spot-check: search a user by PINFL in the admin panel, and accept a pending
   ceremony invitation.

## 3. Rotate Django and JWT keys

```bash
python -c "import secrets;print(secrets.token_urlsafe(50))"   # once for each key
```

- `DJANGO_SECRET_KEY` and `JWT_SIGNING_KEY` must be **different** values. Since this branch,
  production refuses to start if they are equal, empty, or still the `.env.example` placeholders
  (`config/secret_guard.py`).
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

Removing a file in a new commit does **not** remove it from history. The cleanup below changes
public history, so it needs an explicit owner decision and a coordinated push.

1. Finish §1–§5 first. Cleaning history does not un-leak anything; rotation does.
2. Make a full mirror backup: `git clone --mirror <repo> repo-backup.git`.
3. Rewrite with [git-filter-repo](https://github.com/newren/git-filter-repo) on a fresh mirror clone:
   ```bash
   git clone --mirror <repo> clean.git && cd clean.git
   git filter-repo --invert-paths \
     --path backend/.env --path backend/.env.bak-lan --path backend/.env.bak-postgres \
     --path backend/db.sqlite3 --path-glob '*.DS_Store'
   ```
4. Verify: `git log --all -- backend/.env backend/db.sqlite3` prints nothing, and
   `git rev-list --all --objects | grep -E 'db.sqlite3|\.env$'` prints nothing.
5. Force-push all branches and tags (`git push --force --mirror`). Then ask every collaborator to
   re-clone, because old clones still hold the data.
6. GitHub keeps unreachable commits and cached views for a while. Ask GitHub Support to purge
   cached views and to garbage-collect. Forks are separate copies and are not cleaned.

## 8. Prevention (already in this repository)

- `.gitignore` covers `.env*`, `*.sqlite3`, `backend/credentials/*`, client-secret JSON, keys.
- CI `repo-hygiene` runs `tools/check-no-secrets.sh` on every push and PR.
- Production refuses placeholder or empty secrets (`config/secret_guard.py`).
- `rotate_encryption_keys` makes routine key rotation a ten-minute job. Consider doing it yearly.
