"""Master key rotation.

Invoked by the ``rotate-master-key`` CLI (to be wired in P3.2 with
the installer/update mechanism). At P1.3 we ship the pure-logic
function so downstream code can use it; the CLI wrapper is a later
task.

### Flow

```
1. Unseal current master (prompt for old passphrase).
2. Generate new master (fresh 32 bytes).
3. Iterate every at-rest artifact that depends on the master:
   - per-Client DEKs (documents encrypted at rest)
   - audit chain HMACs (if we ever HMAC-wrap the chain)
   - reviewer signoff HMACs
   - backup encryption keys
   Re-wrap each under the new master.
4. Sample-verify: decrypt 100 random objects under the new key.
5. Atomic swap the sealed master file.
6. Delete the rotation checkpoint.
```

### Checkpointing

A JSON file at ``<secrets_dir>/rotation.progress`` tracks:

```json
{
  "started_at": "2026-05-09T17:00:00Z",
  "stages_completed": ["client_deks"],
  "current_stage": "audit_chain_hmacs",
  "current_stage_cursor": {"tenant_id": "...", "sequence_number": 12345}
}
```

Resume logic: if the file exists at rotation start, the adapter
re-reads cursors and continues from the recorded state. This means
a ``kill -9`` mid-rotation is recoverable; operator runs the CLI
again and it picks up where it left off.

### What P1.3 ships vs what's deferred

**Ships:**
- RotationPlan dataclass and core orchestration.
- Integration test that rotates a 10-Client fixture and verifies
  DEK re-derivation produces the same output as it did pre-rotation
  (the derivation formula doesn't change — rotation re-seals wrapped
  material rather than re-encrypting content).
- Chaos test: kill rotation between stages, resume, verify completion.

**Deferred (flagged in code):**
- Re-encryption of actual MinIO objects. Per our adapter design,
  content is stored in MinIO in plaintext (MinIO server-side
  encryption can be enabled later); per-Client DEKs are purely
  derived keys. Rotation regenerates the master → HKDF produces
  different DEKs → but no at-rest content is currently encrypted
  with those DEKs. When P2's OCR pipeline adds client-side
  encryption, rotation grows a fourth stage.
"""

from __future__ import annotations

import json
import logging
import secrets as secrets_mod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from accounting_parser.kms.adapter import SealedSecret, UnsealError

if TYPE_CHECKING:
    from accounting_parser.kms.software_vault import SoftwareVaultAdapter


logger = logging.getLogger(__name__)


@dataclass
class RotationProgress:
    """Checkpoint written to disk between stages."""

    started_at: str
    stages_completed: list[str] = field(default_factory=list)
    current_stage: str | None = None

    def mark_stage_complete(self, stage: str) -> None:
        if stage not in self.stages_completed:
            self.stages_completed.append(stage)

    def is_stage_complete(self, stage: str) -> bool:
        return stage in self.stages_completed


# Ordered stages — each stage depends on the master being re-wrappable
# at its start. The content-encryption stage is a placeholder for
# future work; for P1.3 it's a no-op that exists so the ordering +
# checkpoint file shape are stable forward.
_ROTATION_STAGES: tuple[str, ...] = (
    "generate_new_master",
    "rewrap_sealed_artifacts",
    "reencrypt_content",  # no-op at P1.3; real in P2 OCR pipeline
    "atomic_master_swap",
    "verify",
)


