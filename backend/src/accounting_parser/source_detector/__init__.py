"""Source detection: fingerprint a document to its originating system.

Each ``SourceFormatAdapter`` contributes confidence signals; the detector
picks the highest-confidence adapter above ``UNKNOWN_THRESHOLD``.

Adapters are registered via ``REGISTERED_ADAPTERS`` — the spec calls for
``pyproject.toml`` entry points, which will be wired once we're ready
to support third-party plugins. At MVP the in-process registry is enough.
"""

from accounting_parser.source_detector.adapters import (
    HIGH_CONFIDENCE_FLOOR,
    UNKNOWN_THRESHOLD,
    BankStatementPDFAdapter,
    CCHEngagementTemplateAdapter,
    DetectionSignal,
    GenericFallbackAdapter,
    IRSFormPDFAdapter,
    NetSuiteAdapter,
    QuickBooksDesktopAdapter,
    QuickBooksOnlineAdapter,
    SageIntacctAdapter,
    SourceFormatAdapter,
    XeroAdapter,
)
from accounting_parser.source_detector.detector import (
    DetectionResult,
    detect_source,
    REGISTERED_ADAPTERS,
)

__all__ = [
    "REGISTERED_ADAPTERS",
    "DetectionResult",
    "DetectionSignal",
    "SourceFormatAdapter",
    "detect_source",
    "HIGH_CONFIDENCE_FLOOR",
    "UNKNOWN_THRESHOLD",
    # adapters
    "QuickBooksOnlineAdapter",
    "QuickBooksDesktopAdapter",
    "XeroAdapter",
    "NetSuiteAdapter",
    "SageIntacctAdapter",
    "CCHEngagementTemplateAdapter",
    "IRSFormPDFAdapter",
    "BankStatementPDFAdapter",
    "GenericFallbackAdapter",
]
