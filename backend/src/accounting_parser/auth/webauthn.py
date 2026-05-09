"""WebAuthn / FIDO2 helpers.

Wraps the ``fido2`` library into a narrow, deterministic surface
we control:

- ``generate_registration_challenge`` — produces a 32-byte random
  challenge bound to the (user_id, expected_rp_id) pair.
- ``verify_registration`` — parses an attestation CBOR into the
  ``PasskeyCredential`` DTO. Returns the credential to store.
- ``generate_assertion_challenge`` — 32-byte random challenge.
- ``verify_assertion`` — verifies an assertion against a stored
  public key; returns the new sign_count.

We do NOT call Authentik's WebAuthn API during these verifications.
Application is the authority for passkey verification at signup;
Authentik is notified afterward (via ``AuthentikAuthAdapter.enroll_passkey``)
so its own login flows work.

Why split it this way: if the adapter-to-IdP path fails (network
glitch, Authentik down), signup must still be able to succeed so
the firm isn't locked out of their own install. The passkey is
verified and stored locally; Authentik mirrors it on best-effort.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fido2 import cbor
from fido2.server import Fido2Server
from fido2.webauthn import (
    AttestationObject,
    AuthenticatorData,
    CollectedClientData,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    UserVerificationRequirement,
)

from accounting_parser.auth.adapter import PasskeyCredential


@dataclass(frozen=True)
class RegistrationChallenge:
    """The challenge presented to a browser during passkey enrollment.

    ``state`` is the opaque fido2 server state the caller must hand
    back to ``verify_registration`` — we don't persist it; the route
    returns the state to the browser as a signed cookie or HMAC-ed
    session value.
    """

    challenge: bytes
    state: dict[str, object]
    rp: dict[str, str]
    user: dict[str, bytes | str]


@dataclass(frozen=True)
class AssertionChallenge:
    """The challenge presented during passkey login / step-up auth."""

    challenge: bytes
    state: dict[str, object]
    credential_ids: list[bytes]


def _server(rp_id: str, rp_name: str) -> Fido2Server:
    """Construct a fido2 server bound to our Relying Party.

    Rebuild every time rather than caching — the RP can differ per
    request in test environments, and construction is cheap.
    """
    rp = PublicKeyCredentialRpEntity(id=rp_id, name=rp_name)
    return Fido2Server(rp)


def generate_registration_challenge(
    *,
    user_id: bytes,
    user_name: str,
    user_display_name: str,
    rp_id: str,
    rp_name: str,
    existing_credentials: list[bytes] | None = None,
) -> RegistrationChallenge:
    """Start a WebAuthn registration ceremony."""
    server = _server(rp_id, rp_name)
    user = PublicKeyCredentialUserEntity(
        id=user_id,
        name=user_name,
        display_name=user_display_name,
    )
    options, state = server.register_begin(
        user=user,
        credentials=[_public_key_credential_from_id(c) for c in existing_credentials or []],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    # options.public_key is a dict the browser consumes; expose the
    # challenge separately for audit logging.
    return RegistrationChallenge(
        challenge=bytes(options.public_key.challenge),
        state=state,
        rp={"id": rp_id, "name": rp_name},
        user={"id": user_id, "name": user_name, "display_name": user_display_name},
    )


def verify_registration(
    *,
    state: dict[str, object],
    client_data_json: bytes,
    attestation_object_cbor: bytes,
    rp_id: str,
    rp_name: str,
) -> PasskeyCredential:
    """Complete a WebAuthn registration ceremony.

    Raises if verification fails. The raised exception bubbles up
    so the caller can audit-log the failure and return a 400.
    """
    server = _server(rp_id, rp_name)
    client_data = CollectedClientData(client_data_json)
    att_obj = AttestationObject(attestation_object_cbor)
    auth_data = server.register_complete(state, client_data, att_obj)
    credential_data = auth_data.credential_data
    if credential_data is None:
        raise ValueError("attestation did not include credential data")
    # ``credential_data.public_key`` is a COSE map; serialize back
    # to CBOR so we can round-trip through the database untouched.
    public_key_cose = cbor.encode(credential_data.public_key)
    return PasskeyCredential(
        credential_id=bytes(credential_data.credential_id),
        public_key=public_key_cose,
        sign_count=auth_data.counter,
        aaguid=bytes(credential_data.aaguid) if credential_data.aaguid else None,
        transports=(),  # browser includes them; we don't persist at MVP
    )


def generate_assertion_challenge(
    *,
    credential_ids: list[bytes],
    rp_id: str,
    rp_name: str,
) -> AssertionChallenge:
    """Start a WebAuthn assertion (login) ceremony."""
    server = _server(rp_id, rp_name)
    options, state = server.authenticate_begin(
        credentials=[_public_key_credential_from_id(cid) for cid in credential_ids],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return AssertionChallenge(
        challenge=bytes(options.public_key.challenge),
        state=state,
        credential_ids=credential_ids,
    )


def verify_assertion(
    *,
    assertion_cbor: bytes,
    challenge: bytes,
    credential_id: bytes,
    public_key_cose: bytes,
    stored_sign_count: int,
    expected_origin: str,
    expected_rp_id: str,
) -> int:
    """Verify a WebAuthn assertion response.

    Returns the new sign_count to persist. Raises on any verification
    failure. Caller (``AuthentikAuthAdapter.verify_passkey_assertion``)
    maps exceptions to ``PasskeyAssertionError``.

    The assertion_cbor is the CBOR-decoded response bundle:
    ``{clientDataJSON, authenticatorData, signature, userHandle}``.
    """
    bundle = cbor.decode(assertion_cbor)
    client_data = CollectedClientData(bundle["clientDataJSON"])
    auth_data = AuthenticatorData(bundle["authenticatorData"])
    signature = bundle["signature"]

    # Construct a minimal Fido2Server. For assertion verification
    # we need the RP and the credential's public key; the library
    # handles signature + challenge + origin + sign_count checks.
    server = _server(expected_rp_id, "accounting-parser")
    public_key = cbor.decode(public_key_cose)

    # The fido2 server expects a "credentials" list of PublicKeyCredentialDescriptor
    # plus a state matching the challenge. We rebuild state from the challenge
    # because stateless assertion verification (we store challenge, credential,
    # public key; no server-side blob) keeps the flow simpler.
    state = {
        "challenge": bytes(challenge),
        "user_verification": UserVerificationRequirement.REQUIRED.value,
    }
    credentials = [
        _attested_credential(
            credential_id=credential_id,
            public_key=public_key,
            sign_count=stored_sign_count,
        )
    ]
    auth_result = server.authenticate_complete(
        state=state,
        credentials=credentials,
        credential_id=credential_id,
        client_data=client_data,
        auth_data=auth_data,
        signature=signature,
    )
    # ``auth_result.counter`` is the new sign_count. Caller persists.
    return auth_result.new_sign_count


# ---- Internal helpers ---------------------------------------------


def _public_key_credential_from_id(credential_id: bytes) -> dict[str, object]:
    """Adapt a raw credential id into the fido2 register-begin shape."""
    return {
        "type": "public-key",
        "id": credential_id,
    }


def _attested_credential(
    *,
    credential_id: bytes,
    public_key: object,
    sign_count: int,
) -> object:
    """Build the object fido2's server expects in ``credentials`` for assertion.

    The fido2 library accepts dict-like objects with ``.credential_id``,
    ``.public_key``, and ``.sign_count`` attributes. We construct a
    simple namespace here to avoid leaking fido2-internal classes into
    the rest of the codebase.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        credential_id=credential_id,
        public_key=public_key,
        sign_count=sign_count,
    )


def hash_credential_id(credential_id: bytes) -> bytes:
    """Return the sha256 of a credential id.

    Used in session-token ``credhash`` claim (R26.3 session binding).
    """
    return hashlib.sha256(credential_id).digest()


def random_challenge(length: int = 32) -> bytes:
    """Return a cryptographically random challenge of ``length`` bytes."""
    return secrets.token_bytes(length)
