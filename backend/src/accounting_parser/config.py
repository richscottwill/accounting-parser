"""Application configuration via pydantic-settings.

Every setting has a sensible dev default so the app runs against the
docker-compose stack with no env vars. Production overrides via
environment variables (prefix ``ACCOUNTING_PARSER_``).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Environment variable mapping: ``ACCOUNTING_PARSER_<UPPERCASE_FIELD>``.
    Example: ``ACCOUNTING_PARSER_DB_URL=postgresql+psycopg://...``.
    """

    model_config = SettingsConfigDict(
        env_prefix="ACCOUNTING_PARSER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database --------------------------------------------------------
    db_url: str = Field(
        default=(
            "postgresql+psycopg://accounting_parser:dev_only_password"
            "@localhost:5432/accounting_parser_dev"
        ),
        description="Superuser DSN. App runtime code rewrites the user to app_user.",
    )
    db_app_user: str = Field(default="app_user")
    db_app_password: str = Field(default="test_only")

    # --- AWS / LocalStack ------------------------------------------------
    aws_region: str = Field(default="us-east-1")
    aws_endpoint_url: str | None = Field(
        default="http://localhost:4566",
        description="LocalStack endpoint for dev. Set to None in production.",
    )
    aws_access_key_id: str = Field(default="test")
    aws_secret_access_key: str = Field(default="test")

    # --- Auth: Cognito ---------------------------------------------------
    cognito_preparer_pool_name: str = Field(default="accounting-parser-preparer")
    cognito_client_portal_pool_name: str = Field(
        default="accounting-parser-client-portal"
    )
    cognito_jwt_audience: str | None = Field(default=None)

    # Cognito backend selector.
    #
    # - ``aws``: call real boto3 (or LocalStack Pro's cognito-idp mock).
    #   This is production default.
    # - ``fake``: in-process stub that allocates deterministic pool IDs +
    #   user subs. Used in dev against LocalStack Community (which does
    #   not implement cognito-idp) and in tests. No network calls.
    #
    # The split keeps real Cognito behavior under test via the ``aws``
    # path (unit-tested against moto + an integration test against real
    # AWS in staging) without blocking local dev on LocalStack Pro.
    cognito_backend: str = Field(default="fake")

    # --- Auth: WebAuthn --------------------------------------------------
    webauthn_rp_id: str = Field(default="localhost")
    webauthn_rp_name: str = Field(default="accounting-parser")
    webauthn_origin: str = Field(default="http://localhost:3000")
    webauthn_challenge_ttl_seconds: int = Field(default=300)

    # --- Auth: Session ---------------------------------------------------
    # Short-lived JWT issued by the app after a successful passkey assertion.
    # Cognito may also mint tokens; this is the app-layer session token used
    # for subsequent API calls. Signed with HS256 over session_secret.
    session_secret: str = Field(
        default="dev-only-session-secret-not-for-production-use-at-all",
        description="HS256 signing key for app-issued session JWTs.",
    )
    session_ttl_hours: int = Field(default=24)

    # --- App ------------------------------------------------------------
    app_name: str = Field(default="accounting-parser")
    debug: bool = Field(default=False)

    # --- Ingestion ------------------------------------------------------
    max_upload_bytes: int = Field(default=100 * 1024 * 1024)  # 100 MB
    storage_backend: str = Field(default="local")  # "s3" | "local"
    local_storage_root: str = Field(default="/tmp/accounting-parser-storage")
    s3_bucket_prefix: str = Field(default="accounting-parser")
    malware_scanner_backend: str = Field(default="eicar")  # "clamav" | "eicar" | "skip"
    clamav_host: str = Field(default="localhost")
    clamav_port: int = Field(default=3310)

    # --- OCR ------------------------------------------------------------
    ocr_backend: str = Field(default="fake")  # "aws-textract" | "azure-di" | "fake"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Uses lru_cache so settings are resolved once."""
    return Settings()
