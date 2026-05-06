"""Interchange-format parsers: OFX, QFX, QIF, IIF, XBRL.

Each parser returns a canonical ParseResult. Grammar errors produce
structured Validator findings rather than raising.

Design reference: requirements R6.1-R6.9.
"""

from accounting_parser.interchange.iif import IIF_GRAMMAR_ERROR, parse_iif
from accounting_parser.interchange.ofx import parse_ofx
from accounting_parser.interchange.qif import parse_qif
from accounting_parser.interchange.xbrl import parse_xbrl

__all__ = [
    "parse_ofx",
    "parse_qif",
    "parse_iif",
    "parse_xbrl",
    "IIF_GRAMMAR_ERROR",
]
