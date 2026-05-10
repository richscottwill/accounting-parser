"""Bundle format round-trip + checksum enforcement."""

from __future__ import annotations

import pytest

from accounting_parser.backup.bundle import BackupBundle, BundleManifest


def _sample_bundle() -> BackupBundle:
    return BackupBundle(
        manifest=BundleManifest(
            firm_instance_id="11111111-1111-1111-1111-111111111111",
            postgres_schema_version="0005",
            counts={"documents": 3, "engagements": 1},
        ),
        postgres_dump=b"pg_dump_bytes_fixture",
        objects_tar=b"objects_tar_fixture",
        secrets_tar=b"secrets_tar_fixture",
    )


def test_round_trip_preserves_components():
    bundle = _sample_bundle()
    packed = bundle.pack()
    restored = BackupBundle.unpack(packed)
    assert restored.postgres_dump == bundle.postgres_dump
    assert restored.objects_tar == bundle.objects_tar
    assert restored.secrets_tar == bundle.secrets_tar


def test_manifest_checksums_populated_on_pack():
    bundle = _sample_bundle()
    bundle.pack()
    assert set(bundle.manifest.sha256) == {
        "postgres.dump",
        "objects.tar",
        "secrets.tar.gz",
    }
    for v in bundle.manifest.sha256.values():
        assert len(v) == 64


def test_unpack_rejects_tampered_bytes():
    """Flip a byte → checksum verification catches it."""
    bundle = _sample_bundle()
    packed = bytearray(bundle.pack())
    # Flip one byte somewhere deep in the tarball.
    packed[len(packed) // 2] ^= 0xFF
    with pytest.raises(ValueError):
        BackupBundle.unpack(bytes(packed))


def test_unpack_rejects_truncated_bundle():
    bundle = _sample_bundle()
    packed = bundle.pack()
    with pytest.raises(ValueError):
        BackupBundle.unpack(packed[:100])


def test_manifest_round_trip_via_json():
    original = BundleManifest(
        firm_instance_id="22222222-2222-2222-2222-222222222222",
        postgres_schema_version="0005",
        counts={"documents": 42},
    )
    text = original.to_json()
    restored = BundleManifest.from_json(text)
    assert restored.firm_instance_id == original.firm_instance_id
    assert restored.counts == {"documents": 42}
    assert restored.postgres_schema_version == "0005"
