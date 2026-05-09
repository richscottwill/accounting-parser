"""SoftwareVaultAdapter behavior tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from accounting_parser.kms.adapter import DerivationPurpose, SealedSecret, UnsealError
from accounting_parser.kms.software_vault import SoftwareVaultAdapter


def test_provisioning_creates_sealed_file(fresh_vault: SoftwareVaultAdapter):
    assert not fresh_vault.config.sealed_master_path.exists()
    fresh_vault.provision_new_master(passphrase="hunter2")
    assert fresh_vault.config.sealed_master_path.exists()
    assert fresh_vault.is_unsealed()


def test_provisioning_refuses_to_overwrite(fresh_vault: SoftwareVaultAdapter):
    fresh_vault.provision_new_master(passphrase="a")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        fresh_vault.provision_new_master(passphrase="b")


def test_provisioning_overwrite_flag_allows_replacement(
    fresh_vault: SoftwareVaultAdapter,
):
    fresh_vault.provision_new_master(passphrase="a")
    # Same config, overwrite=True should succeed (destructive by design).
    fresh_vault.provision_new_master(passphrase="b", overwrite=True)
    assert fresh_vault.is_unsealed()


def test_unseal_wrong_passphrase_raises(fresh_vault: SoftwareVaultAdapter):
    fresh_vault.provision_new_master(passphrase="correct")
    fresh_vault.seal()
    with pytest.raises(UnsealError):
        fresh_vault.unseal("wrong")


def test_unseal_is_idempotent(provisioned_vault: SoftwareVaultAdapter):
    # provisioned_vault is already unsealed. Calling unseal again is a no-op.
    provisioned_vault.unseal("test-pass")
    assert provisioned_vault.is_unsealed()


def test_seal_zeroizes_master(provisioned_vault: SoftwareVaultAdapter):
    assert provisioned_vault.is_unsealed()
    provisioned_vault.seal()
    assert not provisioned_vault.is_unsealed()
    # After seal, any derive call must raise.
    with pytest.raises(UnsealError):
        provisioned_vault.derive_data_key(
            firm_id=uuid4(),
            client_id=uuid4(),
            purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK,
        )


def test_derive_data_key_is_deterministic(provisioned_vault: SoftwareVaultAdapter):
    firm_id = uuid4()
    client_id = uuid4()
    k1 = provisioned_vault.derive_data_key(
        firm_id=firm_id, client_id=client_id, purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK
    )
    k2 = provisioned_vault.derive_data_key(
        firm_id=firm_id, client_id=client_id, purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK
    )
    assert k1.material == k2.material
    assert len(k1.material) == 32


def test_derive_data_key_differs_per_client(provisioned_vault: SoftwareVaultAdapter):
    firm_id = uuid4()
    c1 = uuid4()
    c2 = uuid4()
    k1 = provisioned_vault.derive_data_key(
        firm_id=firm_id, client_id=c1, purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK
    )
    k2 = provisioned_vault.derive_data_key(
        firm_id=firm_id, client_id=c2, purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK
    )
    assert k1.material != k2.material


def test_derive_data_key_differs_per_purpose(provisioned_vault: SoftwareVaultAdapter):
    firm_id = uuid4()
    client_id = uuid4()
    k_dek = provisioned_vault.derive_data_key(
        firm_id=firm_id, client_id=client_id, purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK
    )
    k_hmac = provisioned_vault.derive_data_key(
        firm_id=firm_id, client_id=client_id, purpose=DerivationPurpose.AUDIT_CHAIN_HMAC
    )
    assert k_dek.material != k_hmac.material


def test_derive_hmac_key_no_client_scope(provisioned_vault: SoftwareVaultAdapter):
    """derive_hmac_key takes only firm_id — same firm → same key."""
    firm_id = uuid4()
    k1 = provisioned_vault.derive_hmac_key(
        firm_id=firm_id, purpose=DerivationPurpose.REVIEW_SIGNOFF_HMAC
    )
    k2 = provisioned_vault.derive_hmac_key(
        firm_id=firm_id, purpose=DerivationPurpose.REVIEW_SIGNOFF_HMAC
    )
    assert k1.material == k2.material


def test_seal_unseal_round_trip(provisioned_vault: SoftwareVaultAdapter):
    secret = b"super-secret-payload"
    sealed = provisioned_vault.seal_secret(secret, "cover-passphrase")
    recovered = provisioned_vault.unseal_secret(sealed, "cover-passphrase")
    assert recovered == secret


def test_seal_unseal_wrong_passphrase_raises(provisioned_vault: SoftwareVaultAdapter):
    sealed = provisioned_vault.seal_secret(b"payload", "right")
    with pytest.raises(UnsealError):
        provisioned_vault.unseal_secret(sealed, "wrong")


def test_sealed_secret_serialization_round_trip():
    from pathlib import Path

    from accounting_parser.kms.software_vault import SoftwareVaultAdapter, VaultConfig

    cfg = VaultConfig(
        sealed_master_path=Path("/unused"),
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
    )
    vault = SoftwareVaultAdapter(config=cfg)
    sealed = vault.seal_secret(b"x" * 100, "p")
    round_tripped = SealedSecret.from_bytes(sealed.to_bytes())
    assert round_tripped == sealed
    assert vault.unseal_secret(round_tripped, "p") == b"x" * 100


def test_unseal_corrupt_bundle_raises():
    with pytest.raises(UnsealError):
        SealedSecret.from_bytes(b"NOT_APVS")
    with pytest.raises(UnsealError):
        SealedSecret.from_bytes(b"")


def test_corrupted_sealed_file_raises_on_unseal(fresh_vault: SoftwareVaultAdapter):
    """Truncated / replaced sealed file produces UnsealError, not crash."""
    fresh_vault.provision_new_master(passphrase="x")
    fresh_vault.seal()
    # Truncate the sealed file.
    path = fresh_vault.config.sealed_master_path
    path.write_bytes(path.read_bytes()[:10])
    with pytest.raises(UnsealError):
        fresh_vault.unseal("x")


def test_missing_sealed_file_raises_clear_error(fresh_vault: SoftwareVaultAdapter):
    """Clean UnsealError when the sealed file doesn't exist yet."""
    with pytest.raises(UnsealError, match="missing"):
        fresh_vault.unseal("any")


