"""KeyManagementAdapter Protocol conformance."""

from __future__ import annotations

import pytest

from accounting_parser.kms.adapter import DerivationPurpose
from accounting_parser.kms.cloud_stub import KmsAdapter
from accounting_parser.kms.software_vault import SoftwareVaultAdapter


@pytest.mark.parametrize(
    "adapter_factory",
    [
        lambda cfg: KmsAdapter(key_alias="stub"),
        lambda cfg: SoftwareVaultAdapter(config=cfg),
    ],
)
def test_adapter_conforms_to_protocol(adapter_factory, fast_argon_config):
    adapter = adapter_factory(fast_argon_config)
    for attr in (
        "provider",
        "is_unsealed",
        "unseal",
        "seal",
        "derive_data_key",
        "derive_hmac_key",
        "seal_secret",
        "unseal_secret",
    ):
        assert hasattr(adapter, attr), f"{type(adapter).__name__} missing {attr}"


def test_cloud_kms_adapter_is_stub():
    adapter = KmsAdapter()
    from uuid import uuid4

    with pytest.raises(NotImplementedError):
        adapter.unseal("x")
    with pytest.raises(NotImplementedError):
        adapter.derive_data_key(
            firm_id=uuid4(),
            client_id=uuid4(),
            purpose=DerivationPurpose.CLIENT_DOCUMENT_DEK,
        )
    with pytest.raises(NotImplementedError):
        adapter.seal_secret(b"x", "p")


def test_providers_are_distinct():
    assert SoftwareVaultAdapter.provider == "software_vault"
    assert KmsAdapter.provider == "aws_kms"
