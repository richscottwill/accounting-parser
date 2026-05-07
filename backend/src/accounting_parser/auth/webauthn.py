"""WebAuthn (passkey) registration and assertion via python-fido2.

Two ceremonies:

1. **Registration** (a.k.a. ``attestation``): a new passkey is enrolled.
   ``begin_registration`` issues options (challenge + RP metadata) to the
   browser. ``complete_registration`` verifies the attestation response
   and persists the credential to ``webauthn_credential``.

2. **Authentication** (a.k.a. ``assertion``): an existing passkey is used
   to log in. ``begin_authentication`` issues a challenge scoped to the
   user's registered credentials. ``complete_authentication`` verifies
   the signed assertion and returns the matched credential row.

Both ceremonies persist short-lived challenges to ``auth_challenge`` so the
backend can verify the exact challenge the authenticator signed (per WebAuthn
spec — challenges must be single-use, per-ceremony, unpredictable).

The library layer (``fido2``) handles the cryptographic details. This
module handles the app-layer persistence and audit logging.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fido2.server import Fido2Server
from fido2.webauthn import (
    AttestedCredentialData,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialType,
    PublicKeyCredentialUserEntity,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class RegistrationBegin:
    """Output of begin_registration: options for the browser, challenge ID for the server."""

    options: dict[str, Any]
    challenge_id: UUID


@dataclass
class RegistrationComplete:
    """Output of complete_registration: the persisted credential row id."""

    credential_id: UUID
    credential_bytes: bytes


@dataclass
class AuthenticationBegin:
    """Output of begin_authentication."""

    options: dict[str, Any]
    challenge_id: UUID


@dataclass
class AuthenticationComplete:
    """Output of complete_authentication: the matched credential + user."""

    credential_id: UUID
    user_id: UUID


def _get_server(settings: Settings) -> Fido2Server:
    rp = PublicKeyCredentialRpEntity(
        id=settings.webauthn_rp_id,
        name=settings.webauthn_rp_name,
    )
    return Fido2Server(rp)


def _store_challenge(
    session: Session,
    *,
    tenant_id: UUID | None,
    user_id: UUID | None,
    purpose: str,
    challenge_bytes: bytes,
    rp_id: str,
    origin: str,
    ttl_seconds: int,
) -> UUID:
    """Insert a row into auth_challenge, return its id."""
    challenge_uuid = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    session.execute(
        text(
            """
            INSERT INTO auth_challenge (
                id, tenant_id, user_id, purpose,
                challenge_bytes, rp_id, origin, expires_at
            )
            VALUES (
                :id, :tenant_id, :user_id, :purpose,
                :challenge_bytes, :rp_id, :origin, :expires
            )
            """
        ),
        {
            "id": str(challenge_uuid),
            "tenant_id": str(tenant_id) if tenant_id else None,
            "user_id": str(user_id) if user_id else None,
            "purpose": purpose,
            "challenge_bytes": challenge_bytes,
            "rp_id": rp_id,
            "origin": origin,
            "expires": expires,
        },
    )
    return challenge_uuid


def _consume_challenge(session: Session, challenge_id: UUID) -> dict[str, Any]:
    """Fetch + mark-consumed a challenge. Raises if expired or already consumed."""
    row = session.execute(
        text(
            """
            SELECT tenant_id, user_id, purpose, challenge_bytes,
                   rp_id, origin, expires_at, consumed_at
            FROM auth_challenge
            WHERE id = :id
            """
        ),
        {"id": str(challenge_id)},
    ).mappings().first()
    if row is None:
        raise ValueError(f"Unknown challenge {challenge_id}")
    if row["consumed_at"] is not None:
        raise ValueError(f"Challenge {challenge_id} already consumed")
    expires = row["expires_at"]
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise ValueError(f"Challenge {challenge_id} has expired")
    session.execute(
        text("UPDATE auth_challenge SET consumed_at = now() WHERE id = :id"),
        {"id": str(challenge_id)},
    )
    return dict(row)


def begin_registration(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    user_email: str,
    display_name: str,
    existing_credential_ids: list[bytes] | None = None,
    settings: Settings | None = None,
) -> RegistrationBegin:
    """Start a WebAuthn registration ceremony.

    Returns options for the browser to pass to ``navigator.credentials.create()``
    and a challenge_id the client must echo back on ``complete_registration``.
    """
    settings = settings or get_settings()
    server = _get_server(settings)

    user_entity = PublicKeyCredentialUserEntity(
        id=user_id.bytes,
        name=user_email,
        display_name=display_name,
    )
    exclude: list[PublicKeyCredentialDescriptor] = [
        PublicKeyCredentialDescriptor(
            type=PublicKeyCredentialType.PUBLIC_KEY, id=cid
        )
        for cid in (existing_credential_ids or [])
    ]

    options, state = server.register_begin(
        user=user_entity,
        credentials=exclude,
        user_verification="preferred",
    )

    challenge_raw = state["challenge"]
    challenge_bytes = (
        challenge_raw
        if isinstance(challenge_raw, (bytes, bytearray))
        else _b64_to_bytes(challenge_raw)
    )

    challenge_id = _store_challenge(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        purpose="registration",
        challenge_bytes=bytes(challenge_bytes),
        rp_id=settings.webauthn_rp_id,
        origin=settings.webauthn_origin,
        ttl_seconds=settings.webauthn_challenge_ttl_seconds,
    )

    return RegistrationBegin(options=dict(options), challenge_id=challenge_id)


def complete_registration(
    session: Session,
    *,
    challenge_id: UUID,
    client_data_json: bytes,
    attestation_object: bytes,
    friendly_name: str | None = None,
    settings: Settings | None = None,
) -> RegistrationComplete:
    """Verify a registration response and persist the credential.

    Raises ValueError on any verification failure.
    """
    settings = settings or get_settings()
    server = _get_server(settings)

    challenge_row = _consume_challenge(session, challenge_id)
    if challenge_row["purpose"] != "registration":
        raise ValueError(f"Challenge {challenge_id} is not a registration challenge")

    # Rebuild state in the shape fido2 expects. With webauthn_json_mapping
    # enabled, challenge is base64url-encoded. Without, it's bytes. We store
    # raw bytes in Postgres; convert back to the matching in-memory shape.
    challenge_stored = bytes(challenge_row["challenge_bytes"])
    state = {
        "challenge": _bytes_to_b64url(challenge_stored),
        "user_verification": "preferred",
    }

    # fido2 expects typed CollectedClientData + AttestationObject — not raw
    # bytes. Wrap the client-supplied bytes before calling register_complete.
    from fido2.webauthn import AttestationObject, CollectedClientData

    auth_data = server.register_complete(
        state,
        client_data=CollectedClientData(client_data_json),
        attestation_object=AttestationObject(attestation_object),
    )

    cred_data: AttestedCredentialData = auth_data.credential_data  # type: ignore[assignment]
    credential_id_bytes = bytes(cred_data.credential_id)
    # cred_data.public_key is a COSE dict. Serialize back to CBOR so we can
    # round-trip it through Postgres bytea and rebuild AttestedCredentialData
    # at assertion time.
    from fido2 import cbor

    public_key_cose = cbor.encode(dict(cred_data.public_key))
    aaguid_bytes = bytes(cred_data.aaguid) if cred_data.aaguid else None

    cred_uuid = uuid4()
    session.execute(
        text(
            """
            INSERT INTO webauthn_credential (
                id, tenant_id, user_id, credential_id, public_key_cose,
                sign_count, aaguid, friendly_name
            )
            VALUES (
                :id, :tenant_id, :user_id, :cid, :pk,
                :sc, :aaguid, :name
            )
            """
        ),
        {
            "id": str(cred_uuid),
            "tenant_id": str(challenge_row["tenant_id"]),
            "user_id": str(challenge_row["user_id"]),
            "cid": credential_id_bytes,
            "pk": public_key_cose,
            "sc": 0,
            "aaguid": str(UUID(bytes=aaguid_bytes)) if aaguid_bytes else None,
            "name": friendly_name,
        },
    )

    logger.info(
        "WebAuthn credential registered",
        extra={
            "credential_uuid": str(cred_uuid),
            "user_id": str(challenge_row["user_id"]),
            "tenant_id": str(challenge_row["tenant_id"]),
        },
    )

    return RegistrationComplete(credential_id=cred_uuid, credential_bytes=credential_id_bytes)


def begin_authentication(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    settings: Settings | None = None,
) -> AuthenticationBegin:
    """Start a WebAuthn authentication ceremony for a known user."""
    settings = settings or get_settings()
    server = _get_server(settings)

    rows = session.execute(
        text(
            """
            SELECT credential_id
            FROM webauthn_credential
            WHERE user_id = :uid
            """
        ),
        {"uid": str(user_id)},
    ).all()
    if not rows:
        raise ValueError(f"User {user_id} has no registered credentials")

    descriptors = [
        PublicKeyCredentialDescriptor(
            type=PublicKeyCredentialType.PUBLIC_KEY, id=bytes(r[0])
        )
        for r in rows
    ]

    options, state = server.authenticate_begin(
        credentials=descriptors, user_verification="preferred"
    )

    challenge_raw = state["challenge"]
    challenge_bytes = (
        challenge_raw
        if isinstance(challenge_raw, (bytes, bytearray))
        else _b64_to_bytes(challenge_raw)
    )

    challenge_id = _store_challenge(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        purpose="authentication",
        challenge_bytes=bytes(challenge_bytes),
        rp_id=settings.webauthn_rp_id,
        origin=settings.webauthn_origin,
        ttl_seconds=settings.webauthn_challenge_ttl_seconds,
    )

    return AuthenticationBegin(options=dict(options), challenge_id=challenge_id)


def complete_authentication(
    session: Session,
    *,
    challenge_id: UUID,
    credential_id_bytes: bytes,
    client_data_json: bytes,
    authenticator_data: bytes,
    signature: bytes,
    settings: Settings | None = None,
) -> AuthenticationComplete:
    """Verify an authentication assertion and return the matched credential."""
    settings = settings or get_settings()
    server = _get_server(settings)

    challenge_row = _consume_challenge(session, challenge_id)
    if challenge_row["purpose"] != "authentication":
        raise ValueError(f"Challenge {challenge_id} is not an authentication challenge")

    cred_row = session.execute(
        text(
            """
            SELECT id, user_id, public_key_cose, sign_count
            FROM webauthn_credential
            WHERE credential_id = :cid
            """
        ),
        {"cid": credential_id_bytes},
    ).mappings().first()
    if cred_row is None:
        raise ValueError("Unknown credential_id")
    if str(cred_row["user_id"]) != str(challenge_row["user_id"]):
        raise ValueError("Credential does not belong to the user in the challenge")

    # Build the credential data shape fido2 expects.
    from fido2.webauthn import AttestedCredentialData

    cred_data = AttestedCredentialData.create(
        aaguid=bytes(16),  # not checked at assertion time; zero-filled is fine
        credential_id=credential_id_bytes,
        public_key=dict(_cose_bytes_to_dict(bytes(cred_row["public_key_cose"]))),
    )

    state = {"challenge": _bytes_to_b64url(bytes(challenge_row["challenge_bytes"])),
             "user_verification": "preferred"}

    # Same typed-wrapper treatment as register_complete.
    from fido2.webauthn import AuthenticatorData, CollectedClientData

    server.authenticate_complete(
        state,
        credentials=[cred_data],
        credential_id=credential_id_bytes,
        client_data=CollectedClientData(client_data_json),
        auth_data=AuthenticatorData(authenticator_data),
        signature=signature,
    )

    # Bump sign_count + last_used_at.
    session.execute(
        text(
            """
            UPDATE webauthn_credential
            SET sign_count = sign_count + 1,
                last_used_at = now()
            WHERE id = :id
            """
        ),
        {"id": str(cred_row["id"])},
    )

    return AuthenticationComplete(
        credential_id=UUID(str(cred_row["id"])),
        user_id=UUID(str(cred_row["user_id"])),
    )


def _cose_bytes_to_dict(cose_bytes: bytes) -> Any:
    """Decode COSE-encoded public key bytes back into the dict fido2 wants."""
    from fido2 import cbor

    return cbor.decode(cose_bytes)


def _b64_to_bytes(s: str) -> bytes:
    """URL-safe or standard base64 → bytes, padding-tolerant."""
    import base64 as _b64

    s_std = s.replace("-", "+").replace("_", "/")
    padding = "=" * (-len(s_std) % 4)
    return _b64.b64decode(s_std + padding)


def _bytes_to_b64url(b: bytes) -> str:
    """bytes → base64url without padding, matching fido2's JSON mapping."""
    import base64 as _b64

    return _b64.urlsafe_b64encode(b).decode("ascii").rstrip("=")
