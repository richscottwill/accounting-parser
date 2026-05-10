"""Parent Task 22 + Task 26 template registration."""

from __future__ import annotations

from accounting_parser.workflow.templates import (
    all_templates,
    get_template,
    individual_1040_prep,
    year_end_tax_prep,
)


def test_individual_1040_prep_registered():
    """Task 22: individual_1040_prep findable via the registry."""
    t = get_template("individual_1040_prep")
    assert t.id == "individual_1040_prep"
    assert "tax_return" in t.applies_to_engagement_types


def test_individual_1040_prep_has_ocr_gate_step():
    """Task 22: the ceremony must pause for OCR-field confirmation."""
    t = individual_1040_prep
    pause_steps = [s for s in t.steps if s.step_type == "require_preparer_review"]
    assert len(pause_steps) >= 1
    assert any("OCR" in (s.config.get("reason") or "") for s in pause_steps)


def test_year_end_tax_prep_registered():
    """Task 26 flagship scenario template registered."""
    t = get_template("year_end_tax_prep")
    assert t.id == "year_end_tax_prep"


def test_year_end_tax_prep_has_two_pause_points():
    """Flagship has both preparer review AND reviewer signoff."""
    t = year_end_tax_prep
    has_preparer = any(s.step_type == "require_preparer_review" for s in t.steps)
    has_reviewer = any(s.step_type == "require_reviewer_signoff" for s in t.steps)
    assert has_preparer
    assert has_reviewer


def test_year_end_tax_prep_ends_with_export():
    """Last step is the CCH export — the flagship's deliverable."""
    t = year_end_tax_prep
    assert t.steps[-1].step_type == "emit_export"
    assert t.steps[-1].config.get("target") == "cch_engagement"


def test_all_three_p1_p2_templates_registered():
    ids = {t.id for t in all_templates()}
    assert {
        "monthly_close_bookkeeping",
        "individual_1040_prep",
        "year_end_tax_prep",
    }.issubset(ids)
