"""DocumentStoreAdapter Protocol — structural + behavioral conformance."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest

from accounting_parser.storage.adapter import (
    InvalidKeyError,
    ObjectNotFoundError,
    ObjectRef,
    build_key,
)
from accounting_parser.storage.memory import InMemoryDocumentStoreAdapter
from accounting_parser.storage.s3 import S3DocumentStoreAdapter


@pytest.mark.parametrize(
    "adapter_factory",
    [
        lambda: InMemoryDocumentStoreAdapter(),
        lambda: S3DocumentStoreAdapter(bucket="stub"),
    ],
)
def test_adapter_conforms_to_protocol(adapter_factory):
    """Every adapter must satisfy the Protocol's attribute surface."""
    adapter = adapter_factory()
    for attr in (
        "provider",
        "store",
        "retrieve",
        "delete",
        "object_exists",
        "list_by_prefix",
    ):
        assert hasattr(adapter, attr)


def test_s3_adapter_is_a_stub():
    """Cloud-variant adapter raises NotImplementedError on every op."""
    adapter = S3DocumentStoreAdapter(bucket="x")
    ref = ObjectRef(bucket="x", key="y")
    with pytest.raises(NotImplementedError):
        adapter.store(ref, io.BytesIO(b""), content_type="text/plain")
    with pytest.raises(NotImplementedError):
        adapter.retrieve(ref)
    with pytest.raises(NotImplementedError):
        adapter.delete(ref)
    with pytest.raises(NotImplementedError):
        adapter.object_exists(ref)
    with pytest.raises(NotImplementedError):
        adapter.list_by_prefix("x", "y")


def test_in_memory_round_trip():
    """Store → retrieve → same bytes. Delete → object_exists False."""
    adapter = InMemoryDocumentStoreAdapter()
    ref = ObjectRef(bucket="test", key="foo/bar.bin")
    adapter.store(ref, io.BytesIO(b"hello-world"), content_type="application/octet-stream")
    assert adapter.object_exists(ref)
    with adapter.retrieve(ref) as stream:
        assert stream.read() == b"hello-world"
    adapter.delete(ref)
    assert not adapter.object_exists(ref)


def test_retrieve_missing_raises_object_not_found():
    adapter = InMemoryDocumentStoreAdapter()
    with pytest.raises(ObjectNotFoundError):
        adapter.retrieve(ObjectRef(bucket="test", key="no-such-key"))


def test_delete_missing_is_idempotent():
    adapter = InMemoryDocumentStoreAdapter()
    # No raise: delete of a missing key is a successful no-op.
    adapter.delete(ObjectRef(bucket="test", key="gone"))


def test_build_key_layout_matches_contract():
    """build_key returns the exact firms/.../clients/.../documents/... layout."""
    firm_id = uuid4()
    client_id = uuid4()
    sha = "a" * 64
    key = build_key(
        firm_id=firm_id,
        client_id=client_id,
        sha256_hex=sha,
        filename="report.pdf",
    )
    assert key.startswith(f"firms/{firm_id}/clients/{client_id}/documents/{sha}/")
    assert key.endswith("/report.pdf")


def test_build_key_rejects_invalid_sha():
    with pytest.raises(InvalidKeyError):
        build_key(firm_id=uuid4(), client_id=uuid4(), sha256_hex="nope", filename="x")


def test_list_by_prefix_returns_matching_keys_only():
    adapter = InMemoryDocumentStoreAdapter()
    for suffix in ("a", "b", "c"):
        adapter.store(
            ObjectRef(bucket="b1", key=f"p1/{suffix}"),
            io.BytesIO(b""),
            content_type="text/plain",
        )
    adapter.store(
        ObjectRef(bucket="b1", key="p2/elsewhere"),
        io.BytesIO(b""),
        content_type="text/plain",
    )
    # Different bucket should NOT appear.
    adapter.store(
        ObjectRef(bucket="b2", key="p1/zzz"),
        io.BytesIO(b""),
        content_type="text/plain",
    )
    keys = adapter.list_by_prefix("b1", "p1/")
    assert keys == ["p1/a", "p1/b", "p1/c"]
