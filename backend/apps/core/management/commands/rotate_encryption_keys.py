"""Move every stored secret onto the current primary keys (key rotation / leaked-key response).

Two independent key sets are covered:

``pinfl`` — ``PINFL_ENCRYPTION_KEYS`` (Fernet) and ``PINFL_HASH_KEY`` (HMAC blind index)
    * ``accounts.User.pinfl_encrypted``                       re-encrypted with the first key
    * ``accounts.User.pinfl_hash``                            recomputed from the plaintext
    * ``ceremonies.CeremonyInvitation.recipient_identifier_*`` re-encrypted + index recomputed

``vault`` — ``GOOGLE_TOKEN_ENCRYPTION_KEY`` (Fernet)
    * ``storage.StorageCredential.refresh_token_encrypted``
    * ``storage.OAuthState.code_verifier_encrypted``
    * ``media.CeremonyMedia.upload_session_encrypted``       (non-empty only)

Procedure (see docs/SECURITY_INCIDENT_RESPONSE.md):

1. Put the NEW key first and keep the OLD key after it: ``PINFL_ENCRYPTION_KEYS=new,old``.
   If the hash key is rotated too, set ``PINFL_HASH_KEY=new`` (the old hash key is not needed:
   indexes are rebuilt from the decrypted plaintext). Stop the web workers first — until this
   command finishes, PINFL / invitation lookups would not match.
2. ``python manage.py rotate_encryption_keys``          — dry run: verifies every row decrypts.
3. ``python manage.py rotate_encryption_keys --apply``  — rewrites the rows in one transaction.
4. Remove the OLD key from the environment, start the workers.

Nothing is written unless *every* row of a scope decrypts with the configured keys, and only
counts are printed — never plaintext, ciphertext or keys. Running it twice is harmless.
"""

from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import pinfl as pinfl_utils
from apps.accounts.models import User
from apps.ceremonies.models import CeremonyInvitation, IdentifierType
from apps.ceremonies.ownership import phone_index
from apps.core import crypto
from apps.media.models import CeremonyMedia
from apps.storage import vault
from apps.storage.models import OAuthState, StorageCredential

BATCH = 500


@dataclass
class Plan:
    """Rows to rewrite per model, plus the number of rows that failed to decrypt."""

    updates: dict = field(default_factory=dict)  # model -> (fields, [instances])
    failures: dict = field(default_factory=dict)  # label -> count

    def add(self, model, fields, obj):
        self.updates.setdefault(model, (fields, []))[1].append(obj)

    def fail(self, label):
        self.failures[label] = self.failures.get(label, 0) + 1


def _pinfl_plan() -> Plan:
    plan = Plan()
    # _base_manager: soft-deleted accounts too — their ciphertext must survive removing the old key.
    users = User._base_manager.exclude(pinfl_encrypted="").only("pk", "pinfl_encrypted", "pinfl_hash")
    for user in users.iterator():
        try:
            value = crypto.decrypt(user.pinfl_encrypted)
        except ValueError:
            plan.fail("accounts.User.pinfl_encrypted")
            continue
        user.pinfl_encrypted = crypto.rotate(user.pinfl_encrypted)
        user.pinfl_hash = pinfl_utils.hash_of(value)
        plan.add(User, ["pinfl_encrypted", "pinfl_hash"], user)

    invitations = CeremonyInvitation.objects.only(
        "pk", "identifier_type", "recipient_identifier_encrypted", "recipient_identifier_hash"
    )
    for inv in invitations.iterator():
        try:
            value = crypto.decrypt(inv.recipient_identifier_encrypted)
        except ValueError:
            plan.fail("ceremonies.CeremonyInvitation.recipient_identifier_encrypted")
            continue
        index = phone_index(value) if inv.identifier_type == IdentifierType.PHONE else pinfl_utils.hash_of(value)
        inv.recipient_identifier_encrypted = crypto.rotate(inv.recipient_identifier_encrypted)
        inv.recipient_identifier_hash = index
        plan.add(CeremonyInvitation, ["recipient_identifier_encrypted", "recipient_identifier_hash"], inv)
    return plan


def _vault_plan() -> Plan:
    plan = Plan()
    targets = [
        (StorageCredential, "refresh_token_encrypted", StorageCredential.objects.all()),
        (OAuthState, "code_verifier_encrypted", OAuthState.objects.all()),
        (CeremonyMedia, "upload_session_encrypted", CeremonyMedia.objects.exclude(upload_session_encrypted="")),
    ]
    for model, name, queryset in targets:
        pk = model._meta.pk.attname
        for obj in queryset.only(pk, name).iterator():
            try:
                setattr(obj, name, vault.reseal(getattr(obj, name)))
            except (InvalidToken, vault.VaultNotConfigured):
                plan.fail(f"{model._meta.label}.{name}")
                continue
            plan.add(model, [name], obj)
    return plan


class Command(BaseCommand):
    help = "Re-encrypt stored secrets with the current primary keys and rebuild PINFL blind indexes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scope", choices=["pinfl", "vault", "all"], default="all", help="Which key set to rotate."
        )
        parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run).")

    def handle(self, *args, scope, apply, **options):
        scopes = ["pinfl", "vault"] if scope == "all" else [scope]
        if "vault" in scopes and not vault.is_configured():
            if scope == "vault":
                raise CommandError("GOOGLE_TOKEN_ENCRYPTION_KEY is not configured.")
            self.stdout.write("vault: GOOGLE_TOKEN_ENCRYPTION_KEY not configured — skipped.")
            scopes.remove("vault")

        for name in scopes:
            plan = _pinfl_plan() if name == "pinfl" else _vault_plan()
            for model, (_, objs) in plan.updates.items():
                self.stdout.write(f"{name}: {model._meta.label}: {len(objs)} row(s) to rewrite")
            if not plan.updates:
                self.stdout.write(f"{name}: nothing stored.")
            if plan.failures:
                details = ", ".join(f"{label}: {count}" for label, count in plan.failures.items())
                raise CommandError(
                    f"{name}: some rows cannot be decrypted with the configured keys ({details}). "
                    "Nothing was written. Add the old key after the new one and run again."
                )
            if apply:
                with transaction.atomic():
                    for model, (fields, objs) in plan.updates.items():
                        model._base_manager.bulk_update(objs, fields, batch_size=BATCH)
                self.stdout.write(self.style.SUCCESS(f"{name}: rotated."))

        if not apply:
            self.stdout.write("Dry run: nothing written. Re-run with --apply.")
