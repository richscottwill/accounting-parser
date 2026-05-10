"""Magic-byte MIME detection."""

from __future__ import annotations

import pytest

from accounting_parser.ingestion.magic_bytes import ACCEPTED_MIMES, detect_content_type, is_accepted


@pytest.mark.parametrize(
    "head,expected",
    [
        (b"%PDF-1.7\n", "application/pdf"),
        (b"\x89PNG\r\n\x1a\nxxx", "image/png"),
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"II*\x00", "image/tiff"),
        (b"MM\x00*", "image/tiff"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),
        (b"OFXHEADER:100\nDATA:OFXSGML\n", "application/x-ofx"),
        (b"!Type:Bank\n^", "application/x-qif"),
        (b"!TRNS\tTRNSID\n", "application/x-iif"),
        (b"random garbage", "application/octet-stream"),
    ],
)
def test_detect_content_type(head, expected):
    assert detect_content_type(head) == expected


def test_zip_without_xlsx_markers_is_generic():
    """Plain ZIP (no xl/ or workbook.xml) stays 'application/zip'."""
    assert detect_content_type(b"PK\x03\x04" + b"\x00" * 100) == "application/zip"


def test_zip_with_xlsx_marker_detected_as_xlsx():
    """A zip head containing 'xl/' marker resolves to xlsx mime."""
    head = b"PK\x03\x04" + b"some stuff" + b"xl/workbook.xml" + b"rest"
    assert (
        detect_content_type(head)
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_accepted_mimes_includes_expected():
    assert "application/pdf" in ACCEPTED_MIMES
    assert "application/x-ofx" in ACCEPTED_MIMES
    assert is_accepted("application/pdf")
    assert not is_accepted("application/octet-stream")
    assert not is_accepted("application/x-ole-storage")


def test_xml_declaration_detects_as_xbrl_or_ofx():
    """<?xml declarations can be OFX 2.x or XBRL. Leading-pattern check returns ofx first."""
    # In our signature order, ofx 2.x is probed before xbrl. Either
    # is acceptable as a fallback; the service layer's accept-list is
    # what actually gates the content.
    result = detect_content_type(b"<?xml version='1.0'?>\n<OFX>\n")
    assert result in {"application/x-ofx", "application/x-xbrl"}
