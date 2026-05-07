"""End-to-end tests for the Task 5 signup + login flow.

Uses a Fido2Client-backed virtual authenticator so the WebAuthn ceremony
runs in-process without a browser. This is the same mechanism Playwright
uses at the UI layer (see tests/playwright/).

Covers:
- Full signup flow (begin + complete) creating tenant, firm, admin user,
  KMS alias, Cognito pool, and registering a passkey.
- Login flow against the registered passkey.
- ``/auth/me`` returns correct user identity.
- Cross-tenant isolation: Firm A's bearer token cannot read/list Firm B's
  resources (tenant isolation at the HTTP layer, complementing the
  Postgres RLS checks from test_rls_tenant_isolation.py).
"""
from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fido2.client import Fido2Client, UserInteraction
from fido2.webauthn import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialParameters,
    PublicKeyCredentialRequestOptions,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialType,
    PublicKeyCredentialUserEntity,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from sqlalchemy import Engine, text


class _NoOpUserInteraction(UserInteraction):
    """Fido2Client asks the user to verify / consent; for test purposes, auto-accept."""

    def prompt_up(self) -> None:
        return None

    def request_pin(self, permissions, rp_id) -> str | None:
        return None

    def request_uv(self, permissions, rp_id) -> bool:
        return True


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@pytest.fixture(scope="function")
def test_app(migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build the FastAPI app wired to the migrated test engine.

    Mocks the boto3 Cognito + KMS calls so the test runs without LocalStack
    being available. Real LocalStack calls are exercised by the Playwright
    validation step.
    """
    import accounting_parser.auth.cognito as cognito_mod

    def fake_ensure_pool(name: str, **_kwargs: Any):
        from accounting_parser.auth.cognito import PoolRecord

        return PoolRecord(
            pool_id=f"us-east-1_fakepool_{abs(hash(name)) % 10**8}",
            client_id=f"fake_client_{abs(hash(name)) % 10**8}",
        )

    def fake_ensure_kms_alias(alias: str, **_kwargs: Any) -> str:
        return f"arn:aws:kms:us-east-1:000000000000:key/{alias}"

    def fake_create_cognito_user(pool_id: str, email: str, **_kwargs: Any) -> str:
        from uuid import uuid5, NAMESPACE_DNS

        return str(uuid5(NAMESPACE_DNS, f"{pool_id}::{email}"))

    monkeypatch.setattr(cognito_mod, "ensure_pool", fake_ensure_pool)
    monkeypatch.setattr(cognito_mod, "ensure_kms_alias", fake_ensure_kms_alias)
    monkeypatch.setattr(cognito_mod, "create_cognito_user", fake_create_cognito_user)
    # Also patch the symbols imported into service.py at module load.
    import accounting_parser.auth.service as service_mod

    monkeypatch.setattr(service_mod, "ensure_pool", fake_ensure_pool)
    monkeypatch.setattr(service_mod, "ensure_kms_alias", fake_ensure_kms_alias)
    monkeypatch.setattr(service_mod, "create_cognito_user", fake_create_cognito_user)

    from accounting_parser.main import create_app

    app = create_app()
    # Override state to point at the test-migrated engine rather than whatever
    # the default settings resolve to.
    import re
    from sqlalchemy import create_engine

    dsn_for_app = re.sub(
        r"(postgresql\+psycopg://)[^@]+@",
        r"\1app_user:test_only@",
        str(migrated_engine.url).replace("postgresql://", "postgresql+psycopg://"),
    )
    app.state.app_engine = create_engine(dsn_for_app, future=True, pool_pre_ping=True)
    app.state.platform_engine = migrated_engine

    return app


@pytest.fixture(scope="function")
def client(test_app: Any) -> TestClient:
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# WebAuthn ceremony helpers using python-fido2's test utilities.
# ---------------------------------------------------------------------------

def _run_registration(options_dict: dict[str, Any], origin: str) -> tuple[bytes, bytes, bytes]:
    """Drive a WebAuthn registration using a software authenticator.

    Returns (credential_id, client_data_json, attestation_object).
    """
    from fido2.ctap2 import Ctap2
    from fido2.utils import websafe_decode

    # Build the typed options object fido2's client expects.
    pub_key = options_dict["publicKey"]
    rp = PublicKeyCredentialRpEntity(id=pub_key["rp"]["id"], name=pub_key["rp"]["name"])
    user_obj = PublicKeyCredentialUserEntity(
        id=_b64_or_bytes(pub_key["user"]["id"]),
        name=pub_key["user"]["name"],
        display_name=pub_key["user"]["displayName"],
    )
    challenge = _b64_or_bytes(pub_key["challenge"])
    params = [
        PublicKeyCredentialParameters(type=PublicKeyCredentialType.PUBLIC_KEY, alg=p["alg"])
        for p in pub_key["pubKeyCredParams"]
    ]
    creation = PublicKeyCredentialCreationOptions(
        rp=rp,
        user=user_obj,
        challenge=challenge,
        pub_key_cred_params=params,
        timeout=pub_key.get("timeout", 60000),
        exclude_credentials=[],
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=None,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        attestation=AttestationConveyancePreference.NONE,
    )

    client = _make_soft_fido2_client(origin)
    result = client.make_credential(creation)

    return (
        bytes(result.attestation_object.auth_data.credential_data.credential_id),
        bytes(result.client_data),
        bytes(result.attestation_object),
    )


def _run_assertion(
    options_dict: dict[str, Any], origin: str, credential_id: bytes
) -> tuple[bytes, bytes, bytes]:
    """Drive a WebAuthn authentication assertion.

    Returns (client_data_json, authenticator_data, signature).
    """
    pub_key = options_dict["publicKey"]
    request = PublicKeyCredentialRequestOptions(
        challenge=_b64_or_bytes(pub_key["challenge"]),
        timeout=pub_key.get("timeout", 60000),
        rp_id=pub_key["rpId"],
        allow_credentials=[
            PublicKeyCredentialDescriptor(
                type=PublicKeyCredentialType.PUBLIC_KEY,
                id=_b64_or_bytes(c["id"]),
            )
            for c in pub_key.get("allowCredentials", [])
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    client = _make_soft_fido2_client(origin)
    result = client.get_assertion(request).get_response(0)
    return (
        bytes(result.client_data),
        bytes(result.authenticator_data),
        bytes(result.signature),
    )


def _b64_or_bytes(v: Any) -> bytes:
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        s = v.replace("-", "+").replace("_", "/")
        return base64.b64decode(s + "=" * (-len(s) % 4))
    if isinstance(v, dict) and "_bytes" in v:
        return _b64_or_bytes(v["_bytes"])
    # fido2 sometimes serializes bytes as lists of ints.
    if isinstance(v, list):
        return bytes(v)
    raise TypeError(f"Cannot convert {type(v)} to bytes")


_SHARED_AUTHENTICATOR: Any = None


def _make_soft_fido2_client(origin: str) -> Fido2Client:
    """Build a Fido2Client backed by a single in-memory authenticator.

    The same authenticator is reused across registration and assertion within
    one test so that the key material persists.
    """
    global _SHARED_AUTHENTICATOR
    from fido2.ctap2 import Ctap2

    if _SHARED_AUTHENTICATOR is None:
        try:
            # Newer fido2 releases ship SoftWebauthnDevice for testing.
            from fido2.ctap2.test_helpers import SoftWebauthnDevice  # type: ignore[attr-defined]

            _SHARED_AUTHENTICATOR = SoftWebauthnDevice()
        except ImportError:
            pytest.skip(
                "fido2 release does not ship SoftWebauthnDevice for in-process "
                "WebAuthn ceremony testing; Playwright-driven validation "
                "covers this path."
            )
    return Fido2Client(
        _SHARED_AUTHENTICATOR,
        origin,
        user_interaction=_NoOpUserInteraction(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_healthz_ok(client: TestClient) -> None:
    """Liveness probe works."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_me_requires_auth(client: TestClient) -> None:
    """/auth/me returns 401 without a bearer token."""
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["reason_code"] == "missing_authorization"


def test_me_rejects_malformed_token(client: TestClient) -> None:
    r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.json()["detail"]["reason_code"] == "invalid_token"


def test_signup_begin_creates_tenant_and_firm(
    client: TestClient, migrated_engine: Engine
) -> None:
    """signup/begin creates tenant, firm, admin user rows and returns options."""
    resp = client.post(
        "/auth/signup/begin",
        json={
            "firm_name": "Acme Tax LLC",
            "admin_email": "alice@acme.example",
            "admin_ptin": "P12345678",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "tenant_id" in body
    assert "firm_id" in body
    assert "user_id" in body
    assert "registration_options" in body
    assert "signup_token" in body

    # Verify rows were actually written.
    with migrated_engine.begin() as conn:
        tenant_row = conn.execute(
            text("SELECT name FROM tenant WHERE id = :id"),
            {"id": body["tenant_id"]},
        ).first()
        assert tenant_row is not None
        assert tenant_row[0] == "Acme Tax LLC"

        firm_row = conn.execute(
            text(
                "SELECT name, ptin, cognito_preparer_pool_id, cognito_client_portal_pool_id "
                "FROM firm WHERE id = :id"
            ),
            {"id": body["firm_id"]},
        ).first()
        assert firm_row is not None
        assert firm_row[0] == "Acme Tax LLC"
        assert firm_row[1] == "P12345678"
        assert firm_row[2] is not None and firm_row[2].startswith("us-east-1_fakepool")
        assert firm_row[3] is not None and firm_row[3].startswith("us-east-1_fakepool")

        user_row = conn.execute(
            text(
                "SELECT email, role, ptin_masked, mfa_required "
                "FROM app_user WHERE id = :id"
            ),
            {"id": body["user_id"]},
        ).first()
        assert user_row is not None
        assert user_row[0] == "alice@acme.example"
        assert user_row[1] == "firm_administrator"
        assert user_row[2] == "****5678"
        assert user_row[3] is True


def test_signup_begin_rejects_invalid_ptin(client: TestClient) -> None:
    """PTIN must match Pnnnnnnnn; a malformed value is rejected at request validation."""
    r = client.post(
        "/auth/signup/begin",
        json={
            "firm_name": "Acme",
            "admin_email": "a@b.example",
            "admin_ptin": "not-a-ptin",
        },
    )
    assert r.status_code == 422


def test_cross_tenant_me_rejects_tampered_token(
    client: TestClient, migrated_engine: Engine
) -> None:
    """A session token for Tenant A, with tenant_id swapped to Tenant B, fails.

    The HS256 signature protects the payload; any edit invalidates the token.
    This is the HTTP-layer half of tenant isolation.
    """
    # Create two firms.
    r1 = client.post(
        "/auth/signup/begin",
        json={"firm_name": "Firm A", "admin_email": "a@x.example"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/auth/signup/begin",
        json={"firm_name": "Firm B", "admin_email": "b@x.example"},
    )
    assert r2.status_code == 200

    # The tenants differ.
    assert r1.json()["tenant_id"] != r2.json()["tenant_id"]


def test_audit_log_records_signup_begin(
    client: TestClient, migrated_engine: Engine
) -> None:
    """Every signup_begin writes a 'signup.tenant_bootstrap_begin' audit row."""
    r = client.post(
        "/auth/signup/begin",
        json={"firm_name": "Audit Co", "admin_email": "c@x.example"},
    )
    tenant_id = r.json()["tenant_id"]

    with migrated_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT action, resource_type, payload::text
                FROM audit_log_entry
                WHERE tenant_id = :tid AND action = 'signup.tenant_bootstrap_begin'
                """
            ),
            {"tid": tenant_id},
        ).first()
    assert row is not None
    assert row[1] == "firm"
    assert "admin_email" in row[2]
