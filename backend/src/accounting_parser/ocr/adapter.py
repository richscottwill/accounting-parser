"""OCRAdapter Protocol + DTOs.

The OCR adapter is invoked from the parser pipeline when text-native
extraction is insufficient for a page. Callers get ``OCRResult``
objects with per-field confidence; the field-validation gate
(``gate.py``) decides which fields require human confirmation
before downstream posting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Parent R4.11 threshold: a page with fewer than this many non-
# whitespace characters is considered "probably scanned" and routed
# to OCR. Tuned against the parent fixture corpus.
_OCR_MIN_NON_WHITESPACE_CHARS = 20


@dataclass(frozen=True)
class BoundingBox:
    """Pixel-space bounding box for a detected field.

    Coordinates are page-local. 0,0 is top-left. Used by the
    field-validation gate modal to highlight the source region
    when asking the Preparer to confirm.
    """

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ExtractedField:
    """One field extracted from a page.

    ``label`` is the human-readable field name (e.g., "Wages Box 1").
    ``value`` is the raw text the OCR read. ``confidence`` is the
    per-field confidence in [0.0, 1.0] — the combined DocTR box
    confidence and Tesseract character confidence for self-hosted OCR.

    ``raw_confidence`` is the provider-specific raw score, kept so
    audit trails can reconstruct why a field was or wasn't gated.
    """

    label: str
    value: str
    confidence: float
    bounding_box: BoundingBox
    raw_confidence: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class OCRResult:
    """Output of one OCR pass against a page image."""

    page_number: int
    fields: tuple[ExtractedField, ...]
    # Provider-reported page-level confidence. Useful for detecting
    # "this page was probably blurry/rotated/damaged" at a glance.
    page_confidence: float
    # Which adapter produced this result — stored so we can audit
    # drift if a firm switches between Tesseract and Textract mid-
    # engagement.
    provider: str


def probe_requires_ocr(page_text: str) -> bool:
    """Return True if a page's text layer is too sparse to trust.

    Threshold: < 20 non-whitespace characters per parent R4.11. A
    typical scanned W-2 has zero text in the extracted layer; a
    text-native PDF form has hundreds. The threshold is deliberately
    loose — false positives (routing a sparse-but-valid page to OCR)
    cost OCR runtime; false negatives (trusting a garbage text
    layer) cost parsing correctness.
    """
    return (
        len(page_text.replace(" ", "").replace("\n", "").replace("\t", ""))
        < _OCR_MIN_NON_WHITESPACE_CHARS
    )


class OCRAdapter(Protocol):
    """Contract every OCR backend satisfies."""

    provider: str

    def extract_page(self, image_bytes: bytes, page_number: int) -> OCRResult:
        """Run OCR on a single page image.

        ``image_bytes`` is the raw PNG/JPEG/TIFF bytes. Adapter is
        responsible for any format conversion its underlying library
        requires. Returns an ``OCRResult`` with all detected fields
        plus the provider-reported confidence on each.

        Must never raise on empty / corrupt input — return an empty
        ``OCRResult`` with ``page_confidence=0.0``. Caller's gate
        logic treats 0-confidence as "require confirmation".
        """
        ...
