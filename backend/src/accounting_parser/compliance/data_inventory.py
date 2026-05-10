"""Data inventory report — R31.4.

For every Document in the firm, render: client, filename, content
type, byte size, sha256, ingest date, retention clock state.
Output: CSV optimized for legal discovery review + destruction
scheduling.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DataInventoryEntry:
    """One row of the data inventory report."""

    client_id: str
    client_name: str
    document_id: str
    filename: str
    content_type: str
    byte_size: int
    sha256_hex: str
    uploaded_at: datetime
    engagement_id: str
    retention_state: str  # "active" | "past_retention" | "destroyed"


def generate_data_inventory(entries: list[DataInventoryEntry]) -> bytes:
    """Render CSV of the inventory."""
    sorted_entries = sorted(
        entries,
        key=lambda e: (e.client_name, e.uploaded_at.timestamp()),
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "client_id",
            "client_name",
            "document_id",
            "filename",
            "content_type",
            "byte_size",
            "sha256_hex",
            "uploaded_at",
            "engagement_id",
            "retention_state",
        ]
    )
    for e in sorted_entries:
        writer.writerow(
            [
                e.client_id,
                e.client_name,
                e.document_id,
                e.filename,
                e.content_type,
                e.byte_size,
                e.sha256_hex,
                e.uploaded_at.isoformat(),
                e.engagement_id,
                e.retention_state,
            ]
        )
    return buf.getvalue().encode("utf-8")
