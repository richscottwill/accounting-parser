"""Synthetic-document factories for accounting-parser tests.

All factories emit deterministic output given the same seed. Numeric values
use obvious-fake patterns (e.g., $12,345.67) so accidental exposure during
screenshots is visually detectable.

No real taxpayer data, no PII, no vendor copyrighted content.
"""

# Enable ReportLab's invariant mode BEFORE any reportlab imports. This pins
# CreationDate/ModDate and the PDF /ID trailer so byte-identical output
# is guaranteed across runs with identical inputs (Correctness Property 3
# precursor).
from reportlab import rl_config as _rl_config

_rl_config.invariant = 1

from factories.qbo_tb_pdf import qbo_tb_pdf_factory
from factories.qbd_gl_pdf import qbd_gl_pdf_factory
from factories.xero_tb_xlsx import xero_tb_xlsx_factory
from factories.netsuite_tb_xlsx import netsuite_tb_xlsx_factory
from factories.sage_intacct_tb_pdf import sage_intacct_tb_pdf_factory
from factories.irs_form_pdf import irs_form_pdf_factory
from factories.bank_statement_pdf import bank_statement_pdf_factory
from factories.cch_engagement_xlsx import cch_engagement_import_xlsx_factory
from factories.interchange import (
    ofx_factory,
    qfx_factory,
    qif_factory,
    iif_factory,
    xbrl_factory,
)
from factories.rejection_samples import (
    password_protected_pdf_factory,
    password_protected_xlsx_factory,
    corrupted_pdf_factory,
    corrupted_xlsx_factory,
    image_only_scan_pdf_factory,
)

__all__ = [
    "qbo_tb_pdf_factory",
    "qbd_gl_pdf_factory",
    "xero_tb_xlsx_factory",
    "netsuite_tb_xlsx_factory",
    "sage_intacct_tb_pdf_factory",
    "irs_form_pdf_factory",
    "bank_statement_pdf_factory",
    "cch_engagement_import_xlsx_factory",
    "ofx_factory",
    "qfx_factory",
    "qif_factory",
    "iif_factory",
    "xbrl_factory",
    "password_protected_pdf_factory",
    "password_protected_xlsx_factory",
    "corrupted_pdf_factory",
    "corrupted_xlsx_factory",
    "image_only_scan_pdf_factory",
]
