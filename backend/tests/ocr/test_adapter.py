"""OCRAdapter protocol + probe tests."""

from __future__ import annotations

import pytest

from accounting_parser.ocr.adapter import OCRResult, probe_requires_ocr
from accounting_parser.ocr.self_hosted import SelfHostedOCRAdapter


def test_self_hosted_adapter_conforms_to_protocol():
    adapter = SelfHostedOCRAdapter()
    for attr in ("provider", "extract_page"):
        assert hasattr(adapter, attr)


def test_self_hosted_adapter_provider_tag():
    assert SelfHostedOCRAdapter.provider == "tesseract_doctr"


def test_extract_page_on_empty_bytes_returns_empty_result():
    """No extraction possible → empty result with 0 confidence, no raise."""
    adapter = SelfHostedOCRAdapter()
    result = adapter.extract_page(b"", page_number=1)
    assert isinstance(result, OCRResult)
    assert result.fields == ()
    assert result.page_confidence == 0.0
    assert result.provider == "tesseract_doctr"


def test_extract_page_on_invalid_bytes_returns_empty_not_raises():
    """Malformed image bytes: failure surfaces as empty result, logged."""
    adapter = SelfHostedOCRAdapter()
    result = adapter.extract_page(b"not an image", page_number=1)
    assert result.fields == ()
    assert result.page_confidence == 0.0


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", True),
        ("   ", True),
        ("abc", True),  # < 20 non-whitespace chars
        ("abcdefghij" * 2, False),  # exactly 20 — threshold is strict <
        ("abcdefghijklmnopqrstuvwxyz", False),
        ("page with many characters and several words of text", False),
    ],
)
def test_probe_requires_ocr(text: str, expected: bool):
    assert probe_requires_ocr(text) is expected
