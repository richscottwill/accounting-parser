"""Ingestion service — accepts Document uploads, performs safety + dedup,
writes to tenant-isolated storage, enqueues parse jobs.

Implements Task 6.

Components:
- ``storage.py``  — storage backend (S3 via boto3 or local-disk fake)
- ``scanner.py``  — malware scanner adapter (clamav, command-line, or skip)
- ``mime.py``     — magic-byte detection; declared-vs-detected mismatch check
- ``service.py``  — orchestration: size/MIME/magic/scan/hash/dedup → DB write
- ``routes.py``   — FastAPI multipart upload + download + list endpoints
"""
