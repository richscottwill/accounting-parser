"""Authentication and authorization subsystem.

This package implements the self-hosted single-firm fork's auth model
(spec: ``.kiro/specs/accounting-parser-self-hosted/requirements.md`` R26).

The identity provider is pluggable via ``AuthAdapter`` (see ``adapter.py``).
The default shipping adapter is ``AuthentikAuthAdapter``; ``CognitoAuthAdapter``
exists as a stub so the adapter contract is exercised by both cloud and
self-hosted variants even before cloud is re-instated.

Entry points for the rest of the application:

- ``AuthAdapter``               — the Protocol the rest of the code depends on.
- ``get_auth_adapter()``        — resolves the configured adapter from settings.
- ``AuthMiddleware``            — FastAPI middleware; validates session tokens,
                                  resolves User + Firm, calls ``set_tenant_context``.
- ``AuthService``               — business logic: signup, single-firm check,
                                  passkey enrollment, magic-link issuance.

Nothing in this package imports FastAPI at module load except ``middleware.py``
and the route modules — keeping the adapter layer usable from Celery workers
and CLI tools without pulling the HTTP stack.
"""

from accounting_parser.auth.adapter import (
    AuthAdapter,
    AuthenticatedUser,
    PasskeyCredential,
    SessionToken,
    SignupRequest,
)
from accounting_parser.auth.authentik import AuthentikAuthAdapter
from accounting_parser.auth.cognito import CognitoAuthAdapter
from accounting_parser.auth.service import (
    AuthService,
    FirmAlreadyProvisionedError,
    InvalidMagicLinkError,
    PasskeyEnrollmentError,
)

__all__ = [
    "AuthAdapter",
    "AuthService",
    "AuthenticatedUser",
    "AuthentikAuthAdapter",
    "CognitoAuthAdapter",
    "FirmAlreadyProvisionedError",
    "InvalidMagicLinkError",
    "PasskeyCredential",
    "PasskeyEnrollmentError",
    "SessionToken",
    "SignupRequest",
]
