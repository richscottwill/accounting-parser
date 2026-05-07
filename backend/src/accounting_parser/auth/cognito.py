"""Cognito user pool provisioning.

Idempotent: calling ``ensure_pool(name)`` creates the pool if it doesn't
exist, returns the existing pool ID otherwise. Used at signup to bootstrap
a per-Firm preparer pool + client-portal pool.

In dev, points at LocalStack's cognito-idp via
``AWS_ENDPOINT_URL=http://localhost:4566``. In prod, points at real AWS.
Behavior is identical because both honor the boto3 client interface.

LocalStack's cognito-idp implementation has quirks:
- ``AdminCreateUser`` works fine.
- ``DescribeUserPool`` returns minimal data vs real AWS.
- WebAuthn / passkey verification on Cognito's managed UI is not supported
  on LocalStack, so we keep passkeys in application state (``webauthn_credential``
  table) and use Cognito purely for identity-sub allocation at MVP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

from accounting_parser.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PoolRecord:
    """A Cognito pool + client-id pair allocated to a firm."""

    pool_id: str
    client_id: str


def _cognito_client(settings: Settings) -> Any:
    """Return a boto3 cognito-idp client wired to the configured endpoint."""
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("cognito-idp", **kwargs)


def _kms_client(settings: Settings) -> Any:
    """Return a boto3 KMS client wired to the configured endpoint."""
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    return boto3.client("kms", **kwargs)


def find_pool_by_name(cognito: Any, name: str) -> str | None:
    """Return pool ID for a pool with the given name, or None."""
    # ListUserPools is paginated; 60 pool cap is fine at MVP.
    resp = cognito.list_user_pools(MaxResults=60)
    for pool in resp.get("UserPools", []):
        if pool.get("Name") == name:
            return pool["Id"]
    return None


def _fake_pool_record(name: str) -> PoolRecord:
    """Deterministic fake pool allocator for dev against LocalStack Community.

    LocalStack Community does not ship cognito-idp. Rather than forcing a
    Pro-tier dependency for local dev, we provide a deterministic in-process
    allocator that returns stable (pool_id, client_id) pairs derived from the
    pool name. The IDs are shaped like real Cognito identifiers so code that
    logs or persists them sees values of the expected form.
    """
    # Stable derivation so reruns produce identical IDs (matters for tests
    # and for signup-is-idempotent semantics).
    from hashlib import sha256

    digest = sha256(name.encode("utf-8")).hexdigest()
    pool_id = f"us-east-1_fake{digest[:8]}"
    client_id = f"fake{digest[8:24]}"
    return PoolRecord(pool_id=pool_id, client_id=client_id)


def _fake_user_sub(pool_id: str, email: str) -> str:
    """Deterministic fake Cognito sub UUID."""
    from uuid import uuid5, NAMESPACE_DNS

    return str(uuid5(NAMESPACE_DNS, f"{pool_id}::{email}"))


def ensure_pool(name: str, *, settings: Settings | None = None) -> PoolRecord:
    """Create the pool + app-client if absent. Idempotent.

    Args:
        name: Unique pool name (e.g., ``"firm-<uuid>-preparer"``).

    Returns:
        PoolRecord with pool_id and client_id. On the first call for a name,
        the pool is newly created; on subsequent calls, existing IDs are
        discovered and returned.
    """
    settings = settings or get_settings()
    if settings.cognito_backend == "fake":
        return _fake_pool_record(name)
    cognito = _cognito_client(settings)

    existing_pool_id = find_pool_by_name(cognito, name)
    if existing_pool_id:
        # Reuse existing pool; find or create the app client.
        client_resp = cognito.list_user_pool_clients(
            UserPoolId=existing_pool_id, MaxResults=10
        )
        clients = client_resp.get("UserPoolClients", [])
        if clients:
            return PoolRecord(pool_id=existing_pool_id, client_id=clients[0]["ClientId"])
        new_client = cognito.create_user_pool_client(
            UserPoolId=existing_pool_id,
            ClientName=f"{name}-client",
            GenerateSecret=False,
            ExplicitAuthFlows=["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )
        return PoolRecord(
            pool_id=existing_pool_id,
            client_id=new_client["UserPoolClient"]["ClientId"],
        )

    # Create pool.
    pool_resp = cognito.create_user_pool(
        PoolName=name,
        Policies={
            "PasswordPolicy": {
                "MinimumLength": 12,
                "RequireUppercase": True,
                "RequireLowercase": True,
                "RequireNumbers": True,
                "RequireSymbols": True,
                "TemporaryPasswordValidityDays": 1,
            },
        },
        MfaConfiguration="OPTIONAL",
        AutoVerifiedAttributes=["email"],
        UsernameAttributes=["email"],
        Schema=[
            {"Name": "email", "AttributeDataType": "String", "Required": True, "Mutable": True},
            {"Name": "ptin", "AttributeDataType": "String", "Mutable": True},
        ],
    )
    pool_id = pool_resp["UserPool"]["Id"]
    logger.info("Created Cognito pool", extra={"pool_id": pool_id, "name": name})

    client_resp = cognito.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=f"{name}-client",
        GenerateSecret=False,
        ExplicitAuthFlows=["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    )
    return PoolRecord(pool_id=pool_id, client_id=client_resp["UserPoolClient"]["ClientId"])


def ensure_kms_alias(alias: str, *, settings: Settings | None = None) -> str:
    """Create a per-Tenant KMS key with the given alias. Idempotent.

    Args:
        alias: Alias in the form ``"alias/<tenant-uuid>"``.

    Returns:
        The KMS key ARN.
    """
    settings = settings or get_settings()
    kms = _kms_client(settings)

    try:
        resp = kms.describe_key(KeyId=alias)
        return resp["KeyMetadata"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NotFoundException":
            raise

    key_resp = kms.create_key(
        Description=f"Per-tenant CMK for {alias}",
        KeyUsage="ENCRYPT_DECRYPT",
    )
    key_id = key_resp["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName=alias, TargetKeyId=key_id)
    logger.info("Created KMS key with alias", extra={"alias": alias, "key_id": key_id})
    return key_resp["KeyMetadata"]["Arn"]


def create_cognito_user(
    pool_id: str,
    email: str,
    *,
    settings: Settings | None = None,
    temporary_password: str | None = None,
) -> str:
    """Create a user in the given pool. Returns the Cognito ``sub`` UUID."""
    settings = settings or get_settings()
    if settings.cognito_backend == "fake":
        return _fake_user_sub(pool_id, email)
    cognito = _cognito_client(settings)

    # AdminCreateUser requires a temporary password in real AWS; LocalStack
    # is lenient but we supply one anyway so behavior is identical.
    from secrets import token_urlsafe

    temp_pw = temporary_password or f"Init!{token_urlsafe(12)}A1"
    try:
        resp = cognito.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            TemporaryPassword=temp_pw,
            MessageAction="SUPPRESS",
        )
    except ClientError as e:
        # Idempotency on collision: look up the existing user's sub and return.
        if e.response["Error"]["Code"] == "UsernameExistsException":
            existing = cognito.admin_get_user(UserPoolId=pool_id, Username=email)
            for attr in existing["UserAttributes"]:
                if attr["Name"] == "sub":
                    return attr["Value"]
            raise RuntimeError(
                "UsernameExistsException but no sub attribute found"
            ) from e
        raise

    for attr in resp["User"]["Attributes"]:
        if attr["Name"] == "sub":
            return attr["Value"]

    raise RuntimeError("AdminCreateUser returned no sub attribute")
