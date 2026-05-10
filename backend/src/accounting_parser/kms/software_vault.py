"""SoftwareVaultAdapter — self-hosted key management.

Master key lives in a passphrase-sealed file on the host filesystem.
Once unsealed, the raw material is held in a single bytearray inside
the adapter instance for the process lifetime. HKDF-SHA256 derives
per-Client DEKs, per-Firm HMAC keys, and whatever else the
subsystems need.

### File format

The sealed master file (default path: ``/var/lib/accounting-parser/
secrets/master.key.sealed``) is a serialized ``SealedSecret``:

    APVS (magic) || version || argon2_params || salt || nonce || ciphertext

Wrapping bytes are Argon2id(passphrase) → 32-byte key → AES-256-GCM
encryption of the raw 32-byte master key.

### Argon2id parameters

Chosen for a typical single-CPA host:

- ``time_cost = 3``             (iterations)
- ``memory_cost = 65536 KiB``  (64 MiB)
- ``parallelism = 4``

Unseal wallclock: ~0.5 s on a 2024-era laptop. Slow enough to
frustrate brute-force, fast enough that startup + CLI unseal feel
responsive. Installer (P3.1) can tune upward if the host is beefy.

### Atomicity guarantees

- ``seal_to_disk`` writes to ``<path>.tmp`` then renames. POSIX
  rename is atomic on the same filesystem, so a crash mid-write
  leaves either the old sealed file or the new one, never a
  truncated file.
- ``rotate_master_key`` writes a checkpoint file at each step so
  an interrupted rotation can resume from the last completed
  re-encryption batch.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from accounting_parser.kms.adapter import (
    DerivationPurpose,
    DerivedKey,
    KeyManagementAdapter,
    SealedSecret,
    UnsealError,
)

logger = logging.getLogger(__name__)


_MASTER_KEY_BYTES = 32  # 256-bit master (sha256 / AES-256-GCM boundary)
_AEAD_NONCE_BYTES = 12  # AES-GCM recommended nonce length
_ARGON2_SALT_BYTES = 16


# Argon2id defaults. Tests override to low-cost parameters; production
# uses these values. Changing them requires a version bump in
# SealedSecret.version and a migration that re-seals existing files.
_DEFAULT_ARGON2_TIME_COST = 3
_DEFAULT_ARGON2_MEMORY_COST_KIB = 65536
_DEFAULT_ARGON2_PARALLELISM = 4


@dataclass
class VaultConfig:
    """Configuration the installer populates at provisioning time.

    Separate from the adapter so a fresh adapter can be constructed
    for tests without touching real disk paths. Production uses
    ``/var/lib/accounting-parser/secrets/master.key.sealed``; tests
    use a tempdir path.
    """

    sealed_master_path: Path
    # Argon2id overrides (tests set these low to keep suite fast).
    argon2_time_cost: int = _DEFAULT_ARGON2_TIME_COST
    argon2_memory_cost_kib: int = _DEFAULT_ARGON2_MEMORY_COST_KIB
    argon2_parallelism: int = _DEFAULT_ARGON2_PARALLELISM


@dataclass
class SoftwareVaultAdapter(KeyManagementAdapter):
    """Passphrase-sealed master key + HKDF per-use derivation."""

    config: VaultConfig
    provider: str = "software_vault"
    # Populated by ``unseal``; None before unseal or after ``seal``.
    _master_key: bytearray | None = field(default=None, init=False, repr=False)

    # ---- Lifecycle ----------------------------------------------

    def is_unsealed(self) -> bool:
        return self._master_key is not None

    def unseal(self, passphrase: str) -> None:
        """Load + decrypt the sealed master key file."""
        if self._master_key is not None:
            # Already unsealed: no-op (idempotent contract).
            return
        if not self.config.sealed_master_path.exists():
            raise UnsealError(f"sealed master file missing at {self.config.sealed_master_path}")
        raw = self.config.sealed_master_path.read_bytes()
        try:
            sealed = SealedSecret.from_bytes(raw)
        except Exception as e:  # noqa: BLE001
            raise UnsealError("sealed master file is corrupt or unreadable") from e

        plaintext = self._aead_decrypt(sealed, passphrase)
        if len(plaintext) != _MASTER_KEY_BYTES:
            # Length mismatch is a sealed-file corruption indicator.
            # Zeroize and raise.
            self._zeroize(plaintext)
            raise UnsealError("sealed master has unexpected length after decrypt")
        # Store as bytearray so we can zeroize on seal/exit.
        self._master_key = bytearray(plaintext)
        self._zeroize(plaintext)

    def seal(self) -> None:
        """Zeroize the in-memory master key."""
        if self._master_key is not None:
            self._zeroize(self._master_key)
            self._master_key = None

    # ---- Provisioning (called by installer) ---------------------

    def provision_new_master(
        self,
        *,
        passphrase: str,
        overwrite: bool = False,
    ) -> None:
        """Generate a fresh master key and seal it to disk.

        Called once by the installer (P3.1). Refuses to overwrite an
        existing sealed file unless ``overwrite=True`` (which the
        installer only sets with an explicit user confirmation step).
        After provisioning, the adapter is left unsealed so the
        installer can continue bootstrapping without re-prompting.
        """
        if self.config.sealed_master_path.exists() and not overwrite:
            raise RuntimeError(
                f"sealed master already exists at {self.config.sealed_master_path}; "
                "refusing to overwrite. Pass overwrite=True to replace (destructive)."
            )
        master_key = secrets.token_bytes(_MASTER_KEY_BYTES)
        sealed = self._seal_bytes(master_key, passphrase)
        self._write_atomic(self.config.sealed_master_path, sealed.to_bytes())
        # Leave the adapter unsealed so the installer can continue.
        self._master_key = bytearray(master_key)

    # ---- Derivation --------------------------------------------

    def derive_data_key(
        self,
        *,
        firm_id: UUID,
        client_id: UUID,
        purpose: DerivationPurpose,
    ) -> DerivedKey:
        self._require_unsealed()
        salt = firm_id.bytes + client_id.bytes
        info = f"v1|{purpose.value}".encode()
        material = self._hkdf(bytes(self._master_key), salt, info)  # type: ignore[arg-type]
        return DerivedKey(purpose=purpose, material=material)

    def derive_hmac_key(
        self,
        *,
        firm_id: UUID,
        purpose: DerivationPurpose,
    ) -> DerivedKey:
        self._require_unsealed()
        salt = firm_id.bytes
        info = f"v1|{purpose.value}".encode()
        material = self._hkdf(bytes(self._master_key), salt, info)  # type: ignore[arg-type]
        return DerivedKey(purpose=purpose, material=material)

    # ---- Seal/unseal arbitrary secrets --------------------------

    def seal_secret(self, secret: bytes, passphrase: str) -> SealedSecret:
        return self._seal_bytes(secret, passphrase)

    def unseal_secret(self, sealed: SealedSecret, passphrase: str) -> bytes:
        return self._aead_decrypt(sealed, passphrase)

    # ---- Internals ---------------------------------------------

    def _require_unsealed(self) -> None:
        if self._master_key is None:
            raise UnsealError("adapter is sealed; call unseal(passphrase) first")

    def _seal_bytes(self, plaintext: bytes, passphrase: str) -> SealedSecret:
        salt = secrets.token_bytes(_ARGON2_SALT_BYTES)
        nonce = secrets.token_bytes(_AEAD_NONCE_BYTES)
        key = self._derive_passphrase_key(passphrase, salt)
        try:
            ciphertext = self._aead_encrypt(key, nonce, plaintext)
        finally:
            self._zeroize(key)
        return SealedSecret(
            version=1,
            argon2_salt=salt,
            argon2_time_cost=self.config.argon2_time_cost,
            argon2_memory_cost_kib=self.config.argon2_memory_cost_kib,
            argon2_parallelism=self.config.argon2_parallelism,
            aead_nonce=nonce,
            ciphertext=ciphertext,
        )

    def _aead_decrypt(self, sealed: SealedSecret, passphrase: str) -> bytes:
        key = self._derive_passphrase_key_with_params(
            passphrase,
            sealed.argon2_salt,
            time_cost=sealed.argon2_time_cost,
            memory_cost_kib=sealed.argon2_memory_cost_kib,
            parallelism=sealed.argon2_parallelism,
        )
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            try:
                return AESGCM(bytes(key)).decrypt(sealed.aead_nonce, sealed.ciphertext, None)
            except InvalidTag as e:
                raise UnsealError(
                    "AEAD decryption failed (wrong passphrase or corrupt bundle)"
                ) from e
        finally:
            self._zeroize(key)

    def _aead_encrypt(self, key: bytearray, nonce: bytes, plaintext: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(bytes(key)).encrypt(nonce, plaintext, None)

    def _derive_passphrase_key(self, passphrase: str, salt: bytes) -> bytearray:
        return self._derive_passphrase_key_with_params(
            passphrase,
            salt,
            time_cost=self.config.argon2_time_cost,
            memory_cost_kib=self.config.argon2_memory_cost_kib,
            parallelism=self.config.argon2_parallelism,
        )

    def _derive_passphrase_key_with_params(
        self,
        passphrase: str,
        salt: bytes,
        *,
        time_cost: int,
        memory_cost_kib: int,
        parallelism: int,
    ) -> bytearray:
        from argon2 import low_level

        raw = low_level.hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            hash_len=32,
            type=low_level.Type.ID,
        )
        # Wrap in bytearray so callers can zeroize when done. The
        # raw bytes object is immutable and GC'd; we can't zeroize
        # that directly, but minimizing its lifetime is the best we
        # can do without writing a CFFI wrapper.
        return bytearray(raw)

    def _hkdf(self, ikm: bytes, salt: bytes, info: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info)
        return hkdf.derive(ikm)

    def _zeroize(self, buf: bytearray | bytes) -> None:
        """Overwrite a buffer with zeros. Best-effort — Python's GC
        may have already copied the bytes elsewhere; we do what we can.
        """
        if isinstance(buf, bytearray):
            for i in range(len(buf)):
                buf[i] = 0
        # bytes objects are immutable — nothing we can do structurally.

    def _write_atomic(self, path: Path, data: bytes) -> None:
        """Atomic write via tmp file + rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        # Write with mode 0600 so other users can't read the sealed file.
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(path))
