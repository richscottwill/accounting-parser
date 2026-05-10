"""BackupRunner + RestoreRunner round-trip (CP30)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from accounting_parser.backup.runner import (
    BackupRunner,
    ObjectTreeSnapshotter,
    PostgresDumper,
    RestoreError,
    RestoreRunner,
    SecretsSnapshotter,
)


@dataclass
class _FakePgDumper(PostgresDumper):
    payload: bytes = b""

    def dump(self, *, dsn: str) -> bytes:
        return self.payload


@dataclass
class _FakeObjectStore(ObjectTreeSnapshotter):
    tar_bytes: bytes = b""
    restored: bytes | None = None

    def snapshot(self) -> bytes:
        return self.tar_bytes

    def restore(self, tar_bytes: bytes) -> None:
        self.restored = tar_bytes


@dataclass
class _FakeSecrets(SecretsSnapshotter):
    tar_bytes: bytes = b""
    restored: bytes | None = None

    def snapshot(self) -> bytes:
        return self.tar_bytes

    def restore(self, tar_bytes: bytes) -> None:
        self.restored = tar_bytes


def test_backup_then_restore_round_trip(tmp_path: Path):
    """CP30: backup → restore reproduces the component bytes verbatim."""
    pg_payload = b"PG_DUMP_CONTENTS" * 100
    obj_payload = b"OBJ_TAR_CONTENTS" * 200
    sec_payload = b"SECRETS_CONTENTS" * 50

    backup = BackupRunner(
        postgres_dumper=_FakePgDumper(payload=pg_payload),
        object_snapshotter=_FakeObjectStore(tar_bytes=obj_payload),
        secrets_snapshotter=_FakeSecrets(tar_bytes=sec_payload),
    )

    out_path = tmp_path / "bundle.tar.gz"
    result = backup.run(
        firm_instance_id=uuid4(),
        postgres_dsn="postgresql://ignored",
        schema_version="0005",
        counts={"documents": 7},
        output_path=out_path,
    )

    assert out_path.exists()
    assert result.byte_size == out_path.stat().st_size
    assert result.manifest.counts == {"documents": 7}

    # Restore into fresh fakes; assert bytes round-trip.
    obj_restorer = _FakeObjectStore()
    sec_restorer = _FakeSecrets()
    restore = RestoreRunner(
        object_restorer=obj_restorer,
        secrets_restorer=sec_restorer,
    )

    pg_restored: list[bytes] = []
    manifest = restore.run(
        bundle_path=out_path,
        postgres_restore_cmd=lambda b: pg_restored.append(b),
    )

    assert manifest.counts == {"documents": 7}
    assert pg_restored == [pg_payload]
    assert obj_restorer.restored == obj_payload
    assert sec_restorer.restored == sec_payload


def test_restore_rejects_tampered_bundle(tmp_path: Path):
    """Verify that bundle tampering causes restore to refuse."""
    backup = BackupRunner(
        postgres_dumper=_FakePgDumper(payload=b"pg"),
        object_snapshotter=_FakeObjectStore(tar_bytes=b"obj"),
        secrets_snapshotter=_FakeSecrets(tar_bytes=b"sec"),
    )
    out = tmp_path / "bundle.tar.gz"
    backup.run(
        firm_instance_id=uuid4(),
        postgres_dsn="x",
        schema_version="0005",
        output_path=out,
    )

    tampered = bytearray(out.read_bytes())
    tampered[len(tampered) // 2] ^= 0xFF
    out.write_bytes(bytes(tampered))

    restore = RestoreRunner(
        object_restorer=_FakeObjectStore(),
        secrets_restorer=_FakeSecrets(),
    )
    with pytest.raises(RestoreError):
        restore.run(bundle_path=out)


def test_aead_encrypt_decrypt_round_trip(tmp_path: Path):
    """With encrypt/decrypt functions, the on-disk bytes are opaque
    but restore recovers the plaintext bundle."""
    # Fake AEAD: XOR with a fixed pad. Not real crypto — real impl
    # lives in kms/software_vault.py; this just exercises the seam.
    pad = bytes(range(256))

    def fake_encrypt(data: bytes) -> bytes:
        return bytes(b ^ pad[i % 256] for i, b in enumerate(data))

    def fake_decrypt(data: bytes) -> bytes:
        return bytes(b ^ pad[i % 256] for i, b in enumerate(data))

    backup = BackupRunner(
        postgres_dumper=_FakePgDumper(payload=b"pg"),
        object_snapshotter=_FakeObjectStore(tar_bytes=b"obj"),
        secrets_snapshotter=_FakeSecrets(tar_bytes=b"sec"),
    )
    out = tmp_path / "encrypted.bundle"
    backup.run(
        firm_instance_id=uuid4(),
        postgres_dsn="x",
        schema_version="0005",
        aead_encrypt=fake_encrypt,
        output_path=out,
    )

    # Raw bytes should NOT contain the tarball magic anywhere
    # because every byte is XORed.
    encrypted = out.read_bytes()
    assert b"manifest.json" not in encrypted

    restore = RestoreRunner(
        object_restorer=_FakeObjectStore(),
        secrets_restorer=_FakeSecrets(),
    )
    pg: list[bytes] = []
    restore.run(
        bundle_path=out,
        aead_decrypt=fake_decrypt,
        postgres_restore_cmd=lambda b: pg.append(b),
    )
    assert pg == [b"pg"]
