"""OCR subsystem — Task 9.

Pluggable OCR adapter following the same pattern as
``ingestion.scanner`` and ``auth.cognito``:

- ``aws-textract``: real boto3 client against Textract (or LocalStack Pro).
- ``azure-di``:     Azure Document Intelligence bank-statement model.
- ``fake``:         deterministic in-process OCR that returns configured
                    per-field confidence scores. Used by Task 9 tests and
                    by CI when no external OCR vendor is wired.

The field-validation gate (Requirement 4.24 / Correctness Property 26)
is implemented in ``gate.py``: any Tax_Form_Field with OCR confidence
below 0.95 is blocked from posting to the Working_Trial_Balance until a
Preparer confirms or corrects it. Every confirm/correct event is
audit-logged with the original + corrected value.
"""
