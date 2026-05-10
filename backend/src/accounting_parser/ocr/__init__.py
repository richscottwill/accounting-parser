"""OCR subsystem (self-hosted fork, Phase 2 P2.1).

Absorbs parent Task 9 with self-hosted Tesseract + DocTR as the
default adapter (R29.1). External cloud providers (Textract, Azure
Document Intelligence) are opt-in via firm-supplied credentials (R29.2).

### Contract

``OCRAdapter`` Protocol with methods:

- ``extract_page(image_bytes, page_num)`` — run OCR on a single page
  image and return fields with per-field confidence.
- ``probe_requires_ocr(page_text)`` — return True if a PDF page's
  extracted text is too sparse to trust (< 20 non-whitespace chars
  per R4.11).

### Self-hosted adapter

``SelfHostedOCRAdapter`` wraps Tesseract (character recognition) +
DocTR (form structure detection). Confidence per field is computed
as DocTR box confidence × Tesseract character confidence.

### Field-validation gate

``R29.3`` raises the gate threshold from parent R4.24's 0.95 to
**0.98** for self-hosted OCR output — Tesseract is materially less
accurate than Textract on tax forms so more confirmation events are
correct, not a bug. ``FieldValidationGate`` emits a gate event for
every field with confidence < threshold; nothing posts to the export
layer until every flagged field is Preparer-confirmed.
"""

from accounting_parser.ocr.adapter import ExtractedField, OCRAdapter, OCRResult, probe_requires_ocr
from accounting_parser.ocr.gate import FieldValidationGate, GateEvent, GateResolution
from accounting_parser.ocr.self_hosted import SelfHostedOCRAdapter

__all__ = [
    "ExtractedField",
    "FieldValidationGate",
    "GateEvent",
    "GateResolution",
    "OCRAdapter",
    "OCRResult",
    "SelfHostedOCRAdapter",
    "probe_requires_ocr",
]
