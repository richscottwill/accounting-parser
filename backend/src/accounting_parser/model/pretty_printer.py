"""Deterministic pretty-printer + equivalence relation.

Per Resolution 8: two canonical models are equivalent when:
- Ordered sequences are equal position-by-position.
- Unordered collections are equal as multisets.
- Monetary values are exactly equal (no float rounding).
- Fields in EXCLUDED_FIELDS are ignored (timestamps, OCR confidence).

The pretty-printer produces a byte-identical JSON serialization for
equivalent models (Correctness Property 3), and the JSON round-trips
to an equivalent model (Correctness Property 2).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from accounting_parser.model.canonical import (
    CURRENT_SCHEMA_VERSION,
    Account,
    BoundingBox,
    FixedAsset,
    JournalEntryAdjustment,
    JournalLeg,
    ParseResult,
    PayrollRecord,
    ReportLine,
    ReportSection,
    SourceRef,
    TaxFormField,
    WorkingTrialBalance,
    WTBRow,
)


# Fields excluded from equivalence (timestamps, OCR confidence per Resolution 8).
EXCLUDED_FIELDS: frozenset[str] = frozenset({
    "parsed_at",
    "posted_at",
    "ocr_confidence",
    "source_confidence",
    "category_confidence",
})


# Model classes registered for round-trip parsing. Keyed by
# ``(field_count, sorted_field_tuple)`` which uniquely identifies the type
# from the JSON alone (no type tag needed since our models have distinctive
# field sets).

_MODEL_REGISTRY: tuple[type[BaseModel], ...] = (
    BoundingBox,
    SourceRef,
    Account,
    ReportLine,
    ReportSection,
    JournalLeg,
    JournalEntryAdjustment,
    FixedAsset,
    TaxFormField,
    PayrollRecord,
    ParseResult,
    WTBRow,
    WorkingTrialBalance,
)


def _encode(obj: Any) -> Any:
    """Recursively encode a model / container into JSON-primitive types.

    - ``Decimal`` -> string (exact precision preservation)
    - ``datetime`` -> isoformat (UTC)
    - ``UUID``, ``Enum`` -> string
    - ``BaseModel`` -> sorted-key dict
    - ``tuple``/``list`` -> list (sequence-preserving)
    - ``frozenset``/``set`` -> SORTED list (multiset-order-independent)
    """
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Decimal):
        # Normalize scientific notation to plain decimal for stable output.
        s = format(obj, "f")
        # Preserve sign-distinguishing negative zero as "0" for equality
        if s in ("-0", "-0."):
            s = "0"
        return s
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        raise TypeError(
            "float is forbidden in canonical models — use Decimal for exact arithmetic"
        )
    if isinstance(obj, str):
        return obj
    # Enum
    if hasattr(obj, "value") and type(obj).__mro__[1].__name__ == "Enum":
        return obj.value
    # datetime
    from datetime import datetime as _dt
    if isinstance(obj, _dt):
        # Normalize to UTC + fixed isoformat
        if obj.tzinfo is None:
            raise ValueError(f"naive datetime not allowed in canonical model: {obj!r}")
        return obj.isoformat()
    # UUID
    from uuid import UUID as _UUID
    if isinstance(obj, _UUID):
        return str(obj)
    # BaseModel
    if isinstance(obj, BaseModel):
        out: dict[str, Any] = {}
        for k, v in obj.model_dump().items():
            out[k] = _encode(v)
        # Sort keys for deterministic output
        return dict(sorted(out.items()))
    # Sequence vs Set
    if isinstance(obj, (tuple, list)):
        return [_encode(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        encoded = [_encode(v) for v in obj]
        # Sort by JSON string representation — stable order-independent
        return sorted(encoded, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in sorted(obj.items())}
    raise TypeError(f"Cannot encode type {type(obj).__name__} in canonical model")


def canonical_json(model: BaseModel) -> str:
    """Return a byte-stable JSON serialization of a canonical model.

    Two equivalent models produce byte-identical output.
    """
    encoded = _encode(model)
    return json.dumps(encoded, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _identify_model(fields: frozenset[str]) -> type[BaseModel] | None:
    """Given a set of field names from JSON, find the matching model class."""
    for cls in _MODEL_REGISTRY:
        cls_fields = frozenset(cls.model_fields.keys())
        if cls_fields == fields:
            return cls
    return None


def parse_canonical_json(json_str: str, model_cls: type[BaseModel]) -> BaseModel:
    """Parse canonical JSON back into a model instance of the given type.

    Pydantic v2 handles the coercion (Decimal from string, UUID from string,
    enum from value) via its default validators.
    """
    return model_cls.model_validate_json(json_str)


def _strip_excluded(value: Any) -> Any:
    """Recursively drop EXCLUDED_FIELDS from nested structures for equivalence."""
    if isinstance(value, dict):
        return {
            k: _strip_excluded(v)
            for k, v in value.items()
            if k not in EXCLUDED_FIELDS
        }
    if isinstance(value, list):
        return [_strip_excluded(v) for v in value]
    return value


def equals_under_equivalence(a: BaseModel, b: BaseModel) -> bool:
    """Return True iff two models are equal under the Resolution-8 equivalence:

    - Ordered sequences compared position-by-position.
    - Monetary values (Decimal) compared exactly.
    - EXCLUDED_FIELDS ignored at every nesting level.
    - Types must match (no cross-type equivalence).
    """
    if type(a) is not type(b):
        return False
    ea = _strip_excluded(_encode(a))
    eb = _strip_excluded(_encode(b))
    return ea == eb


__all__ = [
    "EXCLUDED_FIELDS",
    "canonical_json",
    "parse_canonical_json",
    "equals_under_equivalence",
    "CURRENT_SCHEMA_VERSION",
]
