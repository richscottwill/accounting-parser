"""Observability subsystem — Task 27.

Structured-log middleware with PII redaction, CloudWatch metric emission
stubs, OpenTelemetry tracing helpers.

Redaction (Requirement 15.4 / 21.8 / Correctness Property 25) is the
most consequential piece: SSN, EIN, bank account numbers, and dollar
amounts attached to taxpayer identifiers MUST NOT escape the Tenant
boundary via any aggregate metric or external log.
"""
