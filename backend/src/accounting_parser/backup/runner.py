"""BackupRunner + RestoreRunner — pure orchestration, testable.

Production paths shell out to ``pg_dump``, ``pg_restore``, and
``mc mirror`` via the compose-networked services. Tests inject fake
sources/sinks so we exercise the orchestration without standing up
all of MinIO + Postgres.

### BackupRunner

```
snapshot_postgres()   →  bytes (pg_dump --format=custom)
snapshot_objects()    →  bytes (tar of all objects)
snapshot_secrets()    →  bytes (tar.gz of sealed secrets)
build BundleManifest  →  counts, schema version
pack + AEAD encrypt   →  bytes to write to disk
```

### RestoreRunner

```
read encrypted bytes           →  AEAD decrypt
unpack bundle (verifies sha256)→  BundleManifest + raw components
drop + reload postgres         →  pg_restore --clean --if-exists
clear + repopulate objects     →  mc mb + mc cp
restore sealed secrets         →  atomic file swap
```

Every stage audits to ``audit_log_entry`` so restore drills leave a
verifiable trail. CP30 property: a fresh host restored from a T-time
bundle produces a firm_instance equivalent to the source at T.
"""

from __future__ import annotations

import io
import logging
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from accounting_parser.backup.bundle import BackupBundle, BundleManifest

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Raised when a backup stage fails; caller retries or alerts."""


class RestoreError(RuntimeError):
    """Raised when restore aborts; live services are NOT started back up."""


@dataclass(frozen=True)
class BackupResult:
    """Metadata about a completed backup."""

    bundle_path: Path
    byte_size: int
    manifest: BundleManifest


# ---- Source protocols --------------------------------------------


class PostgresDumper(Protocol):
    """Produces a pg_dump byte stream."""

    def dump(self, *, dsn: str) -> bytes: ...


class ObjectTreeSnapshotter(Protocol):
    """Produces a tar of every object in the store."""

    def snapshot(self) -> bytes: ...
    def restore(self, tar_bytes: bytes) -> None: ...


class SecretsSnapshotter(Protocol):
    """Tars up the sealed-secrets directory."""

    def snapshot(self) -> bytes: ...
    def restore(self, tar_bytes: bytes) -> None: ...


# ---- Production implementations ----------------------------------


class PgDumpDumper(PostgresDumper):
    """Shell-out implementation of ``pg_dump --format=custom``."""

    def dump(self, *, dsn: str) -> bytes:
        # pg_dump is provided by the container image PATH; partial-
        # path is correct here, not a security smell. Ruff's S607
        # rule is too broad for this case.
        result = subprocess.run(  # noqa: S603
            ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", dsn],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise BackupError(
                f"pg_dump failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace')[:500]}"
            )
        return result.stdout


class FilesystemSecretsSnapshotter(SecretsSnapshotter):
    """Tars/untars a directory (e.g., ``/var/lib/accounting-parser/secrets``)."""

    def __init__(self, *, path: Path) -> None:
        self.path = path

    def snapshot(self) -> bytes:
        if not self.path.exists():
            return b""
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as tar:
            tar.add(str(self.path), arcname=self.path.name)
        return out.getvalue()

    def restore(self, tar_bytes: bytes) -> None:
        if not tar_bytes:
            return
        # Extract into parent; tar archive includes the directory name.
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            tar.extractall(str(self.path.parent), filter="data")


# ---- Runners ------------------------------------------------------


class BackupRunner:
    """Compose the component snapshots into a bundle + encrypt + write."""

    def __init__(
        self,
        *,
        postgres_dumper: PostgresDumper,
        object_snapshotter: ObjectTreeSnapshotter,
        secrets_snapshotter: SecretsSnapshotter,
    ) -> None:
        self.postgres_dumper = postgres_dumper
        self.object_snapshotter = object_snapshotter
        self.secrets_snapshotter = secrets_snapshotter

    def run(
        self,
        *,
        firm_instance_id: UUID,
        postgres_dsn: str,
        schema_version: str,
        counts: dict[str, int] | None = None,
        aead_encrypt: Callable[[bytes], bytes] | None = None,
        output_path: Path,
    ) -> BackupResult:
        """Produce a backup at ``output_path``.

        If ``aead_encrypt`` is provided, the bundle bytes pass through
        it before being written (typical: a closure over the KMS
        adapter's ``seal_secret`` for the backup key). If omitted,
        the bundle is written plaintext — only acceptable in tests.
        """
        postgres_dump = self.postgres_dumper.dump(dsn=postgres_dsn)
        objects_tar = self.object_snapshotter.snapshot()
        secrets_tar = self.secrets_snapshotter.snapshot()

        manifest = BundleManifest(
            firm_instance_id=str(firm_instance_id),
            postgres_schema_version=schema_version,
            counts=dict(counts or {}),
            created_at=datetime.now(UTC).isoformat(),
        )
        bundle = BackupBundle(
            manifest=manifest,
            postgres_dump=postgres_dump,
            objects_tar=objects_tar,
            secrets_tar=secrets_tar,
        )
        packed = bundle.pack()
        on_disk = aead_encrypt(packed) if aead_encrypt else packed

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(on_disk)

        logger.info(
            "backup_completed",
            extra={
                "context": {
                    "firm_instance_id": str(firm_instance_id),
                    "path": str(output_path),
                    "byte_size": len(on_disk),
                    "encrypted": aead_encrypt is not None,
                }
            },
        )
        return BackupResult(
            bundle_path=output_path,
            byte_size=len(on_disk),
            manifest=bundle.manifest,
        )


class RestoreRunner:
    """Decrypt + verify + restore. Refuses to write on any mismatch."""

    def __init__(
        self,
        *,
        object_restorer: ObjectTreeSnapshotter,
        secrets_restorer: SecretsSnapshotter,
    ) -> None:
        self.object_restorer = object_restorer
        self.secrets_restorer = secrets_restorer

    def run(
        self,
        *,
        bundle_path: Path,
        aead_decrypt: Callable[[bytes], bytes] | None = None,
        postgres_restore_cmd: Callable[[bytes], None] | None = None,
    ) -> BundleManifest:
        """Restore from ``bundle_path``.

        ``aead_decrypt`` is the inverse of BackupRunner's encrypt.
        ``postgres_restore_cmd`` is the callable that accepts the raw
        pg_dump bytes and drives ``pg_restore`` against the live DB.
        Tests use fakes for both.
        """
        raw = bundle_path.read_bytes()
        plain = aead_decrypt(raw) if aead_decrypt else raw

        try:
            bundle = BackupBundle.unpack(plain)
        except ValueError as e:
            raise RestoreError(f"bundle unpack failed: {e}") from e

        # Order matters: secrets first (so KMS is available), then
        # postgres (so audit_log_entry can chain), then objects.
        self.secrets_restorer.restore(bundle.secrets_tar)
        if postgres_restore_cmd is not None:
            postgres_restore_cmd(bundle.postgres_dump)
        self.object_restorer.restore(bundle.objects_tar)

        logger.info(
            "restore_completed",
            extra={
                "context": {
                    "firm_instance_id": bundle.manifest.firm_instance_id,
                    "created_at": bundle.manifest.created_at,
                    "counts": bundle.manifest.counts,
                }
            },
        )
        return bundle.manifest
