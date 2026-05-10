"""Access review report — R31.3.

For every User + every Client they accessed in a window, emit a
row with: user email, role, client name, first access, last access,
access count.

Data source: ``audit_log_entry`` filtered by ``action LIKE
'document.%'`` and joined against ``app_user`` + ``client``. The
generator takes already-fetched rows rather than the DB session so
it's testable and so routes can batch the fetch with their own
pagination rules.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccessReviewEntry:
    """One row of the access review report."""

    user_id: str
    user_email: str
    user_role: str
    client_id: str
    client_name: str
    first_access: datetime
    last_access: datetime
    access_count: int


def generate_access_review(entries: list[AccessReviewEntry]) -> bytes:
    """Render a CSV for the given entries.

    Sort order: user_email, then last_access DESC so each user's
    most recent activity surfaces at the top of their block. CSV is
    preferred over JSON here — access review is typically opened in
    Excel by the firm principal + legal counsel.
    """
    sorted_entries = sorted(
        entries,
        key=lambda e: (e.user_email, -e.last_access.timestamp()),
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "user_id",
            "user_email",
            "user_role",
            "client_id",
            "client_name",
            "first_access",
            "last_access",
            "access_count",
        ]
    )
    for e in sorted_entries:
        writer.writerow(
            [
                e.user_id,
                e.user_email,
                e.user_role,
                e.client_id,
                e.client_name,
                e.first_access.isoformat(),
                e.last_access.isoformat(),
                e.access_count,
            ]
        )
    return buf.getvalue().encode("utf-8")
