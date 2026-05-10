"""Backup bundle format + manifest.

A backup bundle is a single encrypted tar.gz file with this layout:

```
manifest.json          — versions, checksums, timestamps
postgres.dump          — pg_dump --format=custom output
objects.tar            — MinIO object tree (uncompressed; pg_dump
                         compresses internally so double-compressing
                         hurts more than it helps)
secrets.tar.gz         — sealed secrets snapshot
```

The outer tar.gz is AEAD-encrypted using AES-256-GCM with a key
derived from the Firm master via HKDF (purpose BACKUP_ENCRYPTION).

### Manifest contract

```json
{
  "version": 1,
  "created_at": "2026-05-10T00:00:00Z",
  "firm_instance_id": "...",
  "postgres_schema_version": "0005",
  "sha256": {
    "postgres.dump": "...",
    "objects.tar": "...",
    "secrets.tar.gz": "..."
  },
  "counts": {
    "documents": 42,
    "engagements": 3,
    "workflow_runs": 5
  }
}
```

Restoration verifies every sha256 before touching the live stores.
A truncated or tampered bundle fails verification and the restore
aborts with a loud error — no half-restored state.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_BUNDLE_FORMAT_VERSION = 1


@dataclass
class BundleManifest:
    """Metadata about a backup bundle."""

    version: int = _BUNDLE_FORMAT_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    firm_instance_id: str = ""
    postgres_schema_version: str = ""
    sha256: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        payload: dict[str, Any] = {
            "version": self.version,
            "created_at": self.created_at,
            "firm_instance_id": self.firm_instance_id,
            "postgres_schema_version": self.postgres_schema_version,
            "sha256": dict(self.sha256),
            "counts": dict(self.counts),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> BundleManifest:
        data = json.loads(text)
        return cls(
            version=int(data.get("version", _BUNDLE_FORMAT_VERSION)),
            created_at=str(data.get("created_at", "")),
            firm_instance_id=str(data.get("firm_instance_id", "")),
            postgres_schema_version=str(data.get("postgres_schema_version", "")),
            sha256=dict(data.get("sha256", {})),
            counts=dict(data.get("counts", {})),
        )


@dataclass
class BackupBundle:
    """A backup bundle constructed in memory before AEAD wrapping.

    Kept small by design — for the firm's typical data volume
    (hundreds of clients, thousands of documents) the inner tar is
    tens of MB, not GB. If a firm grows past that, P3 will swap to
    streaming directly to disk; the API here stays stable.
    """

    manifest: BundleManifest
    postgres_dump: bytes
    objects_tar: bytes
    secrets_tar: bytes

    def pack(self) -> bytes:
        """Pack the components into a tarball with manifest checksums.

        Returns plaintext bytes. Callers pass this through the KMS
        adapter's AEAD before writing to disk.
        """
        # Finalize checksums.
        self.manifest.sha256 = {
            "postgres.dump": hashlib.sha256(self.postgres_dump).hexdigest(),
            "objects.tar": hashlib.sha256(self.objects_tar).hexdigest(),
            "secrets.tar.gz": hashlib.sha256(self.secrets_tar).hexdigest(),
        }

        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as tar:
            _add_bytes(tar, "manifest.json", self.manifest.to_json().encode())
            _add_bytes(tar, "postgres.dump", self.postgres_dump)
            _add_bytes(tar, "objects.tar", self.objects_tar)
            _add_bytes(tar, "secrets.tar.gz", self.secrets_tar)
        return out.getvalue()

    @classmethod
    def unpack(cls, packed: bytes) -> BackupBundle:
        """Reverse of ``pack``. Verifies manifest checksums.

        Raises ``ValueError`` on missing member, corrupt tar, or
        checksum mismatch. Also raises ``ValueError`` on truncated
        tar.gz input (EOFError from gzip is re-raised as ValueError
        so callers have a single exception type to handle).
        """
        try:
            with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as tar:
                members = {m.name: m for m in tar.getmembers()}
                needed = {"manifest.json", "postgres.dump", "objects.tar", "secrets.tar.gz"}
                missing = needed - members.keys()
                if missing:
                    raise ValueError(f"bundle missing members: {sorted(missing)}")

                def _read(name: str) -> bytes:
                    fh = tar.extractfile(members[name])
                    if fh is None:
                        raise ValueError(f"cannot read {name}")
                    return fh.read()

                manifest = BundleManifest.from_json(_read("manifest.json").decode())
                postgres_dump = _read("postgres.dump")
                objects_tar = _read("objects.tar")
                secrets_tar = _read("secrets.tar.gz")
        except (tarfile.TarError, EOFError, OSError) as e:
            raise ValueError(f"bundle could not be unpacked: {e}") from e

        # Verify checksums recorded in manifest.
        expected = manifest.sha256
        actual = {
            "postgres.dump": hashlib.sha256(postgres_dump).hexdigest(),
            "objects.tar": hashlib.sha256(objects_tar).hexdigest(),
            "secrets.tar.gz": hashlib.sha256(secrets_tar).hexdigest(),
        }
        for name, expected_hash in expected.items():
            if actual[name] != expected_hash:
                raise ValueError(
                    f"bundle checksum mismatch for {name}: "
                    f"expected {expected_hash}, got {actual[name]}"
                )

        return cls(
            manifest=manifest,
            postgres_dump=postgres_dump,
            objects_tar=objects_tar,
            secrets_tar=secrets_tar,
        )


def write_manifest(manifest: BundleManifest, path: Path) -> None:
    """Write a manifest to disk (used for out-of-bundle inspection)."""
    path.write_text(manifest.to_json())


def read_manifest(path: Path) -> BundleManifest:
    return BundleManifest.from_json(path.read_text())


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = int(datetime.now(UTC).timestamp())
    tar.addfile(info, io.BytesIO(data))