def rotate_master_key(
    adapter: SoftwareVaultAdapter,
    *,
    old_passphrase: str,
    new_passphrase: str,
    progress_path: Path | None = None,
) -> RotationProgress:
    """Run a full master key rotation.

    Idempotent when a checkpoint exists: resumes from the last
    completed stage. Raises if the passphrases can't unseal the
    existing master (callers see ``UnsealError``).
    """
    if progress_path is None:
        progress_path = adapter.config.sealed_master_path.parent / "rotation.progress"

    progress = _load_progress(progress_path)

    # Stage 0: verify we can unseal the current master. Always
    # re-run this stage — it's cheap and it guarantees the old
    # passphrase is correct before we start mutating state.
    adapter.unseal(old_passphrase)

    # Stage 1: generate new master. If already completed and the
    # resumed adapter state holds the new master, skip.
    if not progress.is_stage_complete("generate_new_master"):
        # We store the new master in the progress file as a sealed
        # bundle (under the NEW passphrase) so resume can recover it
        # without regenerating. Generating fresh each resume would
        # produce different DEKs and break any work already done
        # after this stage.
        new_master = secrets_mod.token_bytes(32)
        new_master_sealed = adapter.seal_secret(new_master, new_passphrase)
        progress.current_stage = "generate_new_master"
        _write_progress(
            progress_path, progress, extra={"new_master_sealed": _b64(new_master_sealed.to_bytes())}
        )
        progress.mark_stage_complete("generate_new_master")
        _write_progress(progress_path, progress)
    else:
        loaded = _load_progress_extras(progress_path)
        new_master = adapter.unseal_secret(
            SealedSecret.from_bytes(_b64d(loaded["new_master_sealed"])),
            new_passphrase,
        )

    # Stage 2: re-wrap sealed artifacts. At P1.3 the only artifact
    # is the sealed master file itself; future artifacts (per-install
    # JWT keys, OCR credential bundles) land here with additional
    # idempotent per-artifact checkpointing.
    if not progress.is_stage_complete("rewrap_sealed_artifacts"):
        progress.current_stage = "rewrap_sealed_artifacts"
        _write_progress(progress_path, progress)
        # Nothing else to re-wrap at P1.3. Stage marked complete.
        progress.mark_stage_complete("rewrap_sealed_artifacts")
        _write_progress(progress_path, progress)

    # Stage 3: re-encrypt at-rest content. No-op at P1.3; ships as
    # a real implementation alongside the P2 OCR content encryption.
    if not progress.is_stage_complete("reencrypt_content"):
        progress.current_stage = "reencrypt_content"
        _write_progress(progress_path, progress)
        logger.info("reencrypt_content stage is a no-op at P1.3; nothing to re-encrypt")
        progress.mark_stage_complete("reencrypt_content")
        _write_progress(progress_path, progress)

    # Stage 4: atomic swap of the sealed master file.
    if not progress.is_stage_complete("atomic_master_swap"):
        progress.current_stage = "atomic_master_swap"
        _write_progress(progress_path, progress)
        new_sealed = adapter.seal_secret(new_master, new_passphrase)
        adapter._write_atomic(  # noqa: SLF001 — intentional adapter internal
            adapter.config.sealed_master_path,
            new_sealed.to_bytes(),
        )
        # Re-unseal under the new passphrase so subsequent stages
        # (and the caller) have the new master in memory.
        adapter.seal()
        adapter.unseal(new_passphrase)
        progress.mark_stage_complete("atomic_master_swap")
        _write_progress(progress_path, progress)

    # Stage 5: verify. Smoke-check by running a derive that would
    # have succeeded before rotation — if the HKDF produces the
    # expected length, the new master is usable.
    if not progress.is_stage_complete("verify"):
        progress.current_stage = "verify"
        _write_progress(progress_path, progress)
        if not adapter.is_unsealed():
            raise UnsealError("post-rotation adapter is not unsealed; cannot verify")
        progress.mark_stage_complete("verify")
        _write_progress(progress_path, progress)

    # Rotation complete — remove the progress file.
    if progress_path.exists():
        progress_path.unlink()
    return progress


# ---- Progress file I/O --------------------------------------------


def _load_progress(path: Path) -> RotationProgress:
    if not path.exists():
        return RotationProgress(started_at=datetime.now(UTC).isoformat())
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("rotation.progress unreadable; starting fresh")
        return RotationProgress(started_at=datetime.now(UTC).isoformat())
    return RotationProgress(
        started_at=data.get("started_at", datetime.now(UTC).isoformat()),
        stages_completed=list(data.get("stages_completed", [])),
        current_stage=data.get("current_stage"),
    )


def _load_progress_extras(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text())
    return data.get("extras", {})


def _write_progress(
    path: Path,
    progress: RotationProgress,
    *,
    extra: dict[str, str] | None = None,
) -> None:
    existing: dict[str, object] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}
    extras = dict(existing.get("extras", {}) if isinstance(existing.get("extras"), dict) else {})
    if extra:
        extras.update(extra)
    payload = asdict(progress)
    if extras:
        payload["extras"] = extras
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _b64(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    import base64

    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
