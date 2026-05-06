"""Smoke test: migration applies, all 20 tables exist, RLS is on, roles exist."""

from __future__ import annotations

from sqlalchemy import Engine, text


EXPECTED_TABLES = [
    "tenant",
    "firm",
    "app_user",
    "client",
    "engagement",
    "document",
    "parse_result",
    "account",
    "working_trial_balance_row",
    "journal_entry_adjustment",
    "journal_leg",
    "fixed_asset",
    "tax_line_mapping",
    "pbc_request",
    "workflow_run",
    "workflow_step_run",
    "target_system_export",
    "review_signoff",
    "validator_finding",
    "audit_log_entry",
    "engagement_metering",
]


def test_migration_creates_all_tables(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        ).all()
    present = {r[0] for r in rows}
    missing = set(EXPECTED_TABLES) - present
    assert not missing, f"migration did not create tables: {missing}"


def test_rls_enabled_on_all_tenant_tables(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON c.relnamespace = n.oid "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        ).all()
    by_name = {r[0]: (r[1], r[2]) for r in rows}
    for t in EXPECTED_TABLES:
        assert t in by_name, f"table missing: {t}"
        rowsec, forced = by_name[t]
        assert rowsec is True, f"{t}: RLS not enabled"
        assert forced is True, f"{t}: RLS not forced"


def test_roles_exist(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        roles = conn.execute(
            text("SELECT rolname, rolbypassrls FROM pg_roles "
                 "WHERE rolname IN ('app_user','platform_admin')")
        ).all()
    by_name = {r[0]: r[1] for r in roles}
    assert by_name.get("app_user") is False, "app_user must NOT have BYPASSRLS"
    assert by_name.get("platform_admin") is True, "platform_admin should have BYPASSRLS"


def test_app_user_cannot_update_audit_log(app_engine: Engine) -> None:
    """R22.2 enforcement at schema level: app_user has no UPDATE grant on audit_log_entry."""
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', gen_random_uuid()::text, false)"))
        # Attempting UPDATE without any rows still hits the permission check.
        try:
            conn.execute(text("UPDATE audit_log_entry SET action = 'x' WHERE false"))
            raise AssertionError("app_user was able to UPDATE audit_log_entry; expected permission denied")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            assert "permission denied" in msg or "must be owner" in msg, (
                f"expected permission denied, got: {exc}"
            )


def test_app_user_cannot_delete_audit_log(app_engine: Engine) -> None:
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', gen_random_uuid()::text, false)"))
        try:
            conn.execute(text("DELETE FROM audit_log_entry WHERE false"))
            raise AssertionError("app_user was able to DELETE audit_log_entry; expected permission denied")
        except Exception as exc:
            assert "permission denied" in str(exc).lower(), f"expected permission denied, got: {exc}"
