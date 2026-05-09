"""KeyManagementAdapter Protocol + DTOs.

Every method takes typed DTOs rather than ambient state so adapter
implementations stay pure with respect to inputs. The master key
lives inside an adapter instance; a single process has exactly one
adapter instance (constructed at startup after unsealing) and
services receive the adapter via dependency injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID


class DerivationPurpose(str, Enum):
    """Stable, registered purposes for HKDF derivation.

    HKDF takes a purpose/info label. Using an Enum gives us a finite,
    code-enforced set of derivations — prevents a future caller from
    inventing a new purpose label that silently collides with an
    existing one (HKDF is deterministic; same IKM + salt + info →
    same key, so purpose collision is a real correctness hazard).

    Adding a purpose requires a code change + a migration note +
    (if it affects at-rest artifacts) a rotation pass.
    """

    # Per-Client data encryption key for document objects.
    CLIENT_DOCUMENT_DEK = "client.document.dek"
    # Per-Firm HMAC key for audit log chain signatures (if we later
    # wrap the sha256 chain in HMAC-SHA256).
    AUDIT_CHAIN_HMAC = "audit.chain.hmac"
    # Per-Firm JWT signing key seed. The actual JWT signing key is
    # RSA-2048 generated separately; this purpose exists if the team
    # ever wants to derive it deterministically from the master.
    SESSION_JWT_SIGNING = "session.jwt.signing"
    # Per-Firm HMAC key for ReviewSignoff integrity (parent R25).
    REVIEW_SIGNOFF_HMAC = "review.signoff.hmac"
    # Per-Firm backup encryption key (R27.3).
    BACKUP_ENCRYPTION = "backup.encryption"
    # Per-Firm HMAC for magic-link token hashing (optional future
    # strengthening; currently we use plain sha256 in magic_link.py).
    MAGIC_LINK_HMAC = "magic_link.hmac"


@dataclass(frozen=True)
class SealedSecret:
    """An opaque bundle representing a passphrase-sealed secret.

    The payload is AEAD-encrypted (AES-256-GCM) with a key derived
    from the passphrase via Argon2id. The ``salt`` + ``nonce`` are
    stored alongside the ciphertext so unseal can reproduce the
    derivation deterministically.

    ``version`` is bumped when the derivation parameters change so
    future versions can read old bundles and migrate forward.
    """

    version: int
    argon2_salt: bytes
    argon2_time_cost: int
    argon2_memory_cost_kib: int
    argon2_parallelism: int
    aead_nonce: bytes
    ciphertext: bytes

    def to_bytes(self) -> bytes:
        """Serialize to a portable byte representation.

        Format: magic(4) || version(1) || argon2_params(12) ||
        salt_len(1) || salt || nonce_len(1) || nonce || ciphertext.
        No length prefix on ciphertext — read to EOF.
        """
        import struct

        return (
            b"APVS"  # magic: Accounting-Parser Vault Sealed
            + struct.pack(">B", self.version)
            + struct.pack(
                ">III",
                self.argon2_time_cost,
                self.argon2_memory_cost_kib,
                self.argon2_parallelism,
            )
            + struct.pack(">B", len(self.argon2_salt))
            + self.argon2_salt
            + struct.pack(">B", len(self.aead_nonce))
            + self.aead_nonce
            + self.ciphertext
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> SealedSecret:
        import struct

        if len(data) < 4 or data[:4] != b"APVS":
            raise UnsealError("bundle missing APVS magic bytes")
        pos = 4
        version = struct.unpack_from(">B", data, pos)[0]
        pos += 1
        time_cost, memory_cost, parallelism = struct.unpack_from(">III", data, pos)
        pos += 12
        salt_len = struct.unpack_from(">B", data, pos)[0]
        pos += 1
        salt = data[pos : pos + salt_len]
        pos += salt_len
        nonce_len = struct.unpack_from(">B", data, pos)[0]
        pos += 1
        nonce = data[pos : pos + nonce_len]
        pos += nonce_len
        ciphertext = data[pos:]
        return cls(
            version=version,
            argon2_salt=salt,
            argon2_time_cost=time_cost,
            argon2_memory_cost_kib=memory_cost,
            argon2_parallelism=parallelism,
            aead_nonce=nonce,
            ciphertext=ciphertext,
        )


class UnsealError(RuntimeError):
    """Raised when a sealed secret cannot be opened.

    Single error type for all unseal failures (wrong passphrase,
    corrupt bundle, wrong version, truncated data). Keeping one
    exception prevents callers from differentiating "wrong passphrase"
    from "corrupt bundle" — both fail the same way from a security
    standpoint, and distinguishing them would help an attacker.
    """


@dataclass(frozen=True)
class DerivedKey:
    """A key derived from the master via HKDF.

    Always 32 bytes (sha256 output length). Wrapped in a DTO so
    callers can't accidentally pickle + log + transmit raw bytes
    as easily — the DTO has no __str__/__repr__ revealing material.
    """

    purpose: DerivationPurpose
    material: bytes

    def __repr__(self) -> str:
        # Prevent accidental key leakage through logs / tracebacks.
        return f"DerivedKey(purpose={self.purpose.value}, material=<{len(self.material)} bytes>)"


class KeyManagementAdapter(Protocol):
    """Contract every key-management backend satisfies."""

    provider: str

    def is_unsealed(self) -> bool:
        """Return True if the adapter currently has the master key in memory."""
        ...

    def unseal(self, passphrase: str) -> None:
        """Load the sealed master key from disk + decrypt it.

        Idempotent: calling unseal twice on an already-unsealed adapter
        is a no-op. Callers that want to ensure fresh state call ``seal``
        / re-construct.

        Raises ``UnsealError`` on wrong passphrase or missing/corrupt
        sealed file.
        """
        ...

    def seal(self) -> None:
        """Zeroize the in-memory master key.

        After ``seal()``, ``is_unsealed()`` is False and every derive
        call raises ``UnsealError``.
        """
        ...

    def derive_data_key(
        self,
        *,
        firm_id: UUID,
        client_id: UUID,
        purpose: DerivationPurpose,
    ) -> DerivedKey:
        """Derive a per-(Firm, Client) key for ``purpose``.

        HKDF-SHA256 with the master as IKM, (firm_id + client_id)
        bytes as salt, and purpose.value as info. Deterministic:
        same inputs → same output.
        """
        ...

    def derive_hmac_key(
        self,
        *,
        firm_id: UUID,
        purpose: DerivationPurpose,
    ) -> DerivedKey:
        """Derive a per-Firm HMAC key (no client scope)."""
        ...

    def seal_secret(self, secret: bytes, passphrase: str) -> SealedSecret:
        """Passphrase-seal ``secret`` using Argon2id-derived key + AES-GCM.

        Returns a bundle safe to persist on disk. Decryption requires
        the same passphrase.
        """
        ...

    def unseal_secret(self, sealed: SealedSecret, passphrase: str) -> bytes:
        """Inverse of ``seal_secret``."""
        ...
