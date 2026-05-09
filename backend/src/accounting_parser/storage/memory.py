"""InMemoryDocumentStoreAdapter — test-only.

Keeps the storage layer out of unit tests. Every byte stays in
process memory in a ``dict[ObjectRef, bytes]``. Deterministic,
dependency-free, fast.

Not exposed to production config paths. ``create_app`` refuses to
construct this adapter without explicit injection.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import BinaryIO

from accounting_parser.storage.adapter import DocumentStoreAdapter, ObjectNotFoundError, ObjectRef


@dataclass
class InMemoryDocumentStoreAdapter(DocumentStoreAdapter):
    """Store bytes in a dict. Provides ``contents`` for test assertions."""

    provider: str = "memory"
    contents: dict[tuple[str, str], bytes] = field(default_factory=dict)
    content_types: dict[tuple[str, str], str] = field(default_factory=dict)

    def store(
        self,
        ref: ObjectRef,
        stream: BinaryIO,
        *,
        content_type: str,
        content_length: int | None = None,
    ) -> None:
        data = stream.read()
        self.contents[(ref.bucket, ref.key)] = data
        self.content_types[(ref.bucket, ref.key)] = content_type

    def retrieve(self, ref: ObjectRef) -> BinaryIO:
        try:
            data = self.contents[(ref.bucket, ref.key)]
        except KeyError as e:
            raise ObjectNotFoundError(f"no object at {ref.uri}") from e
        return io.BytesIO(data)

    def delete(self, ref: ObjectRef) -> None:
        self.contents.pop((ref.bucket, ref.key), None)
        self.content_types.pop((ref.bucket, ref.key), None)

    def object_exists(self, ref: ObjectRef) -> bool:
        return (ref.bucket, ref.key) in self.contents

    def list_by_prefix(self, bucket: str, prefix: str) -> list[str]:
        return sorted(key for (b, key) in self.contents if b == bucket and key.startswith(prefix))
