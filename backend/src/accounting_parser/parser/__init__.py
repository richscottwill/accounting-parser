"""Document parsers: PDF (text-native) and Excel.

PDF OCR-path and Textract/Azure DI integration (Task 9) are deferred —
require AWS credentials + Azure API and are not local-runnable.
"""

from accounting_parser.parser.excel_parser import parse_excel
from accounting_parser.parser.pdf_parser import (
    MoneyParseResult,
    parse_money,
    parse_pdf_text_native,
)

__all__ = [
    "parse_pdf_text_native",
    "parse_excel",
    "parse_money",
    "MoneyParseResult",
]
