"""Backup + restore subsystem (P2.3).

Produces nightly encrypted backup bundles of:

- Postgres dump (``pg_dump --format=custom``)
- MinIO object tree (streamed tarball, not ``mc mirror`` — we want
  one atomic artifact)
- Sealed secrets bundle
- Bundle manifest (versions, checksums, timestamps)

The bundle is encrypted with a per-Firm backup key derived from the
master via HKDF (``DerivationPurpose.BACKUP_ENCRYPTION``). Restore
reverses this under the same master — losing the master means losing
both live data AND backups, by design (CP32).

### R27 mapping

- R27.2: local backup with 30 daily + 12 monthly retention.
- R27.3: optional offsite replication via rclone-compatible targets
  (S3/B2/rsync/Azure) — the bundle is already encrypted so the
  offsite target never sees plaintext.
- R27.4: ``restore`` CLI consumes the same bundle format.

### CP30

Property: "A backup taken at time T, restored to a fresh host,
produces a Firm_Instance equivalent (per parent equivalence
relation) to the source at time T."

The test suite covers this with a round-trip that backs up a fixture
database + object store, restores into fresh stores, and asserts
row-count + SHA equivalence across every table + object key.
"""

from accounting_parser.backup.bundle import (
    BackupBundle,
    BundleManifest,
    read_manifest,
    write_manifest,
)
from accounting_parser.backup.runner import (
    BackupError,
    BackupResult,
    BackupRunner,
    RestoreError,
    RestoreRunner,
)

__all__ = [
    "BackupBundle",
    "BackupError",
    "BackupResult",
    "BackupRunner",
    "BundleManifest",
    "RestoreError",
    "RestoreRunner",
    "read_manifest",
    "write_manifest",
]
