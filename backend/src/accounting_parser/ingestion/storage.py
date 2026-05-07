"""Document storage backend — S3 via boto3 or local-disk fallback.

Design mirrors Task 5's cognito.py split: the production path uses real
boto3 (optionally against LocalStack); dev machines without LocalStack
can use ``storage_backend=local`` which writes to a per-Tenant directory
under ``settings.local_storage_root``.

Per Requirement 1.8 objects are encrypted at rest. With the S3 backend
we pass the per-Tenant KMS key alias (``alias/<tenant-uuid>``) as the
``SSEKMSKeyId`` on PutObject so each Tenant's objects are encrypted with
their own CMK. With the local backend we skip encryption (dev-only).
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

import boto3
from botocore.exceptions import ClientError

from accounting_parser.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredObject:
    """Receipt for a persisted object."""

    bucket: str
    object_key: str
    size_bytes: int
    sha256: bytes

    @property
    def storage_key(self) -> str:
        """Backward-compat composite key ``"<bucket>/<object_key>"``."""
        return f"{self.bucket}/{self.object_key}"


class DocumentStorage(Protocol):
    backend: str

    def put(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        quarantine: bool = False,
    ) -> StoredObject: ...

    def get(self, storage_key: str) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...

    def ensure_buckets(self, tenant_id: UUID) -> None: ...


def _key_for(tenant_id: UUID, document_id: UUID, filename: str, *, quarantine: bool) -> str:
    """Build a deterministic S3 / local key from identity."""
    prefix = "quarantine" if quarantine else "documents"
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)[:120]
    return f"{prefix}/{tenant_id}/{document_id}/{safe}"


class LocalDiskStorage:
    """Filesystem-backed storage for dev / CI without LocalStack."""

    backend = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, storage_key: str) -> Path:
        return self.root / storage_key

    def put(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        quarantine: bool = False,
    ) -> StoredObject:
        key = _key_for(tenant_id, document_id, filename, quarantine=quarantine)
        bucket = "quarantine" if quarantine else "documents"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(
            bucket=bucket,
            object_key=key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).digest(),
        )

    def get(self, storage_key: str) -> bytes:
        # ``storage_key`` is "<bucket>/<object_key>"; the local backend stores
        # under object_key root already, so take the object_key half.
        _, _, object_key = storage_key.partition("/")
        return self._path(object_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        _, _, object_key = storage_key.partition("/")
        p = self._path(object_key)
        if p.exists():
            p.unlink()

    def ensure_buckets(self, tenant_id: UUID) -> None:
        for prefix in ("documents", "quarantine", "exports"):
            (self.root / prefix / str(tenant_id)).mkdir(parents=True, exist_ok=True)


class S3Storage:
    """Production storage — S3 with per-Tenant KMS CMK."""

    backend = "s3"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._s3 = self._client("s3", settings)
        self._kms_alias_prefix = "alias/"

    @staticmethod
    def _client(service: str, settings: Settings):
        kwargs = {
            "region_name": settings.aws_region,
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        return boto3.client(service, **kwargs)

    def _bucket(self, tenant_id: UUID, *, quarantine: bool) -> str:
        suffix = "quarantine" if quarantine else "documents"
        return f"{self.settings.s3_bucket_prefix}-{tenant_id}-{suffix}"

    def ensure_buckets(self, tenant_id: UUID) -> None:
        for suffix in ("documents", "exports", "quarantine"):
            bucket = f"{self.settings.s3_bucket_prefix}-{tenant_id}-{suffix}"
            try:
                self._s3.head_bucket(Bucket=bucket)
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("404", "NoSuchBucket", "NotFound"):
                    self._s3.create_bucket(Bucket=bucket)
                    try:
                        self._s3.put_bucket_versioning(
                            Bucket=bucket,
                            VersioningConfiguration={"Status": "Enabled"},
                        )
                    except ClientError:
                        logger.warning("Could not enable versioning on %s", bucket)
                elif code == "403":
                    raise
                else:
                    raise

    def put(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        quarantine: bool = False,
    ) -> StoredObject:
        bucket = self._bucket(tenant_id, quarantine=quarantine)
        key = _key_for(tenant_id, document_id, filename, quarantine=quarantine)
        extra: dict = {
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": f"{self._kms_alias_prefix}{tenant_id}",
        }
        self._s3.put_object(Bucket=bucket, Key=key, Body=content, **extra)
        return StoredObject(
            bucket=bucket,
            object_key=key,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).digest(),
        )

    def get(self, storage_key: str) -> bytes:
        bucket, _, key = storage_key.partition("/")
        resp = self._s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()

    def delete(self, storage_key: str) -> None:
        bucket, _, key = storage_key.partition("/")
        self._s3.delete_object(Bucket=bucket, Key=key)


def get_storage(settings: Settings | None = None) -> DocumentStorage:
    settings = settings or get_settings()
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    if settings.storage_backend == "local":
        root = Path(settings.local_storage_root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return LocalDiskStorage(root)
    raise ValueError(f"Unknown storage_backend: {settings.storage_backend!r}")
