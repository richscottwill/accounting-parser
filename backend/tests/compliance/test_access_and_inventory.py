"""Access review + data inventory generators."""

from __future__ import annotations

from datetime import UTC, datetime

from accounting_parser.compliance.access_review import AccessReviewEntry, generate_access_review
from accounting_parser.compliance.data_inventory import DataInventoryEntry, generate_data_inventory


def test_access_review_csv_sorted_by_email_then_recency():
    entries = [
        AccessReviewEntry(
            user_id="u1",
            user_email="alice@x.com",
            user_role="preparer",
            client_id="c1",
            client_name="Acme",
            first_access=datetime(2026, 5, 1, tzinfo=UTC),
            last_access=datetime(2026, 5, 3, tzinfo=UTC),
            access_count=4,
        ),
        AccessReviewEntry(
            user_id="u1",
            user_email="alice@x.com",
            user_role="preparer",
            client_id="c2",
            client_name="Beta",
            first_access=datetime(2026, 5, 2, tzinfo=UTC),
            last_access=datetime(2026, 5, 9, tzinfo=UTC),  # more recent
            access_count=2,
        ),
        AccessReviewEntry(
            user_id="u2",
            user_email="zara@x.com",
            user_role="reviewer",
            client_id="c1",
            client_name="Acme",
            first_access=datetime(2026, 5, 5, tzinfo=UTC),
            last_access=datetime(2026, 5, 6, tzinfo=UTC),
            access_count=1,
        ),
    ]
    csv_bytes = generate_access_review(entries)
    lines = csv_bytes.decode("utf-8").strip().splitlines()
    assert lines[0].startswith("user_id,user_email,user_role,")
    # Alice entries before Zara; within Alice, most recent first.
    assert "alice@x.com" in lines[1]
    assert "Beta" in lines[1]  # last_access 2026-05-09
    assert "Acme" in lines[2]  # last_access 2026-05-03
    assert "zara@x.com" in lines[3]


def test_access_review_empty_entries_yields_header_only():
    csv_bytes = generate_access_review([])
    text = csv_bytes.decode("utf-8")
    assert text.strip().count("\n") == 0  # just the header line


def test_data_inventory_csv_sorted_by_client_then_upload_time():
    entries = [
        DataInventoryEntry(
            client_id="c2",
            client_name="Beta Co",
            document_id="d2",
            filename="b.pdf",
            content_type="application/pdf",
            byte_size=2048,
            sha256_hex="b" * 64,
            uploaded_at=datetime(2026, 5, 1, tzinfo=UTC),
            engagement_id="e2",
            retention_state="active",
        ),
        DataInventoryEntry(
            client_id="c1",
            client_name="Acme",
            document_id="d1",
            filename="a.pdf",
            content_type="application/pdf",
            byte_size=1024,
            sha256_hex="a" * 64,
            uploaded_at=datetime(2026, 5, 2, tzinfo=UTC),
            engagement_id="e1",
            retention_state="active",
        ),
        DataInventoryEntry(
            client_id="c1",
            client_name="Acme",
            document_id="d3",
            filename="c.pdf",
            content_type="application/pdf",
            byte_size=512,
            sha256_hex="c" * 64,
            uploaded_at=datetime(2026, 5, 3, tzinfo=UTC),
            engagement_id="e1",
            retention_state="past_retention",
        ),
    ]
    csv_bytes = generate_data_inventory(entries)
    lines = csv_bytes.decode("utf-8").strip().splitlines()
    # Client alpha sort: Acme (c1) before Beta (c2).
    assert "Acme" in lines[1]
    assert "Acme" in lines[2]
    assert "Beta" in lines[3]
    # Within Acme, uploaded_at ASC.
    assert "a.pdf" in lines[1]
    assert "c.pdf" in lines[2]
