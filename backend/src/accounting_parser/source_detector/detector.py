"""Source detector: run every registered adapter and pick the best match."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from accounting_parser.source_detector.adapters import (
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


# In-process registry (entry-point discovery is a post-MVP refinement).
REGISTERED_ADAPTERS: tuple[SourceFormatAdapter, ...] = (
    QuickBooksOnlineAdapter(),
    QuickBooksDesktopAdapter(),
    XeroAdapter(),
    NetSuiteAdapter(),
    SageIntacctAdapter(),
    CCHEngagementTemplateAdapter(),
    IRSFormPDFAdapter(),
    BankStatementPDFAdapter(),
    GenericFallbackAdapter(),
)


@dataclass(frozen=True)
class DetectionResult:
    source_system: str  # "unknown" when below threshold
    confidence: float
    signals: tuple[str, ...]
    # All non-null candidate signals in descending confidence.
    candidates: tuple[DetectionSignal, ...]


def detect_source(
    path: Path, *, adapters: tuple[SourceFormatAdapter, ...] | None = None,
) -> DetectionResult:
    """Classify the document at ``path`` as one of the known source systems."""
    adapters = adapters if adapters is not None else REGISTERED_ADAPTERS
    candidates: list[DetectionSignal] = []
    for adapter in adapters:
        try:
            sig = adapter.detect(path)
        except Exception:
            sig = None
        if sig is not None:
            candidates.append(sig)
    # Exclude the generic fallback from the "best" pick unless nothing else
    # cleared the threshold.
    non_generic = [c for c in candidates if c.source_system != "generic"]
    best = max(non_generic, key=lambda c: c.confidence, default=None)
    if best is None or best.confidence < UNKNOWN_THRESHOLD:
        # Fall back to generic if it's present, else Unknown.
        generic = next((c for c in candidates if c.source_system == "generic"), None)
        if generic is not None and best is None:
            return DetectionResult(
                source_system="unknown",
                confidence=generic.confidence,
                signals=generic.signals,
                candidates=tuple(
                    sorted(candidates, key=lambda c: c.confidence, reverse=True)
                ),
            )
        return DetectionResult(
            source_system="unknown",
            confidence=(best.confidence if best else 0.0),
            signals=(best.signals if best else ()),
            candidates=tuple(
                sorted(candidates, key=lambda c: c.confidence, reverse=True)
            ),
        )
    return DetectionResult(
        source_system=best.source_system,
        confidence=best.confidence,
        signals=best.signals,
        candidates=tuple(
            sorted(candidates, key=lambda c: c.confidence, reverse=True)
        ),
    )
