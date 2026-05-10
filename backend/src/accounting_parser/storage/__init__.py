"""Document object storage.

The ``DocumentStoreAdapter`` Protocol abstracts over S3, MinIO, and
in-memory test doubles. ``IngestionService`` (in ``ingestion/``) is
the sole client of this package — upload logic, dedup, and virus
scanning live there, not here.
"""

from accounting_parser.storage.adapter import (
    DocumentStoreAdapter,
    ObjectNotFoundError,
    ObjectRef,
    StorageError,
)
from accounting_parser.storage.memory import InMemoryDocumentStoreAdapter
from accounting_parser.storage.minio import MinIODocumentStoreAdapter
from accounting_parser.storage.s3 import S3DocumentStoreAdapter

__all__ = [
    "DocumentStoreAdapter",
    "InMemoryDocumentStoreAdapter",
    "MinIODocumentStoreAdapter",
    "ObjectNotFoundError",
    "ObjectRef",
    "S3DocumentStoreAdapter",
    "StorageError",
]
