# Fixture corpus spot-check log

Task 2's `[Validate]` sub-step requires a one-time human spot-check of the fixture corpus. Record each check here.

| Date | Checker | Fixtures opened | Notes |
| ---- | ------- | --------------- | ----- |
|      |         |                 |       |

## Protocol

1. Run `poetry run python generate_all.py --output-dir generated` from `tests/fixtures/`.
2. Pick 3 random PDFs from the 16 PDF fixtures and open them in a real PDF viewer (Adobe Reader, Preview, or similar). Confirm:
   - Page renders
   - Text is legible and resembles the claimed format (QBO TB layout vs QBD GL layout vs bank statement, etc.)
   - Numeric values look obviously-fake ($12,345.67 pattern)
3. Pick 3 random XLSX files from the 5 XLSX fixtures and open them in Excel. Confirm:
   - Sheets render
   - Column headers match the vendor's documented layout
   - Number formatting is accounting-style
4. Log the date, your name, and any anomalies.

Until this check is completed, the fixture corpus should be considered provisional. Downstream tasks (3+) can proceed against it, but any parser test failure caused by fixture malformation is a Task 2 defect, not a Task 8+ defect.
