"""Client Portal (Task 23) — PBC lifecycle + Client-scoped upload.

The preparer-facing APIs already exist under ``/ingest`` (Task 6). The
portal adds:
- Magic-link + email-OTP authentication for Client users (separate
  Cognito pool — when cognito_backend=aws; fake backend for dev).
- PBC_Request lifecycle transitions: requested → received → under_review →
  accepted / rejected_resubmit / waived.
- Auto-match: on Client upload, the portal attempts to match the
  uploaded Document to an outstanding PBC_Request based on
  ``Source_Detector`` output + declared category.
"""
