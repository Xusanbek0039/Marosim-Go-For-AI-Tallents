"""`manage.py rotate_encryption_keys`: leaked-key response without losing encrypted data."""

from io import StringIO

import pytest
from cryptography.fernet import Fernet
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.accounts import pinfl as pinfl_utils
from apps.accounts.models import User
from apps.ceremonies import ownership
from apps.ceremonies.models import CeremonyInvitation, IdentifierType
from apps.storage import vault
from apps.storage.models import StorageConnection, StorageCredential
from tests.test_ceremony_ownership import invitation, world  # noqa: F401 - fixture

NEW_PINFL_KEY = Fernet.generate_key().decode()
NEW_VAULT_KEY = Fernet.generate_key().decode()
NEW_HASH_KEY = "rotated-hash-key-0123456789abcdef"


def run(*args) -> str:
    out = StringIO()
    call_command("rotate_encryption_keys", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def stored(world, make_user):
    """Rows encrypted with the ORIGINAL (to be retired) keys."""
    pinfl = "41203990123456"
    user = make_user(pinfl=pinfl)
    deleted = make_user()
    User.objects.filter(pk=deleted.pk).update(deleted_at=timezone.now())
    by_phone = invitation(world["ceremony"], user.phone_number)
    by_pinfl = invitation(world["ceremony"], pinfl, identifier_type=IdentifierType.PINFL)
    return {"user": user, "deleted": deleted, "pinfl": pinfl, "by_phone": by_phone, "by_pinfl": by_pinfl}


def test_dry_run_writes_nothing(stored):
    before = User.objects.get(pk=stored["user"].pk).pinfl_encrypted
    out = run()
    assert "Dry run" in out and "accounts.User: " in out
    assert User.objects.get(pk=stored["user"].pk).pinfl_encrypted == before


def test_rotation_moves_data_to_new_keys_and_old_key_can_be_dropped(stored, settings):
    old_key = settings.PINFL_ENCRYPTION_KEYS[0]
    settings.PINFL_ENCRYPTION_KEYS = [NEW_PINFL_KEY, old_key]
    settings.PINFL_HASH_KEY = NEW_HASH_KEY

    out = run("--scope", "pinfl", "--apply")
    assert "pinfl: rotated." in out

    settings.PINFL_ENCRYPTION_KEYS = [NEW_PINFL_KEY]  # old key retired
    user = User.objects.get(pk=stored["user"].pk)
    assert user.get_pinfl() == stored["pinfl"]
    assert user.pinfl_hash == pinfl_utils.hash_of(stored["pinfl"])  # index under the NEW hash key
    assert User.objects.filter(pinfl_hash=pinfl_utils.hash_of(stored["pinfl"])).get() == user  # exact search works
    deleted = User._base_manager.get(pk=stored["deleted"].pk)
    assert deleted.get_pinfl()  # soft-deleted rows are rotated too

    for key in ("by_phone", "by_pinfl"):
        inv = CeremonyInvitation.objects.get(pk=stored[key].pk)
        assert ownership.is_recipient(user, inv)  # the recipient still matches after the hash key change


def test_unknown_ciphertext_aborts_without_writing(stored, settings):
    # Old key missing: rows cannot be decrypted, so nothing may be touched.
    settings.PINFL_ENCRYPTION_KEYS = [NEW_PINFL_KEY]
    before = list(User._base_manager.order_by("pk").values_list("pinfl_encrypted", flat=True))
    with pytest.raises(CommandError, match="Nothing was written"):
        run("--scope", "pinfl", "--apply")
    assert list(User._base_manager.order_by("pk").values_list("pinfl_encrypted", flat=True)) == before


def test_output_never_contains_secrets(stored, settings):
    settings.PINFL_ENCRYPTION_KEYS = [NEW_PINFL_KEY, settings.PINFL_ENCRYPTION_KEYS[0]]
    out = run("--apply")
    assert stored["pinfl"] not in out and stored["user"].phone_number not in out
    assert NEW_PINFL_KEY not in out


def test_vault_rotation_keeps_drive_refresh_token(super_admin, settings):
    old_key = settings.GOOGLE_TOKEN_ENCRYPTION_KEYS[0]
    conn = StorageConnection.objects.create(connected_by=super_admin)
    StorageCredential.objects.create(connection=conn, refresh_token_encrypted=vault.seal("refresh-token-value"))

    settings.GOOGLE_TOKEN_ENCRYPTION_KEYS = [NEW_VAULT_KEY, old_key]
    assert "vault: rotated." in run("--scope", "vault", "--apply")

    settings.GOOGLE_TOKEN_ENCRYPTION_KEYS = [NEW_VAULT_KEY]
    assert vault.unseal(StorageCredential.objects.get().refresh_token_encrypted) == "refresh-token-value"


def test_vault_scope_requires_configured_key(settings, db):
    settings.GOOGLE_TOKEN_ENCRYPTION_KEYS = []
    with pytest.raises(CommandError, match="GOOGLE_TOKEN_ENCRYPTION_KEY"):
        run("--scope", "vault")
    assert "vault: GOOGLE_TOKEN_ENCRYPTION_KEY not configured" in run()
