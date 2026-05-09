"""DocumentStoreAdapter Protocol and DTOs.

The application stores uploaded documents in object storage, not in
the database. The database holds metadata (filename, content type,
sha256, byte size, ingest state, source-system detection, per-Client
encryption key id); the bytes live in object storage.

### Contract

Every adapter MUST be able to:

- ``store(ref, stream, content_type)``    — write an object; idempotent
  on identical content (ref is stable for the same sha256 within the
  same (firm, client) scope).
- ``retrieve(ref)``                        — read an object's bytes.
- ``delete(ref)``                          — remove an object; safe
  on missing.
- ``object_exists(ref)``                   — fast existence check.
- ``list_by_prefix(prefix)``               — enumerate keys, used by
  cleanup jobs + audit tooling.

Per-Client isolation is enforced by the **key layout**:

    firms/{firm_id}/clients/{client_id}/documents/{sha256}/{filename}

The storage adapter MUST reject a store call whose key does not match
this pattern. The firm_id + client_id prefix means a compromised per-
Client DEK cannot decrypt another Client's objects even within the
same bucket (the DEKs are different; the keys are different).

### What this package deliberately does NOT do

- No dedup. ``IngestionService`` handles that at the database layer
  (document_dedup_unique constraint). The adapter happily writes
  objects with identical content; duplicates are the caller's concern.
- No virus scan. ``IngestionService`` handles that.
- No MIME detection. ``IngestionService`` handles that.
- No encryption. The adapter writes whatever bytes the caller hands
  it. In production, those bytes are already encrypted client-side by
  the KMS adapter (P1.3). The adapter trusts its upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID


class StorageError(RuntimeError):
    """Base error for all storage-adapter failures.

    Subclasses surface specific failure shapes. Callers catch the
    base class when the specific cause doesn't matter (e.g., in a
    retry decorator that doesn't care whether the failure was
    missing bucket or network partition).
    """


class ObjectNotFoundError(StorageError):
    """Raised by ``retrieve`` / ``delete`` for an unknown key.

    Distinct from ``store`` which accepts a fresh key without
    error. Routes catch this and return 404.
    """


class InvalidKeyError(StorageError):
    """Raised when a caller hands the adapter a key that doesn't
    match the mandated ``firms/.../clients/.../documents/...`` layout.

    This is a programming-error signal, not a runtime condition —
    middleware should never see this. It exists so the adapter
    refuses to write to ad-hoc locations (which would break backup
    + per-Client isolation + key-rotation iteration).
    """


@dataclass(frozen=True)
class ObjectRef:
    """A fully-qualified reference to an object in storage.

    Immutable. The key layout is enforced by ``build_key`` rather
    than left to the caller — prevents drift when a new route adds
    a fresh object type.

    ``bucket`` is the MinIO/S3 bucket name. For single-firm installs
    there is one bucket named ``accounting-parser``. Multi-firm SaaS
    would use one bucket per firm; the adapter doesn't care.

    ``key`` is the object key within the bucket; matches the layout
    pattern described in the module docstring.
    """

    bucket: str
    key: str

    @property
    def uri(self) -> str:
        """S3-style URI (``s3://bucket/key``) useful for logging."""
        return f"s3://{self.bucket}/{self.key}"


def build_key(
    *,
    firm_id: UUID,
    client_id: UUID,
    sha256_hex: str,
    filename: str,
) -> str:
    """Compose an object key using the mandated layout.

    Callers should use this rather than format-string-building keys
    by hand — a typo in the prefix would break backup + rotation +
    isolation all at once. All key construction in production flows
    through this one function so the layout is a single source of
    truth.

    ``filename`` is URL-safe-but-human-readable (not sanitized here
    — upstream magic-byte validation and the dedup constraint mean
    the filename is metadata, not authenticated content).
    """
    if len(sha256_hex) != 64 or not all(c in "0123456789abcdef" for c in sha256_hex.lower()):
        raise InvalidKeyError(f"sha256_hex must be 64 lowercase hex chars, got {sha256_hex!r}")
    # Hex keeps the key human-inspectable in mc / S3 console. No
    # base32/64 — key length isn't a concern here and readability
    # matters when a CPA asks Richard to eyeball what's in storage.
    return f"firms/{firm_id}/clients/{client_id}/documents/" f"{sha256_hex.lower()}/{filename}"


class DocumentStoreAdapter(Protocol):
    """Contract every object-storage backend satisfies.

    Implementations: ``MinIODocumentStoreAdapter`` (self-hosted
    default), ``S3DocumentStoreAdapter`` (cloud-variant stub),
    ``InMemoryDocumentStoreAdapter`` (tests).
    """

    provider: str  # short identifier: "minio", "s3", "memory"

    def store(
        self,
        ref: ObjectRef,
        stream: BinaryIO,
        *,
        content_type: str,
        content_length: int | None = None,
    ) -> None:
        """Write ``stream`` to storage under ``ref``.

        ``stream`` is consumed; callers should not re-use it. The
        adapter MAY buffer to RAM for small payloads or stream in
        chunks for large ones — the behavior is an implementation
        detail the contract doesn't pin.

        Existing object at ref: overwritten. The dedup-unique
        constraint on the document table means the application layer
        has already decided whether to overwrite; at the storage
        layer, same key means same content (since the key includes
        the sha256).
        """
        ...

    def retrieve(self, ref: ObjectRef) -> BinaryIO:
        """Open a stream over an object's bytes.

        Caller closes the returned stream. Raises ``ObjectNotFoundError``
        if the key doesn't exist. The stream is forward-only; seekable
        is not guaranteed.
        """
        ...

    def delete(self, ref: ObjectRef) -> None:
        """Remove an object. No-op on missing (idempotent).

        Callers should NOT rely on delete to discover missingness —
        use ``object_exists`` for that.
        """
        ...

    def object_exists(self, ref: ObjectRef) -> bool:
        """Return True if the object is present.

        Does NOT fetch bytes — uses the head/metadata API on S3-family
        backends. Meant for quick pre-check before upload (though the
        application layer's dedup constraint is the real dedup check).
        """
        ...

    def list_by_prefix(self, bucket: str, prefix: str) -> list[str]:
        """Return keys whose prefix matches.

        Used by cleanup jobs + key-rotation iteration (P1.3). The
        adapter MUST return at most 10000 keys in a single call; if
        more exist, the adapter truncates and callers iterate. The
        Protocol doesn't expose pagination tokens because all current
        callers either (a) want the first page or (b) iterate with
        their own prefix scoping.
        """
        ...
