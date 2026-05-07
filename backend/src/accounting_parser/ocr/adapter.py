"""OCR adapter protocol + implementations.

Every OCR result carries per-field confidence in [0.0, 1.0] so the
downstream field-validation gate can decide what needs human review.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import boto3

from accounting_parser.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedField:
    name: str
    value: str
    confidence: float  # [0.0, 1.0]
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class OCRResult:
    engine: str
    engine_version: str
    pages: int
    fields: list[ExtractedField] = field(default_factory=list)


class OCRAdapter(Protocol):
    engine: str

    def analyze(self, content: bytes, *, filename: str) -> OCRResult: ...


class FakeOCR:
    """Deterministic OCR used in tests + CI.

    Reads a configured dict of ``{field_name: (value, confidence)}`` and
    returns it verbatim. Production code uses real Textract / Azure DI.
    """

    engine = "fake"

    def __init__(self, fields: dict[str, tuple[str, float]] | None = None):
        self._fields = fields or {}

    def analyze(self, content: bytes, *, filename: str) -> OCRResult:
        return OCRResult(
            engine=self.engine,
            engine_version="1.0",
            pages=1,
            fields=[
                ExtractedField(name=n, value=v, confidence=c, page=1)
                for n, (v, c) in self._fields.items()
            ],
        )


class TextractOCR:
    """AWS Textract adapter via boto3.

    Uses ``analyze_document`` with FORMS feature so field/value pairs
    come back structured. Per-field confidence is taken from the KEY
    block's Confidence attribute (0-100 → normalized to [0, 1]).
    """

    engine = "aws-textract"

    def __init__(self, settings: Settings):
        kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        self._client = boto3.client("textract", **kwargs)

    def analyze(self, content: bytes, *, filename: str) -> OCRResult:
        resp = self._client.analyze_document(
            Document={"Bytes": content}, FeatureTypes=["FORMS"]
        )
        fields: list[ExtractedField] = []
        blocks_by_id = {b["Id"]: b for b in resp.get("Blocks", [])}
        for block in resp.get("Blocks", []):
            if block.get("BlockType") != "KEY_VALUE_SET":
                continue
            if "KEY" not in block.get("EntityTypes", []):
                continue
            name = _extract_text(block, blocks_by_id, "CHILD")
            value_block_id = None
            for rel in block.get("Relationships", []):
                if rel.get("Type") == "VALUE":
                    value_block_id = rel["Ids"][0]
                    break
            if value_block_id is None:
                continue
            value_block = blocks_by_id.get(value_block_id, {})
            value = _extract_text(value_block, blocks_by_id, "CHILD")
            fields.append(
                ExtractedField(
                    name=name.strip(),
                    value=value.strip(),
                    confidence=min(block.get("Confidence", 0.0), 100.0) / 100.0,
                    page=block.get("Page", 1),
                )
            )
        return OCRResult(
            engine=self.engine,
            engine_version="textract-v1",
            pages=max((f.page or 1) for f in fields) if fields else 1,
            fields=fields,
        )


def _extract_text(block: dict, blocks_by_id: dict[str, dict], rel_type: str) -> str:
    """Concatenate WORD children from a block's relationships."""
    out: list[str] = []
    for rel in block.get("Relationships", []):
        if rel.get("Type") != rel_type:
            continue
        for child_id in rel.get("Ids", []):
            child = blocks_by_id.get(child_id, {})
            if child.get("BlockType") == "WORD":
                out.append(child.get("Text", ""))
    return " ".join(out)


def get_ocr(settings: Settings | None = None) -> OCRAdapter:
    settings = settings or get_settings()
    backend = settings.ocr_backend
    if backend == "aws-textract":
        return TextractOCR(settings)
    if backend == "fake":
        return FakeOCR()
    raise ValueError(f"Unknown ocr_backend: {backend!r}")
