"""KmsAdapter — cloud-variant stub (parent R22.1).

Same pattern as ``CognitoAuthAdapter`` and ``S3DocumentStoreAdapter``:
every method raises NotImplementedError. Exists so the Protocol is
exercised against two implementations and so a future cloud re-
instatement doesn't require refactoring the call sites.
"""

from __future__ import annotations

from uuid import UUID

from accounting_parser.kms.adapter import (
    DerivationPurpose,
    DerivedKey,
    KeyManagementAdapter,
    SealedSecret,
)

_NOT_IMPLEMENTED_MSG = (
    "KmsAdapter is a stub in the self-hosted fork. The cloud variant "
    "(AWS KMS) is out of scope; see .kiro/specs/accounting-parser-"
    "self-hosted/README.md §Non-goals. If you reached this, check your "
    "KMS_ADAPTER configuration or your test harness."
)


class KmsAdapter(KeyManagementAdapter):
    """Stub cloud adapter. Every operation raises NotImplementedError."""

    provider: str = "aws_kms"

    def __init__(self, *, key_alias: str | None = None, region: str | None = None) -> None:
        self.key_alias = key_alias
        self.region = region

    def is_unsealed(self) -> bool:
        return False

    def unseal(self, passphrase: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def seal(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def derive_data_key(
        self,
        *,
        firm_id: UUID,
        client_id: UUID,
        purpose: DerivationPurpose,
    ) -> DerivedKey:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def derive_hmac_key(
        self,
        *,
        firm_id: UUID,
        purpose: DerivationPurpose,
    ) -> DerivedKey:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def seal_secret(self, secret: bytes, passphrase: str) -> SealedSecret:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def unseal_secret(self, sealed: SealedSecret, passphrase: str) -> bytes:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
