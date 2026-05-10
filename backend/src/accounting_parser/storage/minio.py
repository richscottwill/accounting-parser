"""MinIODocumentStoreAdapter — self-hosted object storage.

MinIO is S3-protocol-compatible, so this adapter uses boto3 with a
custom endpoint URL. No MinIO-specific SDK is pulled in; every
operation goes through the generic S3 client.

### Connection model

- Endpoint: configurable via settings (``MINIO_ENDPOINT_URL``).
  Default is the compose-stack hostname (http://minio:9000) for
  container-internal access, or localhost for dev.
- Credentials: access key + secret key provisioned by the installer.
  Stored sealed; unsealed into memory at startup.
- TLS: disabled by default (MinIO runs inside the stack, Caddy
  terminates external TLS). For dev the endpoint is plain HTTP to
  avoid self-signed-cert friction.

### Bucket lifecycle

The adapter does NOT auto-create buckets. ``ensure_bucket_exists``
is called once at startup (by ``create_app``) so operational
failures surface at boot, not at the first upload request.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, BinaryIO

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from accounting_parser.storage.adapter import (
    DocumentStoreAdapter,
    ObjectNotFoundError,
    ObjectRef,
    StorageError,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


class MinIODocumentStoreAdapter(DocumentStoreAdapter):
    """boto3-backed adapter pointed at a MinIO endpoint.

    Thread-safe because boto3 clients are thread-safe. Callers that
    want a fresh client per request can construct a new adapter
    cheaply; construction cost is dominated by the first TLS /
    credential-resolver call which happens lazily on first use.
    """

    provider: str = "minio"

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.region = region
        if client is not None:
            # Test-path: caller supplies a pre-configured boto3 client
            # (e.g., a ``moto`` mock). We stash it and never create
            # our own.
            self._client = client
        else:
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=BotoConfig(
                    signature_version="s3v4",
                    # MinIO expects path-style access (host/bucket/key)
                    # not virtual-host-style (bucket.host/key).
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )

    # ---- Administration -----------------------------------------

    def ensure_bucket_exists(self, bucket: str) -> None:
        """Create the bucket if it doesn't exist.

        Idempotent: head-bucket first, then create-bucket if 404.
        Intended to be called once per process at startup, not per
        upload. MinIO's permissions let the service account create
        buckets; in cloud S3 a bucket would be pre-provisioned by IaC.
        """
        try:
            self._client.head_bucket(Bucket=bucket)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise StorageError(f"unexpected error checking bucket {bucket!r}: {e}") from e
        try:
            # MinIO ignores CreateBucketConfiguration for the default
            # region; S3 requires it for anything other than us-east-1.
            if self.region and self.region != "us-east-1":
                self._client.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": self.region},
                )
            else:
                self._client.create_bucket(Bucket=bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            # BucketAlreadyOwnedByUs: another process raced us; safe to ignore.
            if code not in {"BucketAlreadyOwnedByUs", "BucketAlreadyExists"}:
                raise StorageError(f"failed to create bucket {bucket!r}: {e}") from e

    # ---- DocumentStoreAdapter API -------------------------------

    def store(
        self,
        ref: ObjectRef,
        stream: BinaryIO,
        *,
        content_type: str,
        content_length: int | None = None,
    ) -> None:
        put_kwargs: dict[str, Any] = {
            "Bucket": ref.bucket,
            "Key": ref.key,
            "Body": stream,
            "ContentType": content_type,
        }
        if content_length is not None:
            put_kwargs["ContentLength"] = content_length
        try:
            self._client.put_object(**put_kwargs)
        except ClientError as e:
            raise StorageError(f"failed to store object {ref.uri}: {e}") from e

    def retrieve(self, ref: ObjectRef) -> BinaryIO:
        try:
            response = self._client.get_object(Bucket=ref.bucket, Key=ref.key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise ObjectNotFoundError(f"no object at {ref.uri}") from e
            raise StorageError(f"failed to retrieve {ref.uri}: {e}") from e
        # boto3 returns a StreamingBody which implements read() — good
        # enough for BinaryIO semantics. We don't wrap to preserve the
        # callback hooks boto3 clients rely on.
        return response["Body"]  # type: ignore[no-any-return]

    def delete(self, ref: ObjectRef) -> None:
        try:
            self._client.delete_object(Bucket=ref.bucket, Key=ref.key)
        except ClientError as e:
            # S3 delete is idempotent by protocol. Log at debug for
            # visibility; never raise. Catastrophic connection errors
            # still propagate.
            logger.debug("delete ignored for %s: %s", ref.uri, e)

    def object_exists(self, ref: ObjectRef) -> bool:
        try:
            self._client.head_object(Bucket=ref.bucket, Key=ref.key)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in {"404", "NotFound", "NoSuchKey"}:
                return False
            raise StorageError(f"head_object failed for {ref.uri}: {e}") from e

    def list_by_prefix(self, bucket: str, prefix: str) -> list[str]:
        try:
            response = self._client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=10000,
            )
        except ClientError as e:
            raise StorageError(f"list failed for {bucket}/{prefix}: {e}") from e
        contents = response.get("Contents", [])
        return [item["Key"] for item in contents]
