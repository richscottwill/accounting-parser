"""SelfHostedOCRAdapter — Tesseract + DocTR.

Shipped as the default OCR adapter for the self-hosted fork (R29.1).
Works without any external credentials; the installer bundles the
models so the firm doesn't need a separate setup step.

### Why both Tesseract and DocTR

DocTR is good at detecting document structure — it finds the
bounding boxes for each field on a tax form. Tesseract is good at
character recognition inside a known box. Composing them gives us:

1. DocTR → "on this W-2 the 'Wages, tips, other compensation' field
   is the box at x=120, y=340, w=180, h=28."
2. Tesseract → "the text inside that box reads '75,342.18' with
   character confidence 0.93."

Per-field confidence = DocTR box confidence × Tesseract character
confidence. Combined scores drop fast when either signal is weak,
which is the right behavior for tax documents where a missed box
matters more than a low-confidence word that human review can catch.

### Model loading

Models load lazily on first ``extract_page`` call. This avoids
paying the startup cost in contexts that don't actually OCR — for
example, the parse-only test suite — while still meeting the
parent R29.4 runtime target (≤ 10s for a single-page W-2 on
reference hardware) once the models are warm.

### Production vs tests

In tests we inject a fake adapter. The real Tesseract/DocTR imports
are deferred into the ``extract_page`` method so tests that never
touch OCR don't pay the deps import cost.
"""

from __future__ import annotations

import logging
from typing import Any

from accounting_parser.ocr.adapter import BoundingBox, ExtractedField, OCRAdapter, OCRResult

logger = logging.getLogger(__name__)


class SelfHostedOCRAdapter(OCRAdapter):
    """Tesseract + DocTR adapter.

    Stateful in that models load once per instance and are reused.
    Thread-safe because both underlying libraries release the GIL
    for their native kernels; construct a single instance per
    process and share across request threads.
    """

    provider: str = "tesseract_doctr"

    def __init__(
        self,
        *,
        tesseract_lang: str = "eng",
        doctr_model: str = "db_resnet50",
    ) -> None:
        self.tesseract_lang = tesseract_lang
        self.doctr_model_name = doctr_model
        self._doctr_predictor: Any | None = None
        self._tesseract: Any | None = None

    def extract_page(self, image_bytes: bytes, page_number: int) -> OCRResult:
        """Run DocTR then Tesseract on the page image.

        Returns an empty result on failure rather than raising —
        the gate logic treats that as "require Preparer confirmation"
        which is the correct fallback for an unreadable scan.
        """
        if not image_bytes:
            return OCRResult(
                page_number=page_number,
                fields=(),
                page_confidence=0.0,
                provider=self.provider,
            )
        try:
            return self._extract_with_models(image_bytes, page_number)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "ocr_page_extraction_failed",
                extra={
                    "page_number": page_number,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
            )
            return OCRResult(
                page_number=page_number,
                fields=(),
                page_confidence=0.0,
                provider=self.provider,
            )

    def _extract_with_models(self, image_bytes: bytes, page_number: int) -> OCRResult:
        """Real extraction path; separated so ``extract_page`` can
        handle the exception taxonomy uniformly."""
        # Import lazily — tests using fake adapters don't need
        # Tesseract + DocTR installed.
        doctr = self._get_doctr()
        pytesseract = self._get_tesseract()

        from io import BytesIO

        from PIL import Image  # type: ignore[import-not-found]

        image = Image.open(BytesIO(image_bytes))

        # DocTR wants RGB numpy arrays. PIL gives us that via asarray.
        import numpy as np  # type: ignore[import-not-found]

        np_image = np.asarray(image.convert("RGB"))

        # DocTR detection: find text regions + their confidences.
        doctr_result = doctr([np_image])
        page = doctr_result.pages[0]

        fields: list[ExtractedField] = []
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    box = _geometry_to_box(word.geometry, image.size)
                    box_conf = float(word.confidence)
                    # Tesseract refinement over the single word box.
                    crop = image.crop((box.x, box.y, box.x + box.width, box.y + box.height))
                    tess_data = pytesseract.image_to_data(
                        crop,
                        lang=self.tesseract_lang,
                        output_type=pytesseract.Output.DICT,
                    )
                    text, char_conf = _extract_best_text(tess_data)
                    if not text:
                        continue
                    combined = box_conf * char_conf
                    fields.append(
                        ExtractedField(
                            label=text,  # self-hosted OCR doesn't know labels
                            value=text,
                            confidence=combined,
                            bounding_box=box,
                            raw_confidence={
                                "doctr_box": box_conf,
                                "tesseract_char": char_conf,
                            },
                        )
                    )

        avg_conf = sum(f.confidence for f in fields) / len(fields) if fields else 0.0
        return OCRResult(
            page_number=page_number,
            fields=tuple(fields),
            page_confidence=avg_conf,
            provider=self.provider,
        )

    def _get_doctr(self) -> Any:
        if self._doctr_predictor is not None:
            return self._doctr_predictor
        from doctr.models import ocr_predictor  # type: ignore[import-not-found]

        self._doctr_predictor = ocr_predictor(pretrained=True)
        return self._doctr_predictor

    def _get_tesseract(self) -> Any:
        if self._tesseract is not None:
            return self._tesseract
        import pytesseract  # type: ignore[import-not-found]

        self._tesseract = pytesseract
        return self._tesseract


def _geometry_to_box(
    geometry: tuple[tuple[float, float], tuple[float, float]],
    image_size: tuple[int, int],
) -> BoundingBox:
    """Convert DocTR's normalized ((x0, y0), (x1, y1)) to pixel box."""
    (x0, y0), (x1, y1) = geometry
    width, height = image_size
    return BoundingBox(
        x=int(x0 * width),
        y=int(y0 * height),
        width=int((x1 - x0) * width),
        height=int((y1 - y0) * height),
    )


def _extract_best_text(tess_data: dict[str, list]) -> tuple[str, float]:
    """Pull the highest-confidence word Tesseract reported.

    Tesseract's ``image_to_data`` returns parallel lists of text + conf.
    We pick the single best word in the crop — DocTR already gave us
    a word-level box, so we expect one dominant word here.
    """
    texts = tess_data.get("text", [])
    confs = tess_data.get("conf", [])
    best_text, best_conf = "", 0.0
    for text, conf_raw in zip(texts, confs, strict=False):
        if not text or not text.strip():
            continue
        try:
            conf = float(conf_raw) / 100.0
        except (TypeError, ValueError):
            continue
        if conf > best_conf:
            best_text, best_conf = text.strip(), conf
    return best_text, best_conf
