"""KMS test fixtures.

The software vault touches a filesystem path; tests use tmp_path so
every test case runs against a fresh directory. Argon2id parameters
are lowered aggressively (time_cost=1, memory=8 KiB, parallelism=1)
so the full suite completes in milliseconds rather than seconds.
Production uses the defaults from software_vault.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from accounting_parser.kms.software_vault import SoftwareVaultAdapter, VaultConfig


@pytest.fixture
def fast_argon_config(tmp_path: Path) -> VaultConfig:
    """Low-cost Argon2id config; only acceptable in tests."""
    return VaultConfig(
        sealed_master_path=tmp_path / "secrets" / "master.key.sealed",
        argon2_time_cost=1,
        argon2_memory_cost_kib=8,
        argon2_parallelism=1,
    )


@pytest.fixture
def fresh_vault(fast_argon_config: VaultConfig) -> SoftwareVaultAdapter:
    """An unprovisioned adapter pointed at a tmp_path sealed file."""
    return SoftwareVaultAdapter(config=fast_argon_config)


@pytest.fixture
def provisioned_vault(fresh_vault: SoftwareVaultAdapter) -> SoftwareVaultAdapter:
    """Adapter with a fresh master key provisioned under passphrase 'test-pass'."""
    fresh_vault.provision_new_master(passphrase="test-pass")
    return fresh_vault
