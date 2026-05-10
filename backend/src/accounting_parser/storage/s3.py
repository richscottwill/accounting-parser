"""S3DocumentStoreAdapter — stub for the cloud variant.

Same role as ``CognitoAuthAdapter`` in the auth package: confirm the
Protocol abstraction holds and reserve the adapter identity for a
future cloud-variant reinstatement. Every method raises
``NotImplementedError``.

If the spec changes and S3 becomes a first-class adapter again, the
implementation is a subset of ``MinIODocumentStoreAdapter`` (same
boto3 client, drop the custom endpoint_url, rely on instance IAM
credentials). Until then, this stub prevents silent misconfiguration.
"""

from __future__ import annotations

from typing import BinaryIO

from accounting_parser.storage.adapter import DocumentStoreAdapter, ObjectRef

_NOT_IMPLEMENTED_MSG = (
    "S3DocumentStoreAdapter is a stub in the self-hosted fork. "
    "The cloud variant is out of scope; see "
    ".kiro/specs/accounting-parser-self-hosted/README.md §Non-goals. "
    "If you reached this, either (a) DOC_STORE_ADAPTER=s3 was set in "
    "configuration without re-instating the adapter, or (b) a test "
    "is exercising the Protocol shape against both implementations."
)


class S3DocumentStoreAdapter(DocumentStoreAdapter):
    """Stub cloud adapter. Every operation raises NotImplementedError."""

    provider: str = "s3"

    def __init__(self, *, bucket: str | None = None, region: str | None = None) -> None:
        # Accept the parent-spec config shape so the constructor doesn't
        # need a test change if the adapter ever gets reinstated.
        self.bucket = bucket
        self.region = region

    def store(
        self,
        ref: ObjectRef,
        stream: BinaryIO,
        *,
        content_type: str,
        content_length: int | None = None,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def retrieve(self, ref: ObjectRef) -> BinaryIO:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def delete(self, ref: ObjectRef) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def object_exists(self, ref: ObjectRef) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def list_by_prefix(self, bucket: str, prefix: str) -> list[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