def test_sealed_file_permissions_are_0600(fresh_vault: SoftwareVaultAdapter):
    """Sealed master file must be owner-readable only (0600).

    Posix permission check — skipped on Windows if we ever ship there
    (installer uses DPAPI on Windows anyway).
    """
    import os
    import stat
    import sys

    if sys.platform.startswith("win"):
        pytest.skip("POSIX permission model")
    fresh_vault.provision_new_master(passphrase="x")
    mode = os.stat(fresh_vault.config.sealed_master_path).st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_derived_key_repr_does_not_leak_material(
    provisioned_vault: SoftwareVaultAdapter,
):
    """DerivedKey.__repr__ redacts the material — defense against log leakage."""
    key = provisioned_vault.derive_data_key(
        firm_id=uuid4(),
        client_id=uuid4(),
        purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK,
    )
    assert "<32 bytes>" in repr(key)
    # Raw hex should NOT appear in repr.
    assert key.material.hex() not in repr(key)


# ---- Property-based ------------------------------------------------


@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(secret=st.binary(min_size=0, max_size=1024))
def test_seal_unseal_round_trip_property(provisioned_vault: SoftwareVaultAdapter, secret: bytes):
    """For every plausible secret, seal + unseal returns the input verbatim."""
    sealed = provisioned_vault.seal_secret(secret, "prop-test")
    recovered = provisioned_vault.unseal_secret(sealed, "prop-test")
    assert recovered == secret
