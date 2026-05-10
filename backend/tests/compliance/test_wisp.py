"""WISP generator."""

from __future__ import annotations

from accounting_parser.compliance.wisp import WispContext, generate_wisp_markdown


def test_generated_wisp_has_all_required_sections():
    """Structure matches IRS Pub 5708 numbered sections 1-10."""
    ctx = WispContext(
        firm_name="Acme CPA",
        firm_administrator_name="Alice Principal",
        firm_administrator_email="alice@acme-cpa.example",
        host_os="Ubuntu 22.04",
        deployment_address="100 Main St, Seattle WA",
    )
    md = generate_wisp_markdown(ctx)
    for section_number in range(1, 11):
        assert f"## {section_number}." in md, f"missing section {section_number}"


def test_firm_fields_populated_in_output():
    ctx = WispContext(
        firm_name="Test Firm",
        firm_administrator_name="Bob Smith",
        firm_administrator_email="bob@test.firm",
        host_os="Windows Server 2022",
        deployment_address="Somewhere",
    )
    md = generate_wisp_markdown(ctx)
    assert "Test Firm" in md
    assert "Bob Smith" in md
    assert "bob@test.firm" in md
    assert "Windows Server 2022" in md


def test_missing_offsite_backup_renders_none_configured():
    """ctx.offsite_backup_target=None should render gracefully."""
    ctx = WispContext(
        firm_name="Firm",
        offsite_backup_target=None,
    )
    md = generate_wisp_markdown(ctx)
    assert "none configured" in md
    # And the [TO BE COMPLETED] placeholder at the detail line.
    assert "[TO BE COMPLETED]" in md


def test_version_stamp_appears():
    ctx = WispContext(firm_name="X")
    md = generate_wisp_markdown(ctx, firm_instance_version="0.3.0")
    assert "accounting-parser 0.3.0" in md
