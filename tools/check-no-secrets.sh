#!/usr/bin/env bash
# Fails when files that must never be committed are tracked by git, or when tracked text contains
# private-key / Google OAuth client-secret patterns. Prints file names only, never matching content.
# Run from the repository root:  bash tools/check-no-secrets.sh
set -euo pipefail

status=0

# 1) Forbidden file names (templates *.example are allowed).
forbidden=$(git ls-files | grep -E \
  -e '(^|/)\.env$' \
  -e '(^|/)\.env\.[^/]*$' \
  -e '(^|/)[^/]*\.env$' \
  -e '\.(sqlite3|sqlite3-journal|db)$' \
  -e '(^|/)backend/credentials/' \
  -e '(^|/)client_secret[^/]*\.json$' \
  -e 'oauth_client[^/]*\.json$' \
  -e '\.(pem|key|p12|pfx)$' \
  | grep -vE '\.example$' | grep -v '^backend/credentials/README\.md$' || true)
if [[ -n "$forbidden" ]]; then
  echo "Tracked files that must not be in git:" >&2
  echo "$forbidden" | sed 's/^/  /' >&2
  status=1
fi

# 2) Secret patterns inside tracked text files (binary files skipped by -I).
patterns='-----BEGIN [A-Z ]*PRIVATE KEY-----|GOCSPX-[A-Za-z0-9_-]{10,}|"refresh_token" *: *"1//'
# git grep exits 0 = matches, 1 = no match, anything else = error (must fail the check, not pass it).
grep_status=0
hits=$(git grep -I -l -E -e "$patterns" -- . ':!tools/check-no-secrets.sh') || grep_status=$?
if [[ $grep_status -gt 1 ]]; then
  echo "git grep failed (exit $grep_status); cannot verify tracked content." >&2
  status=1
elif [[ -n "$hits" ]]; then
  echo "Tracked files containing secret-like patterns (content not shown):" >&2
  echo "$hits" | sed 's/^/  /' >&2
  status=1
fi

if [[ $status -eq 0 ]]; then
  echo "No secret files or secret patterns tracked."
fi
exit $status
