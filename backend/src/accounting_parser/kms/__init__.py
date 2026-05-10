"""Key management subsystem (self-hosted fork, Phase 1 P1.3).

Provides the ``KeyManagementAdapter`` abstraction. Default
implementation is ``SoftwareVaultAdapter`` — a passphrase-sealed
master key stored on the host filesystem, with per-Client DEK
derivation via HKDF-SHA256.

Cloud variant reserved as ``KmsAdapter`` stub for parity with the
parent spec.

### Contract

Every adapter provides:

- ``derive_data_key(firm, client, purpose)`` — per-Client DEK
- ``derive_hmac_key(firm, purpose)``         — per-Firm HMAC key
- ``seal(secret, passphrase)``               — AEAD encrypt
- ``unseal(sealed, passphrase)``             — AEAD decrypt
- ``rotate_master()``                        — re-key every at-rest
  artifact; resumable via checkpoint file

### Threat model

- Master passphrase lives only in the firm principal's head (and
  the paper recovery worksheet the installer prints). Never at
  rest, never transmitted.
- Sealed master key file lives on the host filesystem at
  ``/var/lib/accounting-parser/secrets/master.key.sealed``.
- Once unsealed (at startup or via CLI), the master key lives in
  API process memory only. Zeroized on process exit — best effort;
  a crash leaves a window, which is why R30.5 observability alerts
  on unexpected restarts.
- **Correctness Property 32 (CP32):** losing the passphrase with no
  sealed-key backup makes the data unrecoverable by design. No
  escrow, no backdoor.
"""

from accounting_parser.kms.adapter import (
    DerivationPurpose,
    KeyManagementAdapter,
    SealedSecret,
    UnsealError,
)
from accounting_parser.kms.cloud_stub import KmsAdapter
from accounting_parser.kms.software_vault import SoftwareVaultAdapter

__all__ = [
    "DerivationPurpose",
    "KeyManagementAdapter",
    "KmsAdapter",
    "SealedSecret",
    "SoftwareVaultAdapter",
    "UnsealError",
]
